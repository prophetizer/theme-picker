"""HTTP routes. stdlib http.server, one handler class. Applying a theme goes
through apply.apply_theme(), which holds the allowlist check."""

import ipaddress
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from . import apply, config, dashboards, editor, hooks, monitor, ntfy, schedule, shots, state, themes
from .coverage import cached_coverage
from .prom import render_metrics
from .render import STATIC, STATIC_TYPES, render_page
from .summary import current_summary


# Sent with every response. The picker changes the whole homelab with one
# click and, on the LAN, needs no login -- so it must not be frameable
# (clickjacking) and its responses must not be MIME-sniffed.
SECURITY_HEADERS = {
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}


def content_security_policy():
    """Scripts only from this origin (the page has no inline script or
    handler); stylesheets and their images/fonts from here and theme-park,
    which the picker dresses itself from -- every theme sheet references only
    relative URLs on its own host. Inline style ATTRIBUTES stay allowed for
    the swatches; a <style> element would not be. No framing, no plugins, no
    <base> rewriting, forms post only here."""
    tp = urlsplit(config.base_url())
    theme_park = f" {tp.scheme}://{tp.netloc}" if tp.scheme and tp.netloc else ""
    return ("default-src 'self'; script-src 'self'; "
            f"style-src 'self'{theme_park}; style-src-attr 'unsafe-inline'; "
            f"img-src 'self'{theme_park} data: blob:; font-src 'self'{theme_park} data:; "
            "connect-src 'self'; object-src 'none'; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'")


class Handler(BaseHTTPRequestHandler):
    def end_headers(self):
        for k, v in SECURITY_HEADERS.items():
            self.send_header(k, v)
        self.send_header("Content-Security-Policy", content_security_policy())
        super().end_headers()

    def _same_origin(self):
        """False for a POST a browser made on another site's behalf.

        Every state-changing request needs this, not just a content-type
        check: behind an auth proxy that lets LAN clients through without a
        login, a LAN visitor's browser carries no credential for an attacker
        to lack, so any page they open elsewhere could otherwise drive the
        picker. Browsers mark cross-site requests
        with Sec-Fetch-Site and always send Origin on POST; a request with
        neither (curl, the dashboards, the tests) did not come from a page,
        so it is not a CSRF vector. "null" (sandboxed/opaque) never matches."""
        site = (self.headers.get("Sec-Fetch-Site") or "").lower()
        if site and site not in ("same-origin", "none"):
            return False
        origin = self.headers.get("Origin")
        if origin is None:
            return True
        hosts = {h.strip().lower() for h in (self.headers.get("Host"), self.headers.get("X-Forwarded-Host")) if h}
        return urlsplit(origin).netloc.lower() in hosts

    def _send_html(self, body, status=200):
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, payload, status=200):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _wants_json(self):
        return "application/json" in (self.headers.get("Accept") or "")

    def _reply(self, message, ok=False, theme="", status=200):
        """One exit point for both callers: JSON for the in-page fetch, a full
        re-rendered page for a plain form POST with JavaScript disabled."""
        if self._wants_json():
            self._send_json({"ok": ok, "message": message, "theme": theme,
                             "css": themes.theme_css_url(theme) if ok else ""},
                            status=status)
        else:
            self._send_html(render_page(message), status=status)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path in ("/", ""):
            self._send_html(render_page())
        elif path.startswith("/static/") and path[len("/static/"):] in STATIC:
            name = path[len("/static/"):]
            data = STATIC[name]
            self.send_response(200)
            self.send_header("Content-Type", STATIC_TYPES[name])
            self.send_header("Content-Length", str(len(data)))
            # The page links a content-hashed URL, so a long cache is safe.
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            self.end_headers()
            self.wfile.write(data)
        elif path.startswith("/dashboards/") and path[len("/dashboards/"):] in dashboards.STYLESHEETS:
            # Linked from Homepage's custom.css / Glance's custom-css-file:
            # the live theme's colours in that dashboard's own variables.
            # no-store, not no-cache: a browser may reuse a no-cache copy it
            # has no way to revalidate (restored tabs, back/forward, some
            # reloads), and Homarr showed a theme hours old that way. The
            # sheet is tiny; never keeping it costs nothing.
            css = dashboards.STYLESHEETS[path[len("/dashboards/"):]](themes.current_theme())
            data = css.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/css; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.end_headers()
            self.wfile.write(data)
        elif path.startswith("/shots/"):
            self._send_shot(path)
        elif path == "/api/current":
            # Read-only, for the Glance/Homepage widgets, which call it over the
            # Docker network (http://theme-picker:8090) and never meet Authelia.
            self._send_json(current_summary())
        elif path == "/metrics":
            # For Prometheus, over the Docker network. Serves the scheduled
            # check's last result; a scrape never triggers a check.
            body = render_metrics().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/api/coverage":
            self._send_json(cached_coverage())
        elif path == "/api/theme-vars":
            q = parse_qs(urlsplit(self.path).query)
            t = (q.get("theme") or [""])[0]
            if t not in themes.allowed_themes():
                return self._send_json({"error": "unknown theme"}, status=400)
            self._send_json(editor.theme_vars(t))
        elif path == "/api/schedule":
            self._send_json(schedule.status())
        elif path == "/api/editor/status":
            q = parse_qs(urlsplit(self.path).query)
            n = (q.get("name") or [""])[0]
            self._send_json(editor.editor_status(n))
        else:
            self._send_html("Not found", status=404)

    def _json_body(self):
        """Parse a JSON POST body. Requiring application/json is the second
        CSRF guard (after _same_origin): a cross-site page cannot send that
        content type without a CORS preflight, which this server never grants.
        The MIME type must match EXACTLY -- "text/plain; x=application/json" is
        CORS-safelisted (no preflight) and passed an earlier substring check."""
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return None
        length = self._length(20_000)
        if length is None:
            return None
        try:
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return None

    def _length(self, limit):
        """The declared body size if it is a whole number from 0 to `limit`,
        else None. It used to be trusted: a huge value made the server buffer
        that much, a negative one read until the client hung up, and a
        non-number raised."""
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        return n if 0 <= n <= limit else None

    def _send_shot(self, path):
        """Serve one screenshot, if shots.shot_file() accepts the path."""
        found = shots.shot_file(path)
        if not found:
            return self._send_html("Not found", status=404)
        f, ctype = found
        data = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "max-age=600")
        self.end_headers()
        self.wfile.write(data)

    def _who(self):
        """Who made a change, for the history and the notification: the auth
        proxy's Remote-User when present, else the forwarded client address.
        Both are filtered to a safe character set before use.

        Attribution only, never authorisation: when the proxy lets a request
        through without a login it sets no Remote-User, so one sent by the
        client can pass through unless the proxy strips it."""
        user = (self.headers.get("Remote-User") or "").strip()
        if re.fullmatch(r"[\w.@-]{1,64}", user):
            return user
        ip = (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()
        if not re.fullmatch(r"[0-9a-fA-F.:]{2,45}", ip):
            return "unknown"
        # Behind NAT every LAN request arrives from the same router address,
        # so recording it tells nobody anything. Say what it actually means:
        # someone on the LAN, let in without a login.
        try:
            if ipaddress.ip_address(ip).is_private:
                return "someone on the LAN (no login)"
        except ValueError:
            pass
        return ip

    def do_POST(self):
        path = urlsplit(self.path).path
        if not self._same_origin():
            if path.startswith("/api/") or self._wants_json():
                return self._send_json({"ok": False, "message": "cross-site request refused"}, status=403)
            return self._send_html("Cross-site request refused", status=403)
        if path.startswith("/api/"):
            data = self._json_body()
            if data is None:
                return self._send_json({"ok": False, "message": "expected a JSON body"}, status=415)
            if path == "/api/override":
                ok, msg = state.set_override(str(data.get("app", "")), str(data.get("theme", "")))
                return self._send_json({"ok": ok, "message": msg, "pinned": state.read_overrides()},
                                       status=200 if ok else 400)
            if path == "/api/favourite":
                ok = state.set_favourite(str(data.get("theme", "")), bool(data.get("on")))
                return self._send_json({"ok": ok, "favourites": state.read_favourites()},
                                       status=200 if ok else 400)
            if path == "/api/hook/theme":
                # Token-protected, for automations (see hooks.py). 404 while
                # no token is configured, so the endpoint isn't advertised.
                if not hooks.enabled():
                    return self._send_json({"ok": False, "message": "not found"}, status=404)
                if not hooks.authorised(self.headers.get("Authorization")):
                    return self._send_json({"ok": False, "message": "bad or missing token"}, status=401)
                ok, msg, status, theme = hooks.set_theme(data)
                return self._send_json({"ok": ok, "message": msg, "theme": theme}, status=status)
            if path == "/api/schedule":
                before = themes.current_theme()
                ok, msg = schedule.save(data)
                now = themes.current_theme()
                return self._send_json(
                    {"ok": ok, "message": msg, "schedule": schedule.status(),
                     "theme": now, "previous": before, "css": themes.theme_css_url(now)},
                    status=200 if ok else 400)
            if path == "/api/editor/save":
                ok, msg = editor.editor_save(data)
                return self._send_json({"ok": ok, "message": msg}, status=200 if ok else 400)
            return self._send_json({"ok": False, "message": "not found"}, status=404)
        if path != "/set-theme":
            self._send_html("Not found", status=404)
            return

        length = self._length(4096)                 # "theme=<name>" is tiny
        if length is None:
            self._reply("Request body missing or too large.", status=413)
            return
        body = self.rfile.read(length).decode("utf-8", "replace")
        theme = (parse_qs(body).get("theme") or [""])[0]

        who = self._who()
        ok, message, status = apply.apply_theme(theme, who)
        if not ok:
            self._reply(message, status=status)
            return
        # The notification's link comes from config, never from request
        # headers a client could set to point it somewhere else.
        ntfy.schedule_notify(theme, who, config.picker_url())
        self._reply(message, ok=True, theme=theme)

    def log_message(self, fmt, *args):
        pass  # keep container logs quiet; Traefik/access logs cover requests


def main(host=None, port=None):
    host = host or config.SETTINGS["listen.host"]
    port = port or config.SETTINGS["listen.port"]
    monitor.start()
    schedule.start()
    ThreadingHTTPServer((host, port), Handler).serve_forever()

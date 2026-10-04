# Deploying Theme Picker

Theme Picker switches the [theme.park](https://theme-park.dev) theme of every
app behind your Traefik at once. It does this by writing a Traefik dynamic
config file: one [`traefik-themepark`](https://github.com/packruler/traefik-themepark)
middleware per app. Traefik watches that file, so a click in the picker
re-themes every app within a second or two, with no restarts.

This guide takes you from nothing to a working picker, then covers the
optional extras.


> To try it first, the [starter stack](starter/) brings up Traefik,
> theme.park, the picker and a demo app on `http://*.localhost` with one command.

## What you need

- **Traefik v3**, with the file provider watching a directory.
- **Docker** (or any Python 3.12 host; the picker is stdlib + PyYAML).
- **Apps that theme.park supports**, each routed through Traefik. The
  supported list is theme.park's [`css/base/`](https://github.com/themepark-dev/theme.park/tree/master/css/base)
  directory; the folder name is the app's `theme_app` id.
- **An auth layer in front of the picker** (Authelia, Authentik, basic
  auth...). The picker has no login of its own; see [Protect it](#5-protect-it).

theme.park itself can be the public `https://theme-park.dev` or a self-hosted
instance; see [Self-hosting theme.park](#self-hosting-themepark).

## 1. Add the plugin and file provider to Traefik

In Traefik's **static** configuration (CLI flags shown; the `traefik.yml`
equivalents work the same):

```yaml
command:
  - "--experimental.plugins.themepark.modulename=github.com/packruler/traefik-themepark"
  - "--experimental.plugins.themepark.version=v1.4.2"
  - "--providers.file.directory=/etc/traefik/dynamic"
  - "--providers.file.watch=true"
volumes:
  - ./traefik/dynamic:/etc/traefik/dynamic
```

Restart Traefik once so it downloads the plugin. From then on the picker writes
`themes.yml` into that dynamic directory, and Traefik reloads it by itself.

## 2. Create a data directory

The picker keeps its configuration and state (current theme, history,
favourites, pins, schedule) in one directory. Create it with two files.

**`apps.yml`**: the apps to theme.

```yaml
apps:
  - name: sonarr          # middleware becomes "sonarr-theme"
    theme_app: sonarr     # theme.park's id for the app
  - name: radarr
    theme_app: radarr
  - name: jellyseerr
    theme_app: overseerr  # theme.park styles Jellyseerr under "overseerr"
    host: requests        # optional: the app lives at requests.<domain>
    addons: []            # optional: theme.park addons for this app
```

`host` defaults to `name`. The coverage check requests `https://<host>.<domain>/`
to confirm each app really receives its theme, and the Apps tab links there.
It uses the scheme and port of `picker_url`. An app that lives somewhere else
(another domain, a port, a path) takes a full `url:` instead.

You can also skip the file and list the apps in `picker.yml` under `apps:`.
Each one is a name, `name:theme_app`, or the same mapping as above. They also
fit in one environment variable: `THEME_APPS="sonarr radarr jellyseerr:overseerr"`.

**`picker.yml`**: settings. Every key is optional; `picker.example.yml`
documents them all.

```yaml
theme_switcher_dir: /data                 # this data directory, as the container sees it
theme_park_url: https://theme-park.dev    # or your own instance
domain: example.com
picker_url: https://theme-picker.example.com/
backend:
  type: traefik-file
  output_file: /traefik-dynamic/themes.yml
```

Any setting can also be given as an environment variable, which wins over the
file (e.g. `DOMAIN`, `THEME_PARK_URL`, `THEME_OUTPUT_FILE`). The variable names
are listed next to each key in `picker.example.yml`.

## 3. Run it

Use the published image, `ghcr.io/prophetizer/theme-picker`. It's built for
`linux/amd64` and `linux/arm64` and tagged by version: `1.0.0`, `1.0`, `1`
and `latest`. It runs as UID 1000 by default and reads everything from
`/data`, so `picker.yml` goes at `/data/picker.yml`.

```yaml
services:
  theme-picker:
    image: ghcr.io/prophetizer/theme-picker:1
    container_name: theme-picker
    restart: unless-stopped
    user: "1000:1000"                  # must be able to write the data dir and the output file
    environment:
      - TZ=Europe/London               # history timestamps and the day/night schedule
    volumes:
      - ./theme-picker-data:/data      # picker.yml, apps.yml and the picker's state
      - ./traefik/dynamic:/traefik-dynamic   # the directory Traefik watches
    networks:
      - proxy
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.theme-picker.rule=Host(`theme-picker.example.com`)"
      - "traefik.http.routers.theme-picker.entrypoints=websecure"
      - "traefik.http.routers.theme-picker.tls.certresolver=letsencrypt"
      - "traefik.http.routers.theme-picker.middlewares=your-auth@docker"
      - "traefik.http.services.theme-picker.loadbalancer.server.port=8090"
```

The image has a health check, `/healthz` on port 8090. It answers without
contacting theme.park, so the container stays healthy while theme.park is down.

**From a checkout instead:** clone the repo and use the stock
`python:3.12-slim` image. Mount the checkout at `/app` read-only, set
`working_dir: /app` and `PICKER_CONFIG=/data/picker.yml`, and run
`pip install --target=/tmp/pylibs --require-hashes -r requirements.txt &&
python3 server.py` with `PYTHONPATH=/tmp/pylibs`. That's how the author runs
it, to edit the code live.

The first theme you pick creates `themes.yml`. Until then the `<name>-theme`
middlewares don't exist, and Traefik logs "middleware does not exist" for any
router that references one. Pick a theme before wiring apps (step 4), or accept
a minute of those errors.

## 4. Wire each app to its middleware

Add `<name>-theme@file` to each themed app's router, alongside whatever
middlewares it already has:

```yaml
labels:
  - "traefik.http.routers.sonarr.middlewares=sonarr-theme@file"
  # with existing middlewares:
  # - "traefik.http.routers.sonarr.middlewares=your-auth@docker,sonarr-theme@file"
```

This is one line per app, done once. Switching themes afterwards never touches
the apps again.

## 5. Protect it

Anyone who can reach the picker can change the theme of every app. Put it
behind your auth middleware, as in the compose example. The picker then:

- refuses cross-site POSTs (`Sec-Fetch-Site` / `Origin` checks, and JSON
  endpoints need an exact `application/json` type), so a malicious page
  can't drive a logged-in or LAN-bypassed browser;
- sends a strict CSP and anti-framing headers on every response;
- passes a theme name on only after an exact match against the list of known
  themes;
- answers only to its own host names (421 otherwise), which stops a
  DNS-rebinding page from reaching it as "same-origin". IP addresses,
  localhost, single-word Docker names and `.local` / `.lan` / `.internal` /
  `.home.arpa` names always work, as does `picker_url`'s host. List any
  other name you use under `allowed_hosts` in `picker.yml`.

Keep port 8090 unpublished (no `ports:`), so everything reaches it through
the proxy, with the proxy's auth, timeouts and connection limits. The
picker's own server is simple: it caps request bodies and idle time, but it
has no rate limiting or connection cap of its own.

Two paths are safe to leave out of the proxy's authentication:
- `/dashboards/*.css` serves only the live theme's colours. See
  [Dashboards](#dashboards-follow-the-theme).
- `/api/hook/theme` needs its own bearer token, compared in constant time,
  and is off without one. See [Automation hook](#automation-hook).

## 6. Check that it works

1. Open the picker and apply a theme.
2. `cat` the output file: it should list one `<name>-theme` middleware per app
   with that theme.
3. Ask an app for HTML and look for the injected stylesheet:

   ```bash
   curl -s -H 'Accept: text/html' https://sonarr.example.com/ | grep -o 'theme-park[^"]*'
   ```

   The `Accept` header matters: the plugin only injects into HTML responses,
   so without it every app looks unthemed.
4. The **Apps & coverage** tab runs the same check for every app.

## Optional extras

### Self-hosting theme.park

Point both `theme_park_url` and the plugin's `baseUrl` at your instance (the
picker writes `baseUrl` from `theme_park_url`). If an app sends its own
`Content-Security-Policy`, that policy must allow your theme.park origin in
`style-src`, or the browser will block the stylesheet the plugin injects.

### Screenshots

By default each tile shows colour bands. Real screenshots come from the
capture, an optional second container. While it runs, it cycles the live
theme through every theme, so everyone sees it change; the picker shows a
banner meanwhile ("theme 509 of 772, about 40 min left"), read from
`capture-status.json`, which the capture writes to the state directory
(`GET /api/capture` serves it). It photographs
`screenshots.apps` from `picker.yml`; pick apps whose themed page shows
without a login screen.

The image is `ghcr.io/prophetizer/theme-picker-capture`, tagged like the
picker. It holds Playwright and its Chromium, so it is large (about 3.7 GB).
Give it the picker's settings and mounts: it switches the theme through the
same files, and writes the screenshots into `/data/screenshots`, where the
picker reads them.

```yaml
  theme-picker-capture:
    image: ghcr.io/prophetizer/theme-picker-capture:1
    user: "1000:1000"                  # the same user as the picker
    environment:
      - TZ=Europe/London
      - CAPTURE_AT=04:30               # nightly at this local time; empty = once, then exit
    volumes:                           # the picker's volumes, exactly
      - ./theme-picker-data:/data
      - ./traefik/dynamic:/traefik-dynamic
    shm_size: 1gb                      # Chromium needs more than Docker's 64 MB
    networks:
      - proxy
    restart: unless-stopped
```

- **First start:** it shoots straight away when there are no screenshots
  yet (`CAPTURE_ON_START=0` turns that off). After that, a run re-shoots only
  what is missing, plus custom themes whose file changed.
- **Reaching your apps:** the capture loads each app at the address the
  coverage check uses. From inside the container, your apps' names must
  lead to Traefik.
- **`*.localhost` names:** Chromium always sends these to its own loopback.
  Use `CAPTURE_HOST_RULES="MAP *.localhost traefik"` to send them to the
  proxy instead. The [starter stack](starter/) does this.
- **Sandbox:** Chromium's own sandbox is off in the image, because Docker's
  default seccomp profile does not let it start. The container is the
  boundary. It needs no secrets, so don't give it the picker's token files.

**On a host instead:** `capture-theme-screenshots.sh` runs the same script
against an installed Chrome, in a pinned venv it creates from
`capture-requirements.txt`, with Chrome's sandbox on. `install-cron.sh`
schedules it nightly. That's how the author runs it.

### Notifications (ntfy)

Set `ntfy.url`, `ntfy.topic` and `ntfy.token_file`. You'll get a debounced
notice on each theme change, and an alert when an app stops receiving its
theme (checked every `coverage.interval` seconds; 0 disables it).

Set `ntfy.digest` (e.g. `"mon 09:00"`, local time) for a weekly summary:
- theme changes, and the themes most on screen
- themes added that week
- coverage
- themes still missing screenshots

It starts from the next slot after you set it. A slot missed while the picker
was down is sent once when it comes back. The Stats tab can preview it
without sending.

### Automation hook

Put a random token in a file and set `hooks.token_file`. Home Assistant or any
other automation can then set the theme:

```bash
curl -X POST https://theme-picker.example.com/api/hook/theme \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"theme": "nord"}'          # or "random-favourite"
```

Without a token file the endpoint returns 404. Ready-made Home Assistant
automations (by the sun's height, presence, dashboard buttons, the media
player) are in [docs/home-assistant.md](docs/home-assistant.md).

The screenshot capture posts to the same ntfy topic when a nightly run leaves
shots missing, cannot put the live theme back, or crashes: give it the same
`ntfy.*` settings (or `NTFY_*` variables) as the picker.

### Dashboards follow the theme

The picker serves `/dashboards/homepage.css`, `/dashboards/glance.css` and
`/dashboards/homarr.css`, recomputed from the live theme on every request.
Link each once:

- **Homepage:** `@import` it in `custom.css`.
- **Glance:** set `theme.custom-css-file` to its URL.
- **Homarr:** `@import` it in each board's custom CSS.

If a dashboard can't pass your auth layer (Homarr fetching from outside the
LAN, for example), give `/dashboards/` its own unauthenticated router with a
higher priority:

```yaml
- "traefik.http.routers.theme-picker-dashboards.rule=Host(`theme-picker.example.com`) && PathPrefix(`/dashboards/`)"
- "traefik.http.routers.theme-picker-dashboards.entrypoints=websecure"
- "traefik.http.routers.theme-picker-dashboards.tls.certresolver=letsencrypt"
- "traefik.http.routers.theme-picker-dashboards.service=theme-picker"
```

### Prometheus

`/metrics` reports the last scheduled coverage check. A scrape never runs a
check itself.

## Custom themes

The picker can manage your own themes too: it lists them, deploys them into
your self-hosted theme.park, and saves new ones from the editor. It needs
two things:

1. **A folder of themes**, one `<name>.css` per theme. For 100 ready-made
   ones, clone [theme-park-themes](https://github.com/prophetizer/theme-park-themes)
   and use its `themes/` folder.
2. **theme.park's `www` directory mounted into the picker, read-write.** This
   is theme.park's served folder, `/config/www` inside its container. Run
   both containers as the same user (theme.park's `PUID`/`PGID`) so the
   picker can write there.

```yaml
# picker.yml
custom_themes:
  dir: /data/custom-themes          # e.g. a clone of theme-park-themes/themes
  theme_park_www: /theme-park-www   # theme.park's /config/www, mounted here
```

```yaml
# the picker's compose service, in addition to step 3's volumes
    volumes:
      - ./theme-park-themes/themes:/data/custom-themes
      - ./theme-park/config/www:/theme-park-www
```

With that set, the picker keeps theme.park in step with the folder. It checks
at start and every minute:

- It copies new or changed themes into `css/theme-options/`.
- It runs theme.park's own `themes.py`, which builds the per-app CSS.
- It removes themes you've deleted.
- It puts back anything a theme.park restart or a new volume lost.

Adding a theme means dropping a file into the folder. The editor's *Save &
deploy* writes straight into the folder and deploys immediately.
`/api/custom-themes` reports the last run.

**Light/dark twins.** Before each run, the picker also makes every theme's
opposite-mode twin, so each one comes in a light and a dark form. That covers
your themes and theme.park's own: `<name>-light.css` for a dark theme,
`<name>-dark.css` for a light one. The twins are written into the same folder
and deployed with the rest.
- A theme that already has a real twin (`gruvbox` and `gruvbox-light`) gets
  no generated one.
- A twin is remade when its source changes, and removed when the source is.
- The picker only ever replaces or removes files it generated. Those carry
  `Generated variant:` in their header, so a theme you wrote is never touched.
- Set `custom_themes.twins: false` to turn this off. Expect about 40 twins
  for theme.park's own themes on the first run, which takes a few seconds.

What it refuses, and why:
- **A name theme.park already uses** (e.g. `nord.css`). theme.park copies its
  own files over `www` on every start, so the two would fight. The one
  exception is a file you copied in by hand earlier, identical byte for
  byte, which the picker adopts.
- **Names with capitals or dots.** theme.park lowercases names and splits
  them at dots, so they would only half-deploy.
- **Symlinks, and files over 64 KB.**

**Trust:** with `theme_park_www` set, the picker runs `themes.py` from
theme.park's directory, so whatever can write that directory can run code
as the picker (which holds your hook and ntfy tokens and writes Traefik's
theme config). Mount only theme.park's `www` there, and don't share it with
anything you trust less than the picker.

Leave `theme_park_www` unset if something else deploys your themes. The
picker then only lists them, and the editor queues saves for an external
job, as in the author's own setup.

## Updating

```bash
docker compose pull theme-picker && docker compose up -d theme-picker
```

`:1` follows every 1.x release; pin `:1.0.0` to choose when you update. From
a checkout, `git pull` and restart the container instead. Your data directory
is never touched by an update.

## Removing it

1. Remove `<name>-theme@file` from each app's router.
2. Stop the container.
3. Delete `themes.yml` from Traefik's dynamic directory.

Apps go back to their stock look as soon as Traefik reloads.

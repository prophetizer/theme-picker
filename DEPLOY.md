# Deploying Theme Picker

Theme Picker switches the [theme.park](https://theme-park.dev) theme of every
app behind your Traefik at once. It does this by writing a Traefik dynamic
config file: one [`traefik-themepark`](https://github.com/packruler/traefik-themepark)
middleware per app. Traefik watches that file, so a click in the picker
re-themes every app within a second or two, with no restarts.

This guide takes you from nothing to a working picker, then covers the
optional extras.

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

`host` defaults to `name`. It is only used by the coverage check, which
requests `https://<host>.<domain>/` to confirm each app really receives its
theme.

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

There is no published image yet: the picker runs from a checkout on the stock
`python:3.12-slim` image and installs its one dependency at start.

```bash
git clone https://github.com/prophetizer/theme-picker.git /opt/theme-picker
```

```yaml
services:
  theme-picker:
    image: python:3.12-slim
    container_name: theme-picker
    restart: unless-stopped
    user: "1000:1000"                  # must be able to write the data dir and output file
    working_dir: /app
    command: ["sh", "-c", "pip install --no-cache-dir --target=/tmp/pylibs pyyaml >/dev/null && python3 server.py"]
    environment:
      - PYTHONPATH=/tmp/pylibs
      - PICKER_CONFIG=/data/picker.yml
      - TZ=Europe/London               # history timestamps and the day/night schedule
    volumes:
      - /opt/theme-picker:/app:ro
      - ./theme-picker-data:/data
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
  themes.

`/dashboards/*.css` is the one path that is safe to leave unauthenticated: it
serves only the live theme's colours. See [Dashboards](#dashboards-follow-the-theme).

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

By default each tile shows colour bands. Real screenshots come from
`capture-theme-screenshots.sh`, which runs **on the host** rather than in the
container:

- It drives an installed Chrome through Playwright, in a pinned venv it
  creates from `capture-requirements.txt`.
- It cycles the live theme through every theme, so everyone sees it change
  while it runs.
- It photographs `screenshots.apps` from `picker.yml`. Pick apps whose themed
  page shows without a login screen.

`install-cron.sh` schedules it nightly.

### Notifications (ntfy)

Set `ntfy.url`, `ntfy.topic` and `ntfy.token_file`. You'll get a debounced
notice on each theme change, and an alert when an app stops receiving its
theme (checked every `coverage.interval` seconds; 0 disables it).

### Automation hook

Put a random token in a file and set `hooks.token_file`. Home Assistant or any
other automation can then set the theme:

```bash
curl -X POST https://theme-picker.example.com/api/hook/theme \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"theme": "nord"}'          # or "random-favourite"
```

Without a token file the endpoint returns 404.

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

What it refuses, and why:
- **A name theme.park already uses** (e.g. `nord.css`). theme.park copies its
  own files over `www` on every start, so the two would fight. The one
  exception is a file you copied in by hand earlier, identical byte for
  byte, which the picker adopts.
- **Names with capitals or dots.** theme.park lowercases names and splits
  them at dots, so they would only half-deploy.
- **Symlinks, and files over 64 KB.**

Leave `theme_park_www` unset if something else deploys your themes. The
picker then only lists them, and the editor queues saves for an external
job, as in the author's own setup.

## Updating

```bash
git -C /opt/theme-picker pull
docker restart theme-picker
```

Your data directory is never touched by an update.

## Removing it

1. Remove `<name>-theme@file` from each app's router.
2. Stop the container.
3. Delete `themes.yml` from Traefik's dynamic directory.

Apps go back to their stock look as soon as Traefik reloads.

# Starter stack

Try Theme Picker in a few minutes, on your own machine: Traefik, a self-hosted
theme.park, the picker, and one demo app (File Browser) that changes with it.
No domain, no certificates, nothing to edit.

```bash
git clone https://github.com/prophetizer/theme-picker
cd theme-picker/starter
docker compose up -d
```

Then open:

- **http://picker.localhost**: pick a theme
- **http://files.localhost**: the demo app, in that theme within a second or two

`*.localhost` addresses lead to your own machine in every current browser. If
port 80 is taken, choose another: `STARTER_PORT=8088 docker compose up -d`,
then use `http://picker.localhost:8088` and `http://files.localhost:8088`.

## What runs

| Service | Image | Job |
|---|---|---|
| traefik | `traefik:v3.7` | Routes the three hosts; its themepark plugin adds the theme to the demo app's pages |
| themepark | `ghcr.io/themepark-dev/theme.park` | Serves the theme stylesheets |
| picker | `ghcr.io/prophetizer/theme-picker:1` | The UI; writes Traefik's theme config |
| files | `filebrowser/filebrowser` | The demo app, read-only, without a login |
| routes | `busybox` | Runs once at start: puts `traefik/routes.yml` beside the picker's config |

The picker keeps its state (history, favourites, pins, and the `themes.yml`
Traefik reads) in the `picker-data` volume.

## Add your own app

1. Add it to `apps.yml`: a `name`, theme.park's name for it as `theme_app`
   (see [theme.park's app list](https://docs.theme-park.dev/themes/)), and its
   first address part as `host`.
2. Give it a router in `traefik/routes.yml` with `middlewares: [<name>-theme@file]`,
   and a service pointing at it.
3. Add the app to `compose.yml`, then `docker compose up -d`.

## Not for production

Plain HTTP, and no login in front of the picker. For a real setup, behind your
own Traefik with TLS and authentication, see [DEPLOY.md](../DEPLOY.md).

`docker compose down -v` removes everything again, volume included.

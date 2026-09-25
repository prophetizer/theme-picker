# Theme Picker

A web UI for switching a self-hosted [theme.park](https://theme-park.dev) theme
across every app behind Traefik at once — with live previews, real screenshots,
a contrast audit, per-app pins and an in-browser theme editor.

> **Status: early.** It needs Traefik with its file provider and the
> [`traefik-themepark`](https://github.com/packruler/traefik-themepark) plugin;
> it writes the plugin's middleware config itself. Official and community
> themes work out of the box. Custom themes and the in-browser editor still
> depend on a companion pipeline that isn't in this repository yet.
>
> **[Deployment guide → DEPLOY.md](DEPLOY.md)**. Every setting is documented
> in `picker.example.yml`.

## Features

- Every official, community and custom theme as a tile with a colour-band
  preview, or a real screenshot of any app in that theme
- Filters (name, light/dark, gradient, readable, high contrast, new,
  favourites, accent colour), sorting, keyboard navigation, "surprise me"
- Contrast audit on every theme: *low contrast* and *high contrast* (WCAG AAA
  for every text role) badges, measured rather than claimed
- Lightbox of real screenshots per theme, captured by a headless-Chrome job
- Recent-theme history chips and usage stats
- Per-app theme pins, with a coverage check that every app actually received
  the theme it should
- In-browser theme editor with live preview and contrast readout; saved themes
  are committed and deployed automatically
- ntfy notifications (debounced) and a JSON endpoint for dashboard widgets
- Homepage and Glance take on the live theme too, via stylesheets the picker
  serves
- Start a theme from any image (colours extracted in the browser)
- A token-protected hook so Home Assistant or any automation can set the theme
- Day/night schedule, undo, side-by-side screenshot compare

## License

[MIT](LICENSE)

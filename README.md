# Theme Picker

A web UI for switching a self-hosted [theme.park](https://theme-park.dev) theme
across every app behind Traefik at once — with live previews, real screenshots,
a contrast audit, per-app pins and an in-browser theme editor.

![Every theme as a tile, your own themes first in foldable groups, with filters on the left and the live theme across the top](docs/screenshots/themes.png)

*Hand-made themes come first, in foldable groups (dark, light, gradients, made
in the editor), then theme.park's Community and Official themes. Any sort other
than "By section" pools them into one list.*

> **Requirements:** Traefik with its file provider and the
> [`traefik-themepark`](https://github.com/packruler/traefik-themepark) plugin;
> the picker writes the plugin's middleware config itself. Official and
> community themes work out of the box. It can also deploy your own themes
> into a self-hosted theme.park: 153 are ready-made, each in light and dark,
> in [theme-park-themes](https://github.com/prophetizer/theme-park-themes).

## Install

**Just want to look?** The [live demo](https://prophetizer.github.io/theme-picker/)
is the real page with sample data: pick themes, open the editor, try the
filters. Nothing is applied anywhere.

**Just want to try it?** The [starter stack](starter/) runs Traefik,
theme.park, the picker and a demo app on `http://*.localhost` with one
`docker compose up -d`.

The image is published for linux/amd64 and linux/arm64:

```bash
docker pull ghcr.io/prophetizer/theme-picker:1
```

Tags: `1.0.0` (exact release), `1.0` and `1` (latest patch or minor of that
line), `latest`. Pin `1` to get fixes without breaking changes.

It runs as a non-root user, listens on port 8090, and keeps its config and
state in `/data`. Put it behind your reverse proxy's authentication rather
than publishing the port. The **[deployment guide → DEPLOY.md](DEPLOY.md)**
has the full compose example and Traefik wiring; every setting is documented
in [`picker.example.yml`](picker.example.yml).

## Features

- Every official, community and custom theme as a tile with a colour-band
  preview, or a real screenshot of any app in that theme
- Filters (name, light/dark, gradient, readable, high contrast, new,
  favourites, accent colour), sorting, keyboard navigation, "surprise me"
- Contrast audit on every theme: *low contrast* and *high contrast* (WCAG AAA
  for every text role) badges, measured rather than claimed
- A preview of each theme: real screenshots of your apps (captured nightly by
  an optional headless-Chromium container, or a host cron job, with a
  progress banner while it runs), the themes that look like it, a colour-vision check, and export to base16 and
  terminal formats
- Recent-theme history chips and usage stats, with the themes the last
  capture photographed
- Per-app theme pins, and app groups to pin several at once, with a coverage
  check that every app actually received the theme it should
- Like or dislike themes: every random pick favours the liked and skips the
  disliked
- In-browser theme editor with live preview and contrast readout; saved themes
  are committed and deployed automatically
- ntfy notifications (debounced), a weekly digest, and a JSON endpoint for
  dashboard widgets
- Homepage and Glance take on the live theme too, via stylesheets the picker
  serves
- Start a theme from any image (colours extracted in the browser)
- A token-protected hook so Home Assistant or any automation can set the theme
  ([Home Assistant recipes](docs/home-assistant.md): by the sun's height,
  when someone comes home, dashboard buttons, the media player)
- Schedules: day/night by the clock or by sunrise and sunset, a theme of the
  day, or a rotation every few hours, random or through your own ordered list
- Installs as an app on phones and desktops (web app manifest)
- Undo, side-by-side screenshot compare

## A tour of the tabs

Every tab shares the header strip:
- the live theme and its colours
- **Undo**, which puts back the previous theme
- **Surprise me · N**, which applies a random theme from the N that the
  current filters show
- the most recent themes, one click each

The picker wears the live theme itself.

### Themes

Every official, community and custom theme is a tile with a colour-band
preview, and every one comes in a light and a dark form. The sidebar narrows
the list:
- search
- readable only, high contrast, gradients, favourites, new
- accent colour
- **collection**: Light, Dark, High contrast, the four seasons (suggested
  from each theme's colours and name), or one of your own, built from a
  theme's preview with *Add to collection*
- **closest to a colour**: pick any colour and the themes that use it come first
- hidden themes: **hide** a theme you never want (in its preview, or **H**) and
  it leaves the grid, Surprise me and the theme of the day; "Show hidden
  themes" brings them back

Here the **Winter** collection is picked, 145 of the 475 themes:

![The Themes tab narrowed to the built-in Winter collection](docs/screenshots/collections.png)

It also sorts the list by section, name, lightness, accent colour or date
added. Click a tile to apply it everywhere. The ☀/☾ switch on a tile flips
that theme between its light and dark form: the author's own where they made
both, otherwise a generated twin.

*Show themes as* **Light** or **Dark** flips every theme at once. Here it is
set to **Light** in Catppuccin Latte:

![The picker in a light theme, with every theme shown in its light form](docs/screenshots/light.png)

Badges come from a real contrast audit of each theme's CSS:
- **low contrast**: body text under 4.5:1, or muted text or button labels
  under 3:1.
- **high contrast**: every text role at WCAG AAA, 7:1.

### A theme's preview

The ▣ on any tile (or **P**) opens a theme's preview:
- **screenshots** of your apps in that theme, if the capture runs, side by side
  with another theme on request
- the five themes that **look most like it**
- **colour vision**: the screenshots and the theme's colours as seen with
  protanopia, deuteranopia or tritanopia, and a warning when links blur into
  text, or buttons into links or panels
- **export as** theme.park CSS, base16 YAML, or a Ghostty, Kitty, Alacritty,
  Windows Terminal or Xresources scheme, to take the theme to your terminal
- **👍 / 👎**: a liked theme comes up three times as often in Surprise me,
  the theme of the day and rotation; a disliked one never does (it stays in
  the grid, dimmed)
- **Edit a copy**, **Hide** (the whole theme, or **only this light or dark
  form** so the theme stays in its other form), and a link that shows the
  picker in that theme

![A theme's preview in deuteranopia: each colour as designed and as seen](docs/screenshots/preview.png)

### Apps & coverage

Every themed app, the theme it should get, and whether it actually gets it.
The check requests each app's page the way a browser would and reads which
stylesheet was injected, so a router that lost its middleware shows up as
**missing**. It runs on a schedule too and can alert through ntfy. Pin an
app to keep it on one theme whatever the live theme is. Apps that are fine
and follow the live theme fold behind one button, so pinned and failing ones
stand out; here the list is unfolded, Prowlarr is pinned to Nord and Grafana
is missing its theme. **App groups** pin several apps at once: name a group
(say, every *arr app) and give it a theme.

![Apps and coverage: an app group for the *arr apps, six apps, five themed, one pinned, one missing its theme](docs/screenshots/apps.png)

*Sample apps and sample coverage results.*

### Schedule

A day theme and a night theme, switched at the times you set, or at **sunrise
and sunset** where you are (worked out in the picker from your coordinates,
nothing looked up online), each moved by an offset if you like. A theme picked
by hand holds until the next switch, then the schedule takes over again.

Or a **theme of the day**: a random pick every morning. Or a **rotation**: a
new theme every few hours, picked at random from your favourites or every
theme, or a **collection** (Winter all winter, say), or taken **in order from
your own list** (seven themes every 24 hours is a theme per weekday). Random picks never choose a hidden or disliked
theme. One schedule runs at a time.

![Day/night schedule: Catppuccin Latte from 07:00, Catppuccin Mocha from 19:30](docs/screenshots/schedule.png)

### Editor

Build a theme from any existing one, from an image, or by **importing a colour
scheme**: paste a base16/base24 YAML, a Ghostty, Kitty, Alacritty, Xresources or
Windows Terminal scheme, an iTerm2 `.itermcolors` file or a VS Code theme, and it
is mapped onto the fields and made readable. Everything is parsed in the browser.
The preview updates as you edit, with a contrast ratio for each text role, and a
second preview shows the theme's **light or dark twin**.

From any theme's preview, **Edit a copy** opens its colours in the editor, and
on a low-contrast theme **Make a readable copy** opens a copy with every text
role brought to 7:1 (body) or 4.5:1, moving only lightness (and darkening the
page where no text colour could otherwise reach it).

*Save & deploy* adds it to your custom themes and deploys it to theme.park. See
[DEPLOY.md](DEPLOY.md#custom-themes). **Copy share link** puts the colours in a
link (in the part after `#`, which is never sent to a server); whoever opens
it gets them in their own picker's editor, unsaved.

![The theme editor with colour fields, a live preview and contrast ratios](docs/screenshots/editor.png)

### Stats

Which themes spent the most time on screen and which were applied most,
counted from changes made in the picker, and your liked and disliked themes
with how the random picks used them. Where the screenshot capture runs, Stats
also lists the themes its last run photographed and its last 14 runs: when,
how long, and any shots that failed.

![Usage stats: most time on screen and most applied, over three weeks](docs/screenshots/stats.png)

*Sample three-week history and sample capture runs.*

## Accessibility

The picker wears whichever theme is live, and some themes' own colours are
too faint for small text. So the picker checks the live theme's text, muted
text and button labels and, where one falls under 4.5:1, moves only its
lightness until it reads, for the picker's own interface. (The apps keep the
theme exactly as it is; a theme's *Make a readable copy* is the fix there.)
Every control has a name for screen readers, and everything works from the
keyboard: `/` to search, arrow keys between themes, `P` for a preview,
`Escape` to close it.

## Install it as an app

Served over HTTPS, the picker can be installed like an app: *Install* in
Chrome or Edge's address bar, or *Add to Home Screen* on a phone. It opens in
its own window, with the live theme's colour as its toolbar. On a phone the
filters fold into a drawer and tiles sit two to a row:

<img src="docs/screenshots/phone.png" alt="The picker on a phone: the live theme, Surprise me and Undo at the top, two theme tiles per row" width="300">

## License

[MIT](LICENSE)

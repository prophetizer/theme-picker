# Theme Picker

A web interface for choosing one colour theme and having every self-hosted app
behind the reverse proxy wear it at once, with the tools around that choice:
previews, schedules, pins and custom themes.

## Themes

**Theme**:
A named set of colours that dresses every app the same way.
_Avoid_: Skin, style, palette (a palette is where a theme's colours come from)

**Live theme**:
The theme every app is wearing right now.
_Avoid_: Current theme, active theme

**Origin**:
Where a theme comes from: Official, Community or Custom.

**Official theme**:
A theme theme.park ships and maintains itself.

**Community theme**:
A theme theme.park ships on behalf of outside contributors.

**Custom theme**:
A theme of your own, not shipped by theme.park, however it was made: by hand,
ported from a published scheme, built in the editor, or generated as a twin.
_Avoid_: Hand-made theme (as an origin), variant

**New theme**:
A custom lead added in the last 14 days. Generated twins are never new.

**Low-contrast theme**:
A theme whose body text is under 4.5:1, or whose muted text or button labels
are under 3:1. Every other theme is readable.

**High-contrast theme**:
A theme whose every text role reaches 7:1 (WCAG AAA).

## Light and dark

**Mode**:
Whether a theme's background is light or dark.

**Pair**:
A theme together with its opposite-mode counterpart, recognised by name: the
two names differ only by "dark" or "light". Counterparts named differently,
like Catppuccin Latte and Mocha, are separate themes, each with its own twin.

**Form**:
One half of a pair: its light form or its dark form.

**Twin**:
The other form of the same pair, seen from one form.
_Avoid_: Variant

**Generated twin**:
A twin the tooling made from its form by flipping the mode.

**Authored twin**:
A twin the theme's own author made, as with PaperColor Light and Dark.

**Lead**:
The form a pair is listed and hidden under: the source of a generated twin, or
of an authored pair the form without "dark" or "light" in its name, else the
dark one.

## Browsing

**Section**:
Where a theme sits in the grid: custom themes split into dark, light, gradient
and editor-made, then community, then official.
_Avoid_: Group, category

**Preview**:
A theme's preview window: its screenshots, the themes that look like it, how
it reads with colour-vision deficiencies, and export.
_Avoid_: Lightbox

**Share link**:
A link that shows the picker dressed in a theme without applying it.
_Avoid_: Preview link

**Editor share link**:
A link that carries a set of editor colours to someone else's editor, unsaved.

## Curating

**Hidden theme**:
A theme left out of the grid and of every random pick, both forms together.

**Hidden form**:
One form of a pair left out on its own; the pair stays, shown in its other form.

**Favourite**:
A theme you starred; your favourites are a pool and a filter.

**Rating**:
Liked or disliked. A liked theme comes up three times as often in random
picks; a disliked one never does, though it stays in the grid.
_Avoid_: Favourite (a different thing)

**Collection**:
A named set of themes: built in (Light, Dark, High contrast, the four seasons)
or your own.
_Avoid_: Group, set, list

## Changing the live theme

**Schedule**:
An automatic way the live theme changes: Day/night, Theme of the day or
Rotation, one at a time.
_Avoid_: Automation, timer

**Pool**:
The themes a random pick may draw from: your favourites, every theme, or a
collection. Hidden and disliked themes are never in it.

## Apps

**Pin**:
A fixed theme for one app, which it keeps whatever the live theme is.
_Avoid_: Override

**Themed app**:
An app the picker dresses in the live theme or its pin.

**Coverage**:
The share of themed apps actually wearing the theme they should; one that
isn't is missing its theme.

**Dashboard**:
A start page (Homepage, Glance, Homarr) that follows the live theme through a
stylesheet the picker serves, rather than being dressed like a themed app.

**App group**:
A named set of apps you pin to one theme together.
_Avoid_: Group (on its own), collection

## Screenshots

**Capture run**:
One pass of the screenshot capture through the themes, photographing the apps
in each.

**Screenshot**:
One image of one app wearing one theme.
_Avoid_: Snapshot, shot

**Orphan screenshot**:
A screenshot of a theme that no longer exists.

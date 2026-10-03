# Home Assistant recipes

Theme Picker's automation hook lets Home Assistant set the theme of every app
at once. Set it up once (step 1), then use any of the recipes below.

## 1. The hook and a `rest_command`

On the picker side, put a long random token in a file and point
`hooks.token_file` at it (see [DEPLOY.md](../DEPLOY.md#automation-hook)). With
no token file, the hook is off and answers 404.

In Home Assistant, keep the token in `secrets.yaml`, including the word
`Bearer`:

```yaml
# secrets.yaml
theme_picker_auth: "Bearer 4f0c...your-token..."
```

Then add one `rest_command` to `configuration.yaml` and restart Home
Assistant:

```yaml
rest_command:
  set_theme:
    url: https://theme-picker.example.com/api/hook/theme
    method: POST
    headers:
      Authorization: !secret theme_picker_auth
    content_type: application/json
    payload: >-
      {"theme": "{{ theme }}", "source": "{{ source | default('home assistant') }}",
       "notify": {{ 'true' if notify | default(false) else 'false' }}}
```

- `theme`: a theme's name as the picker shows it (`nord`, `catppuccin-latte`),
  or `random-favourite`, which picks one of your starred themes other than the
  live one. Liked themes come up three times as often, and disliked ones never.
- `source`: shown in the picker's history as "automation (…)". Up to 40
  letters, digits, spaces and `.'-`.
- `notify`: `true` also sends the picker's ntfy notice for the change.

**Reaching the picker:** if Home Assistant shares a Docker network with the
picker, `http://theme-picker:8090/api/hook/theme` avoids the proxy and its
login. A one-word host name like that is always allowed. Through the proxy,
the request has to get past whatever authentication sits in front of the
picker.

To test it, go to Developer tools, then Actions, run
`rest_command.set_theme` with `theme: nord`, and check that the apps change.

A theme set this way is like a click in the picker: it holds until the
picker's own schedule (if one is on) next switches.

## 2. Day and night by the sun's height

The picker's own schedule can follow sunrise and sunset. In Home Assistant
you can go further and use the sun's elevation, for example switching to dark
once the sun is 4° below the horizon (civil dusk), when rooms actually get
dark:

```yaml
automation:
  - alias: "Themes: dark at dusk"
    trigger:
      - platform: numeric_state
        entity_id: sun.sun
        attribute: elevation
        below: -4
    action:
      - service: rest_command.set_theme
        data: {theme: catppuccin-mocha, source: dusk}

  - alias: "Themes: light at dawn"
    trigger:
      - platform: numeric_state
        entity_id: sun.sun
        attribute: elevation
        above: 3
    action:
      - service: rest_command.set_theme
        data: {theme: catppuccin-latte, source: dawn}
```

Leave the picker's own day/night schedule off when Home Assistant does this,
or the two will take turns.

## 3. A new theme when someone comes home

```yaml
automation:
  - alias: "Themes: welcome home"
    trigger:
      - platform: state
        entity_id: zone.home
        from: "0"
    action:
      - service: rest_command.set_theme
        data: {theme: random-favourite, source: welcome home, notify: true}
```

`zone.home` counts the people at home, so this fires when the first person
arrives.

## 4. Buttons on a dashboard

A script per theme, with a button for each:

```yaml
script:
  theme_movie_night:
    alias: Movie night theme
    sequence:
      - service: rest_command.set_theme
        data: {theme: tokyo-night, source: movie night}
  theme_surprise:
    alias: Surprise me
    sequence:
      - service: rest_command.set_theme
        data: {theme: random-favourite, source: dashboard}
```

```yaml
# a dashboard card
type: horizontal-stack
cards:
  - type: button
    name: Movie night
    icon: mdi:movie-open
    tap_action: {action: perform-action, perform_action: script.theme_movie_night}
  - type: button
    name: Surprise me
    icon: mdi:palette
    tap_action: {action: perform-action, perform_action: script.theme_surprise}
```

## 5. Follow the media player

Set a dark theme while a film plays in the living room, and put back a
favourite afterwards:

```yaml
automation:
  - alias: "Themes: cinema"
    trigger:
      - platform: state
        entity_id: media_player.living_room
        to: playing
    action:
      - service: rest_command.set_theme
        data: {theme: tokyo-night, source: cinema}
  - alias: "Themes: after the film"
    trigger:
      - platform: state
        entity_id: media_player.living_room
        from: playing
        for: "00:05:00"
    action:
      - service: rest_command.set_theme
        data: {theme: random-favourite, source: after the film}
```

## When it doesn't work

| Answer | Meaning |
|---|---|
| 404 `not found` | No token file is set: the hook is off. |
| 401 `bad or missing token` | The `Authorization` header is missing, or doesn't match the token file. Check the `Bearer ` prefix. |
| 400 `Rejected: '…' is not a known theme.` | The name isn't one the picker knows; copy it from the picker. |
| 400 `no favourite themes to pick from` | `random-favourite` needs some starred themes, and not all of them disliked. |
| 421 | The host name isn't one the picker answers to; add it under `allowed_hosts`. |
| A login page instead of JSON | The request went through the proxy's authentication. Use the internal address, or let the proxy pass `/api/hook/` (the token is the protection there). |

# Pairs are recognised by name only

Two themes form a light/dark pair only when their names differ by "dark" or
"light" (Gruvbox and Gruvbox Light, Ayu Dark and Ayu Light). Counterparts whose
authors named them differently — Catppuccin Latte and Mocha, Rosé Pine and Rosé
Pine Dawn, Tokyo Night and Tokyo Night Day — stay separate themes, and each gets
its own generated twin. The rule is automatic: every theme added, whatever its
origin, pairs or not without anyone keeping a list, and the theme-making tools
use the same rule to decide whether a twin needs generating.

## Considered Options

- **Name rule plus a hand-kept list of authored pairs.** Turned down: it would
  remove a few redundant generated twins, but someone has to keep the list in
  step with theme.park and the custom themes, in two code bases (the picker and
  the twin generator), and a missed entry fails silently.

## Consequences

Hidden themes, ratings, collections and pins all refer to pairs through their
lead, so changing the rule later re-pairs themes under them. Some authored
counterparts also appear next to a generated twin of the same mode (Catppuccin
Latte's generated dark twin beside Catppuccin Mocha).

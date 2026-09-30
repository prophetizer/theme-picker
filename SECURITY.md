# Security policy

## Reporting a vulnerability

Please report security issues privately, not in a public issue: use
GitHub's **[Report a vulnerability](https://github.com/prophetizer/theme-picker/security/advisories/new)**
form (Security tab → Advisories). Include what you found, how to reproduce
it, and which version or commit you tested.

You'll get an acknowledgement within a week. Fixes go into a new release,
and the advisory is published once one is available.

## Supported versions

Only the latest release (and `main`) gets security fixes.

## Deployment notes

Theme Picker changes the theme of every app it manages, so treat it as an
admin tool: keep it behind your reverse proxy and its authentication, and
don't publish port 8090. [DEPLOY.md](DEPLOY.md#5-protect-it) covers what the
picker protects against on its own and what it leaves to the proxy.

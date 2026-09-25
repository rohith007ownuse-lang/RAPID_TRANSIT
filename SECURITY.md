# Security policy

## Supported

FLEET-IQ is a research and demonstration prototype. The maintained surface is
the current `main` branch.

## How auth works (so reviewers know what to expect)

- Passwords: PBKDF2-SHA256, 260k iterations, per-user salt. Never plaintext.
- Sessions: opaque bearer tokens, server-side in SQLite, 12 h default TTL.
- Roles: `operator` < `supervisor` < `admin`, enforced backend-side on every
  privileged endpoint. The frontend role is display-only.
- Production mode (`FLEETIQ_ENV=production`): all reads authenticated (only
  `/api/health` and `/api/auth/login` stay open), startup refuses default
  passwords and missing CORS configuration.
- Development default login is `admin` / `admin123`. It exists so a fresh
  clone runs out of the box; production refuses to start with it.

## Reporting a vulnerability

Please report privately — open a GitHub **private vulnerability report** on
this repo (Security tab → Advisories), or email the maintainers. Include:

1. What you found and where (`file:line` if possible).
2. The impact in plain terms (who can do what).
3. Steps to reproduce, if safe to share.

We will acknowledge within 7 days and aim to fix critical issues within 30.
Please do not probe public demo tunnels beyond normal use of the UI.

# Contributing to FLEET-IQ

Thanks for stopping by. A few ground rules that keep this project honest and demo-ready.

## Before you change code

1. Read [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md). The single most important
   rule in this repo: **never present an estimate as a measurement.**
   Every new value on screen needs a source label — `SIMULATION`, `MODEL`,
   `HEURISTIC`, or `LIVE` — and unknown must render as `—`, never `0`.
2. New thresholds (like hotspot rules) must travel with the API payload, not
   hide in frontend strings — see how `/traffic/hotspots` carries `radius_m`
   and `min_buses`.
3. Tests use an isolated per-test SQLite database (`backend/tests/conftest.py`).
   The real `control_centre.db` must never be touched by tests or scripts.

## Workflow

```bash
git checkout -b feat/short-description
# ... work ...
cd control_centre/backend && venv/bin/python -m pytest -q
cd ../../frontend && npm test && npm run build
git commit -m "Short imperative summary"
```

- One concern per pull request.
- Commit messages are imperative ("Fix …", "Add …"), scoped, and explain *why*
  when the change is not obvious.
- Update `SESSION_CHANGELOG.md` with a short entry for user-visible changes.

## Pull requests

Fill in the PR template: what changed, how it was verified (tests / manual
run), and which source labels are affected. CI must be green (backend tests +
frontend build + frontend tests).

## Security issues

Do not open a public issue for vulnerabilities. See [SECURITY.md](SECURITY.md).

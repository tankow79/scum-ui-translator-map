# Contributing

Thanks for helping! The app is a PyQt6 desktop program for Windows 10/11.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
```

## Checks (run before every pull request)

```bash
python -m ruff check .
python -m pytest
```

Tests run headless (`QT_QPA_PLATFORM=offscreen` is set automatically in CI).

## Project layout

| Folder | Purpose |
|---|---|
| `core/` | UI-independent logic: parsing, translation, filtering, history, profiles, updater |
| `ui/` | PyQt6 windows and widgets |
| `utils/` | Windows API helpers |
| `assets/locales/` | UI translations (`<code>.json`) |
| `tests/` | pytest suite |
| `docs/` | Architecture notes and guides |

## Guidelines

- Keep business logic in `core/` so it can be tested without Qt widgets.
- Every user-visible string goes through `tr("section.key")`; add the key to `assets/locales/en.json`.
- Code, comments and commit messages are in English.
- New settings need a default in `core/config_manager.py` and a toggle in the settings window.
- Never write user data inside the update flow (`config.json`, `points.json`, `profiles.json` are protected).

## Adding a language

See [docs/ADDING_A_LANGUAGE.md](docs/ADDING_A_LANGUAGE.md).

## Releasing

1. Bump `__version__` in `core/version.py` and `version_info.txt`, update `CHANGELOG.md`.
2. Commit, then `git tag vX.Y.Z && git push origin main vX.Y.Z` — the workflow builds both executables.
3. Publish the draft release on GitHub (the in-app updater picks up the `.exe` asset of the latest release).

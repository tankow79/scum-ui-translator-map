# Changelog

All notable changes to this project are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [2.1.1]

### Added
- Releases now include a full `.zip` package (exe + certificate installer + instructions) next to the standalone `.exe` files.

- README rewritten: step-by-step quick start, SmartScreen ("Windows protected your PC") explanation, troubleshooting; README translations are organised in `docs/readme/`.
- The zip no longer ships the self-signed certificate installer (the CI-built exe is not signed with it, and adding a root certificate is not recommended).

All 2.1.0 changes below ship in this release.

## [2.1.0]

### Fixed
- **Auto-update now really updates the app.** The old updater downloaded a file to a hidden temp folder and
  relied on a batch script that silently failed. The new updater saves the build to
  `%LOCALAPPDATA%\SCUM_Chat_Translator\updates`, verifies it (size, `MZ` header, SHA-256 when GitHub provides
  a digest), swaps the running `.exe` in place (the previous build is kept as `.old` until the next start,
  automatic rollback on failure) and restarts the app. It picks the Normal or Portable build to match the
  running one and never installs a source-code archive.
- "Clear all" waypoints now asks for confirmation.
- `profiles.json`, `config.json` and `points.json` are never touched by updates; writes are atomic.
- Missing `requests` dependency added to `requirements.txt`.

### Added
- Steam-style compact update window: progress bar, speed, ETA, cancel, retry and release notes.
- Background update checks every N hours (configurable).
- Chat history window: search, filters (player, type, translated only), export to TXT / CSV / JSON,
  optional on-disk persistence.
- Blocked-word filter (mask / hide / show untranslated, whole-word and case options).
- Language auto-detection that skips needless translation (offline script detection + service result).
- Settings profiles (switch from Settings or the tray menu).
- Waypoint import / export (JSON) with merge or replace.
- Language tab; locales are discovered automatically from `assets/locales/*.json`.
- Rotating log file in `%LOCALAPPDATA%\SCUM_Chat_Translator\logs`.

### Changed
- Interface ships in English only (`uk` / `ru` translations archived in `docs/locales_archive`).
- Application controller moved out of `main.py` into `core/controller.py`; code comments are English.
- CI (lint + tests) and release build workflows added; repository no longer tracks personal data or binaries.

## [2.0.0]
- Multi-language interface, standalone map from the tray, squad chat colour, blacklist fix, autostart.

## [1.1.0]
- Five-tab settings window and the first auto-updater.

## [1.0.0]
- Initial release: tactical map with GPS capture and real-time chat translator overlay.

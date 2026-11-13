# Changelog

All notable changes to this project are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [2.4.0]

### Added
- **Settings -> Players**: the nickname <-> SteamID base. Clickable SteamIDs open the Steam profile; players who renamed expand into a list of old nicknames with the date of each change. Old nicknames or whole players can be deleted, or the whole base cleared, always after a confirmation.
- **Collect SteamIDs** switch (Settings -> Players, on by default). Off: nothing is read or stored. On: all current and old logs are scanned.
- On first launch the app reads **all existing logs** (including old `SCUM-backup-*.log`) to learn every nickname and SteamID; later starts read only what is new.

### Changed
- SteamIDs are never typed by the user any more: bases link to players by the nickname you enter (current or old) and follow renames automatically.
- The map hover card for a base now appears under the cursor and stays open while you move onto it. Each player has a 🔗 button that opens the Steam profile; a player who renamed shows the nickname as a drop-down (▾) that opens a small list with the date of each change and the old nickname.

### Fixed
- The player registry was never filled while the game ran (the log parser passed the nickname and SteamID to the registry in swapped order).

## [2.3.0]

### Added
- **Player registry (`players.json`)**: the app records every player's permanent SteamID64 and current nickname from the `Message from user:` log lines. Nickname changes are tracked automatically.
- **Base players by SteamID**: in a base's players field you can enter a nickname, a SteamID64 or a `steamcommunity.com/profiles/…` link. Linked players follow nickname changes automatically, and hovering a base on the map shows a card with clickable Steam profile links (also in the base's right-click menu).
- **Squadmates setting** (Settings -> Chat -> Players): nicknames listed there are shown in green in the overlay chat.

### Changed
- Overlay chat now mimics the in-game chat: Bahnschrift SemiBold SemiCondensed font (22 px by default), a partial black outline on the right/bottom edges only, one colour for the whole line, and the `[dd/mm/yyyy - HH:MM:SS]` timestamp in local time (SCUM.log stores UTC). Squad green `#C2F800`, other chat blue `#00E6F3`, server messages yellow.
- Overlay chat colours: squadmates green; everything else blue (server messages included); a colour given in the message itself (`<color=#rrggbb>`, `[color=#rrggbb]`, `<font color="#rrggbb">`) is used as is and the tag is hidden.

### Fixed
- Chat timestamps are now local time, matching the in-game chat (SCUM.log stores UTC).

## [2.2.0]

### Added
- **Ukrainian interface** (`uk.json`) next to English; switch it in Settings -> General -> Language. Ukrainian README at `docs/readme/README.uk.md`.
- Update backups are verified byte-for-byte; a failed backup cancels the update. Damaged or missing `config.json` / `points.json` / `profiles.json` are restored at startup, and backups are deleted automatically after a healthy start.

### Changed
- **Settings redesigned:** a sidebar with 5 sections (General, Chat, Appearance, Hotkeys, Profiles) replaces 8 crowded tabs; labels and checkboxes wrap, button rows flow onto new lines.
- Layouts of the waypoints, map, quick chat, overlay, history, tray menu and stock dialogs rebuilt so long translations never overflow; shared dark theme.
- Language list shows "English name - native name" without flag emoji; waypoint category names are translatable.
- Update check interval applies immediately; "Map & Waypoints" no longer loses its `&` in menus.

### Fixed
- Leftover `.update_backup` folder and `*.bak` files after updating.
- Cut-off buttons and labels in the waypoints window and settings.

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

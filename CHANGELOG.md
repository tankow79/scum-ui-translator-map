# Changelog

All notable changes to this project are documented here. Format based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [Unreleased]

## [2.4.2] - 2026-11-13

### Fixed
- **Clear-all-waypoints confirmation redesigned:** a tidy dialog with a warning icon, bold heading, muted explanation, the confirmation tick and right-aligned buttons (the text no longer drifts to the right).
- **Global hotkeys no longer fire outside the game:** F8 / F9 / Ctrl+M / Escape pressed in a browser or an editor used to open the map, unlock the overlay or hide windows. The chat key `T` no longer opens the chat while you type the letter in the map search or a settings field, and Escape no longer closes Settings from underneath a hotkey-recording button.
- Deleted or renamed waypoints no longer come back when the game log is replayed at start-up (deleted chat lines are remembered).
- Pressing Enter in the quick chat could copy the translation of the previous text, and froze the overlay on a bad connection; it now waits for the translation of the current text in the background.
- Overlay, map, waypoint list and the ON/OFF badge keep their position on a second monitor (also one left of the main monitor) instead of jumping to the main one; the overlay can no longer be smaller than its content (the quick-chat bar was cut off at the edge) and is fully repainted after every mode change.
- The waypoint list always stays above the map.
- Settings: conflicting or reserved hotkeys are refused with a message; hotkeys are recorded by physical key (Ukrainian layout, numpad, F13+); holding a key no longer repeats the action; the keyboard hook is restarted if Windows drops it; "keep on top" and "keep history" apply immediately; switching a profile from the tray while Settings is open no longer lets Save overwrite it; created / renamed profiles appear in the tray menu; profile errors are translated; hand-edited numbers in `profiles.json` can no longer crash Settings; "Map only" no longer leaves the overlay unlocked.
- Players: a new game session whose `SCUM.log` is already bigger than the previous one is read from its start (it used to be skipped).
- Imported waypoints get their pin position and sector from the game coordinates (minimal or edited files no longer show sector `??`); points exactly on a grid line stay in their own sector.
- CSV export neutralises spreadsheet formulas coming from other players' names and messages.
- Unnamed waypoints show the placeholder instead of the word "None"; the map hover card no longer shows stale data after an edit; `&` in names displays correctly; a second copy of the program cannot start by mistake or damage the running app's settings.
- **A log line with thousands of spaces froze the log reader for ~20 s** (regex backtracking in the `Message from user:` parser); it now parses from the right in linear time.
- Damaged or hand-edited waypoints (NaN / infinite / absurd coordinates, wrong types, a non-text id) are repaired or skipped instead of reaching the map; imports reject waypoints without a usable position.
- Translation replies are validated: an empty, non-text, 2 MB or otherwise nonsensical answer (or a bogus language code) falls back to the original message and is never cached.
- Offline / dead connection: a message spends at most 7 s on the network, after repeated failures the app stops trying for a few seconds (growing to 60 s) and shows originals immediately; the chat keeps its order during an outage.
- A configured Google API key is sent in a header, not in the URL, so it can no longer end up in log files.
- Update check: a captive portal / proxy page, a dropped connection, HTTP 429 or an oversized reply give a plain message (localized) instead of raw technical text.
- When the program folder is read-only (Program Files, a protected drive) settings and waypoints are kept in `%LOCALAPPDATA%\SCUM_Chat_Translator` instead of being lost at every restart.
- Translations no longer garble coordinates (`-100000.500` became `-100000,500`); the `{X= Y= Z=}` block is always kept exactly.
- Waypoint list stays above the map when the map is clicked (it is now owned by the map window); chat-made point names no longer contain a double space.
- During a burst of messages the chat stays in order: a message waiting in the translation queue no longer counts as "too slow".
- Concurrent saves of `config.json` could, rarely, write an older snapshot last and lose a setting.
- The test-suite no longer needs the network (translation requests are faked), so it is deterministic.

### Added
- **Chat abbreviations** (`GG`, `GGNT`, `GL HF`, `BRB`, `AFK`, `KOS`, `ty`, Cyrillic `гг`, `спс` ... about 350 of them): shown with their full meaning in the chat language (`GGNT` -> "Гарна гра, непогана спроба"). Settings -> Chat lets you translate them, show the English meaning, or leave them as typed. Ambiguous short ones (`ty`, `u`, `np`...) are expanded only when the whole message is made of abbreviations, so Polish "ty" is never turned into "thank you".
- Overlay: when you scroll up and new messages arrive, the chat no longer jumps; a "New messages" button appears at the bottom centre instead. Closing the chat returns to the newest messages. Text can be selected and copied without the chat being rebuilt under it.
- Points: "Clear" now needs a tick box and an explicit "Yes, I confirm the deletion".

## [2.4.1] - 2026-11-13

### Fixed
- **Start-up crash of v2.4.0** (`ScumLogParser` lost `_running`). The release build and the updater now start the application in a `--smoke-test` mode and refuse to publish/install a build that cannot start.
- Updates are safe: the downloaded build is self-tested before it replaces the current one, the previous build is kept until the new one has run healthy (it used to be deleted at start-up), and a new build that fails to start right after an update is rolled back automatically.
- A new build that keeps crashing later than start-up (2 unclean runs in a row, each shorter than 10 minutes) is rolled back to the previous build; the previous build is removed only after 10 minutes of healthy running.
- Importing thousands of waypoints no longer freezes the points window (rows are built in batches).
- Unhandled exceptions in Qt slots and threads are logged instead of silently closing the app.
- Malformed coordinates in chat (`{X=. Y=1 Z=2}`) could crash the app.
- Log reading: a message that is still being written is no longer cut in half; changing the log path in Settings takes effect immediately; the chat backlog replayed at start no longer adds duplicate waypoints.
- Failed translations are no longer cached forever; the translation cache is bounded.
- `config.json`, `points.json`, `profiles.json`, `players.json` are written atomically; an unreadable file is kept as `*.corrupt-<time>` instead of being overwritten; saving settings writes the file once; moving windows no longer writes it on every mouse move.
- Settings: cancelled edits no longer reappear; creating a profile notifies the running app; opacity no longer drifts by 1% per save.
- Update dialog: cancelling a download is not reported as an error, closing during installation is blocked, and the restart safety net actually fires.
- Overlay: the chat is not rebuilt every 500 ms (scrolling works again), Enter no longer freezes on a network error.
- Map: re-opening keeps zoom/position and the focus on a waypoint; the tactical map is no longer replaced by an empty image.
- Chat messages are shown in chat order even when translations finish at different times (a hanging translation waits at most 6 s).
- `SCUM.log` is opened so the game can still rotate it to `SCUM-backup-*.log`, and a rotated log is detected and followed.
- Update errors, file-dialog filters and the nickname placeholder are translated; the portable edition is recognised by a bundled flag, not by the exe name; a damaged `config.json` never replaces a good update backup.
- CI builds the real executables and starts them on every push; builds use pinned, tested dependency versions; Python 3.12/3.13 are the supported versions.
- **Map performance:** panning and zooming no longer stutter or lower the game's frame rate. Only the visible part of the map is drawn, redraws are limited to ~60 per second while moving (full quality returns when you stop), and every pin with its name tag is rendered once and reused (about 6x faster with 150 pins on screen).
- Hand-edited values of the wrong type in `config.json` fall back to the default instead of crashing the start; a second launch now says the app is already running; the portable build has its own version resource; a replace-import of a file without valid waypoints no longer wipes your waypoints.
- History export adds the file extension; the old-nickname delete button removes the right entry; the colour-dialog guard works.

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

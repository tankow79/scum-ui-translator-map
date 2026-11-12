# Architecture

```
SCUM.log ──> ScumLogParser (thread) ──> AppController.raw_message_received
                                              │
                    ┌─────────────────────────┤
                    │ coordinates             │ chat
                    ▼                         ▼
            PointsManager              ChatFilter  (nickname + blocked words)
            (points.json)                     │
                    │                         ▼
                    ▼                 language auto-detect (offline) ──> skip? ──┐
              MapWindow / PointsWindow        │                                   │
                                              ▼                                   │
                                    GoogleTranslatorEngine (thread pool)          │
                                              │  post-check on detected language  │
                                              ▼                                   ▼
                                     AppController._publish ──> ChatHistory + translated_ready ──> ChatOverlay
```

## Modules

| Module | Responsibility |
|---|---|
| `main.py` | Application bootstrap: tray, windows, hotkeys, wiring |
| `core/controller.py` | Message pipeline (filter → detect → translate → history) |
| `core/message_filter.py` | Nickname blacklist and blocked-word rules (pure logic) |
| `core/language_detect.py` | Offline script-based language detection |
| `core/translator.py` | Google translation with host rotation and cache |
| `core/chat_history.py` | Bounded history, JSONL persistence, TXT/CSV/JSON export |
| `core/profiles.py` | Named presets of chat/HUD settings (`profiles.json`) |
| `core/points_manager.py` | Waypoints storage (atomic writes), JSON import/export |
| `core/updater.py` | Release check, download, verification, in-place install |
| `core/i18n.py` | Locale discovery (`assets/locales/*.json`) and `tr()` |
| `core/config_manager.py` | `config.json` with defaults for every setting |
| `ui/*` | PyQt6 windows; no business logic beyond presentation |

## Design rules

- `core/` modules (except those that expose Qt signals) do not import widgets and are unit tested directly.
- Settings are plain keys in `config.json`; the settings window writes them, the controller reads them live, so
  toggles take effect without restart.
- Files next to the `.exe` (`config.json`, `points.json`, `profiles.json`) are user data; everything bulky
  (history, logs, downloaded updates) lives in `%LOCALAPPDATA%\SCUM_Chat_Translator`.

## Update flow

1. `UpdateChecker` → GitHub `releases/latest`, `select_asset()` picks `.exe` / `.zip` matching Normal or Portable build.
2. `UpdateDownloader` → `updates/<asset>.part` → verified → renamed.
3. `UpdateInstaller.apply_update` → running `.exe` renamed to `.old`, new `.exe` moved into place (rollback on error).
4. `restart_application` starts the new build with `--post-update` (it waits for the old process to release the
   single-instance mutex); the old process quits. `cleanup_leftovers()` removes `.old` on the next start.

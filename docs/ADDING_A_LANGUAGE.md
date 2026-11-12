# Adding an interface language

Languages are discovered automatically; no code changes are needed.

1. Copy `assets/locales/en.json` to `assets/locales/<code>.json` (for example `de.json`, `pl.json`, `uk.json`).
2. Set the display name shown in the **Language** tab:

   ```json
   "_meta": { "name": "Deutsch" }
   ```

3. Translate the **values** only. Keep the keys and the `{placeholders}` (`{version}`, `{count}`, ...) unchanged.
4. Restart the app, open **Settings -> Language** and pick the new language.

Missing keys fall back to English, so a partial translation works. `python -m pytest tests/test_i18n.py` checks that
a locale does not contain keys unknown to English.

Earlier Ukrainian and Russian translations are kept in `docs/locales_archive/` as a starting point (they predate the
2.1.0 keys, so some texts will be missing and fall back to English).

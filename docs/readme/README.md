# README translations

The main [README.md](../../README.md) is the English master. Translations live here as `README.<code>.md`
(for example `README.de.md`, `README.uk.md`, `README.pl.md`).

## Available languages

| Language | File |
|---|---|
| English | [README.md](../../README.md) (master) |

## Adding a translation

1. Copy `README.md` from the repository root to `docs/readme/README.<code>.md`.
2. Translate the text; keep the links, images (`../images/...`), badges and code blocks. Fix relative links
   (they need an extra `../../`).
3. Add a row to the table above and add the language name to the **README languages** line near the top of the
   root `README.md`.
4. Keep the SmartScreen section: it is the most important part for new users.

An older Ukrainian README is kept in [`docs/locales_archive/README.uk.old.md`](../locales_archive/README.uk.old.md)
as a starting point (it predates v2.1; sections on history, filters, profiles and the new updater are missing).

The application interface itself is translated separately, see [ADDING_A_LANGUAGE.md](../ADDING_A_LANGUAGE.md).

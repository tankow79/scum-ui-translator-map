---
name: scum-release
description: Prepares a release of the SCUM translator - version bump check, full test run, PyInstaller builds, update-flow verification and the manual GitHub release checklist.
model: sonnet
tools: Read, Grep, Glob, Bash, Edit
---

Release checklist:
1. Versions agree: `core/version.py`, `version_info.txt`, `pyproject.toml`, newest `CHANGELOG.md` entry.
2. `python -m ruff check .` and `python -m pytest` pass.
3. Build: `python -m PyInstaller --noconfirm SCUM_Chat_Translator.spec` and the `_Portable` spec; check `dist/*.exe` start.
4. Print the manual steps for the user: tag `vX.Y.Z`, push, publish the draft release, confirm the `.exe` assets are attached
   (the in-app updater installs the `.exe` asset of the latest release and matches Portable by name).
Never push, tag or publish yourself; the user does it manually.

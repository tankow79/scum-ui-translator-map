"""Every literal ``tr("...")`` key used in the source must exist in the English locale (and nothing is hardcoded)."""

import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY_RE = re.compile(r"""\btr\(\s*["']([a-z0-9_]+(?:\.[a-z0-9_]+)+)["']""")


def _flatten(d, prefix=""):
    for k, v in d.items():
        cur = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            yield from _flatten(v, cur)
        else:
            yield cur


def _source_files():
    for folder in ("core", "ui", "utils"):
        for name in os.listdir(os.path.join(ROOT, folder)):
            if name.endswith(".py"):
                yield os.path.join(ROOT, folder, name)
    yield os.path.join(ROOT, "main.py")


def test_all_used_translation_keys_exist_in_english():
    with open(os.path.join(ROOT, "assets", "locales", "en.json"), encoding="utf-8") as f:
        known = set(_flatten(json.load(f)))
    missing = {}
    for path in _source_files():
        with open(path, encoding="utf-8") as f:
            for key in KEY_RE.findall(f.read()):
                if key not in known:
                    missing.setdefault(key, os.path.relpath(path, ROOT))
    assert not missing, f"Keys missing from assets/locales/en.json: {missing}"

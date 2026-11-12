import os
import py_compile

import pytest

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

def get_project_files():
    files = []
    for root, dirs, filenames in os.walk(ROOT_DIR):
        if any(d in root for d in [".venv", "__pycache__", ".idea", ".git"]):
            continue
        for f in filenames:
            if f.endswith((".py", ".json", ".md")):
                files.append(os.path.join(root, f))
    return files

def test_all_files_utf8_encoding():
    """Check that all project files are valid UTF-8 with no corrupted bytes."""
    files = get_project_files()
    assert len(files) > 0, "No files found to check"

    for file_path in files:
        with open(file_path, "rb") as f:
            raw = f.read()

        # 1. Check UTF-8 validity
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            pytest.fail(f"File {file_path} contains invalid UTF-8 bytes: {e}")

        # 2. Check there are no NUL bytes
        assert "\x00" not in content, f"File {file_path} contains forbidden NUL bytes"

def test_all_python_files_syntax():
    """Syntax validation of all project Python files via py_compile."""
    py_files = [f for f in get_project_files() if f.endswith(".py")]
    assert len(py_files) > 0, "No Python files found"

    for py_file in py_files:
        try:
            py_compile.compile(py_file, doraise=True)
        except py_compile.PyCompileError as e:
            pytest.fail(f"Syntax error in {py_file}: {e}")

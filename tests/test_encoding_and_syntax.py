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
    """Перевірка, що всі файли проєкту закодовані у валідному UTF-8 без пошкоджених байтів."""
    files = get_project_files()
    assert len(files) > 0, "Не знайдено жодного файлу для перевірки"

    for file_path in files:
        with open(file_path, "rb") as f:
            raw = f.read()

        # 1. Перевірка на валідність UTF-8
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as e:
            pytest.fail(f"Файл {file_path} містить невалідні UTF-8 байти: {e}")

        # 2. Перевірка на відсутність NUL байтів
        assert "\x00" not in content, f"Файл {file_path} містить заборонені NUL байти"

def test_all_python_files_syntax():
    """Синтаксична валідація всіх Python файлів проєкту через py_compile."""
    py_files = [f for f in get_project_files() if f.endswith(".py")]
    assert len(py_files) > 0, "Не знайдено Python файлів"

    for py_file in py_files:
        try:
            py_compile.compile(py_file, doraise=True)
        except py_compile.PyCompileError as e:
            pytest.fail(f"Синтаксична помилка у {py_file}: {e}")

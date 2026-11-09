import pytest
from PyQt6.QtWidgets import QWidget, QApplication
import sys
from utils.win_api import (
    set_click_through,
    keep_on_top,
    is_scum_running,
    is_game_foreground,
    force_foreground_window,
    restore_game_focus,
    set_last_game_hwnd,
    get_last_game_hwnd
)


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def test_win_api_window_manipulation(qapp):
    w = QWidget()
    w.resize(200, 200)
    w.show()

    hwnd = int(w.winId())
    assert hwnd > 0

    # Без помилок встановлюємо click-through
    set_click_through(hwnd, True)
    set_click_through(hwnd, False)

    # Без помилок встановлюємо keep_on_top
    keep_on_top(hwnd)

    # Без помилок викликаємо force_foreground_window
    force_foreground_window(hwnd)

    # Тест збереження та повернення дескриптора вікна
    set_last_game_hwnd(hwnd)
    assert get_last_game_hwnd() == hwnd

    # Без помилок викликаємо restore_game_focus
    restore_game_focus(hwnd)

    w.close()


def test_win_api_scum_detection():
    # Перевірка безпечного виклику детектора гри
    running = is_scum_running("scum")
    assert isinstance(running, bool)

    # Перевірка детектора активного вікна гри
    fg = is_game_foreground("scum", allow_own_process=True)
    assert isinstance(fg, bool)

    # Перевірка з неіснуючим процесом
    fg_fake = is_game_foreground("non_existent_game_xyz", allow_own_process=False)
    assert fg_fake is False

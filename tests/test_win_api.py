import sys

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

from utils.win_api import (
    force_foreground_window,
    get_last_game_hwnd,
    is_game_foreground,
    is_scum_running,
    keep_on_top,
    restore_game_focus,
    set_click_through,
    set_last_game_hwnd,
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

    # Set click-through without errors
    set_click_through(hwnd, True)
    set_click_through(hwnd, False)

    # Set keep_on_top without errors
    keep_on_top(hwnd)

    # Call force_foreground_window without errors
    force_foreground_window(hwnd)

    # Test storing and returning the window handle
    set_last_game_hwnd(hwnd)
    if qapp.platformName() != "offscreen":  # the offscreen platform hands out fake handles
        assert get_last_game_hwnd() == hwnd

    # Call restore_game_focus without errors
    restore_game_focus(hwnd)

    w.close()


def test_win_api_scum_detection():
    # Check the game detector can be called safely
    running = is_scum_running("scum")
    assert isinstance(running, bool)

    # Check the active game window detector
    fg = is_game_foreground("scum", allow_own_process=True)
    assert isinstance(fg, bool)

    # Check with a non-existent process
    fg_fake = is_game_foreground("non_existent_game_xyz", allow_own_process=False)
    assert fg_fake is False

import logging
import os
import sys
import time
from typing import Optional

from PyQt6.QtCore import QRect, Qt, QTimer
from PyQt6.QtGui import QAction, QBrush, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from core.chat_history import ChatHistory
from core.config_manager import ConfigManager
from core.controller import AppController
from core.coordinate_parser import parse_chat_coordinate  # noqa: F401  (kept for plugins/tests)
from core.hotkey_manager import GlobalHotkeyManager
from core.i18n import LocalizationManager, tr
from core.log_parser import ScumLogParser
from core.logging_setup import setup_logging
from core.message_filter import ChatFilter
from core.paths import get_user_data_dir
from core.points_manager import PointsManager
from core.profiles import ProfileManager
from core.translator import GoogleTranslatorEngine
from core.updater import UpdateChecker, UpdateInfo, UpdateInstaller
from core.version import __version__
from ui.color_picker import is_color_dialog_active
from ui.history_window import HistoryWindow
from ui.map_window import MapWindow
from ui.overlay import ChatOverlay
from ui.points_window import PointsWindow
from ui.settings_window import SettingsDialog
from ui.status_badge import StatusBadge
from ui.update_dialog import UpdateDialog
from utils.win_api import (
    check_single_instance,
    is_game_foreground,
    is_scum_running,
    restore_game_focus,
    set_last_game_hwnd,
    user32,
)

log = logging.getLogger("scum")


def create_tray_icon_pixmap(has_update: bool = False) -> QPixmap:
    """Generate a compact vector Windows tray icon (Midnight Cyan style) with optional update badge."""
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QBrush(QColor("#0284c7")))  # Sky Blue
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(2, 2, 28, 28, 7, 7)
    painter.setPen(QColor("white"))
    font = painter.font()
    font.setBold(True)
    font.setPointSize(11)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "SC")

    if has_update:
        # Update-available indicator in the top-right corner
        # 1. Dark outline for contrast against the taskbar
        painter.setBrush(QBrush(QColor("#0f172a")))
        painter.drawEllipse(17, 1, 13, 13)

        # 2. Glowing amber update indicator (#f59e0b)
        painter.setBrush(QBrush(QColor("#f59e0b")))
        painter.drawEllipse(18, 2, 11, 11)

        # 3. White update arrow marker
        painter.setPen(QColor("white"))
        badge_font = painter.font()
        badge_font.setBold(True)
        badge_font.setPointSize(7)
        painter.setFont(badge_font)
        painter.drawText(QRect(18, 1, 11, 11), Qt.AlignmentFlag.AlignCenter, "▲")

    painter.end()
    return pixmap


def main():
    setup_logging()
    # Guard against running several copies; a freshly updated process waits for its predecessor to exit.
    post_update = "--post-update" in sys.argv
    if not check_single_instance(wait_seconds=15.0 if post_update else 0.0):
        sys.exit(0)

    # High-DPI scaling setup for 2K/4K and laptop screens
    if hasattr(Qt.ApplicationAttribute, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt.ApplicationAttribute, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Set the application icon
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    icon_path = os.path.join(base_dir, "icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    else:
        app.setWindowIcon(QIcon(create_tray_icon_pixmap()))

    cfg = ConfigManager()
    LocalizationManager.get_instance().set_locale(cfg.get("ui_language", "en"))
    UpdateInstaller.cleanup_leftovers()

    translator = GoogleTranslatorEngine(
        target_lang=cfg.get("target_language", "en"),
        source_lang=cfg.get("source_language", "auto")
    )

    history_path = (os.path.join(get_user_data_dir(), "chat_history.jsonl")
                    if cfg.get("history_save_to_disk", True) else None)
    history = ChatHistory(max_entries=int(cfg.get("history_max_entries", 5000)), path=history_path)
    profiles = ProfileManager(cfg)
    controller = AppController(cfg, translator, history=history, chat_filter=ChatFilter(cfg.config))
    history_win = HistoryWindow(history)

    # Single unified window (overlay + built-in translator)
    overlay = ChatOverlay(cfg)
    overlay.set_translator(translator)

    # NVIDIA-style overlay status indicator (ON green / OFF red)
    status_badge = StatusBadge(cfg)
    is_overlay_enabled_by_user = cfg.get("overlay_enabled", True)

    # Interactive map and saved waypoints module
    points_mgr = PointsManager()
    map_win = MapWindow(cfg, points_mgr)
    points_win = PointsWindow(cfg, points_mgr)

    # Link between the waypoints list window and the map
    points_win.point_focus_requested.connect(map_win.focus_point)
    map_win.point_selected.connect(map_win.focus_point)

    def on_coordinate_detected(pt):
        points_mgr.add_point(pt)
        log.info("New waypoint from chat: %s [%s] %s", pt.name, pt.sector, pt.raw_coord)
        # If the map is open and auto-focus is enabled
        if map_win.isVisible() and cfg.get("auto_focus_new_point", True):
            map_win.focus_point(pt)

    controller.coordinate_detected.connect(on_coordinate_detected)

    # Flag for opening the map manually (tray/UI) to work standalone without the game
    is_standalone_map_mode = False

    def toggle_map_and_points(force_standalone: bool = False):
        nonlocal is_standalone_map_mode
        if map_win.isVisible() or points_win.isVisible():
            map_win.hide()
            points_win.hide()
            is_standalone_map_mode = False
            restore_game_focus()
        else:
            in_game = is_game_foreground("scum", allow_own_process=True)
            if not in_game and not force_standalone:
                # Allow opening the map even outside the game, marking it as standalone
                is_standalone_map_mode = True
            elif force_standalone:
                is_standalone_map_mode = True

            try:
                fg = user32.GetForegroundWindow()
                if fg and fg != int(map_win.winId()) and fg != int(points_win.winId()):
                    set_last_game_hwnd(fg)
            except Exception:
                pass

            map_win.apply_config_geometry()
            points_win.apply_config_geometry()
            map_win.show()
            map_win.raise_()
            map_win.activateWindow()
            points_win.show()
            points_win.raise_()

    def on_map_window_closed():
        nonlocal is_standalone_map_mode
        points_win.hide()
        is_standalone_map_mode = False
        restore_game_focus()

    def on_points_window_closed():
        nonlocal is_standalone_map_mode
        map_win.hide()
        is_standalone_map_mode = False
        restore_game_focus()

    map_win.closed.connect(on_map_window_closed)
    points_win.closed.connect(on_points_window_closed)

    controller.hotkey_toggle_map.connect(toggle_map_and_points)
    overlay.open_map_requested.connect(toggle_map_and_points)

    settings_dialog = SettingsDialog(cfg, profiles=profiles)

    # UI signals
    controller.translated_ready.connect(overlay.add_message)
    overlay.open_settings_requested.connect(settings_dialog.show)

    def on_toggle_lock():
        if not cfg.get("enable_chat_translator", True):
            return
        overlay.toggle_lock()
        status_badge.set_locked(overlay.is_locked)
        if not overlay.is_locked:
            overlay.show()
            status_badge.show()

    controller.hotkey_toggle_lock.connect(on_toggle_lock)

    last_chat_open_time = 0.0

    def on_chat_opened():
        # Chat key (T) reacts ONLY inside the SCUM window and when the translator is enabled
        if not cfg.get("enable_chat_translator", True):
            return
        if not is_game_foreground("scum", allow_own_process=True):
            return

        nonlocal last_chat_open_time
        now = time.time()
        # 300 ms debounce — guards against re-trigger when the user types the letter 't'
        if now - last_chat_open_time < 0.3:
            return
        last_chat_open_time = now

        if not overlay.in_chat_mode:
            overlay.set_in_chat_mode(True)

    def on_escape_pressed():
        # Check whether any of our windows is open
        windows_open = (
            overlay.in_chat_mode or
            map_win.isVisible() or
            points_win.isVisible() or
            settings_dialog.isVisible()
        )

        if not windows_open:
            # No window open — do not intercept Escape inside the game
            return

        # Hide all open windows immediately
        if overlay.in_chat_mode:
            overlay.set_in_chat_mode(False)
        if map_win.isVisible():
            map_win.hide()
        if points_win.isVisible():
            points_win.hide()
        if settings_dialog.isVisible():
            settings_dialog.hide()

        # Immediately return focus and mouse capture to the SCUM window
        restore_game_focus()

    def on_enter_pressed():
        # Enter is handled ONLY when chat mode is active
        if overlay.in_chat_mode:
            if overlay.input_field.text().strip():
                overlay._copy_translation()
            else:
                overlay.set_in_chat_mode(False)

    controller.hotkey_chat_opened.connect(on_chat_opened)
    controller.hotkey_escape_pressed.connect(on_escape_pressed)
    controller.hotkey_enter_pressed.connect(on_enter_pressed)

    def toggle_overlay_visibility():
        if not cfg.get("enable_chat_translator", True):
            return
        nonlocal is_overlay_enabled_by_user
        is_overlay_enabled_by_user = not is_overlay_enabled_by_user
        cfg.set("overlay_enabled", is_overlay_enabled_by_user)
        status_badge.set_status(is_overlay_enabled_by_user)

        if is_overlay_enabled_by_user:
            if is_game_foreground("scum", allow_own_process=True):
                overlay.show()
        else:
            overlay.hide()

    controller.hotkey_toggle_visibility.connect(toggle_overlay_visibility)

    # Hotkey manager
    hotkey_manager = GlobalHotkeyManager()

    def update_registered_hotkeys():
        hotkey_manager.clear()

        k_lock = cfg.get("hotkey_toggle_lock", "F9")
        k_vis = cfg.get("hotkey_toggle_visibility", "F8")
        k_chat = cfg.get("hotkey_quick_chat", "T")
        k_map = cfg.get("hotkey_toggle_map", "Ctrl+M")

        hotkey_manager.register(k_lock, lambda: controller.hotkey_toggle_lock.emit())
        hotkey_manager.register(k_vis, lambda: controller.hotkey_toggle_visibility.emit())
        hotkey_manager.register(k_chat, lambda: controller.hotkey_chat_opened.emit())
        hotkey_manager.register(k_map, lambda: controller.hotkey_toggle_map.emit())

        # Escape and Enter for safe exit from input mode (guarded by in_chat_mode)
        hotkey_manager.register("Escape", lambda: controller.hotkey_escape_pressed.emit())
        hotkey_manager.register("Enter", lambda: controller.hotkey_enter_pressed.emit())

    update_registered_hotkeys()
    hotkey_manager.start()

    # Smart background monitoring of the SCUM game (every 500 ms)
    # If the game is minimized or closed, the overlay and status badge are hidden
    def check_game_window_state():
        if not overlay.is_locked:
            # In position-setup mode the window is always visible
            return

        # If any modal dialog is open (color picker, settings, players, etc.), do not hide windows
        if QApplication.activeModalWidget() is not None or is_color_dialog_active:
            return

        active = is_game_foreground("scum", allow_own_process=True)
        if not active:
            if overlay.in_chat_mode:
                overlay.set_in_chat_mode(False)
            if overlay.isVisible():
                overlay.hide()
            if status_badge.isVisible():
                status_badge.hide()
            # If the map was opened manually (standalone), do not hide it when SCUM is minimized/absent
            if not is_standalone_map_mode:
                if map_win.isVisible():
                    map_win.hide()
                if points_win.isVisible():
                    points_win.hide()
        else:
            enable_chat = cfg.get("enable_chat_translator", True)
            if not enable_chat:
                # "Map Only" mode: chat overlay and status badge are disabled
                if overlay.isVisible():
                    overlay.hide()
                if status_badge.isVisible():
                    status_badge.hide()
            else:
                # Status badge (ON/OFF) is always shown in game
                if not status_badge.isVisible():
                    status_badge.show()

                # Chat overlay is shown only if enabled by the player (F8)
                if is_overlay_enabled_by_user:
                    if not overlay.isVisible():
                        overlay.show()
                else:
                    if overlay.isVisible():
                        overlay.hide()

    game_check_timer = QTimer()
    game_check_timer.timeout.connect(check_game_window_state)
    game_check_timer.start(500)

    def on_settings_changed():
        LocalizationManager.get_instance().set_locale(cfg.get("ui_language", "en"))
        history.set_max_entries(int(cfg.get("history_max_entries", 5000)))
        translator.update_settings(
            target_lang=cfg.get("target_language", "uk"),
            source_lang=cfg.get("source_language", "auto")
        )
        overlay.update_style()
        map_win.canvas.set_variant(cfg.get("map_variant", "regular"))
        map_win.canvas.toggle_grid(cfg.get("map_show_grid", True))
        map_win.canvas.toggle_keypads(cfg.get("map_show_keypads", True))
        update_registered_hotkeys()
        update_tray_texts()

        if log_parser is not None:
            log_parser.set_log_path(cfg.get_resolved_log_path())

        enable_chat = cfg.get("enable_chat_translator", True)
        if not enable_chat:
            if overlay.isVisible():
                overlay.hide()
            if status_badge.isVisible():
                status_badge.hide()
        else:
            if is_game_foreground("scum", allow_own_process=True):
                status_badge.show()
                if is_overlay_enabled_by_user:
                    overlay.show()

    settings_dialog.settings_changed.connect(on_settings_changed)

    # Test message generation
    def send_test_message():
        import random
        from datetime import datetime
        now = datetime.now().strftime("%H:%M:%S")
        samples = [
            ("I ain´t DeAd", "No Vehicles stealing or mine cleaning near a base outside of raid hours!", "player"),
            ("nothingstaysdead", "LOTTERY WINNER Player1 - Check Discord to claim your prize!", "player"),
            ("Aron", "Hey bro, do you have 7.62 ammo for AK47? Meet me at sector B2.", "player"),
            ("ServerAdmin", "Server restart in 10 minutes! Please find a safe spot.", "server"),
            ("Message Of The Day", "Join Discord for Welcome pack https://discord.gg/GRrreuFPRq", "server"),
            ("Ghost", "машина{X=174468.797 Y=345933.000 Z=34103.105|P=342.318665 Y=117.616730 R=0.000000}", "player"),
            ("Player1", "{X=91149.500 Y=-162011.531 Z=31172.863|P=357.522491 Y=354.508392 R=0.000000} база", "player"),
            ("Sniper", "{X=-142861.000 Y=-142348.000 Z=15000.000|P=0.0 Y=0.0 R=0.0}", "player"),
            ("Hunter", "(схрон{X=300000.000 Y=200000.000 Z=25000.000|P=0.0 Y=0.0 R=0.0})", "player"),
        ]
        sender, msg, m_type = random.choice(samples)
        controller.raw_message_received.emit(now, sender, msg, m_type)

    overlay.test_requested.connect(send_test_message)

    # SCUM log parser (always active to auto-collect GPS coordinates onto the tactical map)
    resolved_log_path = cfg.get_resolved_log_path()

    def on_new_log_message(time_str: str, sender: str, msg: str, msg_type: str):
        controller.raw_message_received.emit(time_str, sender, msg, msg_type)

    log.info("Monitoring SCUM log: %s", resolved_log_path)
    log_parser = ScumLogParser(resolved_log_path, on_new_log_message)
    log_parser.start()

    # System tray
    tray = QSystemTrayIcon(QIcon(create_tray_icon_pixmap(has_update=False)), app)
    tray_menu = QMenu()

    # Application updates
    cached_update_info: Optional[UpdateInfo] = None
    update_checker = UpdateChecker()

    def show_update_dialog():
        nonlocal cached_update_info
        if cached_update_info:
            dlg = UpdateDialog(cached_update_info)
            dlg.exec()
        else:
            check_for_updates_interactive()

    # Install-update button (shown at the top of the tray menu when a new version exists)
    action_install_update = QAction(tr("tray.update_btn"), app)
    font_bold = action_install_update.font()
    font_bold.setBold(True)
    action_install_update.setFont(font_bold)
    action_install_update.setVisible(False)
    action_install_update.triggered.connect(show_update_dialog)
    tray_menu.addAction(action_install_update)

    def on_update_detected(info: UpdateInfo):
        nonlocal cached_update_info
        cached_update_info = info
        # 1. Show the update indicator on the tray icon
        tray.setIcon(QIcon(create_tray_icon_pixmap(has_update=True)))
        tray.setToolTip(tr("tray.tooltip_update", version=__version__, new_version=info.version))
        action_install_update.setText(tr("tray.update_btn_version", version=info.version))
        action_install_update.setVisible(True)
        # 2. Windows tray notification
        tray.showMessage(
            tr("tray.update_avail_title"),
            tr("tray.update_avail_body", version=info.version),
            QSystemTrayIcon.MessageIcon.Information,
            8000
        )

    def on_tray_message_clicked():
        if cached_update_info:
            show_update_dialog()

    tray.messageClicked.connect(on_tray_message_clicked)
    update_checker.update_available.connect(on_update_detected)

    action_chat = QAction(app)
    action_chat.triggered.connect(on_chat_opened)
    tray_menu.addAction(action_chat)

    action_map = QAction(app)
    action_map.triggered.connect(lambda: toggle_map_and_points(force_standalone=True))
    tray_menu.addAction(action_map)

    def toggle_chat_enabled_mode():
        curr = cfg.get("enable_chat_translator", True)
        new_val = not curr
        cfg.set("enable_chat_translator", new_val)
        on_settings_changed()

    action_mode_toggle = QAction(app)
    action_mode_toggle.triggered.connect(toggle_chat_enabled_mode)
    tray_menu.addAction(action_mode_toggle)

    action_lock = QAction(app)
    action_lock.triggered.connect(on_toggle_lock)
    tray_menu.addAction(action_lock)

    action_vis = QAction(app)
    action_vis.triggered.connect(toggle_overlay_visibility)
    tray_menu.addAction(action_vis)

    action_test = QAction(app)
    action_test.triggered.connect(send_test_message)
    tray_menu.addAction(action_test)

    tray_menu.addSeparator()

    def check_for_updates_interactive():
        interactive_checker = UpdateChecker()

        def on_avail(info):
            on_update_detected(info)
            dlg = UpdateDialog(info)
            dlg.exec()

        def on_none(curr_ver):
            QMessageBox.information(
                None,
                tr("update.dialog_title"),
                tr("update.up_to_date", version=curr_ver),
                QMessageBox.StandardButton.Ok
            )

        def on_err(err_text):
            QMessageBox.warning(
                None,
                tr("update.check_failed_title"),
                tr("update.check_failed", error=err_text),
                QMessageBox.StandardButton.Ok
            )

        interactive_checker.update_available.connect(on_avail)
        interactive_checker.no_update_found.connect(on_none)
        interactive_checker.check_error.connect(on_err)
        interactive_checker.check_for_updates_async()

    action_check_update = QAction(app)
    action_check_update.triggered.connect(check_for_updates_interactive)
    tray_menu.addAction(action_check_update)

    def show_history_window():
        history_win.show()
        history_win.raise_()
        history_win.activateWindow()

    action_history = QAction(app)
    action_history.triggered.connect(show_history_window)
    tray_menu.addAction(action_history)

    # Profiles submenu (rebuilt whenever the list or the active profile changes)
    profiles_menu = tray_menu.addMenu("")

    def rebuild_profiles_menu():
        profiles_menu.clear()
        profiles_menu.setTitle(tr("tray.profiles", profile=profiles.active))
        for name in profiles.names():
            act = QAction(("● " if name == profiles.active else "    ") + name, profiles_menu)
            act.triggered.connect(lambda _checked=False, n=name: switch_profile(n))
            profiles_menu.addAction(act)

    def switch_profile(name: str):
        if profiles.apply(name):
            on_settings_changed()
            rebuild_profiles_menu()
            tray.showMessage(tr("tray.profile_switched_title"), tr("tray.profile_switched", profile=name),
                             QSystemTrayIcon.MessageIcon.Information, 2500)

    action_settings = QAction(app)
    action_settings.triggered.connect(settings_dialog.show)
    tray_menu.addAction(action_settings)

    action_quit = QAction(app)
    action_quit.triggered.connect(app.quit)
    tray_menu.addAction(action_quit)

    def update_tray_texts():
        k_chat = cfg.get("hotkey_quick_chat", "T")
        k_map = cfg.get("hotkey_toggle_map", "Ctrl+M")
        k_lock = cfg.get("hotkey_toggle_lock", "F9")
        k_vis = cfg.get("hotkey_toggle_visibility", "F8")
        is_chat_on = cfg.get("enable_chat_translator", True)

        action_chat.setText(tr("tray.open_chat", hotkey=k_chat if k_chat else "—"))
        action_map.setText(tr("tray.map_and_points", hotkey=k_map if k_map else "—"))
        action_lock.setText(tr("tray.toggle_lock", hotkey=k_lock if k_lock else "—"))
        action_vis.setText(tr("tray.toggle_vis", hotkey=k_vis if k_vis else "—"))
        action_test.setText(tr("tray.test_msg"))
        action_check_update.setText(tr("tray.check_updates"))
        action_settings.setText(tr("tray.settings"))
        action_history.setText(tr("tray.history"))
        rebuild_profiles_menu()
        action_quit.setText(tr("tray.exit"))

        if is_chat_on:
            action_mode_toggle.setText(f"✔ {tr('tray.mode_full')}")
        else:
            action_mode_toggle.setText(f"🗺 {tr('tray.mode_map_only')}")

        tray.setToolTip(tr("tray.tooltip", version=__version__))

    update_tray_texts()

    def on_tray_activated(reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            toggle_map_and_points(force_standalone=True)
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            # Single click outside the game opens the map quickly in standalone mode
            if not is_scum_running("scum") and not map_win.isVisible():
                toggle_map_and_points(force_standalone=True)

    tray.activated.connect(on_tray_activated)
    tray.setContextMenu(tray_menu)
    tray.show()

    # Background update checks: shortly after start, then every `update_check_interval_hours` (if > 0).
    def background_update_check():
        if cfg.get("auto_check_updates", True) and cached_update_info is None:
            update_checker.check_for_updates_async()

    QTimer.singleShot(4000, background_update_check)
    update_timer = QTimer()
    update_timer.timeout.connect(background_update_check)
    interval_h = float(cfg.get("update_check_interval_hours", 6) or 0)
    if interval_h > 0:
        update_timer.start(int(interval_h * 3600 * 1000))

    # Initial state: if the game is open, show the relevant widgets
    if is_game_foreground("scum", allow_own_process=True):
        if cfg.get("enable_chat_translator", True):
            status_badge.show()
            if is_overlay_enabled_by_user:
                overlay.show()
    else:
        log.info("SCUM is not active; the overlay appears once the game is in the foreground.")

    log.info("SCUM Chat Translator v%s started", __version__)

    ret = app.exec()
    if log_parser is not None:
        log_parser.stop()
    hotkey_manager.stop()
    sys.exit(ret)


if __name__ == "__main__":
    main()

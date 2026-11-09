import sys
import os
import time
from concurrent.futures import ThreadPoolExecutor
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox
from PyQt6.QtGui import QIcon, QAction, QColor, QPixmap, QPainter, QBrush
from PyQt6.QtCore import QObject, pyqtSignal, Qt, QTimer, QRect
from typing import Optional

from core.version import __version__, GITHUB_REPO_URL
from core.updater import UpdateChecker, UpdateInfo
from ui.update_dialog import UpdateDialog
from core.config_manager import ConfigManager
from core.translator import GoogleTranslatorEngine
from core.log_parser import ScumLogParser
from core.hotkey_manager import GlobalHotkeyManager
from ui.overlay import ChatOverlay
from ui.settings_window import SettingsDialog
from ui.status_badge import StatusBadge
from ui.map_window import MapWindow
from ui.points_window import PointsWindow
from core.coordinate_parser import parse_chat_coordinate
from core.points_manager import PointsManager
from utils.win_api import (
    is_game_foreground, is_scum_running, check_single_instance,
    restore_game_focus, set_last_game_hwnd, user32
)


class AppController(QObject):
    raw_message_received = pyqtSignal(str, str, str, str)  # time, sender, msg, msg_type
    translated_ready = pyqtSignal(str, str, str, str, str, str)  # time, sender, orig, trans, src, type
    coordinate_detected = pyqtSignal(object)  # MapPoint
    hotkey_toggle_lock = pyqtSignal()
    hotkey_toggle_visibility = pyqtSignal()
    hotkey_chat_opened = pyqtSignal()
    hotkey_escape_pressed = pyqtSignal()
    hotkey_enter_pressed = pyqtSignal()
    hotkey_toggle_map = pyqtSignal()

    def __init__(self, cfg: ConfigManager, translator: GoogleTranslatorEngine):
        super().__init__()
        self.cfg = cfg
        self.translator = translator
        self.executor = ThreadPoolExecutor(max_workers=3)

        self.raw_message_received.connect(self._handle_raw_message)

    def _handle_raw_message(self, time_str: str, sender: str, msg: str, msg_type: str):
        # 1. Автоматичний пошук координат у чаті (навіть для власних повідомлень)
        point = parse_chat_coordinate(msg, time_str)
        if point:
            self.coordinate_detected.emit(point)

        own_nick = self.cfg.get("own_nickname", "").lower()
        ignore_own = self.cfg.get("ignore_own_messages", False)

        if ignore_own and sender.lower() == own_nick:
            return

        # 2. Чорний список гравців: повідомлення не перекладаються, а виводяться мовою оригіналу
        blacklist = [b.strip().lower() for b in self.cfg.get("blacklist_nicknames", []) if isinstance(b, str) and b.strip()]
        if sender.strip().lower() in blacklist:
            self.translated_ready.emit(time_str, sender, msg, msg, "orig", msg_type)
            return

        self.executor.submit(self._async_translate, time_str, sender, msg, msg_type)

    def _async_translate(self, time_str: str, sender: str, msg: str, msg_type: str):
        translated, src_lang = self.translator.translate(msg)
        self.translated_ready.emit(time_str, sender, msg, translated, src_lang, msg_type)


def create_tray_icon_pixmap(has_update: bool = False) -> QPixmap:
    """Генерація компактної векторної іконки для трею Windows у стилі Midnight Cyan із підтримкою значка оновлення."""
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
        # Індикатор наявності оновлення у правому верхньому кутку
        # 1. Темна обводка для контрасту на фоні таски
        painter.setBrush(QBrush(QColor("#0f172a")))
        painter.drawEllipse(17, 1, 13, 13)

        # 2. Сяючий помаранчево-бурштиновий індикатор оновлення (#f59e0b)
        painter.setBrush(QBrush(QColor("#f59e0b")))
        painter.drawEllipse(18, 2, 11, 11)

        # 3. Білий маркер-стрілочка оновлення
        painter.setPen(QColor("white"))
        badge_font = painter.font()
        badge_font.setBold(True)
        badge_font.setPointSize(7)
        painter.setFont(badge_font)
        painter.drawText(QRect(18, 1, 11, 11), Qt.AlignmentFlag.AlignCenter, "▲")

    painter.end()
    return pixmap


def main():
    # Захист від запуску кількох копій програми
    if not check_single_instance():
        print("[Main] Програма вже запущена в системному треї (значок 'SC' біля годинника).")
        sys.exit(0)

    # Налаштування High-DPI для масштабування на 2K/4K та екранах ноутбуків
    if hasattr(Qt.ApplicationAttribute, "AA_EnableHighDpiScaling"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt.ApplicationAttribute, "AA_UseHighDpiPixmaps"):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # Встановлення іконки додатку
    base_dir = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    icon_path = os.path.join(base_dir, "icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    else:
        app.setWindowIcon(QIcon(create_tray_icon_pixmap()))

    cfg = ConfigManager()

    translator = GoogleTranslatorEngine(
        target_lang=cfg.get("target_language", "uk"),
        source_lang=cfg.get("source_language", "auto")
    )

    controller = AppController(cfg, translator)

    # Єдине уніфіковане вікно (оверлей + вбудований перекладач)
    overlay = ChatOverlay(cfg)
    overlay.set_translator(translator)

    # Індикатор статусу оверлею в стилі NVIDIA (ON - зелений / OFF - червоний)
    status_badge = StatusBadge(cfg)
    is_overlay_enabled_by_user = cfg.get("overlay_enabled", True)

    # Модуль інтерактивної карти та збережених точок координат
    points_mgr = PointsManager()
    map_win = MapWindow(cfg, points_mgr)
    points_win = PointsWindow(cfg, points_mgr)

    # Зв'язок вікна списку точок та карти
    points_win.point_focus_requested.connect(map_win.focus_point)
    map_win.point_selected.connect(map_win.focus_point)

    def on_coordinate_detected(pt):
        points_mgr.add_point(pt)
        print(f"[Main] Виявлено нову точку з чату: {pt.name} [{pt.sector}] {pt.raw_coord}")
        # Якщо карта відкрита та налаштовано авто-фокус
        if map_win.isVisible() and cfg.get("auto_focus_new_point", True):
            map_win.focus_point(pt)

    controller.coordinate_detected.connect(on_coordinate_detected)

    def toggle_map_and_points():
        if map_win.isVisible() or points_win.isVisible():
            map_win.hide()
            points_win.hide()
            restore_game_focus()
        else:
            # Вікна карти та списку точок відкриваються ТІЛЬКИ всередині гри SCUM
            if not is_game_foreground("scum", allow_own_process=True):
                print("[Main] Карта та список точок відкриваються тільки у вікні гри SCUM.")
                return

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

    controller.hotkey_toggle_map.connect(toggle_map_and_points)
    overlay.open_map_requested.connect(toggle_map_and_points)

    settings_dialog = SettingsDialog(cfg)

    # Сигнали інтерфейсу
    controller.translated_ready.connect(overlay.add_message)
    overlay.open_settings_requested.connect(settings_dialog.show)

    def on_toggle_lock():
        overlay.toggle_lock()
        status_badge.set_locked(overlay.is_locked)
        if not overlay.is_locked:
            overlay.show()
            status_badge.show()

    controller.hotkey_toggle_lock.connect(on_toggle_lock)

    last_chat_open_time = 0.0

    def on_chat_opened():
        # Клавіша чату (T) реагує ТІЛЬКИ всередині вікна гри SCUM
        if not is_game_foreground("scum", allow_own_process=True):
            return

        nonlocal last_chat_open_time
        now = time.time()
        # Дебаунс 300мс — захист від повторного виклику, коли користувач вводить літеру 't'
        if now - last_chat_open_time < 0.3:
            return
        last_chat_open_time = now

        if not overlay.in_chat_mode:
            overlay.set_in_chat_mode(True)

    def on_escape_pressed():
        # Перевіряємо, чи відкрите хоч одне вікно нашої програми
        windows_open = (
            overlay.in_chat_mode or
            map_win.isVisible() or
            points_win.isVisible() or
            settings_dialog.isVisible()
        )

        if not windows_open:
            # Жодне вікно не відкрите — не перехоплюємо дію Escape в самій грі
            return

        # Миттєво ховаємо всі відкриті вікна
        if overlay.in_chat_mode:
            overlay.set_in_chat_mode(False)
        if map_win.isVisible():
            map_win.hide()
        if points_win.isVisible():
            points_win.hide()
        if settings_dialog.isVisible():
            settings_dialog.hide()

        # Миттєво повертаємо фокус та захоплення мишки вікну гри SCUM
        restore_game_focus()

    def on_enter_pressed():
        # Enter обробляється ТІЛЬКИ коли режим чату активний
        if overlay.in_chat_mode:
            if overlay.input_field.text().strip():
                overlay._copy_translation()
            else:
                overlay.set_in_chat_mode(False)

    controller.hotkey_chat_opened.connect(on_chat_opened)
    controller.hotkey_escape_pressed.connect(on_escape_pressed)
    controller.hotkey_enter_pressed.connect(on_enter_pressed)

    def toggle_overlay_visibility():
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

    # Менеджер гарячих клавіш
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

        # Escape та Enter для безпечного виходу з режиму введення (ізольовані перевіркою in_chat_mode)
        hotkey_manager.register("Escape", lambda: controller.hotkey_escape_pressed.emit())
        hotkey_manager.register("Enter", lambda: controller.hotkey_enter_pressed.emit())

    update_registered_hotkeys()
    hotkey_manager.start()

    # Розумний фоновий моніторинг гри SCUM (кожні 500 мс)
    # Якщо гра згорнута або закрита — оверлей та значок статусу ховаються
    def check_game_window_state():
        if not overlay.is_locked:
            # У режимі налаштування положення вікна завжди видно
            return

        active = is_game_foreground("scum", allow_own_process=True)
        if not active:
            if overlay.in_chat_mode:
                overlay.set_in_chat_mode(False)
            if overlay.isVisible():
                overlay.hide()
            if status_badge.isVisible():
                status_badge.hide()
            if map_win.isVisible():
                map_win.hide()
            if points_win.isVisible():
                points_win.hide()
        else:
            # Значок статусу (ON/OFF) завжди відображається у грі
            if not status_badge.isVisible():
                status_badge.show()

            # Оверлей чату показується тільки якщо увімкнений гравцем (F8)
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
        translator.update_settings(
            target_lang=cfg.get("target_language", "uk"),
            source_lang=cfg.get("source_language", "auto")
        )
        overlay.update_style()
        map_win.canvas.set_variant(cfg.get("map_variant", "regular"))
        map_win.canvas.toggle_grid(cfg.get("map_show_grid", True))
        map_win.canvas.toggle_keypads(cfg.get("map_show_keypads", True))
        update_registered_hotkeys()
        log_parser.set_log_path(cfg.get_resolved_log_path())

    settings_dialog.settings_changed.connect(on_settings_changed)

    # Генерація тестового повідомлення
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

    # Парсер логів гри SCUM
    resolved_log_path = cfg.get_resolved_log_path()
    print(f"[Main] Моніторинг логу SCUM: {resolved_log_path}")

    def on_new_log_message(time_str: str, sender: str, msg: str, msg_type: str):
        controller.raw_message_received.emit(time_str, sender, msg, msg_type)

    log_parser = ScumLogParser(resolved_log_path, on_new_log_message)
    log_parser.start()

    # Системний трей
    tray = QSystemTrayIcon(QIcon(create_tray_icon_pixmap(has_update=False)), app)
    tray_menu = QMenu()

    # Оновлення програми
    cached_update_info: Optional[UpdateInfo] = None
    update_checker = UpdateChecker()

    def show_update_dialog():
        nonlocal cached_update_info
        if cached_update_info:
            dlg = UpdateDialog(cached_update_info)
            dlg.exec()
        else:
            check_for_updates_interactive()

    # Кнопка встановлення оновлення (з'являється у верхній частині меню трею при наявності нової версії)
    action_install_update = QAction("⚡ Оновити програму (1 клік)", app)
    font_bold = action_install_update.font()
    font_bold.setBold(True)
    action_install_update.setFont(font_bold)
    action_install_update.setVisible(False)
    action_install_update.triggered.connect(show_update_dialog)
    tray_menu.addAction(action_install_update)

    def on_update_detected(info: UpdateInfo):
        nonlocal cached_update_info
        cached_update_info = info
        # 1. Світимо індикатор оновлення на іконці трею
        tray.setIcon(QIcon(create_tray_icon_pixmap(has_update=True)))
        tray.setToolTip(f"SCUM Chat Translator v{__version__} [🔥 Доступне оновлення v{info.version}!]")
        action_install_update.setText(f"⚡ Оновити до v{info.version} (1 клік)")
        action_install_update.setVisible(True)
        # 2. Сповіщення у Windows треї
        tray.showMessage(
            "Доступне оновлення SCUM Translator",
            f"Вийшла нова версія v{info.version}!\nКлікніть тут або в меню трею для оновлення в 1 клік.",
            QSystemTrayIcon.MessageIcon.Information,
            8000
        )

    def on_tray_message_clicked():
        if cached_update_info:
            show_update_dialog()

    tray.messageClicked.connect(on_tray_message_clicked)
    update_checker.update_available.connect(on_update_detected)

    action_chat = QAction("💬 Відкрити переклад (T)", app)
    action_chat.triggered.connect(on_chat_opened)
    tray_menu.addAction(action_chat)

    action_map = QAction(f"🗺 Карта та Точки ({cfg.get('hotkey_toggle_map', 'Ctrl+M')})", app)
    action_map.triggered.connect(toggle_map_and_points)
    tray_menu.addAction(action_map)

    action_lock = QAction("🔒/🔓 Режим налаштування (F9)", app)
    action_lock.triggered.connect(on_toggle_lock)
    tray_menu.addAction(action_lock)

    action_vis = QAction("👁 Показати/Приховати оверлей (F8)", app)
    action_vis.triggered.connect(toggle_overlay_visibility)
    tray_menu.addAction(action_vis)

    action_test = QAction("🧪 Надіслати тестове повідомлення", app)
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
                "Оновлення",
                f"У вас встановлено найновішу версію програми (v{curr_ver}).\nОновлення не потрібні.",
                QMessageBox.StandardButton.Ok
            )

        def on_err(err_text):
            QMessageBox.warning(
                None,
                "Помилка перевірки оновлення",
                f"Не вдалося перевірити оновлення на GitHub:\n{err_text}",
                QMessageBox.StandardButton.Ok
            )

        interactive_checker.update_available.connect(on_avail)
        interactive_checker.no_update_found.connect(on_none)
        interactive_checker.check_error.connect(on_err)
        interactive_checker.check_for_updates_async()

    action_check_update = QAction("🔄 Перевірити оновлення", app)
    action_check_update.triggered.connect(check_for_updates_interactive)
    tray_menu.addAction(action_check_update)

    action_settings = QAction("⚙ Налаштування", app)
    action_settings.triggered.connect(settings_dialog.show)
    tray_menu.addAction(action_settings)

    action_quit = QAction("❌ Вихід", app)
    action_quit.triggered.connect(app.quit)
    tray_menu.addAction(action_quit)

    tray.setContextMenu(tray_menu)
    tray.setToolTip(f"SCUM Chat Translator v{__version__}")
    tray.show()

    # Фонова автоперевірка оновлень при старті програми (через 4 сек без блокування GUI)
    if cfg.get("auto_check_updates", True):
        QTimer.singleShot(4000, update_checker.check_for_updates_async)

    # Початковий стан: якщо гра відкрита, показуємо відповідні віджети
    if is_game_foreground("scum", allow_own_process=True):
        status_badge.show()
        if is_overlay_enabled_by_user:
            overlay.show()
    else:
        print("[Main] Гра SCUM наразі не активна. Оверлей та індикатор з'являться, щойно гра відкриється.")

    print("[Main] SCUM Chat Translator успішно запущено!")
    print(f"[Main] Гарячі клавіші: Зафіксувати [{cfg.get('hotkey_toggle_lock', 'F9')}], Чат [{cfg.get('hotkey_quick_chat', 'T')}], Приховати [{cfg.get('hotkey_toggle_visibility', 'F8')}], Карта [{cfg.get('hotkey_toggle_map', 'Ctrl+M')}]")

    ret = app.exec()
    log_parser.stop()
    hotkey_manager.stop()
    sys.exit(ret)


if __name__ == "__main__":
    main()

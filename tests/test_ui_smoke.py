import pytest
import sys
import time
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QKeyEvent
from core.config_manager import ConfigManager
from core.translator import GoogleTranslatorEngine
from ui.overlay import ChatOverlay
from ui.settings_window import SettingsDialog
from ui.status_badge import StatusBadge
from ui.map_window import MapWindow
from ui.points_window import PointsWindow
from core.points_manager import PointsManager
from core.coordinate_parser import parse_chat_coordinate


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def test_unified_chat_overlay_smoke(qapp, tmp_path):
    cfg_file = tmp_path / "test_cfg.json"
    cfg = ConfigManager(str(cfg_file))
    cfg.set("message_fade_timeout", 1)  # 1 секунда для тесту згасання
    tr = GoogleTranslatorEngine(target_lang="uk")

    overlay = ChatOverlay(cfg)
    overlay.set_translator(tr)

    # 1. Початковий стан: зафіксований (HUD)
    assert overlay.is_locked is True
    assert overlay.header_bar.isHidden()
    assert overlay.input_bar.isHidden()

    # 2. Кнопка тесту на самому оверлеї
    assert overlay.btn_test is not None
    assert overlay.btn_test.text() == "🧪 Тест"

    # 3. Додавання повідомлення
    overlay.add_message("12:00:00", "Aron", "Hello friend", "Привіт друже", "en", "player")
    assert len(overlay._entries) == 1
    assert "Привіт друже" in overlay.chat_view.toHtml()

    # 4. Перемикання режиму чату гри (T / Escape)
    overlay.set_in_chat_mode(True)
    assert overlay.in_chat_mode is True
    assert not overlay.input_bar.isHidden()

    overlay.set_in_chat_mode(False)
    assert overlay.in_chat_mode is False
    assert overlay.input_bar.isHidden()

    # 5. Перемикання блокування (F9)
    overlay.toggle_lock()
    assert overlay.is_locked is False
    assert not overlay.header_bar.isHidden()
    assert not overlay.input_bar.isHidden()

    overlay.toggle_lock()
    assert overlay.is_locked is True
    assert overlay.header_bar.isHidden()
    assert overlay.input_bar.isHidden()

    # 6. Вбудований перекладач: зміна мов та swap
    assert overlay.combo_src.currentData() == "uk"
    assert overlay.combo_tgt.currentData() == "en"

    overlay.swap_languages()
    assert overlay.combo_src.currentData() == "en"
    assert overlay.combo_tgt.currentData() == "uk"
    assert cfg.get("outgoing_my_lang") == "en"
    assert cfg.get("outgoing_target_lang") == "uk"

    # 7. Поле вводу та живий переклад
    overlay.combo_src.setCurrentIndex(overlay.combo_src.findData("uk"))
    overlay.combo_tgt.setCurrentIndex(overlay.combo_tgt.findData("en"))
    overlay.input_field.setText("Дякую за гру")
    assert overlay.input_field.text() == "Дякую за гру"

    # Виклик асинхронного живого перекладу без затримки інтерфейсу
    overlay._do_live_translate()
    import time
    for _ in range(30):
        qapp.processEvents()
        if overlay._current_translation:
            break
        time.sleep(0.05)
    assert overlay._current_translation != ""

    # Копіювання перекладу
    copied_signals = []
    overlay.translate_and_copy.connect(lambda orig, trans: copied_signals.append((orig, trans)))
    overlay._copy_translation()

    assert len(copied_signals) == 1
    assert copied_signals[0][0] == "Дякую за гру"
    assert QApplication.clipboard().text() == copied_signals[0][1]

    # 8. Тест перехоплення клавіші Escape у режимі чату
    overlay.set_in_chat_mode(True)
    assert overlay.in_chat_mode is True
    esc_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    overlay.keyPressEvent(esc_event)
    assert overlay.in_chat_mode is False

    # 9. Очищення чату
    overlay.clear_chat()
    assert len(overlay._entries) == 0


def test_message_fade_logic(qapp, tmp_path):
    cfg_file = tmp_path / "test_cfg.json"
    cfg = ConfigManager(str(cfg_file))
    cfg.set("message_fade_timeout", 1)  # 1 сек

    overlay = ChatOverlay(cfg)
    overlay.add_message("12:00:00", "Aron", "Test message", "Тест", "en", "player")

    # Одразу після додавання повідомлення видно
    visible = overlay._get_visible_entries()
    assert len(visible) == 1

    # Симулюємо час у минулому
    overlay._entries[0].created_time = time.time() - 2.0

    # Тепер воно застаріло і повинно зникнути в HUD режимі
    visible_faded = overlay._get_visible_entries()
    assert len(visible_faded) == 0

    # Але якщо відкрито чат (T) або режим налаштування (F9), воно знову видно!
    overlay.set_in_chat_mode(True)
    assert len(overlay._get_visible_entries()) == 1
    overlay.set_in_chat_mode(False)


def test_settings_dialog_smoke(qapp, tmp_path):
    cfg_file = tmp_path / "test_cfg.json"
    cfg = ConfigManager(str(cfg_file))
    settings = SettingsDialog(cfg)

    # Перевірка завантажених значень
    assert settings.combo_in_lang.currentData() == "uk"
    assert settings.btn_k_lock.current_hotkey == "F9"
    assert settings.btn_k_vis.current_hotkey == "F8"
    assert settings.btn_k_chat.current_hotkey == "T"
    assert settings.slider_fade.value() == 10
    assert settings.chk_font_bold.isChecked() is False

    # Перевірка збереження
    settings.slider_fade.setValue(15)
    settings.chk_font_bold.setChecked(True)
    settings.save_settings()

    assert cfg.get("message_fade_timeout") == 15
    assert cfg.get("font_bold") is True


def test_hotkey_button_clear_and_reset(qapp, tmp_path):
    from ui.settings_window import HotkeyButton
    btn = HotkeyButton("F9")
    assert btn.text() == "F9"
    assert btn.current_hotkey == "F9"

    # Очищення бінда через метод clear_hotkey (кнопка ❌)
    btn.clear_hotkey()
    assert btn.current_hotkey == ""
    assert btn.text() == "— Не призначено —"

    # Встановлення нового значення
    btn.set_hotkey("Ctrl+M")
    assert btn.current_hotkey == "Ctrl+M"
    assert btn.text() == "Ctrl+M"


def test_safe_color_picker_module():
    from ui.color_picker import is_color_dialog_active, open_safe_color_dialog
    assert is_color_dialog_active is False
    assert callable(open_safe_color_dialog)


def test_status_badge_smoke(qapp, tmp_path):
    cfg_file = tmp_path / "test_cfg.json"
    cfg = ConfigManager(str(cfg_file))
    badge = StatusBadge(cfg)

    # 1. Початковий стан: увімкнений (ON) та зафіксований
    assert badge.is_on is True
    assert badge.is_locked is True

    # 2. Зміна стану на OFF
    badge.set_status(False)
    assert badge.is_on is False
    assert cfg.get("overlay_enabled") is False

    # 3. Зміна стану назад на ON
    badge.set_status(True)
    assert badge.is_on is True
    assert cfg.get("overlay_enabled") is True

    # 4. Перемикання блокування (F9)
    badge.set_locked(False)
    assert badge.is_locked is False

    badge.set_locked(True)
    assert badge.is_locked is True


def test_map_window_smoke(qapp, tmp_path):
    cfg_file = tmp_path / "test_cfg.json"
    pts_file = tmp_path / "test_pts.json"
    cfg = ConfigManager(str(cfg_file))
    pts_mgr = PointsManager(str(pts_file))

    map_win = MapWindow(cfg, pts_mgr)
    assert map_win.canvas.current_variant == "regular"

    # Перемикання варіанту
    map_win._toggle_variant()
    assert map_win.canvas.current_variant == "tactical"

    # Додавання точки
    sample_coord = "{X=174468.797 Y=345933.000 Z=34103.105|P=342.318665 Y=117.616730 R=0.000000}"
    pt = parse_chat_coordinate(f"Машина {sample_coord}")
    pts_mgr.add_point(pt)

    map_win.focus_point(pt)
    assert map_win.canvas.active_point_id == pt.id


def test_points_window_smoke(qapp, tmp_path):
    cfg_file = tmp_path / "test_cfg.json"
    pts_file = tmp_path / "test_pts.json"
    cfg = ConfigManager(str(cfg_file))
    pts_mgr = PointsManager(str(pts_file))

    pts_win = PointsWindow(cfg, pts_mgr)
    assert len(pts_win._row_widgets) == 0

    sample_coord = "{X=174468.797 Y=345933.000 Z=34103.105|P=342.318665 Y=117.616730 R=0.000000}"
    pt = parse_chat_coordinate(f"Склад {sample_coord}")
    pts_mgr.add_point(pt)

    assert len(pts_win._row_widgets) == 1
    row = pts_win._row_widgets[pt.id]
    assert row.point.name == "Склад"

    # Редагування назви
    row.txt_name.setText("Головна база")
    row._on_name_edited()
    assert pts_mgr.get_point_by_id(pt.id).name == "Головна база"

    # Фільтрація
    pts_win.txt_filter.setText("база")
    assert not row.isHidden()
    pts_win.txt_filter.setText("вертоліт")
    assert row.isHidden() is True
    pts_win.txt_filter.clear()
    assert not row.isHidden()

    # Зміна кольору шпильки
    row._set_color("#ef4444")
    assert pt.color == "#ef4444"
    assert pts_mgr.get_point_by_id(pt.id).color == "#ef4444"

    # Закриття по Escape
    pts_win.show()
    assert not pts_win.isHidden()
    esc_event = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    pts_win.keyPressEvent(esc_event)
    assert pts_win.isHidden()


def test_blacklist_bypass_and_original_retention(qapp, tmp_path):
    from main import AppController
    cfg_file = tmp_path / "test_cfg.json"
    cfg = ConfigManager(str(cfg_file))
    cfg.set("blacklist_nicknames", ["TrollPlayer", "SpamBot"])
    tr = GoogleTranslatorEngine(target_lang="uk")

    controller = AppController(cfg, tr)
    received = []
    controller.translated_ready.connect(lambda t, s, o, tr_text, src, m_type: received.append((s, o, tr_text, src)))

    # 1. Повідомлення від гравця з чорного списку
    controller._handle_raw_message("10:00:00", "trollplayer", "This is untranslated text", "player")
    # Має видатись миттєво без звернення до перекладача
    qapp.processEvents()
    assert len(received) == 1
    sender, orig, trans, src = received[0]
    assert sender == "trollplayer"
    assert orig == "This is untranslated text"
    assert trans == "This is untranslated text"
    assert src == "orig"

    # 2. Повідомлення від звичайного гравця
    controller._handle_raw_message("10:00:01", "GoodPlayer", "Hello", "player")
    # Чекаємо асинхронного перекладу
    for _ in range(30):
        qapp.processEvents()
        if len(received) >= 2:
            break
        time.sleep(0.05)
    assert len(received) == 2
    assert received[1][0] == "GoodPlayer"
    assert received[1][1] == "Hello"


def test_text_outline_and_scum_colors(qapp, tmp_path):
    from PyQt6.QtGui import QImage, QPainter, QColor
    cfg_file = tmp_path / "test_cfg.json"
    cfg = ConfigManager(str(cfg_file))
    cfg.set("text_outline", True)
    cfg.set("font_bold", False)
    cfg.set("font_size", 13)

    overlay = ChatOverlay(cfg)

    # 1. Додавання серверного повідомлення
    overlay.add_message("02:45:38", "Server", "Rule: No base raiding!", "Rule: No base raiding!", "en", "server")
    html = overlay.chat_view.toHtml()
    # SCUM колір для сервера (#ffca00)
    assert "#ffca00" in html

    # 2. Додавання повідомлення гравця
    overlay.add_message("02:46:00", "PlayerOne", "Hello guys", "Привіт хлопці", "en", "player")
    html = overlay.chat_view.toHtml()
    # SCUM колір для гравця (#00e5ff)
    assert "#00e5ff" in html

    # 3. Перевірка рендерингу обводки
    overlay.chat_view.resize(500, 200)
    img = QImage(500, 200, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    overlay.chat_view.viewport().render(p)
    p.end()

    blacks = sum(1 for y in range(img.height()) for x in range(img.width()) if QColor(img.pixel(x, y)).lightness() < 30 and QColor(img.pixel(x, y)).alpha() > 200)
    assert blacks > 500, f"Expected black outline pixels, got {blacks}"

    # 4. Вимкнення обводки
    cfg.set("text_outline", False)
    overlay._refresh_rendered_chat()
    assert overlay.chat_view.outline_enabled is False


def test_squad_green_color(qapp, tmp_path):
    cfg_file = tmp_path / "test_cfg.json"
    cfg = ConfigManager(str(cfg_file))
    cfg.set("own_nickname", "MyHero")
    overlay = ChatOverlay(cfg)

    # 1. Сквад через msg_type="squad"
    overlay.add_message("12:00:00", "Mate", "Cover me", "Прикрий мене", "en", "squad")
    html1 = overlay.chat_view.toHtml()
    assert "#4ade80" in html1

    # 2. Сквад через префікс у нікнеймі: [Squad] Mate
    overlay.clear_chat()
    overlay.add_message("12:00:01", "[Squad] Mate", "Enemy ahead", "Ворог попереду", "en", "player")
    html2 = overlay.chat_view.toHtml()
    assert "#4ade80" in html2

    # 3. Сквад через український префікс: (сквад) Друг
    overlay.clear_chat()
    overlay.add_message("12:00:02", "(сквад) Друг", "Знайшов лут", "Знайшов лут", "uk", "player")
    html3 = overlay.chat_view.toHtml()
    assert "#4ade80" in html3

    # 4. Власний нікнейм MyHero
    overlay.clear_chat()
    overlay.add_message("12:00:03", "myhero", "Я на базі", "Я на базі", "uk", "player")
    html4 = overlay.chat_view.toHtml()
    assert "#4ade80" in html4


def test_map_only_mode_controller(qapp, tmp_path):
    from main import AppController
    cfg_file = tmp_path / "test_cfg.json"
    cfg = ConfigManager(str(cfg_file))
    cfg.set("enable_chat_translator", False)
    tr = GoogleTranslatorEngine(target_lang="uk")

    controller = AppController(cfg, tr)
    received_translations = []
    received_coords = []

    controller.translated_ready.connect(lambda *args: received_translations.append(args))
    controller.coordinate_detected.connect(lambda pt: received_coords.append(pt))

    # Звичайне повідомлення - не повинно перекладатися і видаватися
    controller._handle_raw_message("14:00:00", "Enemy", "I see you", "player")
    qapp.processEvents()
    time.sleep(0.1)
    assert len(received_translations) == 0

    # Повідомлення з координатами - координати ПОВИННІ бути розпізнані для карти!
    sample_coord = "{X=150000.0 Y=250000.0 Z=1000.0|P=0 Y=0 R=0}"
    controller._handle_raw_message("14:00:05", "Teammate", f"Airdrop here {sample_coord}", "player")
    qapp.processEvents()
    time.sleep(0.1)

    assert len(received_translations) == 0  # Чат вимкнено
    assert len(received_coords) == 1        # Карта отримала точку!
    assert received_coords[0].name == "Airdrop here"


def test_settings_language_switch(qapp, tmp_path):
    from core.i18n import LocalizationManager, tr
    cfg_file = tmp_path / "test_cfg.json"
    cfg = ConfigManager(str(cfg_file))
    cfg.set("ui_language", "en")

    dlg = SettingsDialog(cfg)
    assert LocalizationManager.get_instance().current_locale == "en"
    assert tr("settings.save_btn") == "💾 Save Settings"

    # Перемикаємо на українську і зберігаємо
    idx_uk = dlg.combo_ui_lang.findData("uk")
    dlg.combo_ui_lang.setCurrentIndex(idx_uk)
    dlg.save_settings()

    assert cfg.get("ui_language") == "uk"
    assert LocalizationManager.get_instance().current_locale == "uk"
    assert tr("settings.save_btn") == "💾 Зберегти налаштування"



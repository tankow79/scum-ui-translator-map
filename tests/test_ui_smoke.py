import sys
import time

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

from core.config_manager import ConfigManager
from core.coordinate_parser import parse_chat_coordinate
from core.points_manager import PointsManager
from core.translator import GoogleTranslatorEngine
from ui.map_window import MapWindow
from ui.overlay import ChatOverlay
from ui.points_window import PointsWindow
from ui.settings_window import SettingsDialog
from ui.status_badge import StatusBadge


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def test_unified_chat_overlay_smoke(qapp, tmp_path):
    cfg_file = tmp_path / "test_cfg.json"
    cfg = ConfigManager(str(cfg_file))
    cfg.set("message_fade_timeout", 1)  # 1 second for the fade test
    tr = GoogleTranslatorEngine(target_lang="uk")

    overlay = ChatOverlay(cfg)
    overlay.set_translator(tr)

    # 1. Initial state: locked (HUD)
    assert overlay.is_locked is True
    assert overlay.header_bar.isHidden()
    assert overlay.input_bar.isHidden()

    # 2. Test button on the overlay itself
    assert overlay.btn_test is not None
    assert overlay.btn_test.text() == "🧪 Test"

    # 3. Adding a message
    overlay.add_message("12:00:00", "Aron", "Hello friend", "Привіт друже", "en", "player")
    assert len(overlay._entries) == 1
    assert "Привіт друже" in overlay.chat_view.toHtml()

    # 4. Toggling game chat mode (T / Escape)
    overlay.set_in_chat_mode(True)
    assert overlay.in_chat_mode is True
    assert not overlay.input_bar.isHidden()

    overlay.set_in_chat_mode(False)
    assert overlay.in_chat_mode is False
    assert overlay.input_bar.isHidden()

    # 5. Toggling lock (F9)
    overlay.toggle_lock()
    assert overlay.is_locked is False
    assert not overlay.header_bar.isHidden()
    assert not overlay.input_bar.isHidden()

    overlay.toggle_lock()
    assert overlay.is_locked is True
    assert overlay.header_bar.isHidden()
    assert overlay.input_bar.isHidden()

    # 6. Built-in translator: language change and swap
    assert overlay.combo_src.currentData() == "uk"
    assert overlay.combo_tgt.currentData() == "en"

    overlay.swap_languages()
    assert overlay.combo_src.currentData() == "en"
    assert overlay.combo_tgt.currentData() == "uk"
    assert cfg.get("outgoing_my_lang") == "en"
    assert cfg.get("outgoing_target_lang") == "uk"

    # 7. Input field and live translation
    overlay.combo_src.setCurrentIndex(overlay.combo_src.findData("uk"))
    overlay.combo_tgt.setCurrentIndex(overlay.combo_tgt.findData("en"))
    overlay.input_field.setText("Дякую за гру")
    assert overlay.input_field.text() == "Дякую за гру"

    # Trigger async live translation without UI lag
    overlay._do_live_translate()
    import time
    for _ in range(30):
        qapp.processEvents()
        if overlay._current_translation:
            break
        time.sleep(0.05)
    assert overlay._current_translation != ""

    # Copying the translation
    copied_signals = []
    overlay.translate_and_copy.connect(lambda orig, trans: copied_signals.append((orig, trans)))
    overlay._copy_translation()

    assert len(copied_signals) == 1
    assert copied_signals[0][0] == "Дякую за гру"
    assert QApplication.clipboard().text() == copied_signals[0][1]

    # 8. Test Escape key interception in chat mode
    overlay.set_in_chat_mode(True)
    assert overlay.in_chat_mode is True
    esc_event = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    overlay.keyPressEvent(esc_event)
    assert overlay.in_chat_mode is False

    # 9. Clearing the chat
    overlay.clear_chat()
    assert len(overlay._entries) == 0


def test_message_fade_logic(qapp, tmp_path):
    cfg_file = tmp_path / "test_cfg.json"
    cfg = ConfigManager(str(cfg_file))
    cfg.set("message_fade_timeout", 1)  # 1 sec

    overlay = ChatOverlay(cfg)
    overlay.add_message("12:00:00", "Aron", "Test message", "Тест", "en", "player")

    # Message is visible right after being added
    visible = overlay._get_visible_entries()
    assert len(visible) == 1

    # Simulate time in the past
    overlay._entries[0].created_time = time.time() - 2.0

    # Now it is stale and should disappear in HUD mode
    visible_faded = overlay._get_visible_entries()
    assert len(visible_faded) == 0

    # But if chat (T) or setup mode (F9) is open, it is visible again!
    overlay.set_in_chat_mode(True)
    assert len(overlay._get_visible_entries()) == 1
    overlay.set_in_chat_mode(False)


def test_settings_dialog_smoke(qapp, tmp_path):
    cfg_file = tmp_path / "test_cfg.json"
    cfg = ConfigManager(str(cfg_file))
    settings = SettingsDialog(cfg)

    # Check loaded values
    assert settings.combo_in_lang.currentData() == "uk"
    assert settings.btn_k_lock.current_hotkey == "F9"
    assert settings.btn_k_vis.current_hotkey == "F8"
    assert settings.btn_k_chat.current_hotkey == "T"
    assert settings.slider_fade.value() == 10
    assert settings.chk_font_bold.isChecked() is False

    # Check saving
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

    # Clear the bind via clear_hotkey (the ❌ button)
    btn.clear_hotkey()
    assert btn.current_hotkey == ""
    assert btn.text() == "— Not assigned —"

    # Set a new value
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

    # 1. Initial state: enabled (ON) and locked
    assert badge.is_on is True
    assert badge.is_locked is True

    # 2. Switch state to OFF
    badge.set_status(False)
    assert badge.is_on is False
    assert cfg.get("overlay_enabled") is False

    # 3. Switch state back to ON
    badge.set_status(True)
    assert badge.is_on is True
    assert cfg.get("overlay_enabled") is True

    # 4. Toggling lock (F9)
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

    # Switching variant
    map_win._toggle_variant()
    assert map_win.canvas.current_variant == "tactical"

    # Adding a point
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

    # Editing the name
    row.txt_name.setText("Головна база")
    row._on_name_edited()
    assert pts_mgr.get_point_by_id(pt.id).name == "Головна база"

    # Filtering
    pts_win.txt_filter.setText("база")
    assert not row.isHidden()
    pts_win.txt_filter.setText("вертоліт")
    assert row.isHidden() is True
    pts_win.txt_filter.clear()
    assert not row.isHidden()

    # Changing pin color
    row._set_color("#ef4444")
    assert pt.color == "#ef4444"
    assert pts_mgr.get_point_by_id(pt.id).color == "#ef4444"

    # Closing with Escape
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

    # 1. Message from a blacklisted player
    controller._handle_raw_message("10:00:00", "trollplayer", "This is untranslated text", "player")
    # Should be emitted instantly without calling the translator
    qapp.processEvents()
    assert len(received) == 1
    sender, orig, trans, src = received[0]
    assert sender == "trollplayer"
    assert orig == "This is untranslated text"
    assert trans == "This is untranslated text"
    assert src == "orig"

    # 2. Message from a regular player
    controller._handle_raw_message("10:00:01", "GoodPlayer", "Hello", "player")
    # Wait for async translation
    for _ in range(30):
        qapp.processEvents()
        if len(received) >= 2:
            break
        time.sleep(0.05)
    assert len(received) == 2
    assert received[1][0] == "GoodPlayer"
    assert received[1][1] == "Hello"


def test_text_outline_and_scum_colors(qapp, tmp_path):
    from PyQt6.QtGui import QColor, QImage, QPainter
    cfg_file = tmp_path / "test_cfg.json"
    cfg = ConfigManager(str(cfg_file))
    cfg.set("text_outline", True)
    cfg.set("font_bold", False)
    cfg.set("font_size", 13)

    overlay = ChatOverlay(cfg)

    # 1. Adding a server message
    overlay.add_message("02:45:38", "Server", "Rule: No base raiding!", "Rule: No base raiding!", "en", "server")
    html = overlay.chat_view.toHtml()
    # SCUM color for server (#ffca00)
    assert "#ffca00" in html

    # 2. Adding a player message
    overlay.add_message("02:46:00", "PlayerOne", "Hello guys", "Привіт хлопці", "en", "player")
    html = overlay.chat_view.toHtml()
    # SCUM color for player (#00e5ff)
    assert "#00e5ff" in html

    # 3. Check outline rendering
    overlay.chat_view.resize(500, 200)
    img = QImage(500, 200, QImage.Format.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    overlay.chat_view.viewport().render(p)
    p.end()

    blacks = sum(1 for y in range(img.height()) for x in range(img.width()) if QColor(img.pixel(x, y)).lightness() < 30 and QColor(img.pixel(x, y)).alpha() > 200)
    assert blacks > 500, f"Expected black outline pixels, got {blacks}"

    # 4. Disabling the outline
    cfg.set("text_outline", False)
    overlay._refresh_rendered_chat()
    assert overlay.chat_view.outline_enabled is False


def test_squad_green_color(qapp, tmp_path):
    cfg_file = tmp_path / "test_cfg.json"
    cfg = ConfigManager(str(cfg_file))
    cfg.set("own_nickname", "MyHero")
    overlay = ChatOverlay(cfg)

    # 1. Squad via msg_type="squad"
    overlay.add_message("12:00:00", "Mate", "Cover me", "Прикрий мене", "en", "squad")
    html1 = overlay.chat_view.toHtml()
    assert "#4ade80" in html1

    # 2. Squad via nickname prefix: [Squad] Mate
    overlay.clear_chat()
    overlay.add_message("12:00:01", "[Squad] Mate", "Enemy ahead", "Ворог попереду", "en", "player")
    html2 = overlay.chat_view.toHtml()
    assert "#4ade80" in html2

    # 3. Squad via Ukrainian prefix: (сквад) Друг
    overlay.clear_chat()
    overlay.add_message("12:00:02", "(сквад) Друг", "Знайшов лут", "Знайшов лут", "uk", "player")
    html3 = overlay.chat_view.toHtml()
    assert "#4ade80" in html3

    # 4. Own nickname MyHero
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

    # Regular message - must not be translated or emitted
    controller._handle_raw_message("14:00:00", "Enemy", "I see you", "player")
    qapp.processEvents()
    time.sleep(0.1)
    assert len(received_translations) == 0

    # Message with coordinates - coordinates MUST be recognized for the map!
    sample_coord = "{X=150000.0 Y=250000.0 Z=1000.0|P=0 Y=0 R=0}"
    controller._handle_raw_message("14:00:05", "Teammate", f"Airdrop here {sample_coord}", "player")
    qapp.processEvents()
    time.sleep(0.1)

    assert len(received_translations) == 0  # Chat disabled
    assert len(received_coords) == 1        # Map received the point!
    assert received_coords[0].name == "Airdrop here"


def test_settings_language_tab_lists_installed_locales_and_saves_choice(qapp, tmp_path):
    from core.i18n import LocalizationManager, tr
    cfg = ConfigManager(str(tmp_path / "test_cfg.json"))
    cfg.set("ui_language", "en")

    dlg = SettingsDialog(cfg)
    assert LocalizationManager.get_instance().current_locale == "en"
    assert tr("settings.save_btn") == "💾 Save Settings"

    codes = [dlg.tab_language.combo.itemData(i) for i in range(dlg.tab_language.combo.count())]
    assert "en" in codes
    assert dlg.tab_language.selected_code() == "en"

    dlg.save_settings()
    assert cfg.get("ui_language") == "en"




"""Qt's own texts (file dialogs, standard buttons, the text-edit context menu) follow the interface language."""
import logging
from typing import Optional

from PyQt6.QtCore import QCoreApplication, QLibraryInfo, QTranslator

log = logging.getLogger("scum.qt_translation")

_active: Optional[QTranslator] = None
_active_code = ""


def apply_qt_language(code: str) -> bool:
    """Install Qt's translation for ``code`` (e.g. "uk"); for a language Qt has no file for the built-in English stays."""
    global _active, _active_code
    app = QCoreApplication.instance()
    if app is None or code == _active_code:
        return False
    if _active is not None:
        app.removeTranslator(_active)
        _active = None
    _active_code = code
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    for name in ("qtbase",):
        translator = QTranslator(app)
        if code and code != "en" and translator.load(f"{name}_{code}", folder):
            app.installTranslator(translator)
            _active = translator
            return True
    return False

import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu --no-sandbox')
os.environ['MANUAL_TEST'] = '1'
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)
_APP = QApplication.instance() or QApplication([])   # widgets need a QApplication, created before any test

from manual_app.ui.theme import apply_theme  # noqa: E402

apply_theme(_APP)

import pytest  # noqa: E402


@pytest.fixture
def db(tmp_path):
    from manual_app.core.db import Database
    d = Database(str(tmp_path / 'm.db'))
    yield d
    d.close()


@pytest.fixture
def manual(db):
    from manual_app.core import templates
    mid = templates.create_from_starter(db, 'institutional', {'title_ar': 'دليل الاختبار', 'title_en': 'Test manual',
                                                              'org_ar': 'مدرسة', 'org_en': 'School', 'issue_date': '2026-01-01'})
    return mid

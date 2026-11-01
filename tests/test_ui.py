import os

import pytest
from PySide6.QtWidgets import QAbstractButton, QComboBox, QLineEdit

import manual_app.ui.editor as editor_mod
from manual_app.ui import common


@pytest.fixture
def window(tmp_path, monkeypatch, manual, db):
    from manual_app.main import AppContext
    monkeypatch.setattr(editor_mod.Preview, 'show_html', lambda self, html, w=None: None)
    monkeypatch.setattr(common, 'info', lambda *a, **k: None)
    ctx = AppContext.__new__(AppContext)
    ctx.data_dir, ctx.db, ctx.window, ctx.user, ctx._license = str(tmp_path), db, None, None, None
    db.set('current_manual', manual)
    from manual_app.ui.main_window import MainWindow
    w = MainWindow(ctx)
    from manual_app.ui.theme import size_tree
    size_tree(w)
    yield w
    w.close()


def test_every_page_builds(window):
    for page in (window.home, window.editor, window.org, window.compliance, window.design, window.library,
                 window.doctor, window.export, window.users, window.settings):
        window.show_page(page)
    assert window.editor.tree.topLevelItemCount() > 5


def test_editor_edits_and_saves(window, db, manual):
    ed = window.editor
    v = next(s for s in db.sections(manual) if s['title_en'] == 'Vision')
    ed.reload_tree(select=v['id'])
    assert ed.sid == v['id']
    ed.blocks[0].ar.setPlainText('نص جديد')
    ed.blocks[0].en.setPlainText('New text')
    ed.add_block('table')
    ed.save()
    bl = db.blocks(v['id'])
    assert bl[0]['ar'] == 'نص جديد' and bl[0]['en'] == 'New text' and bl[-1]['kind'] == 'table'


def test_checker_page_fixes_and_undoes(window, db, manual):
    v = next(s for s in db.sections(manual) if s['title_en'] == 'Vision')
    db.replace_blocks(v['id'], [{'kind': 'paragraph', 'ar': 'نص\u200f  هنا', 'en': 'text'}])
    page = window.doctor
    page.measure.setChecked(False)
    page.load_manual(manual)
    page.run(measure=False)
    rules = [x['rule'] for x in page.all_issues()]
    assert 'bidi_marks' in rules and page.table.model.rowCount() == len(rules)
    i = rules.index('bidi_marks')
    page.show_issue(i)
    assert page.ed_ar.isVisibleTo(page) and 'هنا' in page.ed_ar.toPlainText()
    page.fix_all_safe()
    assert db.blocks(v['id'])[0]['ar'] == 'نص هنا'
    page.undo()
    assert db.blocks(v['id'])[0]['ar'] == 'نص\u200f  هنا'


def test_controls_have_accessible_names(window):
    """Every button, list and field the user reaches has a name for screen readers (Qt's own inner parts excepted)."""
    missing = []
    for t in (QAbstractButton, QComboBox, QLineEdit):
        for w in window.findChildren(t):
            if w.objectName().startswith('qt_') or type(w).__name__ == 'QAbstractButton':
                continue
            if isinstance(w.parentWidget(), (QComboBox, QLineEdit)):
                continue
            label = w.accessibleName() or (w.text() if isinstance(w, QAbstractButton) else '') or \
                (w.placeholderText() if isinstance(w, QLineEdit) else '')
            if not label:
                p = w.parentWidget()
                missing.append((type(w).__name__, type(p).__name__ if p else '', w.toolTip()))
    assert not missing, missing


_ = os

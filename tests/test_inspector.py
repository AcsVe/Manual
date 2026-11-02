"""The panel that opens when a part of the preview is clicked: cover, header, blocks and page directions."""
import pytest

from manual_app.core.html import build_html
from manual_app.ui import common


@pytest.fixture
def win(tmp_path, monkeypatch, db, manual):
    import manual_app.ui.editor as editor_mod
    from manual_app.main import AppContext
    from manual_app.ui.main_window import MainWindow
    monkeypatch.setattr(editor_mod.Preview, 'show_html', lambda self, html, w=None: None)
    monkeypatch.setattr(common, 'info', lambda *a, **k: None)
    ctx = AppContext.__new__(AppContext)
    ctx.data_dir, ctx.db, ctx.window, ctx.user, ctx._license = str(tmp_path), db, None, None, None
    db.set('current_manual', manual)
    w = MainWindow(ctx)
    ctx.window = w
    ctx.manual_id = manual
    yield w
    w.close()


def _vision(db, manual):
    return next(s for s in db.sections(manual) if s['title_en'] == 'Vision')


def test_cover_texts_shape_and_undo(win, db, manual):
    insp = win.editor.preview.inspector
    insp.show_for('c org')
    assert 'المؤسسة' in insp.title.text()
    insp.set_layout(lambda l: insp._cover_item(l, 'org').update(hidden=True))
    insp.set_layout(lambda l: insp._cover_item(l, 'title').update(color='#B42318', size=40))
    insp.set_layout(lambda l: l['cover'].update(style='none'))
    html = build_html(db, manual, 'print')
    cover = html[html.index('<div class="cover">'):][:3000]
    assert 'data-cv="org"' not in cover and 'data-cv="shape"' not in cover
    assert 'font-size:40.0pt;font-weight:700;color:#B42318' in cover
    insp.undo()
    assert db.manual(manual)['layout']['cover']['style'] != 'none'           # the last change is undone
    insp.set_manual(org_ar='', org_en='')
    assert not db.manual(manual)['org_ar']


def test_header_colours_and_removal(win, db, manual):
    insp = win.editor.preview.inspector
    insp.show_for('m header')
    insp.set_layout(lambda l: l['header'].update(style='band', color1='#1B6B3A', text_color='#000000'))
    html = build_html(db, manual, 'print')
    assert 'linear-gradient(#1B6B3A,#1B6B3A)' in html and 'color:#000000;font-size:8.5pt' in html
    insp.set_layout(lambda l: l['header'].update(style='none'))
    assert 'linear-gradient(#1B6B3A' not in build_html(db, manual, 'print')


def test_one_page_turned_and_block_look(win, db, manual):
    v = _vision(db, manual)
    db.replace_blocks(v['id'], [{'kind': 'paragraph', 'ar': f'فقرة {i}', 'en': f'para {i}'} for i in range(5)])
    insp = win.editor.preview.inspector
    insp.show_for(f'p page {v["id"]}:1 {v["id"]}:2')
    insp.turn_from(v['id'], 1, 'portrait', (v['id'], 2))      # the test manual is landscape
    kinds = [(b['kind'], (b.get('style') or {}).get('orient')) for b in db.blocks(v['id'])]
    assert kinds == [('paragraph', None), ('pagebreak', 'portrait'), ('paragraph', None), ('paragraph', None),
                     ('pagebreak', 'section'), ('paragraph', None), ('paragraph', None)]
    html = build_html(db, manual, 'print')
    assert '<div class="pgoT">' in html and html.count('class="pgoT"') == 1
    win.editor.picked(f'b {v["id"]}:0 ar')
    insp.set_blocks(v['id'], lambda bl: bl[0].update(style={'color': '#B42318', 'size': 120}))
    assert 'style="color:#B42318;font-size:120%;"' in build_html(db, manual, 'print')
    assert win.editor.sid == v['id']                                          # the editor follows the click


def test_shape_removed_from_one_page_only(win, db, manual):
    v = _vision(db, manual)
    db.replace_blocks(v['id'], [{'kind': 'paragraph', 'ar': f'فقرة {i}', 'en': f'para {i}'} for i in range(4)])
    insp = win.editor.preview.inspector
    insp.show_for(f'm header {v["id"]}:1 {v["id"]}:1')
    assert any('هذه الصفحة فقط' in b.text() for b in insp.findChildren(type(insp.undo_btn)))
    insp.shape_from(v['id'], 1, True, (v['id'], 1))
    heads = [(b['kind'], (b.get('style') or {}).get('head')) for b in db.blocks(v['id'])]
    assert heads == [('paragraph', None), ('pagebreak', 'plain'), ('paragraph', None), ('pagebreak', 'shape'),
                     ('paragraph', None), ('paragraph', None)]
    html = build_html(db, manual, 'print')
    assert 'class="pgoNp"' in html and '@page oriNp{' in html
    page_rule = html[html.index('@page oriNp{'):][:300]
    assert 'background:none' in page_rule or 'background:url' in page_rule      # no wave on that page


def test_right_click_menus_and_field_names(win, db, manual, monkeypatch):
    import PySide6.QtWidgets as qw
    shown = []

    class Menu(qw.QMenu):                     # records the menu instead of waiting for a click
        def exec(self, *a, **k):
            shown.append([x.text() for x in self.actions() if x.text()])
    QMenu = qw.QMenu
    monkeypatch.setattr(qw, 'QMenu', Menu)
    v = _vision(db, manual)
    win.editor.reload_tree(select=v['id'])
    blk = win.editor.blocks[0]
    m = QMenu()
    blk.fill_menu(m)
    texts = [a.text() for a in m.actions() if a.text()]
    assert 'إضافة كتلة بعدها' in texts and 'حذف الكتلة' in texts
    table = win.home.manuals.table
    table._context_menu(table.view.visualRect(table.proxy.index(0, 0)).center())
    assert shown and 'فتح في المحرر' in shown[-1] and 'تصدير إلى Excel…' in shown[-1]
    # header and footer boxes show the names of the fields, and keep the codes when saved
    from manual_app.ui.inspector import TokenEdit
    t = TokenEdit('صفحة {page} من {pages}')
    assert t.edit.text() == 'صفحة [رقم الصفحة] من [عدد الصفحات]' and t.text() == 'صفحة {page} من {pages}'
    t.edit.setText('[عنوان الدليل] — [غير معروف]')
    assert t.text() == '{title} — [غير معروف]'


def test_no_english_words_in_arabic_texts():
    import glob
    import re
    allowed = {'PDF', 'Word', 'Excel', 'HTML', 'RACI', 'PNG', 'JPG', 'ManualBuilder', 'Windows', 'docx', 'https'}
    found = []
    for f in glob.glob('manual_app/ui/*.py') + glob.glob('manual_app/core/*.py'):
        s = open(f, encoding='utf-8').read()
        for m in re.finditer(r"L\(\s*'((?:[^'\\]|\\.)*)'\s*,", s):
            words = set(re.findall(r'[A-Za-z]{3,}', m.group(1))) - allowed
            if words or '{page' in m.group(1):
                found.append((f, m.group(1)[:60]))
    assert not found, found

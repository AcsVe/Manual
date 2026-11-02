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

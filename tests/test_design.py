"""Backgrounds, page direction per section, alignment and whole-page images: the description, the printed pages,
the PDF and the screens that edit them."""
import pytest

from manual_app.core import backgrounds as BG
from manual_app.core import doctor
from manual_app.core.html import build_html
from manual_app.core.templates import layout_with_defaults

PNG = (b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x02\x00\x00\x00\x01\x08\x02\x00\x00\x00{@\xe8\xdd\x00\x00'
       b'\x00\x0fIDATx\x9cc\xf8\xcf\xc0\xf0\x1f\x00\x05\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82')


def _asset(db, w=2, h=1):
    return db.add_asset('bg.png', PNG, 'image/png', 'background', w, h)


def _portrait(db, manual):
    lay = layout_with_defaults(db.manual(manual)['layout'])
    lay['orientation'] = 'portrait'
    db.save_manual({'layout': lay}, manual)
    return lay


def _vision(db, manual):
    return next(s for s in db.sections(manual) if s['title_en'] == 'Vision')


def test_old_backgrounds_read_as_the_new_description():
    lay = {'page_bg_id': 3, 'page_bg_opacity': 0.06, 'cover': {'bg_id': 4}}
    assert BG.of_page(lay)['asset_id'] == 3 and BG.of_page(lay)['opacity'] == 0.06
    assert BG.of_cover(lay)['asset_id'] == 4
    st = BG.of_section({'bg_id': 5, 'bg_mode': 'behind', 'bg_opacity': 0.2, 'bg_fit': 'contain'})
    assert st['area'] == 'section' and st['fit'] == 'contain' and st['opacity'] == 0.2
    assert BG.normalize({'rotate': 45, 'pos': 'x', 'opacity': 9})['rotate'] == 0
    assert BG.normalize({'pos': 'x'})['pos'] == 'center' and BG.normalize({'opacity': 9})['opacity'] == 1.0


def test_turned_image_is_wrapped_and_placed():
    bg = BG.normalize({'asset_id': 1, 'rotate': 90, 'flip': True, 'opacity': 0.5, 'fit': 'width', 'scale': 40,
                       'pos': 'bottom-left'})
    uri = BG.image_uri('data:image/png;base64,AA', 200, 100, bg)
    assert uri.startswith('data:image/svg+xml;base64,')
    import base64
    svg = base64.b64decode(uri.split(',', 1)[1]).decode()
    assert 'width="100" height="200"' in svg and 'rotate(90)' in svg and 'scale(-1,1)' in svg
    assert BG.css(bg, uri).endswith('left bottom / 40% auto no-repeat')


def test_page_cover_and_section_backgrounds_in_the_pages(db, manual):
    a = _asset(db)
    lay = _portrait(db, manual)
    lay['page_bg'] = {'asset_id': a, 'layer': 'front', 'opacity': 0.1}
    lay['cover'] = dict(lay['cover'], bg={'color': '#112233', 'layer': 'behind'})
    lay['align'] = 'center'
    db.save_manual({'layout': lay}, manual)
    v = _vision(db, manual)
    db.save_section({'style': {'bg': {'asset_id': a, 'area': 'section', 'layer': 'behind', 'opacity': 0.2},
                               'orientation': 'landscape'}}, v['id'])
    html = build_html(db, manual, 'print')
    assert '.pagedjs_pagebox::after{background:' in html          # in front of the text of every page
    assert 'rgba(17,34,51' in html and 'C760,470' not in html             # the cover colour replaces the wave
    assert f'pg{v["id"]}' in html and f'@page sp{v["id"]}' in html  # its own (turned) pages
    assert '.bgr1>.frame' in html and '.ar{text-align:center}' in html.replace(' ', '')


def test_whole_page_image_and_block_alignment(db, manual):
    _portrait(db, manual)
    a = _asset(db, 300, 100)
    v = _vision(db, manual)
    db.replace_blocks(v['id'], [{'kind': 'paragraph', 'ar': 'نص', 'en': 'text', 'style': {'align': 'left'}},
                                {'kind': 'image', 'ar': '', 'en': '', 'data': {'asset_id': a},
                                 'style': {'fullpage': True}}])
    html = build_html(db, manual, 'print')
    assert 'al-left' in html and 'fullimg fullL' in html          # a wide image takes a landscape page


def test_mixed_directions_print_as_one_pdf(db, manual, tmp_path):
    from manual_app.core.pdf import make_pdf_blocking, page_size_mm
    from pypdf import PdfReader
    _portrait(db, manual)
    v = _vision(db, manual)
    db.save_section({'style': {'orientation': 'landscape'}}, v['id'])
    out = str(tmp_path / 'm.pdf')
    ok, msg = make_pdf_blocking(build_html(db, manual, 'print'), out, page_size_mm(db.manual(manual)), 240)
    assert ok, msg
    shapes = {(p.mediabox.width > p.mediabox.height) for p in PdfReader(out).pages}
    assert shapes == {True, False}


def test_strong_background_is_found_and_lowered(db, manual):
    a = _asset(db)
    v = _vision(db, manual)
    db.save_section({'style': {'bg': {'asset_id': a, 'area': 'section', 'opacity': 0.9}}}, v['id'])
    issues = [x for x in doctor.check(db, manual) if x['rule'] == 'bg_strong']
    assert issues
    doctor.apply(db, manual, issues)
    assert BG.of_section(db.section(v['id'])['style'])['opacity'] == 0.15


def test_background_dialog(db):
    from manual_app.ui.background import BackgroundDialog
    a = _asset(db)
    d = BackgroundDialog(None, db, {'asset_id': a}, 'x', section=True)
    d.layer.setCurrentIndex(d.layer.findData('front'))
    d.pos.set_value('top-left')
    d.rotate.setCurrentIndex(d.rotate.findData(270))
    d._ok()
    assert d.value['layer'] == 'front' and d.value['pos'] == 'top-left' and d.value['rotate'] == 270
    d2 = BackgroundDialog(None, db, None, 'x')
    d2._ok()
    assert d2.value is None                                          # nothing chosen: no background


@pytest.mark.parametrize('dummy', [0])
def test_block_inserted_after_and_section_direction_saved(dummy, tmp_path, monkeypatch, db, manual):
    import manual_app.ui.editor as editor_mod
    from manual_app.main import AppContext
    from manual_app.ui.main_window import MainWindow
    monkeypatch.setattr(editor_mod.Preview, 'show_html', lambda self, html, w=None: None)
    ctx = AppContext.__new__(AppContext)
    ctx.data_dir, ctx.db, ctx.window, ctx.user, ctx._license = str(tmp_path), db, None, None, None
    db.set('current_manual', manual)
    w = MainWindow(ctx)
    ed = w.editor
    v = _vision(db, manual)
    ed.reload_tree(select=v['id'])
    n = len(ed.blocks)
    ed.add_block('callout', 0)
    assert len(ed.blocks) == n + 1 and ed.blocks[0].value()['kind'] == 'callout'
    ed.blocks[0].align.setCurrentIndex(ed.blocks[0].align.findData('center'))
    ed.form.orientation.setCurrentIndex(ed.form.orientation.findData('landscape'))
    ed.save()
    s = db.section(v['id'])
    assert s['style']['orientation'] == 'landscape'
    assert db.blocks(v['id'])[0]['style']['align'] == 'center'
    w.close()

"""The editor with long sections (blocks in pages), the link from a click on the preview, the direction of the text
boxes, and a block's own look (font, colour, size, alignment) in the PDF page and in Word."""
import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

import manual_app.ui.editor as editor_mod
from manual_app.ui import common


@pytest.fixture
def window(tmp_path, monkeypatch, manual, db):
    from manual_app.main import AppContext
    from manual_app.ui.main_window import MainWindow
    shown = []
    monkeypatch.setattr(editor_mod.Preview, 'show_html', lambda self, html, w=None: shown.append(html))
    monkeypatch.setattr(common, 'info', lambda *a, **k: None)
    ctx = AppContext.__new__(AppContext)
    ctx.data_dir, ctx.db, ctx.window, ctx.user, ctx._license = str(tmp_path), db, None, None, None
    db.set('current_manual', manual)
    w = MainWindow(ctx)
    ctx.window = w
    w.show()
    w.show_page(w.editor)
    w.shown = shown
    yield w
    w.close()


def _long_section(db, manual, n=130):
    s = next(s for s in db.sections(manual) if s['title_en'] == 'Vision')
    db.replace_blocks(s['id'], [{'kind': 'paragraph', 'ar': f'فقرة {i}', 'en': f'Paragraph {i}'} for i in range(n)])
    return s['id']


def test_long_section_opens_a_page_of_blocks_and_saves_them_all(window, db, manual):
    sid = _long_section(db, manual)
    ed = window.editor
    ed.reload_tree(select=sid)
    assert len(ed.blocks) == editor_mod.BLOCK_PAGE and len(ed._stored) == 130 and ed.pager.isVisibleTo(ed)
    ed._show_block_page(100)
    assert ed._first == 100 and len(ed.blocks) == 30
    ed.blocks[0].ar.setPlainText('فقرة معدّلة')
    ed.add_block('paragraph')
    ed.save()
    saved = db.blocks(sid)
    assert len(saved) == 131 and saved[100]['ar'] == 'فقرة معدّلة' and saved[99]['ar'] == 'فقرة 99'
    assert saved[-1]['kind'] == 'paragraph' and saved[129]['ar'] == 'فقرة 129'
    html = window.shown[-1]                            # the preview of a long section: only the open page
    assert 'data-b="%d:100"' % sid in html and 'data-b="%d:5"' % sid not in html


def test_a_click_on_the_preview_opens_the_block_here(window, db, manual):
    sid = _long_section(db, manual)
    ed = window.editor
    ed.reload_tree(select=sid)
    ed.picked(f'b {sid}:3 ar')                         # the same section: the block still comes into view
    assert ed._first == 0 and ed.preview.inspector.isVisible()
    ed.picked(f'b {sid}:120 en')                       # a block on another page of the section
    assert ed._first == 100


def test_text_boxes_follow_their_direction_and_ctrl_shift_aligns(window, db, manual):
    from PySide6.QtWidgets import QApplication as App
    w = editor_mod.BlockWidget(window.ctx, {'kind': 'paragraph', 'ar': '2026 خطة العمل', 'en': 'Plan'})
    b = w.ar.document().firstBlock()
    assert b.textDirection() == Qt.RightToLeft
    assert b.blockFormat().alignment() & Qt.AlignRight and b.blockFormat().alignment() & Qt.AlignAbsolute
    assert w.en.document().firstBlock().blockFormat().alignment() & Qt.AlignLeft
    for t, k, m in ((QEvent.KeyPress, Qt.Key_Control, Qt.NoModifier), (QEvent.KeyPress, Qt.Key_Shift, Qt.ControlModifier),
                    (QEvent.KeyRelease, Qt.Key_Shift, Qt.ControlModifier), (QEvent.KeyRelease, Qt.Key_Control, Qt.NoModifier)):
        App.sendEvent(w.ar, QKeyEvent(t, k, m, 0x2A, 0, 0))       # Ctrl with the left Shift (both let go after)
    assert w.align.currentData() == 'left' and w.value()['style']['align'] == 'left'
    assert w.value()['ar'] == '2026 خطة العمل'                     # the text itself is untouched
    # Qt keeps the modifiers of the last key pressed: a plain key pressed leaves none held for the next tests
    from PySide6.QtWidgets import QWidget
    App.sendEvent(QWidget(), QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))


def test_block_font_in_the_page_and_in_word(db, manual):
    from manual_app.core.docx_export import DocxExporter
    from manual_app.core.html import build_html
    s = next(s for s in db.sections(manual) if s['title_en'] == 'Vision')
    db.replace_blocks(s['id'], [{'kind': 'paragraph', 'ar': 'نص بخط آخر', 'en': 'Other font',
                                 'style': {'font': 'Amiri', 'align': 'left', 'size': 150, 'bold': True, 'color': '#aa0000'}},
                                {'kind': 'paragraph', 'ar': 'خط غير آمن', 'en': '', 'style': {'font': 'x";}body{'}}])
    html = build_html(db, manual, 'print', only=[s['id']])
    assert "--bf:'Amiri';font-family:'Amiri'" in html and 'body{' not in html.split('x";')[0][-5:]
    assert '@font-face{font-family:"Amiri"' in html                 # the program's font travels with the page
    e = DocxExporter(db, manual)
    e.block(db.blocks(s['id'])[0])
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    paras = [p for t in e.doc.tables for c in t._cells for p in c.paragraphs if p.text]
    ar = next(p for p in paras if 'بخط' in p.text)
    run = ar.runs[0]
    assert run.bold and run.font.color.rgb == __import__('docx').shared.RGBColor(0xAA, 0, 0)
    assert run._r.rPr.find(qn('w:rFonts')).get(qn('w:cs')) == 'Amiri'
    assert ar.alignment == WD_ALIGN_PARAGRAPH.RIGHT        # «left» of a right-to-left paragraph in Word
    en = next(p for p in paras if 'Other' in p.text)
    assert en.alignment == WD_ALIGN_PARAGRAPH.LEFT and en.runs[0].font.name == 'Amiri'
    assert abs(en.runs[0].font.size.pt - float(e.lay['fonts']['size']) * 1.5) <= 0.5     # Word keeps half points


def test_panel_chooses_a_font_for_one_block(window, db, manual):
    from manual_app.ui.fonts import FontPicker
    s = next(s for s in db.sections(manual) if s['title_en'] == 'Vision')
    ins = window.editor.preview.inspector
    ins.show_for(f'b {s["id"]}:0 ar')
    pick = next(p for p in ins.findChildren(FontPicker))
    assert pick.value() == ''                                       # «as the manual» first
    pick.setCurrentIndex(pick.findData('Cairo'))
    assert db.blocks(s['id'])[0]['style'].get('font') == 'Cairo'
    pick.setCurrentIndex(pick.findData(''))
    assert 'font' not in (db.blocks(s['id'])[0]['style'] or {})

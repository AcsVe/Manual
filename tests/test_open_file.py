"""Opening any file at once as a new manual, and the short «new manual» dialog."""
import pytest
from PySide6.QtCore import QMarginsF, QRectF, QSizeF
from PySide6.QtGui import QColor, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter

from manual_app.core import importer
from manual_app.ui import common
from manual_app.ui import manuals as manuals_mod


def _scan_pdf(path, pages=2, landscape=True):
    """A PDF of drawings only (no text), like a scanned file."""
    w = QPdfWriter(str(path))
    w.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Landscape if landscape else QPageLayout.Portrait,
                                QMarginsF(0, 0, 0, 0)))
    p = QPainter(w)
    for i in range(pages):
        if i:
            w.newPage()
        p.fillRect(QRectF(100, 100, 3000, 1500), QColor('#335577'))
    p.end()


@pytest.fixture
def quiet(monkeypatch):
    msgs = []
    monkeypatch.setattr(manuals_mod, 'info', lambda _p, t: msgs.append(t))
    monkeypatch.setattr(manuals_mod, 'confirm', lambda _p, t: (msgs.append(t), False)[1])
    monkeypatch.setattr(manuals_mod, 'error', lambda _p, t: msgs.append('ERROR ' + t))
    return msgs


class Ctx:
    def __init__(self, db):
        self.db, self.window, self.manual_id, self.workflow = db, None, None, False


def test_scanned_pdf_opens_as_whole_pages(db, tmp_path, quiet):
    pdf = tmp_path / 'نظام الموارد.pdf'
    _scan_pdf(pdf, 3)
    assert importer.file_orientation(str(pdf)) == 'landscape'
    ctx = Ctx(db)
    mid = manuals_mod.open_file(None, ctx, str(pdf))
    assert mid and ctx.manual_id == mid, quiet
    m = db.manual(mid)
    assert m['title_ar'] == 'نظام الموارد' and m['layout']['orientation'] == 'landscape'
    pics = [b for s in db.sections(mid) for b in db.blocks(s['id']) if b['kind'] == 'image']
    assert len(pics) == 3 and all(b['style'].get('fullpage') for b in pics)
    assert 'صفحة كاملة' in quiet[-1] or 'صفحات' in quiet[-1]


def test_text_picture_and_unsupported_files(db, tmp_path, quiet):
    ctx = Ctx(db)
    txt = tmp_path / 'notes.txt'
    txt.write_text('فقرة أولى\n\nSecond paragraph', encoding='utf-8')
    mid = manuals_mod.open_file(None, ctx, str(txt))
    blocks = [b for s in db.sections(mid) for b in db.blocks(s['id'])]
    text = ' '.join((b['ar'] or '') + (b['en'] or '') for b in blocks)
    assert 'فقرة أولى' in text and 'Second paragraph' in text and db.manual(mid)['title_en'] == 'notes'
    img = QImage(400, 900, QImage.Format_RGB32)
    img.fill(QColor('#ffffff'))
    png = tmp_path / 'page.png'
    img.save(str(png))
    assert importer.file_orientation(str(png)) == 'portrait'
    mid = manuals_mod.open_file(None, ctx, str(png))
    assert db.manual(mid)['layout']['orientation'] == 'portrait'
    doc = tmp_path / 'old.doc'
    doc.write_bytes(b'x')
    n = len(db.manuals())
    assert manuals_mod.open_file(None, ctx, str(doc)) is None
    assert len(db.manuals()) == n and '.docx' in quiet[-1]        # nothing is left behind, and the way out is named


def test_new_manual_needs_nothing(db, monkeypatch):
    monkeypatch.setattr(common, 'info', lambda *a, **k: None)
    d = manuals_mod.NewManualDialog(None, Ctx(db))
    assert not hasattr(d, 'orient')                              # the direction is chosen per section, not here
    d._ok()
    m = db.manual(d.result_id)
    assert m['title_ar'] == 'دليل جديد' and m['layout']['orientation'] == 'portrait'


def _designed_pdf(path):
    """A cover in one colour, then a page with a coloured band, a frame and text."""
    w = QPdfWriter(str(path))
    w.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(0, 0, 0, 0)))
    w.setResolution(72)
    p = QPainter(w)
    p.fillRect(QRectF(0, 0, 595, 842), QColor('#7A1F2B'))
    w.newPage()
    p.fillRect(QRectF(0, 0, 595, 70), QColor('#1B6B3A'))
    p.drawRect(QRectF(30, 90, 535, 700))
    from PySide6.QtGui import QFont
    p.setFont(QFont('DejaVu Sans', 12))
    for i in range(12):
        p.drawText(QRectF(50, 120 + i * 24, 495, 20), 0x0002, f'Rule {i + 1} of the school about the matrix')
    p.end()


def test_pdf_opens_with_its_cover_and_page_design(db, tmp_path, quiet):
    from manual_app.core import backgrounds as BG
    pdf = tmp_path / 'designed.pdf'
    _designed_pdf(pdf)
    ctx = Ctx(db)
    mid = manuals_mod.open_file(None, ctx, str(pdf))
    lay = db.manual(mid)['layout']
    assert BG.active(BG.of_page(lay)) and lay['header']['style'] == 'none' and lay['boxes'] is False
    secs = db.sections(mid)
    assert not any(s['kind'] == 'cover' for s in secs)                   # the file's own first page is the cover
    first = db.blocks(secs[0]['id'])[0]
    assert first['kind'] == 'image' and first['style'].get('fullpage')
    from manual_app.core.html import build_html
    html = build_html(db, mid, 'print')
    assert 'class="fullimg' in html and 'Rule 3 of the school' in html


def test_picture_in_header_and_footer(db, manual):
    from manual_app.core.html import build_html
    from manual_app.core.templates import layout_with_defaults
    aid = db.add_asset('band.png', b'\x89PNG\r\n\x1a\n', 'image/png', 'background', 400, 40)
    lay = layout_with_defaults(db.manual(manual)['layout'])
    lay['header'].update(style='image', image_bg={'asset_id': aid, 'fit': 'contain', 'pos': 'right'})
    lay['footer'].update(style='wave', color1='#1B6B3A', height=12)
    db.save_manual({'layout': lay}, manual)
    css = build_html(db, manual, 'print')
    assert 'top left / 100% 24.0mm' in css or 'top left / 100% 24mm' in css or ') top left / 100%' in css
    assert ') bottom left / 100% 12.0mm no-repeat' in css                 # the footer shape sits at the bottom

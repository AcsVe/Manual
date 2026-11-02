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

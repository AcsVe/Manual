"""شكل ملف PDF الأصلي: التصميم لكل صفحة، والغلاف والصفحات الفاصلة، وتغيّر التصميم داخل الملف، وكلمة المرور، والملف التالف."""
import pytest
from PySide6.QtCore import QMarginsF, QRectF
from PySide6.QtGui import QColor, QFont, QPageLayout, QPageSize, QPainter, QPdfWriter

from manual_app.core import pdf_look
from manual_app.core.html import build_html
from manual_app.ui import manuals as manuals_mod

TEXT = ('Policy text line for the manual, describing duties and the review of permissions in detail '
        'so that the page carries a real paragraph.')


def _pdf(path, pages):
    """pages: [(band colour or None, ground colour or None, lines of text)] — a cover is a page with a ground and one line."""
    w = QPdfWriter(str(path))
    w.setResolution(72)
    w.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(0, 0, 0, 0)))
    p = QPainter(w)
    p.setFont(QFont('DejaVu Sans', 11))
    for i, (band, ground, lines) in enumerate(pages):
        if i:
            w.newPage()
        W, H = w.width(), w.height()
        if ground:
            p.fillRect(QRectF(0, 0, W, H), QColor(ground))
        if band:
            p.fillRect(QRectF(0, 0, W, 80), QColor(band))
        y = 130
        for t in lines:
            p.drawText(60, y, t)
            y += 17
        p.drawText(int(W / 2), H - 25, str(i + 1))
    p.end()


def _two_designs(path):
    _pdf(path, [(None, '#0d2a4d', ['Cover'])] +
         [('#1f4e8c', None, [TEXT[:90]] * 40) for _ in range(3)] +
         [('#2e7d32', None, [TEXT[:90]] * 40) for _ in range(3)])


def test_designs_cover_and_change(tmp_path):
    pdf = tmp_path / 'two.pdf'
    _two_designs(pdf)
    look = pdf_look.analyse(str(pdf))
    try:
        assert look['cover'] and 1 in look['image_pages']
        keys = pdf_look.page_keys(look)
        assert keys[2] == keys[3] == keys[4] and keys[5] == keys[6] == keys[7] and keys[2] != keys[5]
        assert look['number_pos'] == 'center'
        img = pdf_look.group_design(look, int(keys[2][:-1]))
        assert img and img[1] > 500                  # the blue band, without the text
    finally:
        pdf_look.close(look)


def test_pale_ground_is_a_design_and_white_is_plain(tmp_path):
    pale, white = tmp_path / 'pale.pdf', tmp_path / 'white.pdf'
    _pdf(pale, [(None, '#fbf5e6', [TEXT[:90]] * 30)] * 3)
    _pdf(white, [(None, None, [TEXT[:90]] * 30)] * 3)
    a, b = pdf_look.analyse(str(pale)), pdf_look.analyse(str(white))
    try:
        assert not a['groups'][a['pages'][0]['group']]['plain']
        assert b['groups'][b['pages'][0]['group']]['plain']
    finally:
        pdf_look.close(a)
        pdf_look.close(b)


def test_password_and_damaged_files(tmp_path):
    from pypdf import PdfReader, PdfWriter
    src = tmp_path / 'src.pdf'
    _pdf(src, [(None, None, [TEXT[:90]] * 10)] * 2)
    locked = tmp_path / 'locked.pdf'
    w = PdfWriter(clone_from=PdfReader(str(src)))
    w.encrypt(user_password='1234', owner_password='o', algorithm='AES-256')
    w.write(str(locked))
    with pytest.raises(pdf_look.PdfPasswordError):
        pdf_look.prepare(str(locked))
    use, tmp, note = pdf_look.prepare(str(locked), '1234')
    assert note == 'decrypted' and pdf_look.analyse(use)['n'] == 2
    raw = src.read_bytes()
    broken = tmp_path / 'broken.pdf'
    broken.write_bytes(raw[:raw.rfind(b'startxref')] + b'startxref\n99999\n%%EOF\n')
    assert pdf_look.prepare(str(broken))[0]
    cut = tmp_path / 'cut.pdf'
    cut.write_bytes(raw[:len(raw) // 3])
    with pytest.raises(ValueError):
        pdf_look.prepare(str(cut))


class Ctx:
    def __init__(self, db):
        self.db, self.window, self.manual_id, self.workflow = db, None, None, False


@pytest.fixture
def quiet(monkeypatch):
    msgs = []
    monkeypatch.setattr(manuals_mod, 'info', lambda _p, t: msgs.append(t))
    monkeypatch.setattr(manuals_mod, 'confirm', lambda _p, t: (msgs.append(t), False)[1])
    monkeypatch.setattr(manuals_mod, 'error', lambda _p, t: msgs.append('ERROR ' + t))
    return msgs


def test_open_keeps_each_design(db, tmp_path, quiet):
    pdf = tmp_path / 'two.pdf'
    _two_designs(pdf)
    mid = manuals_mod.open_file(None, Ctx(db), str(pdf))
    assert mid, quiet
    lay = db.manual(mid)['layout']
    assert lay['page_bg'] and lay['page_bg']['asset_id'] and lay['header']['style'] == 'none'
    assert lay['footer']['center'] == '{page}' and lay['lang_mode'] == 'en'
    blocks = [b for s in db.sections(mid) for b in db.blocks(s['id'])]
    assert blocks[0]['kind'] == 'image' and blocks[0]['style'].get('fullpage')          # the file's own cover first
    assert not [s for s in db.sections(mid) if s['kind'] == 'cover']
    turns = [b['style'] for b in blocks if b['kind'] == 'pagebreak' and b['style'].get('page_bg')]
    assert turns and all(isinstance(t['page_bg'], int) for t in turns)                  # the green pages
    html = build_html(db, mid, 'print')
    assert 'Ng' + str(turns[0]['page_bg']) in html and '@page oriNg' in html


def test_password_prompt_on_open(db, tmp_path, quiet, monkeypatch):
    from pypdf import PdfReader, PdfWriter
    import PySide6.QtWidgets as W
    src = tmp_path / 'src.pdf'
    _pdf(src, [(None, None, [TEXT[:90]] * 10)] * 2)
    locked = tmp_path / 'locked.pdf'
    w = PdfWriter(clone_from=PdfReader(str(src)))
    w.encrypt(user_password='1234', owner_password='o', algorithm='AES-256')
    w.write(str(locked))
    answers = iter([('0000', True), ('1234', True)])
    monkeypatch.setattr(W.QInputDialog, 'getText', staticmethod(lambda *a, **k: next(answers)))
    mid = manuals_mod.open_file(None, Ctx(db), str(locked))
    assert mid, quiet
    text = ' '.join(b['en'] or '' for s in db.sections(mid) for b in db.blocks(s['id']))
    assert 'Policy text line' in text


def test_a_failed_reading_is_told_and_kept(db, tmp_path, quiet, monkeypatch):
    pdf = tmp_path / 'two.pdf'
    _two_designs(pdf)
    ctx = Ctx(db)
    ctx.data_dir = str(tmp_path / 'data')

    def boom(*_a, **_k):
        raise RuntimeError('reading failed on purpose')
    monkeypatch.setattr(pdf_look, 'analyse', boom)
    assert manuals_mod.open_file(None, ctx, str(pdf)) is None            # the person said no: nothing is made
    assert 'تعذّرت قراءة تصميم' in quiet[-1] and 'open-file.log' in quiet[-1]
    assert 'reading failed on purpose' in (tmp_path / 'data' / 'logs' / 'open-file.log').read_text(encoding='utf-8')
    assert not db.manuals(active_only=False)

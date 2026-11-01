"""The PDF goes through the built-in browser engine: pages, header/footer counters and content must come out."""
from manual_app.core.html import build_html
from manual_app.core.pdf import count_pages, make_pdf_blocking, page_size_mm


def test_pdf_pages(db, manual, tmp_path):
    v = next(s for s in db.sections(manual) if s['title_en'] == 'Vision')
    db.replace_blocks(v['id'], [{'kind': 'paragraph', 'ar': 'نص طويل ' * 900, 'en': 'long text ' * 900}])
    out = str(tmp_path / 'm.pdf')
    ok, msg = make_pdf_blocking(build_html(db, manual, 'print'), out, page_size_mm(db.manual(manual)), 240)
    assert ok, msg
    assert count_pages(out) >= 12          # the long paragraph runs over several pages instead of being cut

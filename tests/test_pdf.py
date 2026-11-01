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


def test_layout_check_measures_pages(db, manual):
    from manual_app.core import doctor
    from manual_app.core.pdf import audit_blocking
    v = next(s for s in db.sections(manual) if s['title_en'] == 'Vision')
    cols = [{'ar': f'عمود {i}', 'en': f'Column {i}'} for i in range(6)]
    db.replace_blocks(v['id'], [{'kind': 'paragraph', 'ar': 'نص ' * 1500, 'en': 'text ' * 1300},
                                {'kind': 'table', 'ar': '', 'en': '', 'data': {'columns': cols, 'rows': [[{'ar': 'x', 'en': 'y'}] * 6] * 4}}])
    a = audit_blocking(build_html(db, manual, 'print'), page_size_mm(db.manual(manual)), 240)
    assert a['pages'] >= 8
    issues = doctor.from_audit(db, manual, a)
    bad = [(x['rule'], x['sid'], x['b'], x['msg'][1]) for x in issues if x['rule'] in ('lay_lost', 'lay_dup')]
    assert not bad, bad      # long text side by side prints whole

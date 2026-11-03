"""Fonts: the program's own fonts and any font installed in Windows, in the design page, the PDF, Word and the chart."""
from PySide6.QtGui import QFontDatabase

from manual_app.core import orgchart, textmeasure
from manual_app.core.html import build_html
from manual_app.core.pdf import make_pdf_blocking, page_size_mm
from manual_app.core.templates import FONTS, layout_with_defaults


def _system_arabic_font():
    from manual_app.ui.fonts import installed_families
    fams = installed_families(arabic=True)
    return fams[0] if fams else None


def _use_fonts(db, manual, ar, en):
    lay = layout_with_defaults(db.manual(manual)['layout'])
    lay['fonts'].update(ar=ar, en=en)
    db.save_manual({'layout': lay}, manual)


def test_picker_lists_program_and_installed_fonts():
    from manual_app.ui.fonts import FontPicker
    p = FontPicker(arabic=True)
    names = [p.itemData(i) for i in range(p.count())]
    assert all(f in names for f in FONTS)
    for fam in names:
        if fam and fam not in FONTS:
            assert QFontDatabase.WritingSystem.Arabic in QFontDatabase.writingSystems(fam)
    p.set_value('A font only on another computer')
    assert p.value() == 'A font only on another computer'      # kept as chosen, marked as not installed
    p.set_value('Amiri')
    assert p.value() == 'Amiri' and not p.is_system()


def test_installed_font_prints_inside_the_pdf(db, manual, tmp_path):
    fam = _system_arabic_font()
    if not fam:
        return
    _use_fonts(db, manual, fam, fam)
    html = build_html(db, manual, 'print')
    assert f'"{fam}"' in html
    out = str(tmp_path / 'f.pdf')
    ok, msg = make_pdf_blocking(html, out, page_size_mm(db.manual(manual)), 240)
    assert ok, msg
    from pypdf import PdfReader
    used = {str(f.get_object()['/BaseFont']) for pg in PdfReader(out).pages
            for f in (pg['/Resources'].get('/Font') or {}).values()}
    assert any(fam.replace(' ', '') in u for u in used), used


def test_word_uses_installed_font_by_name(db, manual):
    from manual_app.core.docx_export import DocxExporter
    fam = _system_arabic_font() or 'Traditional Arabic'
    _use_fonts(db, manual, fam, 'Times New Roman')
    e = DocxExporter(db, manual)
    assert (e.font_ar, e.font_en) == (fam, 'Times New Roman')
    _use_fonts(db, manual, 'Tajawal', 'Tajawal')
    e = DocxExporter(db, manual)
    assert (e.font_ar, e.font_en) == ('Tajawal', 'Calibri')


def test_chart_boxes_fit_their_names():
    name = 'العلاقات العامة والإعلام والاتصال المؤسسي'
    roots = [{'id': 1, 'name_ar': 'مجلس الإدارة', 'name_en': 'Board', 'children': [
        {'id': 2, 'name_ar': name, 'name_en': 'Public Relations, Media and Corporate Communication', 'children': []}]}]
    for fam in list(FONTS) + [f for f in [_system_arabic_font()] if f]:
        svg = orgchart.render_svg(roots, 'bi_side', font=fam)
        inner = orgchart.BW - orgchart.PAD
        for text, size, bold in orgchart._texts(roots[0]['children'][0], 'bi_side'):
            for line in orgchart._wrap(text, size, inner, bold):
                assert textmeasure.width(line, size, bold, fam) <= inner, (fam, line)
        assert 'unicode-range' not in svg or fam in FONTS


def test_chart_fonts_keep_their_letters(db, manual):
    from manual_app.core.html import Renderer
    b = Renderer(db, manual, 'print', embed=False, only=None, workflow=False, draft=False)
    svg = b.svg_with_fonts('<svg xmlns="http://www.w3.org/2000/svg"></svg>')
    assert svg.count('unicode-range') == svg.count('@font-face') > 0

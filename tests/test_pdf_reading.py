"""Arabic read from PDF files in reading order whatever order the file stores it in, and a PDF opened with its own
look (its cover and the design of its pages)."""
from manual_app.core import importer


def _visual(units, size=12.0, start=10.0, width=7.0):
    """Glyphs as a display-order PDF stores them: left to right on the page, one after the other."""
    out, x = [], start
    for u in units:
        if u == ' ':
            x += width
            continue
        out.append((x, x + width, size, u))
        x += width
    return out


def test_lam_alef_and_single_words_keep_their_letters():
    # «مصفوفة الصلاحيات» drawn in display order with presentation forms; ﻼ is one glyph (lam-alef)
    line = list('ﺕﺎﻴﺣ') + ['ﻼ'] + list('ﺼﻟﺍ') + [' '] + list('ﺔﻓﻮﻔﺼﻣ')
    assert importer.line_from_chars(_visual(line)) == 'مصفوفة الصلاحيات'
    # one word alone, which the old guess left reversed («ةفوفصم»)
    assert importer.line_from_chars(_visual(list('ﺔﻓﻮﻔﺼﻣ'))) == 'مصفوفة'
    # a ligature that the file maps to two letters stays in its order (not «ال»)
    line = list('ﺔﻗ') + ['لا'] + list('ﻌﻟﺍ')
    assert importer.line_from_chars(_visual(line)) == 'العلاقة'


def test_numbers_and_brackets_in_arabic():
    # «المادة (12) لعام 2026» in display order
    line = list('2026') + [' '] + list('ﻡﺎﻌﻟ') + [' '] + list('(12)') + [' '] + list('ﺓﺩﺎﻤﻟﺍ')
    assert importer.line_from_chars(_visual(line)) == 'المادة (12) لعام 2026'
    assert importer.line_from_chars(_visual(list('Authority matrix'.replace(' ', ' ')))) .startswith('Authority')


def test_pieces_of_a_line_are_joined_but_columns_stay_apart():
    class C:
        def __init__(self, x0, x1, size=12):
            self.x0, self.x1, self.size = x0, x1, size
    a = {'x0': 300, 'x1': 500, 'y0': 700, 'y1': 712, 'chars': [C(300, 500)], 'raw': 'العلاقة مع الإدارة ('}
    b = {'x0': 270, 'x1': 298, 'y0': 700, 'y1': 712, 'chars': [C(270, 298)], 'raw': '2026'}
    english = {'x0': 40, 'x1': 220, 'y0': 700, 'y1': 712, 'chars': [C(40, 220)], 'raw': 'Relations with management'}
    merged = importer.merge_line_pieces([a, b, english])
    assert len(merged) == 2 and any('2026' in m['raw'] and 'العلاقة' in m['raw'] for m in merged)

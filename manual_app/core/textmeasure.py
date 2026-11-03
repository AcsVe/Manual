"""Text width measured with the program's own bundled fonts and the same shaping the browser uses (HarfBuzz), so
drawings sized in advance (the organisational chart boxes) fit their words exactly. When the shaping library is
missing the caller falls back to its estimate (``width`` returns None)."""
import io
import os

from .templates import FONTS

_FACES = {}          # (slug, subset, weight) -> (hb.Font, set of code points, units per em) or None
ARABIC = 'arabic'
LATIN = 'latin'


def _fonts_dir():
    from .html import assets_dir
    return os.path.join(assets_dir(), 'fonts')


def _face(slug, sub, weight):
    key = (slug, sub, weight)
    if key in _FACES:
        return _FACES[key]
    _FACES[key] = None
    path = os.path.join(_fonts_dir(), f'{slug}-{sub}-{weight}-normal.woff2')
    if not os.path.isfile(path):
        return None
    try:
        import uharfbuzz as hb
        from fontTools.ttLib import TTFont
        f = TTFont(path)                         # woff2 needs brotli to unpack; plain font data for HarfBuzz
        f.flavor = None
        buf = io.BytesIO()
        f.save(buf)
        face = hb.Face(hb.Blob(buf.getvalue()))
        _FACES[key] = (hb.Font(face), set(f.getBestCmap() or {}), face.upem)
    except Exception:  # noqa: BLE001 — no shaping library or an unreadable font: the caller estimates instead
        _FACES[key] = None
    return _FACES[key]


def _runs(text, ar_cmap):
    """Cuts the text into runs for the Arabic subset and the Latin subset (spaces join the run they are in)."""
    runs, cur, cur_sub = [], '', None
    for ch in text:
        if ch.isspace() and cur_sub is not None:
            cur += ch
            continue
        sub = ARABIC if ord(ch) in ar_cmap else LATIN
        if sub != cur_sub and cur:
            runs.append((cur_sub, cur))
            cur = ''
        cur_sub = sub
        cur += ch
    if cur:
        runs.append((cur_sub or LATIN, cur))
    return runs


def width(text, size, bold=False, family='Tajawal'):
    """The width in pixels of ``text`` at ``size`` px, or None when it cannot be measured."""
    if not text:
        return 0.0
    try:
        import uharfbuzz as hb
    except ImportError:
        return None
    if family not in FONTS:
        return _qt_width(text, size, bold, family)
    slug = FONTS[family]
    weight = 700 if bold else 400
    ar = _face(slug, ARABIC, weight)
    la = _face(slug, LATIN, weight) or ar
    if not ar or not la:
        return None
    total = 0.0
    for sub, run in _runs(text, ar[1]):
        font, _, upem = ar if sub == ARABIC else la
        buf = hb.Buffer()
        buf.add_str(run)
        buf.guess_segment_properties()
        hb.shape(font, buf, {})
        total += sum(p.x_advance for p in buf.glyph_positions) * size / upem
    return total


def _qt_width(text, size, bold, family):
    """A font installed in Windows: measured by Qt, which shapes Arabic with HarfBuzz as the browser does.
    None when no Qt application is running or the font is not on this computer."""
    try:
        from PySide6.QtGui import QFont, QFontDatabase, QFontMetricsF, QGuiApplication
    except ImportError:
        return None
    if QGuiApplication.instance() is None or family not in QFontDatabase.families():
        return None
    f = QFont(family)
    f.setPixelSize(100)                   # measured large and scaled: pixel sizes are whole numbers in Qt
    f.setBold(bold)
    f.setKerning(True)
    return QFontMetricsF(f).horizontalAdvance(text) * size / 100


def available():
    return width('اختبار test', 12) is not None

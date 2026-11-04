"""The manual checker: reads the whole manual (page setup, header and footer, page numbers, tables, text direction,
lists and symbols, page breaks, structure, images) and lists what would print badly, each with its place and,
where one is possible, a fix. The checker never changes anything by itself: ``apply`` carries out the fixes the
user chose, keeps what it replaced so ``undo`` can put it back, and ``autofix_blocks`` gives the editor and the
importer the safe text fixes.

An issue is a dict:
    key       stable text that names it (used to hide an issue the user decided to keep)
    rule      code from RULES;  cat, sev  its category and severity
    sid, b    section id and block index (None for the manual itself / the section itself)
    path      where the text is inside the block or the section (['ar'], ['data', 'rows', 2, 1, 'en'], ['title_en'])
    page      page number (layout check only)
    msg       (ar, en) what is wrong;  sample  the text concerned (shortened)
    fix       (ar, en) what the fix does, or None (to be fixed by hand)
    safe      the fix only tidies (no visible change of the layout)
    locked    the section is approved (workflow on): fixing needs it back to draft
    params    what the fix needs
"""
import copy
import json
import re
from datetime import date

from . import backgrounds as BG
from .db import BLOCK_KINDS, SECTION_KINDS
from .richtext import plain
from .templates import FRONT_KINDS, PAGE_SIZES, TOKENS, layout_with_defaults, tokens_to_words

CATEGORIES = {
    'page': ('الصفحة والهوامش', 'Page and margins'),
    'numbers': ('أرقام الصفحات والترويسة والتذييل', 'Page numbers, header and footer'),
    'tables': ('الجداول', 'Tables'),
    'direction': ('اتجاه النص واللغة', 'Text direction and language'),
    'lists': ('القوائم والرموز', 'Lists and symbols'),
    'breaks': ('فواصل الصفحات', 'Page breaks'),
    'structure': ('البنية والعناوين', 'Structure and titles'),
    'images': ('الصور والخلفيات', 'Images and backgrounds'),
    'format': ('التنسيق', 'Formatting'),
    'layout': ('توزيع الصفحات الفعلي', 'Actual page layout'),
}
SEVERITIES = {'error': ('خطأ', 'Error'), 'warning': ('تحذير', 'Warning'), 'info': ('ملاحظة', 'Note')}
SEV_ORDER = {'error': 0, 'warning': 1, 'info': 2}

# code: (category, severity, safe fix, on by default, (ar, en) title)
RULES = {
    'margin_header': ('page', 'error', True, True, ('الهامش العلوي أصغر من الترويسة', 'Top margin smaller than the header')),
    'margin_small': ('page', 'warning', True, True, ('هامش أصغر مما تطبعه الطابعات', 'Margin smaller than printers print')),
    'bi_narrow': ('page', 'warning', False, True, ('عمودا اللغتين ضيّقان في الصفحة الطولية', 'Language columns too narrow on a portrait page')),
    'font_small': ('page', 'info', False, True, ('حجم الخط صغير للطباعة', 'Font size small for printing')),
    'no_page_number': ('numbers', 'warning', True, True, ('لا يوجد رقم صفحة في الترويسة أو التذييل', 'No page number in the header or footer')),
    'unknown_token': ('numbers', 'warning', True, True, ('حقل غير معروف في الترويسة أو التذييل', 'Unknown field in the header or footer')),
    'header_long': ('numbers', 'info', False, True, ('نص الترويسة أو التذييل أطول من مكانه', 'Header or footer text longer than its place')),
    'toc_missing': ('numbers', 'warning', False, True, ('دليل طويل دون فهرس', 'Long manual without contents')),
    'swapped': ('direction', 'warning', True, True, ('نص في خانة اللغة الأخرى', 'Text in the other language box')),
    'mixed': ('direction', 'warning', False, True, ('اللغتان في خانة واحدة', 'Both languages in one box')),
    'bidi_marks': ('direction', 'info', True, True, ('علامات اتجاه خفية', 'Hidden direction marks')),
    'ar_forms': ('direction', 'warning', True, True, ('حروف عربية بأشكال العرض (منسوخة من PDF): لا يجدها البحث', 'Arabic letters in display forms (copied from a PDF): search does not find them')),
    'ar_punct': ('direction', 'info', True, True, ('علامات ترقيم لاتينية في نص عربي', 'Latin punctuation in Arabic text')),
    'spacing': ('direction', 'info', True, True, ('مسافات زائدة أو في غير موضعها', 'Extra or misplaced spaces')),
    'brackets': ('direction', 'warning', False, True, ('أقواس غير متوازنة (تنقلب في النص العربي)', 'Unbalanced brackets (they flip in Arabic text)')),
    'dates': ('format', 'info', True, True, ('تواريخ بغير الصيغة الموحّدة', 'Dates not in the chosen format')),
    'digits_mixed': ('direction', 'info', True, True, ('أرقام لاتينية وعربية مختلطة', 'Western and Arabic-Indic digits mixed')),
    'empty_side': ('direction', 'info', False, True, ('النص بلغة واحدة فقط', 'Text in one language only')),
    'manual_bullets': ('lists', 'warning', True, True, ('تعداد مكتوب يدوياً داخل فقرة', 'List typed by hand inside a paragraph')),
    'list_markers': ('lists', 'info', True, True, ('رموز تعداد مكررة داخل القائمة', 'Repeated list markers inside a list')),
    'list_count': ('lists', 'warning', False, True, ('عدد بنود القائمة مختلف بين اللغتين', 'List items differ between the languages')),
    'pua_symbols': ('lists', 'warning', True, True, ('رموز من خطوط Word الخاصة لا تظهر', 'Symbols from Word symbol fonts that do not show')),
    'pb_double': ('breaks', 'warning', True, True, ('فاصلا صفحة متتاليان (صفحة فارغة)', 'Two page breaks in a row (blank page)')),
    'pb_first': ('breaks', 'warning', True, True, ('فاصل صفحة في أول القسم يفصل العنوان عن محتواه', 'Page break at the start of a section separates the title from its content')),
    'pb_last': ('breaks', 'warning', True, True, ('فاصل صفحة في آخر القسم', 'Page break at the end of a section')),
    'heading_last': ('breaks', 'warning', False, True, ('عنوان فرعي في آخر القسم دون محتوى بعده', 'Sub-heading at the end of a section with nothing after it')),
    'empty_block': ('structure', 'info', True, True, ('كتلة فارغة', 'Empty block')),
    'title_missing': ('structure', 'warning', False, True, ('عنوان القسم ناقص', 'Section title missing')),
    'empty_section': ('structure', 'warning', False, True, ('قسم دون محتوى', 'Section without content')),
    'dup_title': ('structure', 'info', False, True, ('عنوانان متطابقان في المستوى نفسه', 'Two identical titles on the same level')),
    'dup_code': ('structure', 'warning', False, True, ('رمز قسم مكرر', 'Section code used twice')),
    'review_due': ('structure', 'info', False, True, ('موعد المراجعة فات', 'Review date passed')),
    'heading_paragraph': ('structure', 'info', False, True, ('فقرة غامقة قصيرة تبدو عنواناً', 'Short bold paragraph that looks like a heading')),
    'table_ragged': ('tables', 'warning', True, True, ('صفوف الجدول بعدد خلايا مختلف', 'Table rows with a different number of cells')),
    'table_empty_col': ('tables', 'info', True, True, ('عمود فارغ في الجدول', 'Empty table column')),
    'table_empty_rows': ('tables', 'info', True, True, ('صفوف فارغة في الجدول', 'Empty table rows')),
    'table_no_header': ('tables', 'warning', False, True, ('جدول دون عناوين أعمدة', 'Table without column titles')),
    'table_merged': ('tables', 'warning', True, True, ('خلايا مدمجة في Word تكررت نصوصها', 'Cells merged in Word came in with their text repeated')),
    'table_as_text': ('tables', 'warning', False, True, ('جدول يحمل نصاً طويلاً (تنسيق من Word وليس جدولاً)', 'Table holding long text (Word layout, not a table)')),
    'table_wide': ('tables', 'warning', False, True, ('الجدول أعرض من الصفحة', 'Table wider than the page')),
    'table_tall_cell': ('tables', 'info', True, True, ('خلية طويلة لا تنقسم بين صفحتين', 'Long cell that cannot run over two pages')),
    'table_no_border': ('tables', 'warning', False, True, ('حدود الجدول مفقودة أو لا تكاد تُرى', 'Table borders missing or hardly visible')),
    'table_no_shade': ('tables', 'warning', False, True, ('رأس الجدول بلا تظليل يميّزه', 'Table header row without shading')),
    'table_contrast': ('tables', 'warning', False, True, ('تباين ضعيف بين نص الجدول وخلفيته', 'Weak contrast between table text and its background')),
    'table_clipped': ('tables', 'error', False, True, ('جدول مقصوص في الصفحة المطبوعة', 'Table cut off on the printed page')),
    'table_split_short': ('tables', 'warning', False, True, ('جدول قصير انقسم بين صفحتين', 'Short table split over two pages')),
    'table_caption_apart': ('tables', 'warning', False, True, ('عنوان الجدول في صفحة والجدول في التالية', 'Table title on one page, the table on the next')),
    'img_missing': ('images', 'error', True, True, ('صورة محذوفة من المكتبة', 'Image removed from the library')),
    'img_lowres': ('images', 'warning', False, True, ('دقة الصورة منخفضة للطباعة', 'Image resolution low for printing')),
    'img_no_dims': ('images', 'info', True, True, ('أبعاد الصورة غير محفوظة', 'Image size not stored')),
    'bg_strong': ('images', 'warning', True, True, ('خلفية قوية تحت النص تعيق القراءة', 'Strong background under text hinders reading')),
    'logo_flag': ('images', 'info', True, True, ('الشعار مطلوب في الترويسة ولا يوجد شعار', 'Logo asked for in the header but there is none')),
    'inline_colors': ('format', 'info', True, True, ('ألوان نص من خارج ألوان الدليل', 'Text colours outside the manual colours')),
    'lay_overflow_x': ('layout', 'error', False, True, ('عنصر يتجاوز عرض الصفحة', 'Element wider than the page')),
    'lay_overflow_y': ('layout', 'error', False, True, ('صورة أطول من الصفحة', 'Image taller than the page')),
    'lay_lost': ('layout', 'error', False, True, ('محتوى لا يظهر في الملف المطبوع', 'Content that does not show in the printed file')),
    'lay_dup': ('layout', 'error', False, True, ('نص يتكرر في الملف المطبوع', 'Text repeated in the printed file')),
    'lay_cell': ('layout', 'warning', False, True, ('كلمة أو رابط أطول من خلية الجدول', 'Word or link longer than its table cell')),
    'lay_orphan': ('layout', 'warning', False, True, ('عنوان في أسفل الصفحة ومحتواه في التالية', 'Title at the bottom of a page, its content on the next')),
    'lay_blank': ('layout', 'warning', False, True, ('صفحة فارغة', 'Blank page')),
    'lay_sparse': ('layout', 'info', False, False, ('صفحة شبه فارغة', 'Nearly empty page')),
}
# what the editor and the importer may fix on their own (when the user turned it on)
AUTO_ON_SAVE = ('bidi_marks', 'pua_symbols', 'ar_forms', 'list_markers', 'spacing')
AUTO_ON_IMPORT = AUTO_ON_SAVE + ('manual_bullets', 'empty_block', 'pb_double', 'table_ragged', 'table_empty_col',
                                 'table_empty_rows', 'swapped', 'brackets', 'empty_side', 'table_merged')
DEFAULT_PREFS = {'disabled': [], 'before_export': True, 'auto_save': False, 'auto_import': True, 'layout': True,
                 'text_digits': 'keep', 'text_dates': 'iso', 'date_order': 'dmy'}
DATE_STYLES = {'keep': ('دون توحيد', 'Leave them'), 'iso': ('2026-12-31', '2026-12-31'),
               'dmy': ('31/12/2026', '31/12/2026')}
DATE_ORDERS = {'dmy': ('يوم/شهر/سنة (12/11/2024 = 12 تشرين الثاني)', 'Day/month/year (12/11/2024 = 12 November)'),
               'mdy': ('شهر/يوم/سنة (12/11/2024 = 11 كانون الأول)', 'Month/day/year (12/11/2024 = 11 December)')}

AR = '؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿'
_AR = re.compile(f'[{AR}]')
_LAT_WORD = re.compile(r'[A-Za-z]{2,}')
_BIDI = re.compile('[​‎‏‪-‮⁦-⁩﻿]')
_PUA = re.compile('[-]')
# Word's Symbol and Wingdings characters (private use) → the same sign in Unicode; others are removed
PUA_MAP = {'': '•', '': '▪', '': '✓', '': '✗', '': '☒', '': '□', '': '□',
           '': '❑', '': '➢', '': '→', '': '➔', '': '⇨', '': '❖', '': '■',
           '': '●', '': '○', '': '★', '': '◆', '': '◆', '': '►', '': '▼',
           '': '-', '': '*', '': '°', '': '→', '': '←', '': '☺'}
BULLET_CHARS = '•·▪▫●○■□◆◇❖➢➤►▸‣⁃✓✔☐☑✗✘-–—*'
_BULLET = re.compile(rf'^\s*(?:[{re.escape(BULLET_CHARS)}]|o(?=\s+[\u0621-\u064A]))\s*')
_NUMBER = re.compile(r'^\s*(?:\(?[0-9٠-٩]{1,3}[.)\-–]|\(?[a-zA-Zء-ي][.)\-–]|\([0-9٠-٩]{1,3}\))\s+')
_STRONG_BULLET = re.compile(r'^\s*(?:[•·▪▫●○■□◆◇❖➢➤►▸‣⁃✓✔☐☑✗✘]|o(?=\s+[\u0621-\u064A]))\s*')
_O_BULLET = re.compile(r'^\s*o\s+(?=[\u0621-\u064A])')     # Word's «o» bullet (Courier New) before Arabic text
_FORMS = re.compile('[\uFB50-\uFDFF\uFE70-\uFEFF]')
_TOKEN = re.compile(r'\{[a-z_]+\}')
_SPLIT = re.compile(r'(<[^>]+>|&[#\w]+;)')
TEXT_KINDS = ('heading', 'paragraph', 'bullets', 'numbered', 'callout', 'quote')
AR_DIGITS = '٠١٢٣٤٥٦٧٨٩'


def short(text, n=90):
    t = plain(text or '').replace('\n', ' ⏎ ')
    return t if len(t) <= n else t[:n - 1] + '…'


def map_text(html, fn):
    """Applies ``fn`` to the words of an HTML piece, never to its tags or character references."""
    return ''.join(p if (p.startswith('<') or (p.startswith('&') and p.endswith(';'))) else fn(p)
                   for p in _SPLIT.split(html or ''))


def is_latin_only(text):
    t = plain(text)
    return not _AR.search(t) and len(_LAT_WORD.findall(t)) >= 2


def has_arabic(text):
    return bool(_AR.search(plain(text)))


def _brackets_ok(t):
    pairs = {'(': ')', '[': ']', '{': '}', '«': '»'}
    closing = {v: k for k, v in pairs.items()}
    stack = []
    for ch in t:
        if ch in pairs:
            stack.append(ch)
        elif ch in closing:
            if not stack or stack[-1] != closing[ch]:
                return False
            stack.pop()
    return not stack


def tidy_spaces(t):
    t = re.sub(r'[  ]{2,}', ' ', t)
    t = re.sub(r' +([،؛؟,;:!?)\]»])', r'\1', t)
    t = re.sub(r'([(\[«]) +', r'\1', t)
    t = re.sub(rf'([،؛])(?=[{AR}A-Za-z])', r'\1 ', t)
    return t


def tidy_html_spaces(html):
    out = map_text(html, tidy_spaces)
    out = re.sub(r'^(\s|&nbsp;)+|(\s|&nbsp;)+$', '', out)
    return re.sub(r'\s*<br>\s*', '<br>', out)


def ar_punct(t):
    t = re.sub(rf'(?<=[{AR}])\s*,(?!\d)', '،', t)
    t = re.sub(rf'(?<=[{AR}])\s*;', '؛', t)
    t = re.sub(rf'(?<=[{AR}])\s*\?', '؟', t)
    return t


def normal_forms(t):
    import unicodedata
    return _FORMS.sub(lambda m: unicodedata.normalize('NFKC', m.group(0)) if m.group(0) != '\uFEFF' else '', t)


MERGED_MIN = 25          # repeated short values (R, ✓, يعتمد) are real data; merged cells hold longer text
_MIRROR = str.maketrans('()[]{}', ')(][}{')


def fix_pua(t):
    return _PUA.sub(lambda m: PUA_MAP.get(m.group(0), ''), t)


def to_digits(t, style):
    if style == 'arabic':
        return re.sub('[0-9]', lambda m: AR_DIGITS[int(m.group(0))], t)
    return re.sub(f'[{AR_DIGITS}]', lambda m: str(AR_DIGITS.index(m.group(0))), t)


_D = '[0-9\u0660-\u0669]'
_DATE = re.compile(rf'(?<![\w/.\-])(?:({_D}{{4}})([/.\-])({_D}{{1,2}})\2({_D}{{1,2}})|({_D}{{1,2}})([/.\-])({_D}{{1,2}})\6({_D}{{4}}))(?![\w/\-]|\.{_D})')


def _num(s):
    return int(to_digits(s, 'latin'))


def find_dates(t, order='dmy'):
    """Dates written as numbers in a piece of text: [(match, date, Arabic-Indic digits)]. Year first is read
    year-month-day; otherwise day-month-year or month-day-year by ``order`` (a day above 12 settles it)."""
    from datetime import date as _d
    out = []
    for m in _DATE.finditer(t):
        try:
            if m.group(1):
                d = _d(_num(m.group(1)), _num(m.group(3)), _num(m.group(4)))
            else:
                a, b, y = _num(m.group(5)), _num(m.group(7)), _num(m.group(8))
                day, month = (a, b) if order == 'dmy' else (b, a)
                if month > 12 and day <= 12:
                    day, month = month, day
                d = _d(y, month, day)
        except ValueError:
            continue                     # not a date (a version number, a reference…)
        if not 1900 <= d.year <= 2200:
            continue
        out.append((m, d, bool(re.search('[\u0660-\u0669]', m.group(0)))))
    return out


def format_date(d, style, arabic=False):
    s = d.isoformat() if style == 'iso' else f'{d.day:02d}/{d.month:02d}/{d.year}'
    return to_digits(s, 'arabic') if arabic else s


def unify_dates(t, style, order='dmy'):
    if style == 'keep':
        return t
    out, last = [], 0
    for m, d, ar in find_dates(t, order):
        out.append(t[last:m.start()])
        out.append(format_date(d, style, ar))
        last = m.end()
    out.append(t[last:])
    return ''.join(out)


def html_lines(html):
    return [ln for ln in re.split(r'<br\s*/?>', html or '')]


class Ctx:
    def __init__(self, db, manual, prefs=None, workflow=False):
        self.db, self.m = db, manual
        self.lay = layout_with_defaults(manual['layout'] if manual else {})
        self.lm = self.lay['lang_mode']
        self.bi = self.lm in ('bi_side', 'bi_stack')
        self.prefs = dict(DEFAULT_PREFS, **(prefs or {}))
        self.workflow = workflow
        pw, ph = PAGE_SIZES.get(self.lay['page_size'], PAGE_SIZES['A4'])
        if self.lay['orientation'] == 'landscape':
            pw, ph = ph, pw
        mg = self.lay['margins']
        self.page_w, self.page_h = pw, ph
        self.content_w = pw - float(mg['left']) - float(mg['right'])
        self.palette = {str(v).lower() for v in self.lay['colors'].values()}
        self.today = date.today().isoformat()
        self.ignored = set(((manual or {}).get('meta') or {}).get('doctor_ignore') or [])


def _issue(rule, sid=None, b=None, path=None, msg=None, fix=None, sample='', params=None, page=None, extra=''):
    cat, sev, safe, _on, title = RULES[rule]
    key = f'{rule}|{sid}|{b}|{"/".join(str(x) for x in (path or []))}|{extra}'
    return {'key': key, 'rule': rule, 'cat': cat, 'sev': sev, 'sid': sid, 'b': b, 'path': list(path or []),
            'msg': msg or title, 'fix': fix, 'safe': safe and fix is not None, 'sample': sample, 'params': params or {},
            'page': page, 'locked': False}


# ── field walking ────────────────────────────────────────────────────
def block_fields(b):
    """(path, side, text) of every text in a block: its two sides, table titles and cells, list items."""
    k = b.get('kind')
    if k in TEXT_KINDS or k == 'image':
        for side in ('ar', 'en'):
            yield [side], side, b.get(side) or ''
    if k == 'table':
        yield from table_fields(b.get('data') or {}, ['data'])


def table_fields(d, base):
    for c, col in enumerate(d.get('columns') or []):
        if isinstance(col, dict):
            for side in ('ar', 'en'):
                yield base + ['columns', c, side], side, col.get(side) or ''
    for r, row in enumerate(d.get('rows') or []):
        for c, cell in enumerate(row):
            if isinstance(cell, dict):
                for side in ('ar', 'en'):
                    yield base + ['rows', r, c, side], side, cell.get(side) or ''


def get_path(obj, path):
    for p in path:
        obj = obj[p]
    return obj


def set_path(obj, path, value):
    for p in path[:-1]:
        obj = obj[p]
    obj[path[-1]] = value


def other_side(path):
    return path[:-1] + ['en' if path[-1] == 'ar' else 'ar'] if path and path[-1] in ('ar', 'en') else \
        ([('title_en' if path[0] == 'title_ar' else 'title_ar')] if path and path[0] in ('title_ar', 'title_en') else None)


# ── checks ───────────────────────────────────────────────────────────
def check_text(cx, sid, b, path, side, text, obj):
    """Rules on one piece of text. ``obj`` holds it (block or section) so the other language is at hand."""
    out = []
    if not text:
        return out
    t = plain(text)
    if _BIDI.search(text):
        out.append(_issue('bidi_marks', sid, b, path, sample=short(text),
                          fix=('حذف العلامات الخفية', 'Remove the hidden marks')))
    if side == 'ar' and _FORMS.search(text.replace('\uFEFF', '')):
        out.append(_issue('ar_forms', sid, b, path, sample=short(text), fix=('تحويلها إلى الحروف العادية', 'Change them to the ordinary letters')))
    if _PUA.search(text):
        out.append(_issue('pua_symbols', sid, b, path, sample=short(text),
                          fix=('تحويلها إلى الرموز المقابلة', 'Change them to the matching symbols')))
    if tidy_html_spaces(text) != text and re.search(r'[  ]{2,}| [،؛؟,;:!?)\]»]|[(\[«] |[،؛][^\s<]|^\s|\s$', text):
        out.append(_issue('spacing', sid, b, path, sample=short(text), fix=('ضبط المسافات', 'Tidy the spaces')))
    if side == 'ar' and _AR.search(t) and ar_punct(t) != t:
        out.append(_issue('ar_punct', sid, b, path, sample=short(text),
                          fix=('استعمال الفاصلة والفاصلة المنقوطة وعلامة الاستفهام العربية', 'Use the Arabic comma, semicolon and question mark')))
    if not _brackets_ok(re.sub(r'^\s*\(?[0-9٠-٩a-zA-Zء-ي]\)\s', '', t, flags=re.M)):
        flipped = side == 'ar' and _brackets_ok(t.translate(_MIRROR)) and bool(_AR.search(t))
        out.append(_issue('brackets', sid, b, path, sample=short(text),
                          msg=(('أقواس معكوسة: «)نص(» بدل «(نص)»', 'Reversed brackets: «)text(» instead of «(text)»') if flipped else None),
                          fix=(('تصحيح اتجاه الأقواس', 'Turn the brackets the right way') if flipped else None)))
    style = cx.prefs.get('text_dates', 'iso')
    if style != 'keep' and unify_dates(t, style, cx.prefs.get('date_order', 'dmy')) != t:
        found = [m.group(0) for m, _d, _a in find_dates(t, cx.prefs.get('date_order', 'dmy'))]
        out.append(_issue('dates', sid, b, path, sample=short(text), params={'style': style, 'order': cx.prefs.get('date_order', 'dmy')},
                          msg=('تواريخ بغير الصيغة الموحّدة: ' + '، '.join(found[:4]), 'Dates not in the chosen format: ' + ', '.join(found[:4])),
                          fix=(f'كتابتها بالصيغة {DATE_STYLES[style][0]}', f'Write them as {DATE_STYLES[style][1]}')))
    has_lat_d, has_ar_d = bool(re.search('[0-9]', t)), bool(re.search(f'[{AR_DIGITS}]', t))
    pref = cx.prefs.get('text_digits', 'keep')
    if side == 'ar' and ((pref == 'keep' and has_lat_d and has_ar_d) or (pref == 'arabic' and has_lat_d)
                         or (pref == 'latin' and has_ar_d)):
        style = pref if pref != 'keep' else ('arabic' if len(re.findall(f'[{AR_DIGITS}]', t)) >= len(re.findall('[0-9]', t)) else 'latin')
        out.append(_issue('digits_mixed', sid, b, path, sample=short(text), params={'style': style},
                          fix=(('توحيدها أرقاماً عربية مشرقية' if style == 'arabic' else 'توحيدها أرقاماً لاتينية'),
                               ('Make them Arabic-Indic digits' if style == 'arabic' else 'Make them Western digits'))))
    other_p = other_side(path)
    other = ''
    if other_p:
        try:
            other = get_path(obj, other_p) or ''
        except (KeyError, IndexError, TypeError):
            other = ''
    if cx.bi and other_p:
        if side == 'ar' and is_latin_only(text) and (not other or (has_arabic(other) and not _LAT_WORD.search(plain(other)))):
            out.append(_issue('swapped', sid, b, path, sample=short(text),
                              fix=(('تبديل النصين بين الخانتين' if other else 'نقله إلى خانة الإنجليزية'),
                                   ('Swap the two texts' if other else 'Move it to the English box'))))
        elif side == 'en' and has_arabic(text) and not _LAT_WORD.search(t) and not other:
            out.append(_issue('swapped', sid, b, path, sample=short(text),
                              fix=('نقله إلى خانة العربية', 'Move it to the Arabic box')))
        elif side == 'ar' and _AR.search(t):
            lat_lines = [ln for ln in html_lines(text) if is_latin_only(ln) and len(_LAT_WORD.findall(plain(ln))) >= 3]
            if lat_lines or re.search(r'(?:[A-Za-z][A-Za-z\'’-]*[\s,]+){6,}', t):
                fix = ('نقل الأسطر الإنجليزية إلى خانة الإنجليزية', 'Move the English lines to the English box') \
                    if lat_lines and not other else None
                out.append(_issue('mixed', sid, b, path, sample=short(text), fix=fix))
    return out


def check_block(cx, sid, i, b, blocks, sec):
    out = []
    k = b.get('kind')
    ar, en = b.get('ar') or '', b.get('en') or ''
    d = b.get('data') or {}
    for path, side, text in block_fields(b):
        out += check_text(cx, sid, i, path, side, text, b)
    # empty blocks
    empty = (k in TEXT_KINDS and not plain(ar) and not plain(en)) or (k == 'table' and not d.get('columns')) or \
        (k == 'image' and not d.get('asset_id')) or (k == 'links' and not d.get('items'))
    if empty:
        out.append(_issue('empty_block', sid, i, fix=('حذف الكتلة', 'Delete the block'),
                          msg=(f'كتلة «{BLOCK_KINDS.get(k, ("", ""))[0]}» فارغة', f'Empty «{BLOCK_KINDS.get(k, ("", ""))[1]}» block')))
        return out
    if cx.bi and k in TEXT_KINDS and bool(plain(ar)) != bool(plain(en)):
        out.append(_issue('empty_side', sid, i, ['en' if plain(ar) else 'ar'], sample=short(ar or en),
                          msg=(('النص بالعربية فقط' if plain(ar) else 'النص بالإنجليزية فقط'),
                               ('Arabic text only' if plain(ar) else 'English text only'))))
    if k == 'paragraph':
        kind = None
        sides = [x for x in (ar, en) if plain(x)]
        lns = [[ln for ln in html_lines(x) if plain(ln).strip()] for x in sides]
        if sides and all(lns):
            if all(all(_BULLET.match(plain(ln)) for ln in L_) for L_ in lns) and \
                    (any(len(L_) > 1 for L_ in lns) or all(_STRONG_BULLET.match(plain(L_[0])) for L_ in lns)):
                kind = 'bullets'
            elif all(all(_NUMBER.match(plain(ln)) for ln in L_) for L_ in lns) and any(len(L_) > 1 for L_ in lns):
                kind = 'numbered'
        if kind:
            out.append(_issue('manual_bullets', sid, i, params={'kind': kind}, sample=short(ar or en),
                              fix=(('تحويلها إلى قائمة نقطية' if kind == 'bullets' else 'تحويلها إلى قائمة مرقمة'),
                                   ('Make it a bulleted list' if kind == 'bullets' else 'Make it a numbered list'))))
        elif re.fullmatch(r'\s*<b>[^<]{2,80}</b>\s*', ar or en or '') and i + 1 < len(blocks) and \
                blocks[i + 1].get('kind') not in ('heading', 'pagebreak') and not re.search(r'[.:؛]\s*</b>\s*$', ar or en):
            out.append(_issue('heading_paragraph', sid, i, sample=short(ar or en),
                              fix=('تحويلها إلى عنوان فرعي', 'Make it a sub-heading')))
    if k in ('bullets', 'numbered'):
        pat = _BULLET if k == 'bullets' else _NUMBER
        for side, text in (('ar', ar), ('en', en)):
            items = [x for x in plain(text).split('\n') if x.strip()]
            if items and sum(1 for x in items if pat.match(x) or _BULLET.match(x)) >= max(1, len(items) // 2):
                out.append(_issue('list_markers', sid, i, [side], sample=short(text),
                                  fix=('حذف الرموز المكتوبة (يضعها البرنامج)', 'Remove the typed markers (the program adds them)')))
        na, ne = len([x for x in plain(ar).split('\n') if x.strip()]), len([x for x in plain(en).split('\n') if x.strip()])
        if cx.bi and na and ne and na != ne:
            out.append(_issue('list_count', sid, i, msg=(f'القائمة: {na} بنداً بالعربية و{ne} بالإنجليزية',
                                                         f'List: {na} Arabic items and {ne} English items')))
    if k == 'pagebreak':
        if i == 0:
            out.append(_issue('pb_first', sid, i, fix=('حذفه وبدء القسم في صفحة جديدة', 'Remove it and start the section on a new page')))
        elif blocks[i - 1].get('kind') == 'pagebreak':
            out.append(_issue('pb_double', sid, i, fix=('حذف الفاصل الزائد', 'Remove the extra break')))
        elif i == len(blocks) - 1:
            out.append(_issue('pb_last', sid, i, fix=('حذفه وبدء القسم التالي في صفحة جديدة', 'Remove it and start the next section on a new page')))
    if k == 'heading' and i == len(blocks) - 1:
        out.append(_issue('heading_last', sid, i, sample=short(ar or en), fix=('حذف العنوان', 'Delete the heading')))
    if k == 'table':
        out += check_table(cx, sid, i, d, ['data'])
    if k == 'image':
        out += check_image(cx, sid, i, d)
    if k in TEXT_KINDS:
        for side, text in (('ar', ar), ('en', en)):
            cols = {c.lower() for c in re.findall(r'(?<![-\w])color:\s*(#[0-9a-fA-F]{3,8})', text)}
            odd = {c for c in cols if c not in cx.palette and c not in ('#000', '#000000')}
            if odd:
                out.append(_issue('inline_colors', sid, i, [side], sample=short(text),
                                  fix=('إزالة الألوان الخاصة', 'Remove the extra colours')))
    return out


def _width_need(cx, d):
    """A rough least width of a table in mm: every column as wide as its longest word, at the table's size."""
    scale = int(d.get('scale') or 100) / 100
    em = float(cx.lay['fonts']['size']) * 0.92 * scale * 0.3528       # one em in mm
    cols = d.get('columns') or []
    need = 7 if d.get('numbered') else 0
    for c in range(len(cols)):
        words = []
        cells = [cols[c]] + [r[c] for r in (d.get('rows') or []) if c < len(r)]
        for cell in cells:
            for side in ('ar', 'en'):
                v = cell.get(side) if isinstance(cell, dict) else cell
                words += plain(v or '').split()
        longest = max((len(w) for w in words), default=4)
        need += max(12.0, min(longest, 28) * em * 0.55 + 4)
    return need


def _alike(a, c):
    """Two one-language blocks that read as the same text in the two languages: the same numbers, a length in
    proportion, and lists with the same number of items."""
    ta = plain((a.get('ar') or '') + (a.get('en') or ''))
    tc = plain((c.get('ar') or '') + (c.get('en') or ''))
    if not ta.strip() or not tc.strip():
        return False
    da = sorted(re.findall(r'\d+', to_digits(ta, 'latin')))
    dc = sorted(re.findall(r'\d+', to_digits(tc, 'latin')))
    if da != dc:
        return False
    if a.get('kind') in ('bullets', 'numbered') and len([x for x in ta.split('\n') if x.strip()]) != \
            len([x for x in tc.split('\n') if x.strip()]):
        return False
    ratio = (len(ta) + 10) / (len(tc) + 10)
    return 0.35 <= ratio <= 2.8


def check_table(cx, sid, b, d, base):
    out = []
    cols, rows = d.get('columns') or [], d.get('rows') or []
    if not cols:
        return out
    n = len(cols)
    if any(len(r) != n for r in rows):
        extra = any(len(r) > n and any(plain((x or {}).get('ar', '') if isinstance(x, dict) else x) or
                                       plain((x or {}).get('en', '') if isinstance(x, dict) else '') for x in r[n:]) for r in rows)
        out.append(_issue('table_ragged', sid, b, base, fix=(('إضافة أعمدة للخلايا الزائدة' if extra else 'إكمال الصفوف بخلايا فارغة'),
                                                             ('Add columns for the extra cells' if extra else 'Fill the rows with empty cells'))))

    def filled(x):
        return bool(plain((x or {}).get('ar') or '') or plain((x or {}).get('en') or '')) if isinstance(x, dict) else bool(x)
    for c in range(n):
        if not filled(cols[c]) and not any(c < len(r) and filled(r[c]) for r in rows):
            out.append(_issue('table_empty_col', sid, b, base, extra=str(c), params={'col': c},
                              msg=(f'العمود {c + 1} فارغ', f'Column {c + 1} is empty'), fix=('حذف العمود', 'Delete the column')))
    empty_rows = [r for r, row in enumerate(rows) if not any(filled(x) for x in row)]
    if empty_rows and len(empty_rows) < len(rows):
        out.append(_issue('table_empty_rows', sid, b, base, msg=(f'{len(empty_rows)} صف فارغ في الجدول', f'{len(empty_rows)} empty row(s)'),
                          fix=('حذف الصفوف الفارغة', 'Delete the empty rows')))
    if not any(filled(c) for c in cols) and len(rows) >= 2:
        out.append(_issue('table_no_header', sid, b, base, fix=('جعل الصف الأول عناوين للأعمدة', 'Use the first row as column titles')))
    # merged cells: the same text in three or more neighbouring cells of a row
    def txt(x):
        return plain(((x or {}).get('ar') or '') + '|' + ((x or {}).get('en') or '')) if isinstance(x, dict) else plain(x or '')
    merged = 0
    for row in [cols] + rows:
        vals = [txt(x) for x in row]
        run = 1
        for i in range(1, len(vals)):
            run = run + 1 if vals[i] == vals[i - 1] and len(vals[i].strip('| ')) >= MERGED_MIN else 1
            if run == 3:
                merged += 1
                break
    for c in range(n):                     # merged down a column
        vals = [txt(r[c]) if c < len(r) else '' for r in rows]
        run = 1
        for i in range(1, len(vals)):
            run = run + 1 if vals[i] == vals[i - 1] and len(vals[i].strip('| ')) >= MERGED_MIN else 1
            if run == 3:
                merged += 1
                break
    if merged:
        out.append(_issue('table_merged', sid, b, base, params={},
                          msg=(f'{merged} صف فيه نص مكرر في خلايا متجاورة', f'{merged} row(s) with the same text in neighbouring cells'),
                          fix=('إبقاء النص في أول خلية (وجعل عنوان الجدول المكرر عنواناً فوقه)', 'Keep the text in the first cell (a repeated table title goes above the table)')))
    if b is not None and n <= 2:
        lens = [len(txt(x)) for x in cols] + [len(txt(x)) for r in rows for x in r]
        if lens and (max(lens) > 300 or (len(rows) <= 2 and max(lens) > 150)):
            out.append(_issue('table_as_text', sid, b, base, fix=('تحويله إلى فقرات', 'Turn it into paragraphs')))
    need = _width_need(cx, d)
    if need > cx.content_w + 2 or n > 12:
        out.append(_issue('table_wide', sid, b, base, params={'need': round(need)},
                          msg=(f'يحتاج الجدول نحو {round(need)} مم والمتاح {round(cx.content_w)} مم ({n} أعمدة)',
                               f'The table needs about {round(need)} mm and {round(cx.content_w)} mm is available ({n} columns)'),
                          fix=('تصغير خط الجدول وتضييق خلاياه', 'Smaller table font and tighter cells')))
    if not d.get('split_rows'):
        for row in rows:
            if any(len(plain((x or {}).get('ar') or '') + plain((x or {}).get('en') or '')) > 900 for x in row if isinstance(x, dict)):
                out.append(_issue('table_tall_cell', sid, b, base, fix=('السماح بانقسام الصف بين صفحتين', 'Let rows run over two pages')))
                break
    out += check_table_look(cx, sid, b, d, base)
    return out


# ── table colours ────────────────────────────────────────────────────
def luminance(hexcol):
    """The relative luminance of a colour «#RRGGBB» (the measure of the accessibility guidelines)."""
    h = (hexcol or '#000000').lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    try:
        rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    except ValueError:
        return 0.0
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    """The contrast ratio of two colours: 1 (the same) to 21 (black on white)."""
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def readable_on(bg):
    """Black or white, whichever reads better on ``bg``."""
    return '#000000' if contrast('#000000', bg) >= contrast('#FFFFFF', bg) else '#FFFFFF'


TEXT_CONTRAST = 4.5          # the least contrast for ordinary text (accessibility guidelines, level AA)
BORDER_CONTRAST = 1.3        # a border lighter than this on white does not show on paper
SHADE_CONTRAST = 1.12        # a header background this close to white is not a shading


def table_colors(lay, d):
    """The colours a table prints with: its own, else the manual's."""
    c = lay['colors']
    own = d.get('colors') or {}
    out = {'head': c['table_head'], 'head_text': c['table_head_text'], 'stripe': c.get('table_stripe', '#F6F9FD'),
           'border': c.get('table_border', c['box_border']), 'text': c.get('table_text', c['text'])}
    for k, v in own.items():
        if k in out and isinstance(v, str) and re.fullmatch(r'#[0-9a-fA-F]{6}', v):
            out[k] = v
    look = d.get('look') or {}
    if isinstance(look.get('color'), str) and re.fullmatch(r'#[0-9a-fA-F]{6}', look['color']):
        out['text'] = look['color']
    return out


def check_table_look(cx, sid, b, d, base):
    out = []
    tc = table_colors(cx.lay, d)
    if d.get('borders') is False or contrast(tc['border'], '#FFFFFF') < BORDER_CONTRAST:
        out.append(_issue('table_no_border', sid, b, base, params={},
                          fix=('إظهار الحدود بلون يُرى عند الطباعة', 'Show the borders in a colour that prints')))
    if contrast(tc['head'], '#FFFFFF') < SHADE_CONTRAST:
        out.append(_issue('table_no_shade', sid, b, base,
                          fix=('تظليل رأس الجدول بلون الدليل', 'Shade the header row in the manual colour')))
    weak = []
    if contrast(tc['head_text'], tc['head']) < TEXT_CONTRAST:
        weak.append(('نص الرأس على خلفيته', 'header text on its background', round(contrast(tc['head_text'], tc['head']), 1)))
    low = min(contrast(tc['text'], '#FFFFFF'), contrast(tc['text'], tc['stripe']))
    if low < TEXT_CONTRAST:
        weak.append(('نص الخلايا على خلفيتها', 'cell text on its background', round(low, 1)))
    if weak:
        out.append(_issue('table_contrast', sid, b, base,
                          msg=('تباين ضعيف: ' + '، '.join(f'{a} ({r}:1)' for a, _e, r in weak) + ' والمناسب 4.5:1 فأكثر',
                               'Weak contrast: ' + ', '.join(f'{e} ({r}:1)' for _a, e, r in weak) + '; 4.5:1 or more reads well'),
                          fix=('اختيار لون نص يُقرأ على خلفيته (أسود أو أبيض)', 'Use a text colour that reads on its background (black or white)')))
    return out


def check_image(cx, sid, b, d):
    out = []
    aid = d.get('asset_id')
    if not aid:
        return out
    a = cx.db.asset(int(aid)) if cx.db else None
    if not a:
        return [_issue('img_missing', sid, b, fix=('حذف الكتلة', 'Delete the block'))]
    if a['mime'] != 'image/svg+xml':
        if not a.get('width'):
            out.append(_issue('img_no_dims', sid, b, params={'asset': a['id']}, fix=('قراءة أبعادها وحفظها', 'Read and store its size')))
        else:
            width_mm = cx.content_w * int(d.get('width') or 100) / 100
            dpi = a['width'] / (width_mm / 25.4)
            if dpi < 120:
                target = max(20, min(100, int(a['width'] / 150 * 25.4 / cx.content_w * 100)))
                out.append(_issue('img_lowres', sid, b, params={'width': target},
                                  msg=(f'دقة الصورة عند الطباعة نحو {round(dpi)} نقطة في البوصة (المناسب 150 فأكثر)',
                                       f'The image prints at about {round(dpi)} dpi (150 or more is right)'),
                                  fix=(f'تصغيرها إلى {target}% من العرض', f'Reduce it to {target}% of the width')
                                  if target < int(d.get('width') or 100) else None))
    return out


def check_layout(cx):
    out = []
    lay, mg = cx.lay, cx.lay['margins']
    hd, ft = lay['header'], lay['footer']
    hh = float(hd.get('height') or 22)
    if hd.get('style') != 'none' and float(mg['top']) < hh + 3:
        out.append(_issue('margin_header', params={'top': round(hh + 6)},
                          msg=(f'الهامش العلوي {mg["top"]} مم والترويسة {hh:g} مم: النص يقع على الترويسة',
                               f'Top margin {mg["top"]} mm and header {hh:g} mm: the text runs over the header'),
                          fix=(f'جعل الهامش العلوي {round(hh + 6)} مم', f'Make the top margin {round(hh + 6)} mm')))
    small = {k: v for k, v in mg.items() if float(v) < 8}
    if any(ft.get(x) for x in ('start', 'center', 'end')) and float(mg['bottom']) < 12:
        small['bottom'] = mg['bottom']
    small.pop('top', None) if out else None
    if small:
        names = {'top': ('العلوي', 'top'), 'bottom': ('السفلي', 'bottom'), 'left': ('الأيسر', 'left'), 'right': ('الأيمن', 'right')}
        out.append(_issue('margin_small', params={'margins': {k: (12 if k == 'bottom' else 10) for k in small}},
                          msg=('هامش أقل من المناسب: ' + '، '.join(f'{names[k][0]} {v} مم' for k, v in small.items()),
                               'Margin below what prints well: ' + ', '.join(f'{names[k][1]} {v} mm' for k, v in small.items())),
                          fix=('جعلها 10 مم (والسفلي 12 مم مع التذييل)', 'Make them 10 mm (bottom 12 mm with a footer)')))
    if cx.lm == 'bi_side' and cx.content_w < 230:
        out.append(_issue('bi_narrow', msg=(f'عرض كل عمود نحو {round((cx.content_w - 7) / 2)} مم', f'Each column is about {round((cx.content_w - 7) / 2)} mm wide'),
                          fix=('جعل الصفحة عرضية', 'Make the page landscape')))
    if float(lay['fonts']['size']) < 9:
        out.append(_issue('font_small', fix=('جعله 10 نقاط', 'Make it 10 pt')))
    boxes = [(w, p, (hd if w == 'header' else ft).get(p) or '') for w in ('header', 'footer') for p in ('start', 'center', 'end')]
    if not any('{page}' in t for _, _, t in boxes):
        out.append(_issue('no_page_number', fix=('إضافة «صفحة 3 من 20» إلى التذييل', 'Add «Page 3 of 20» to the footer')))
    for w, p, t in boxes:
        bad = [tok for tok in _TOKEN.findall(t) if tok not in TOKENS]
        if bad:
            out.append(_issue('unknown_token', path=[w, p], extra=w + p, sample=tokens_to_words(t), params={'where': w, 'box': p},
                              msg=('حقل غير معروف: ' + '، '.join(bad), 'Unknown field: ' + ', '.join(bad)),
                              fix=('حذف الحقل غير المعروف', 'Remove the unknown field')))
        lit = _TOKEN.sub('', t)
        for tok in _TOKEN.findall(t):
            if tok == '{title}':
                lit += (cx.m.get('title_ar') or '') + ' / ' + (cx.m.get('title_en') or '') if cx.bi else (cx.m.get('title_ar') or cx.m.get('title_en') or '')
            elif tok in ('{org}', '{chapter}', '{section}'):
                lit += 'x' * 28
        cap = (cx.content_w / (3 if p != 'center' else 2.2)) / 1.55
        if len(lit) > cap and lit.strip():
            out.append(_issue('header_long', path=[w, p], extra=w + p, sample=lit[:90],
                              msg=(f'نحو {len(lit)} حرفاً والمكان يتسع لنحو {round(cap)}', f'About {len(lit)} characters where about {round(cap)} fit')))
    style = cx.prefs.get('text_dates', 'iso')
    for col, (ar, en) in (('issue_date', ('تاريخ الإصدار', 'Issue date')),):
        v = cx.m.get(col) or ''
        if style != 'keep' and v and unify_dates(v, style, cx.prefs.get('date_order', 'dmy')) != v:
            out.append(_issue('dates', path=['manual', col], extra=col, sample=v,
                              params={'style': style, 'order': cx.prefs.get('date_order', 'dmy')},
                              msg=(f'{ar} في التصميم بغير الصيغة الموحّدة: {v}', f'{en} in the design not in the chosen format: {v}'),
                              fix=(f'كتابته بالصيغة {DATE_STYLES[style][0]}', f'Write it as {DATE_STYLES[style][1]}')))
    if hd.get('logo') and not cx.m.get('logo_id'):
        out.append(_issue('logo_flag', fix=('إلغاء خيار الشعار في الترويسة', 'Turn off the logo in the header')))
    pbg = BG.of_page(lay)
    if pbg and pbg['asset_id'] and pbg['opacity'] > 0.25:
        pc = round(pbg['opacity'] * 100)
        out.append(_issue('bg_strong', extra='page', params={'page': True},
                          msg=(f'صورة خلفية الصفحات بدرجة ظهور {pc}%', f'Page background image at {pc}%'),
                          fix=('خفضها إلى 8%', 'Lower it to 8%')))
    return out


def check(db, manual_id, prefs=None, workflow=False, only=None):
    """Every rule over the manual (``only``: these section ids). Ignored and turned-off rules are left out."""
    m = db.manual(manual_id)
    if not m:
        return []
    cx = Ctx(db, m, prefs, workflow)
    issues = [] if only else check_layout(cx)
    flat = db.flat(manual_id)
    titles, codes = {}, {}
    toc_rows = 0
    for idx, (s, depth) in enumerate(flat):
        sid = s['id']
        if s['in_toc'] and s['kind'] not in FRONT_KINDS:
            toc_rows += 1
        if only and sid not in only:
            continue
        sec_issues = []
        kind = s['kind']
        st = s.get('style') or {}
        if kind not in ('cover', 'toc'):
            ta, te = (s.get('title_ar') or '').strip(), (s.get('title_en') or '').strip()
            miss = [side for side, v in (('ar', ta), ('en', te)) if not v and (cx.bi or cx.lm == side)]
            for side in miss:
                sec_issues.append(_issue('title_missing', sid, None, ['title_' + side],
                                         msg=(('العنوان العربي ناقص' if side == 'ar' else 'العنوان الإنجليزي ناقص'),
                                              ('Arabic title missing' if side == 'ar' else 'English title missing'))))
            for side, v in (('ar', ta), ('en', te)):
                if v:
                    sec_issues += check_text(cx, sid, None, ['title_' + side], side, v, s)
            key = (s['parent_id'], (ta or te).lower())
            if key[1]:
                titles.setdefault(key, []).append(sid)
        if s.get('code'):
            codes.setdefault(s['code'].strip().lower(), []).append(sid)
        if s.get('next_review') and s['next_review'] < cx.today:
            sec_issues.append(_issue('review_due', sid, msg=(f'كان موعد المراجعة {s["next_review"]}', f'The review was due on {s["next_review"]}')))
        sbg = BG.of_section(st)
        if sbg and sbg['asset_id'] and sbg['opacity'] > (0.25 if sbg['layer'] == 'front' else 0.35) and \
                (sbg['layer'] == 'front' or sbg['area'] == 'section'):
            pc = round(sbg['opacity'] * 100)
            sec_issues.append(_issue('bg_strong', sid, msg=(f'صورة خلفية القسم على النص بدرجة ظهور {pc}%',
                                                            f'Section background image over the text at {pc}%'),
                                     fix=('خفضها إلى 15%', 'Lower it to 15%')))
        blocks = db.blocks(sid)
        if kind == 'table':
            sec_issues += check_table(cx, sid, None, s.get('data') or {}, ['data'])
            for path, side, text in table_fields(s.get('data') or {}, ['data']):
                sec_issues += check_text(cx, sid, None, path, side, text, s)
        has_children = idx + 1 < len(flat) and flat[idx + 1][1] > depth
        if kind in ('text', 'policy', 'links', 'image') and not blocks and not has_children:
            sec_issues.append(_issue('empty_section', sid, fix=('إيقاف القسم (يبقى محفوظاً ولا يُطبع)', 'Turn the section off (kept, not printed)')))
        for i, b in enumerate(blocks):
            sec_issues += check_block(cx, sid, i, b, blocks, s)
        sides = [x for x in sec_issues if x['rule'] == 'empty_side']
        if sides:                          # one line per section; neighbours in the two languages can be joined
            sec_issues = [x for x in sec_issues if x['rule'] != 'empty_side']
            idx = [x['b'] for x in sides]
            pairs, used = [], set()
            for i in idx:
                j = i + 1
                if i in used or j not in idx or j >= len(blocks):
                    continue
                a, c = blocks[i], blocks[j]
                if a['kind'] == c['kind'] and bool(plain(a.get('ar') or '')) != bool(plain(c.get('ar') or '')) \
                        and _alike(a, c):
                    pairs.append([i, j])
                    used.update((i, j))
            msg = (f'{len(idx)} كتلة بلغة واحدة' + (f'، منها {len(pairs)} زوجاً متجاوراً يمكن دمجه' if pairs else ''),
                   f'{len(idx)} block(s) in one language' + (f', {len(pairs)} neighbouring pair(s) can be joined' if pairs else ''))
            sec_issues.append(_issue('empty_side', sid, idx[0], params={'pairs': pairs}, msg=msg, sample=sides[0]['sample'],
                                     fix=(('دمج كل كتلتين متجاورتين بلغتين مختلفتين في كتلة واحدة',
                                           'Join each two neighbouring blocks in different languages into one') if pairs else None)))
        empties = [x for x in sec_issues if x['rule'] == 'empty_block']
        if len(empties) > 1:              # one line per section for its empty blocks
            idx = [x['b'] for x in empties]
            sec_issues = [x for x in sec_issues if x['rule'] != 'empty_block']
            sec_issues.append(_issue('empty_block', sid, idx[0], params={'idx': idx},
                                     msg=(f'{len(idx)} كتل فارغة في القسم', f'{len(idx)} empty blocks in the section'),
                                     fix=('حذف الكتل الفارغة', 'Delete the empty blocks')))
        if workflow and s['status'] == 'approved':
            for x in sec_issues:
                x['locked'] = True
        issues += sec_issues
    if not only:
        for (_p, _t), ids in titles.items():
            if len(ids) > 1:
                for sid in ids[1:]:
                    issues.append(_issue('dup_title', sid))
        for code, ids in codes.items():
            if len(ids) > 1:
                for sid in ids:
                    issues.append(_issue('dup_code', sid, msg=(f'الرمز «{code}» مستعمل في {len(ids)} أقسام', f'The code «{code}» is used by {len(ids)} sections')))
        if toc_rows >= 8 and not any(s['kind'] == 'toc' for s, _ in flat):
            issues.append(_issue('toc_missing', fix=('إضافة فهرس بعد الغلاف', 'Add contents after the cover')))
    return _filter(cx, issues)


def _filter(cx, issues):
    off = set(cx.prefs.get('disabled') or []) | {k for k, r in RULES.items() if not r[3] and k not in (cx.prefs.get('enabled') or [])}
    out = [x for x in issues if x['rule'] not in off]
    for x in out:
        x['hidden'] = x['key'] in cx.ignored
    if not cx.prefs.get('show_hidden'):
        out = [x for x in out if not x['hidden']]
    out.sort(key=lambda x: (SEV_ORDER[x['sev']], x['cat'], x['sid'] or 0, x['b'] if x['b'] is not None else -1))
    return out


def from_audit(db, manual_id, audit, prefs=None, workflow=False):
    """The measured pages (pdf.audit_blocking) as issues."""
    m = db.manual(manual_id)
    cx = Ctx(db, m, prefs, workflow)
    out, seen = [], set()
    blocks_cache = {}

    def block(sid, b):
        if sid not in blocks_cache:
            blocks_cache[sid] = db.blocks(sid)
        bl = blocks_cache[sid]
        return bl[b] if b is not None and b < len(bl) else None
    items, grouped = [], {}
    never = [it for it in audit.get('items') or [] if it.get('never')]
    if never:                                       # the layout stopped early: one point for all that is missing
        order = {s['id']: i for i, (s, _) in enumerate(db.flat(manual_id))}
        never.sort(key=lambda it: order.get(it['sid'], 10 ** 6))
        first = dict(never[0], chars=sum(it.get('chars') or 0 for it in never), sections=len(never))
        audit = dict(audit, items=[it for it in audit['items'] if not it.get('never')] + [first])
    for it in audit.get('items') or []:            # lost or repeated text: one point per section
        if it.get('t') in ('lost', 'dup') and it.get('sid'):
            g = grouped.get((it['t'], it['sid']))
            if g:
                g['chars'] = g.get('chars', 0) + (it.get('chars') or 0)
                g['page'] = min(g['page'], it['page'])
                continue
            grouped[(it['t'], it['sid'])] = it = dict(it)
        items.append(it)
    clipped = set()
    cap_pages = {it.get('page') for it in items if it.get('t') == 'tcap'}
    split_tables = {it.get('b') for it in items if it.get('t') == 'tsplit' and it.get('b')}
    for it in items:
        t, page, sid = it.get('t'), it.get('page'), it.get('sid')
        b = int(it['b'].split(':')[1]) if it.get('b') else None
        if it.get('b'):
            sid = int(it['b'].split(':')[0])
        sig = (t, sid, b, page if t in ('blank', 'sparse', 'orphan') else None, it.get('chars') if t in ('lost', 'dup') else None)
        if sig in seen:
            continue
        seen.add(sig)
        blk = block(sid, b) if sid else None
        is_table = (blk and blk.get('kind') == 'table') or (b is None and sid and (db.section(sid) or {}).get('kind') == 'table')
        is_image = blk and blk.get('kind') == 'image'
        rule = {'x': 'lay_overflow_x', 'y': 'lay_overflow_y', 'cell': 'lay_cell', 'orphan': 'lay_orphan', 'lost': 'lay_lost', 'dup': 'lay_dup',
                'blank': 'lay_blank', 'sparse': 'lay_sparse', 'tsplit': 'table_split_short', 'tcap': 'table_caption_apart'}.get(t)
        if t in ('x', 'cell') and is_table:
            rule = 'table_clipped'
        if not rule:
            continue
        if t in ('x', 'cell') and is_table and (sid, b) in clipped:
            continue                         # one point per table (its width and its cells)
        if t == 'orphan' and (page in cap_pages or it.get('b') in split_tables):
            continue                         # the same place is named by «table title apart» / «short table split»
        fix, params, msg = None, {}, None
        if t in ('x', 'cell') and is_table:
            clipped.add((sid, b))
            fix, params = (('إصلاح تدريجي يتوقف عند أول خطوة كافية: تضييق الخلايا، ثم تصغير الخط، ثم كسر الكلمات الطويلة، ثم صفحة أفقية',
                            'A fix in steps that stops at the first one enough: tighter cells, then a smaller font, then long '
                            'words broken, then a landscape page'), {'fit': True})
            msg = (('عرض الجدول يتجاوز الصفحة' + (f' بنحو {it["mm"]} مم' if it.get('mm') else '') if t == 'x'
                    else 'كلمة أو رابط أعرض من خلية الجدول فيُقص'),
                   ('The table runs past the page' + (f' by about {it["mm"]} mm' if it.get('mm') else '') if t == 'x'
                    else 'A word or link wider than its cell is cut off'))
        elif t == 'tsplit':
            fix, params = ('إبقاء الجدول في صفحة واحدة', 'Keep the table on one page'), {'keep': True}
            msg = (f'جدول قصير بدأ في الصفحة {page} وأكمل في التالية', f'A short table starts on page {page} and goes on to the next')
        elif t == 'tcap':
            hb = int(it['hb'].split(':')[1]) if it.get('hb') and it['hb'].split(':')[0] == str(sid) else b
            fix, params = ('نقل العنوان مع الجدول إلى الصفحة التالية', 'Move the title with its table to the next page'), \
                {'break_before': hb}
        elif t == 'x' and is_image:
            fix, params = ('تصغير الصورة إلى 80% من العرض', 'Reduce the image to 80% of the width'), {'width': 80}
        elif t in ('lost', 'dup') and sid:
            if not (db.section(sid) or {}).get('new_page'):
                fix, params = ('بدء القسم في صفحة جديدة (يعيد توزيع ما قبله)', 'Start the section on a new page (lays out what comes before again)'), {'new_page': True}
            elif b is not None and blk:
                fix, params = ('إضافة فاصل صفحة قبل موضعه', 'Add a page break before its place'), {'break_before': b}
        elif t == 'y' and is_image:
            fix, params = ('تصغير الصورة إلى 60% من العرض', 'Reduce the image to 60% of the width'), {'width': 60}
        elif t == 'orphan' and sid:
            if blk and blk.get('kind') in ('heading', 'table'):
                fix = ('إضافة فاصل صفحة قبله', 'Add a page break before it')
                params = {'break_before': b}
                if blk.get('kind') == 'table':
                    msg = ('عناوين أعمدة الجدول في أسفل الصفحة وصفوفه في التالية', 'Table column titles at the foot of a page, its rows on the next')
            elif b is None:
                fix, params = ('بدء القسم في صفحة جديدة', 'Start the section on a new page'), {'new_page': True}
        elif t == 'blank':
            prev, nxt = it.get('prev'), it.get('next')
            if prev:                    # a page break between the last block before and the first block after
                ps, pb = (int(v) for v in prev.split(':'))
                ns, nb = (int(v) for v in nxt.split(':')) if nxt else (ps, 10 ** 6)
                block(ps, 0)
                for k in range(pb, (nb if ns == ps else len(blocks_cache[ps])) + 1):
                    kb = block(ps, k)
                    if kb and kb.get('kind') == 'pagebreak':
                        sid, b = ps, k
                        fix, params = ('حذف فاصل الصفحة الذي صنعها', 'Remove the page break that makes it'), {'delete': True}
                        break
            if not fix and it.get('nextsid') and (db.section(it['nextsid']) or {}).get('new_page'):
                sid = it['nextsid']
                fix, params = ('إلغاء «صفحة جديدة» للقسم الذي بعدها', 'Turn off «new page» for the section after it'), {'new_page': False}
        if t in ('x', 'y') and it.get('mm') and rule != 'table_clipped':
            title = RULES[rule][4]
            msg = (f'{title[0]} بنحو {it["mm"]} مم', f'{title[1]} by about {it["mm"]} mm')
        if t == 'lost' and it.get('never'):
            fix, params = None, {}
            n = it.get('sections') or 1
            msg = (f'توقف ترتيب الصفحات عند هذا القسم: لم يُطبع هو و{n - 1} قسماً بعده (نحو {it.get("chars", 0)} حرفاً). '
                   'أصلح ملاحظة «نص يتكرر» أو «محتوى لا يظهر» التي قبله ثم أعد الفحص، أو تراجع عن آخر إصلاح.',
                   f'The page layout stopped at this section: it and {n - 1} section(s) after it did not print (about '
                   f'{it.get("chars", 0)} characters). Fix the «repeated» or «not shown» point before it and check again, '
                   'or undo the last fix.')
        elif t in ('lost', 'dup') and it.get('chars'):
            msg = ((f'نحو {it["chars"]} حرفاً لا تظهر في الملف' if t == 'lost' else f'نحو {it["chars"]} حرفاً تتكرر في الملف'),
                   (f'About {it["chars"]} characters do not show in the file' if t == 'lost' else f'About {it["chars"]} characters repeat in the file'))
        if t == 'sparse':
            msg = (f'الصفحة ممتلئة بنحو {it.get("fill", 0)}% فقط', f'The page is only about {it.get("fill", 0)}% full')
        x = _issue(rule, sid, b if b is not None else None, page=page, fix=fix, params=params, msg=msg,
                   extra=str(page) if t in ('blank', 'sparse') else '')
        if workflow and sid and (db.section(sid) or {}).get('status') == 'approved':
            x['locked'] = True
        out.append(x)
    return _filter(cx, out)


# ── fixes ────────────────────────────────────────────────────────────
class Fixer:
    """Carries out fixes. Block lists are edited in memory by their original positions and written once at the end,
    so several fixes on one section never disturb each other. ``undo`` data keeps what was replaced."""

    def __init__(self, db, manual_id, blocks=None):
        self.db, self.mid = db, manual_id
        self.m = db.manual(manual_id) if db and manual_id else None
        self.blocks = dict(blocks or {})
        self.orig_blocks = {}
        self.deleted = {}
        self.insert_before = {}
        self.sections = {}           # sid → changed columns
        self.orig_sections = {}
        self.layout = None
        self.new_sections = []
        self.asset_dims = {}
        self.manual_cols = {}         # columns of the manual itself (the issue date)
        self.done, self.skipped = 0, 0

    # state helpers
    def bl(self, sid):
        if sid not in self.blocks:
            self.blocks[sid] = copy.deepcopy(self.db.blocks(sid))
        if self.db and sid not in self.orig_blocks:
            self.orig_blocks[sid] = copy.deepcopy(self.db.blocks(sid)) if sid else []
        return self.blocks[sid]

    def sec(self, sid):
        cur = self.db.section(sid)
        if sid not in self.orig_sections:
            self.orig_sections[sid] = cur
        merged = dict(cur, **self.sections.get(sid, {}))
        return merged

    def set_sec(self, sid, **cols):
        self.sec(sid)
        self.sections.setdefault(sid, {}).update(cols)

    def lay(self):
        if self.layout is None:
            self.layout = copy.deepcopy(layout_with_defaults(self.m['layout']))
        return self.layout

    def target(self, x):
        """The block or section dict the issue's path points into."""
        if x['b'] is not None:
            return self.bl(x['sid'])[x['b']]
        s = self.sec(x['sid'])
        cols = self.sections.setdefault(x['sid'], {})
        for k in ('data', 'title_ar', 'title_en'):
            cols.setdefault(k, copy.deepcopy(s[k]))
        return cols

    def edit_text(self, x, fn):
        t = self.target(x)
        set_path(t, x['path'], fn(get_path(t, x['path']) or ''))

    def table_data(self, x):
        if x['b'] is not None:
            b = self.bl(x['sid'])[x['b']]
            b.setdefault('data', {})
            return b['data']
        return self.target(x)['data']

    # the run
    def apply(self, issues):
        for x in issues:
            fn = getattr(self, 'fix_' + x['rule'], None)
            if not x.get('fix') or x.get('locked') or fn is None:
                self.skipped += 1
                continue
            try:
                fn(x)
                self.done += 1
            except (KeyError, IndexError, TypeError, ValueError):
                self.skipped += 1          # the content changed since the check: the issue no longer applies
        return self

    def result(self, sid):
        bl = self.blocks.get(sid, [])
        dele = self.deleted.get(sid, set())
        ins = self.insert_before.get(sid, {})
        out = []
        for i, b in enumerate(bl):
            out += ins.get(i, [])
            if i not in dele:
                out.append(b)
        out += ins.get(len(bl), [])
        return out

    def commit(self, note='doctor'):
        undo = {'manual': self.mid, 'blocks': {}, 'sections': {}, 'layout': None, 'new_sections': [], 'assets': {}}
        touched = set(self.blocks) | set(self.deleted) | set(self.insert_before)
        for sid in touched:
            undo['blocks'][sid] = self.orig_blocks.get(sid, [])
            self.db.replace_blocks(sid, [{k: v for k, v in b.items() if k not in ('id', 'section_id', 'sort')}
                                         for b in self.result(sid)])
        for sid, cols in self.sections.items():
            orig = self.orig_sections[sid]
            undo['sections'][sid] = {k: orig[k] for k in cols}
            self.db.save_section(cols, sid)
        if self.layout is not None:
            undo['layout'] = self.m['layout']
            self.db.save_manual({'layout': self.layout}, self.mid)
        if self.manual_cols:
            undo['manual_cols'] = {k: self.m.get(k) for k in self.manual_cols}
            self.db.save_manual(dict(self.manual_cols), self.mid)
        for aid, (w, h) in self.asset_dims.items():
            self.db.conn.execute('UPDATE assets SET width = ?, height = ? WHERE id = ?', (w, h, aid))
        if self.asset_dims:
            self.db.conn.commit()
        for data in self.new_sections:
            undo['new_sections'].append(self.db.save_section(data))
        self.db.audit(note, manual=self.mid, fixed=self.done)
        return undo

    # page and header/footer
    def fix_margin_header(self, x):
        self.lay()['margins']['top'] = x['params']['top']

    def fix_margin_small(self, x):
        mg = self.lay()['margins']
        for k, v in x['params']['margins'].items():
            mg[k] = max(float(mg[k]), v)

    def fix_bi_narrow(self, x):
        self.lay()['orientation'] = 'landscape'

    def fix_font_small(self, x):
        self.lay()['fonts']['size'] = 10

    def fix_no_page_number(self, x):
        ft = self.lay()['footer']
        slot = 'end' if not ft.get('end') else ('center' if not ft.get('center') else 'end')
        ft[slot] = '{page_label} {page} {of} {pages}'
        if ft.get('style') == 'none':
            ft['style'] = 'line'

    def fix_unknown_token(self, x):
        box = self.lay()[x['params']['where']]
        box[x['params']['box']] = re.sub(r'\s{2,}', ' ', _TOKEN.sub(lambda m: m.group(0) if m.group(0) in TOKENS else '',
                                                                   box.get(x['params']['box']) or '')).strip()

    def fix_logo_flag(self, x):
        self.lay()['header']['logo'] = False

    def fix_bg_strong(self, x):
        if x['params'].get('page'):
            lay = self.lay()
            lay['page_bg'] = dict(BG.of_page(lay), opacity=0.08)
            lay['page_bg_id'] = None
        else:
            st = {k: v for k, v in (self.sec(x['sid']).get('style') or {}).items()
                  if k not in ('bg_id', 'bg_mode', 'bg_opacity', 'bg_fit')}
            st['bg'] = dict(BG.of_section(self.sec(x['sid']).get('style')), opacity=0.15)
            self.set_sec(x['sid'], style=st)

    def fix_toc_missing(self, x):
        flat = self.db.flat(self.mid)
        sort = 5
        for s, d in flat:
            if d == 0 and s['kind'] in FRONT_KINDS:
                sort = s['sort'] + 1
        self.new_sections.append({'manual_id': self.mid, 'parent_id': None, 'sort': sort, 'kind': 'toc',
                                  'title_ar': 'الفهرس', 'title_en': 'Contents', 'in_toc': 0, 'new_page': 1})

    # text
    def fix_bidi_marks(self, x):
        self.edit_text(x, lambda t: _BIDI.sub('', t))

    def fix_brackets(self, x):
        self.edit_text(x, lambda t: map_text(t, lambda p: p.translate(_MIRROR)))

    def fix_ar_forms(self, x):
        self.edit_text(x, lambda t: map_text(t, normal_forms))

    def fix_pua_symbols(self, x):
        self.edit_text(x, lambda t: map_text(t, fix_pua))

    def fix_spacing(self, x):
        self.edit_text(x, tidy_html_spaces)

    def fix_ar_punct(self, x):
        self.edit_text(x, lambda t: map_text(t, ar_punct))

    def fix_dates(self, x):
        p = x['params']
        if x.get('path') and x['path'][0] == 'manual':
            self.manual_cols[x['path'][1]] = unify_dates(self.manual_cols.get(x['path'][1], self.m.get(x['path'][1]) or ''),
                                                         p['style'], p['order'])
            return
        self.edit_text(x, lambda t: map_text(t, lambda s: unify_dates(s, p['style'], p['order'])))

    def fix_digits_mixed(self, x):
        self.edit_text(x, lambda t: map_text(t, lambda p: to_digits(p, x['params']['style'])))

    def fix_inline_colors(self, x):
        # the text colour only: a font, a size or a highlight chosen for the words stays
        def drop(m):
            css = ';'.join(p for p in m.group(1).split(';') if p.strip() and not re.match(r'\s*color\s*:', p))
            return f'<span style="{css}">' if css else '<span>'

        def strip(t):
            t = re.sub(r'<span style="([^"]*)">', drop, t)
            while re.search(r'<span>((?:(?!<span[ >]).)*?)</span>', t, flags=re.S):
                t = re.sub(r'<span>((?:(?!<span[ >]).)*?)</span>', r'\1', t, flags=re.S)
            return t
        self.edit_text(x, strip)

    def fix_swapped(self, x):
        t = self.target(x)
        other = other_side(x['path'])
        a, b = get_path(t, x['path']) or '', get_path(t, other) or ''
        set_path(t, x['path'], b)
        set_path(t, other, a)

    def fix_mixed(self, x):
        t = self.target(x)
        other = other_side(x['path'])
        if get_path(t, other):
            raise ValueError('the other side is not empty')
        lines = html_lines(get_path(t, x['path']))
        keep = [ln for ln in lines if not (is_latin_only(ln) and len(_LAT_WORD.findall(plain(ln))) >= 3)]
        move = [ln for ln in lines if ln not in keep]
        set_path(t, x['path'], '<br>'.join(keep))
        set_path(t, other, '<br>'.join(move))

    # lists
    def fix_manual_bullets(self, x):
        b = self.bl(x['sid'])[x['b']]
        kind = x['params']['kind']
        pat = _BULLET if kind == 'bullets' else _NUMBER
        for side in ('ar', 'en'):
            items = [pat.sub('', plain(ln), count=1).strip() for ln in html_lines(b.get(side) or '') if plain(ln).strip()]
            b[side] = '\n'.join(items)
        b['kind'] = kind

    def fix_list_markers(self, x):
        b = self.bl(x['sid'])[x['b']]
        side = x['path'][0]
        items = [x_.strip() for x_ in plain(b.get(side) or '').split('\n') if x_.strip()]
        b[side] = '\n'.join(_NUMBER.sub('', _BULLET.sub('', it, count=1), count=1).strip() for it in items)

    # breaks and blocks
    def fix_pb_double(self, x):
        self.deleted.setdefault(x['sid'], set()).add(x['b'])
        self.bl(x['sid'])

    def fix_pb_first(self, x):
        self.fix_pb_double(x)
        self.set_sec(x['sid'], new_page=1)

    def fix_pb_last(self, x):
        self.fix_pb_double(x)
        flat = [s for s, _ in self.db.flat(self.mid)]
        ids = [s['id'] for s in flat]
        i = ids.index(x['sid'])
        if i + 1 < len(flat):
            self.set_sec(flat[i + 1]['id'], new_page=1)

    def fix_heading_last(self, x):
        self.fix_pb_double(x)

    def fix_empty_block(self, x):
        self.bl(x['sid'])
        self.deleted.setdefault(x['sid'], set()).update(x['params'].get('idx') or [x['b']])

    def fix_img_missing(self, x):
        self.fix_pb_double(x)

    def fix_empty_side(self, x):
        bl = self.bl(x['sid'])
        for i, j in x['params'].get('pairs') or []:
            a, c = bl[i], bl[j]
            for side in ('ar', 'en'):
                if not plain(a.get(side) or '') and plain(c.get(side) or ''):
                    a[side] = c[side]
            self.deleted.setdefault(x['sid'], set()).add(j)

    def fix_heading_paragraph(self, x):
        b = self.bl(x['sid'])[x['b']]
        for side in ('ar', 'en'):
            b[side] = re.sub(r'^\s*<b>(.*)</b>\s*$', r'\1', b.get(side) or '', flags=re.S)
        b['kind'] = 'heading'

    def fix_empty_section(self, x):
        self.set_sec(x['sid'], is_active=0)

    # tables
    def fix_table_ragged(self, x):
        d = self.table_data(x)
        cols, rows = d['columns'], d['rows']
        n = max([len(cols)] + [len(r) for r in rows])
        while len(cols) < n:
            cols.append({'ar': '', 'en': ''})
        for r in rows:
            while len(r) < n:
                r.append({'ar': '', 'en': ''})

    def fix_table_empty_col(self, x):
        d = self.table_data(x)
        c = x['params']['col']
        if c < len(d['columns']):
            d['columns'].pop(c)
            for r in d['rows']:
                if c < len(r):
                    r.pop(c)

    def fix_table_empty_rows(self, x):
        d = self.table_data(x)

        def filled(v):
            return bool(plain((v or {}).get('ar') or '') or plain((v or {}).get('en') or '')) if isinstance(v, dict) else bool(v)
        d['rows'] = [r for r in d['rows'] if any(filled(v) for v in r)] or d['rows'][:1]

    def fix_table_no_header(self, x):
        d = self.table_data(x)
        d['columns'] = [dict(c) if isinstance(c, dict) else {'ar': c, 'en': ''} for c in d['rows'][0]]
        d['rows'] = d['rows'][1:]

    def fix_table_merged(self, x):
        d = self.table_data(x)

        def key(c):
            return (plain((c or {}).get('ar') or ''), plain((c or {}).get('en') or '')) if isinstance(c, dict) else (plain(c or ''), '')

        def long(k):
            return len((k[0] + k[1]).strip()) >= MERGED_MIN

        def thin(row):
            for i in range(len(row) - 1, 0, -1):
                if key(row[i]) == key(row[i - 1]) and long(key(row[i])):
                    row[i] = {'ar': '', 'en': ''}
        cols = d['columns']
        filled = [key(c) for c in cols if any(key(c))]
        if len(filled) >= 3 and len(set(filled)) == 1 and long(filled[0]):
            # one title over the whole table: it becomes the caption, the first row the column titles
            d['caption_ar'], d['caption_en'] = cols[0].get('ar', ''), cols[0].get('en', '')
            if d['rows']:
                d['columns'] = [dict(c) if isinstance(c, dict) else {'ar': c, 'en': ''} for c in d['rows'][0]]
                d['rows'] = d['rows'][1:]
        for row in [d['columns']] + d['rows']:
            thin(row)
        n = max([len(r) for r in d['rows']] + [0])
        for c in range(n):                 # merged down a column: the text stays in the top cell
            prev = None
            for r in d['rows']:
                if c >= len(r):
                    prev = None
                    continue
                k = key(r[c])
                if long(k) and k == prev:
                    r[c] = {'ar': '', 'en': ''}
                else:
                    prev = k

    def fix_table_as_text(self, x):
        b = self.bl(x['sid'])[x['b']]
        d = b.get('data') or {}
        out = []
        for row in [d.get('columns') or []] + (d.get('rows') or []):
            cells = [c if isinstance(c, dict) else {'ar': c, 'en': ''} for c in row]
            ar = '<br>'.join(c.get('ar') or '' for c in cells if plain(c.get('ar') or '') and has_arabic(c.get('ar')))
            en = '<br>'.join(c.get('en') or '' for c in cells if plain(c.get('en') or ''))
            en += ''.join('<br>' + c['ar'] for c in cells if plain(c.get('ar') or '') and not has_arabic(c.get('ar')))
            ar = ar or ''
            en = re.sub(r'^<br>', '', en)
            if plain(ar) or plain(en):
                out.append({'kind': 'paragraph', 'ar': ar, 'en': en, 'data': {}})
        self.insert_before.setdefault(x['sid'], {}).setdefault(x['b'], []).extend(out)
        self.deleted.setdefault(x['sid'], set()).add(x['b'])

    def fix_table_wide(self, x):
        d = self.table_data(x)
        d['compact'] = True
        d['scale'] = min(int(d.get('scale') or 100), 82)

    def fix_table_tall_cell(self, x):
        self.table_data(x)['split_rows'] = True

    def _design(self):
        return layout_with_defaults(self.m['layout'] if self.m else {})

    def _own_colors(self, d, **set_):
        own = dict(d.get('colors') or {})
        own.update(set_)
        d['colors'] = own

    def fix_table_no_border(self, x):
        d = self.table_data(x)
        d.pop('borders', None)
        c = self._design()['colors']
        design = c.get('table_border', c['box_border'])
        own = dict(d.get('colors') or {})
        if contrast(design, '#FFFFFF') >= BORDER_CONTRAST:
            own.pop('border', None)
        else:
            own['border'] = '#9FB3D1'
        d['colors'] = own

    def fix_table_no_shade(self, x):
        d = self.table_data(x)
        c = self._design()['colors']
        head = c['table_head'] if contrast(c['table_head'], '#FFFFFF') >= SHADE_CONTRAST else '#0B3D91'
        tc = table_colors(self._design(), d)
        text = tc['head_text'] if contrast(tc['head_text'], head) >= TEXT_CONTRAST else readable_on(head)
        self._own_colors(d, head=head, head_text=text)

    def fix_table_contrast(self, x):
        d = self.table_data(x)
        tc = table_colors(self._design(), d)
        if contrast(tc['head_text'], tc['head']) < TEXT_CONTRAST:
            self._own_colors(d, head_text=readable_on(tc['head']))
        if min(contrast(tc['text'], '#FFFFFF'), contrast(tc['text'], tc['stripe'])) < TEXT_CONTRAST:
            dark = '#1E293B'
            text = dark if min(contrast(dark, '#FFFFFF'), contrast(dark, tc['stripe'])) >= TEXT_CONTRAST else '#000000'
            self._own_colors(d, text=text)
            if (d.get('look') or {}).get('color'):
                d['look'] = dict(d['look'], color=text)
            if x['b'] is not None:
                b = self.bl(x['sid'])[x['b']]
                st = dict(b.get('style') or {})
                for k in (None, 'ar', 'en'):
                    part = st if k is None else st.get(k)
                    if isinstance(part, dict) and part.get('color'):
                        part['color'] = text
                b['style'] = st

    def fix_table_split_short(self, x):
        self.table_data(x)['keep'] = True

    def fix_table_clipped(self, x):
        """One step further on the way of ``tablefit.STEPS`` (the checker page measures again after each step)."""
        from . import tablefit
        d = self.table_data(x)
        step = tablefit.next_step(d, self.m['layout'] if self.m else {}, None if x['b'] is not None else self.sec(x['sid']).get('style'))
        if step is None:
            raise ValueError('no further step')
        if step == 'landscape' and x['b'] is None:
            st = dict(self.sec(x['sid']).get('style') or {})
            st['orientation'] = 'landscape'
            self.set_sec(x['sid'], style=st)
        else:
            tablefit.apply_step(d, step)

    # images
    def fix_img_lowres(self, x):
        self.bl(x['sid'])[x['b']].setdefault('data', {})['width'] = x['params']['width']

    def fix_img_no_dims(self, x):
        from PySide6.QtGui import QImage
        a = self.db.asset(x['params']['asset'])
        img = QImage()
        if a and img.loadFromData(a['data']):
            self.asset_dims[a['id']] = (img.width(), img.height())

    # the measured layout
    def _layout_fix(self, x):
        p = x['params']
        if p.get('table'):
            self.fix_table_wide(x)
        elif p.get('split'):
            self.fix_table_tall_cell(x)
        elif p.get('width'):
            self.bl(x['sid'])[x['b']].setdefault('data', {})['width'] = p['width']
        elif p.get('break_before') is not None:
            self.bl(x['sid'])
            self.insert_before.setdefault(x['sid'], {}).setdefault(p['break_before'], []).append(
                {'kind': 'pagebreak', 'ar': '', 'en': '', 'data': {}})
        elif p.get('delete'):
            self.bl(x['sid'])
            self.deleted.setdefault(x['sid'], set()).add(x['b'])
        elif 'new_page' in p:
            self.set_sec(x['sid'], new_page=1 if p['new_page'] else 0)
    fix_lay_overflow_x = fix_lay_overflow_y = fix_lay_cell = fix_lay_orphan = fix_lay_lost = fix_lay_dup = fix_lay_blank = _layout_fix
    fix_table_caption_apart = _layout_fix


def apply(db, manual_id, issues, note='doctor_fix'):
    """Fixes the chosen issues; returns (fixed, not fixed, undo data)."""
    fx = Fixer(db, manual_id).apply(issues)
    undo = fx.commit(note)
    return fx.done, fx.skipped, undo


def undo(db, data):
    """Puts back what ``apply`` replaced."""
    for sid, blocks in data['blocks'].items():
        db.replace_blocks(int(sid), [{k: v for k, v in b.items() if k not in ('id', 'section_id', 'sort')} for b in blocks])
    for sid, cols in data['sections'].items():
        db.save_section(cols, int(sid))
    if data.get('layout') is not None:
        db.save_manual({'layout': data['layout']}, data['manual'])
    if data.get('manual_cols'):
        db.save_manual(dict(data['manual_cols']), data['manual'])
    if data.get('new_sections'):
        db.delete_sections(data['new_sections'])
    db.audit('doctor_undo', manual=data['manual'])


def autofix_blocks(blocks, lang_mode='bi_side', rules=AUTO_ON_SAVE):
    """The safe fixes on a list of blocks in memory (the editor's «save»); returns (blocks, how many fixed)."""
    cx = Ctx(None, {'layout': {'lang_mode': lang_mode}, 'meta': {}})
    issues = []
    for i, b in enumerate(blocks):
        issues += [x for x in check_block(cx, 0, i, b, blocks, {}) if x['rule'] in rules and x['fix']]
    if not issues:
        return blocks, 0
    fx = Fixer(None, None, {0: copy.deepcopy(blocks)}).apply(issues)
    return fx.result(0), fx.done


def autofix_sections(db, manual_id, section_ids, rules=AUTO_ON_IMPORT):
    """The safe fixes on some sections (just imported); returns how many were fixed."""
    total = 0
    for _ in range(3):         # a fix can bring out the next one (a Word symbol becomes a bullet, then a list)
        issues = [x for x in check(db, manual_id, {'disabled': []}, only=set(section_ids)) if x['rule'] in rules and x['fix']]
        if not issues:
            break
        fixed, _skipped, _undo = apply(db, manual_id, issues, 'doctor_import')
        total += fixed
    return total


def load_prefs(db):
    try:
        return dict(DEFAULT_PREFS, **json.loads(db.get('doctor') or '{}'))
    except ValueError:
        return dict(DEFAULT_PREFS)


def save_prefs(db, prefs):
    db.set('doctor', json.dumps(prefs, ensure_ascii=False))


def ignore(db, manual_id, keys, on=True):
    m = db.manual(manual_id)
    meta = dict(m.get('meta') or {})
    cur = set(meta.get('doctor_ignore') or [])
    cur = (cur | set(keys)) if on else (cur - set(keys))
    meta['doctor_ignore'] = sorted(cur)
    db.save_manual({'meta': meta}, manual_id)


def location(db, x, L, titles=None):
    """«Section title › block 3 › cell 2×1» for the list."""
    if not x.get('sid'):
        return L('إعدادات الدليل', 'Manual settings')
    s = (titles or {}).get(x['sid']) or db.section(x['sid'])
    name = (s.get('title_ar') or s.get('title_en') or '') if L('a', 'b') == 'a' else (s.get('title_en') or s.get('title_ar') or '')
    kind = SECTION_KINDS.get(s.get('kind'), ('', ''))
    parts = [f'{s.get("code") + " " if s.get("code") else ""}{name or L(kind[0], kind[1])}']
    if x.get('b') is not None:
        parts.append(L(f'الكتلة {x["b"] + 1}', f'block {x["b"] + 1}'))
    p = x.get('path') or []
    if 'rows' in p:
        r, c = p[p.index('rows') + 1], p[p.index('rows') + 2]
        parts.append(L(f'الصف {r + 1} العمود {c + 1}', f'row {r + 1}, column {c + 1}'))
    elif 'columns' in p:
        parts.append(L(f'عنوان العمود {p[p.index("columns") + 1] + 1}', f'column title {p[p.index("columns") + 1] + 1}'))
    elif p and p[0] in ('title_ar', 'title_en'):
        parts.append(L('العنوان', 'title'))
    return ' › '.join(parts)

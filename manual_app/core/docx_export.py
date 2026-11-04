"""The manual as a Word file (.docx) for editing outside the program: the same sections, blocks, tables, images and
organisational chart; page size, margins, header and footer from the layout; Word headings, so Word builds the
table of contents (it is refreshed when the file is opened)."""
import io


from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from . import orgchart
from .db import CONTROL_STATUSES
from .html import DEFAULT_DISCLAIMER, LABELS, _pt, block_font
from .richtext import lines, runs
from .templates import FONTS, PAGE_SIZES, layout_with_defaults


def _rgb(hexcol):
    h = (hexcol or '#000000').lstrip('#')
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _set_rtl(paragraph, rtl=True):
    ppr = paragraph._p.get_or_add_pPr()
    for el in ppr.findall(qn('w:bidi')):
        ppr.remove(el)
    if rtl:
        ppr.append(OxmlElement('w:bidi'))
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT


def _run_rtl(run, font):
    rpr = run._r.get_or_add_rPr()
    rpr.append(OxmlElement('w:rtl'))
    fonts = rpr.find(qn('w:rFonts'))
    if fonts is None:
        fonts = OxmlElement('w:rFonts')
        rpr.append(fonts)
    fonts.set(qn('w:cs'), font)
    fonts.set(qn('w:ascii'), font)
    fonts.set(qn('w:hAnsi'), font)


def _shade(cell, color):
    tcpr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), color.lstrip('#'))
    tcpr.append(shd)


def _run_shade(run, color):
    """A highlight of any colour under the words of a run (Word's own highlight has 16 colours only)."""
    rpr = run._r.get_or_add_rPr()
    for el in rpr.findall(qn('w:shd')):
        rpr.remove(el)
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), color.lstrip('#').upper())
    rpr.append(shd)


def _borders(table, color, size=4):
    """Every line of a table in one colour (``size`` in eighths of a point), as the pages show it."""
    tblpr = table._tbl.tblPr
    for el in tblpr.findall(qn('w:tblBorders')):
        tblpr.remove(el)
    borders = OxmlElement('w:tblBorders')
    for side in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        el = OxmlElement(f'w:{side}')
        el.set(qn('w:val'), 'single')
        el.set(qn('w:sz'), str(size))
        el.set(qn('w:space'), '0')
        el.set(qn('w:color'), color.lstrip('#').upper())
        borders.append(el)
    tblpr.append(borders)


def _cell_margins(table, top_mm, side_mm):
    tblpr = table._tbl.tblPr
    for el in tblpr.findall(qn('w:tblCellMar')):
        tblpr.remove(el)
    mar = OxmlElement('w:tblCellMar')
    for side, mm in (('top', top_mm), ('bottom', top_mm), ('left', side_mm), ('right', side_mm), ('start', side_mm),
                     ('end', side_mm)):
        el = OxmlElement(f'w:{side}')
        el.set(qn('w:w'), str(int(mm * 56.7)))          # twentieths of a point
        el.set(qn('w:type'), 'dxa')
        mar.append(el)
    tblpr.append(mar)


def _fixed_width(table):
    """The table as wide as the page with fixed columns: long words wrap inside their cell (as «break long words»)."""
    tblpr = table._tbl.tblPr
    lay = OxmlElement('w:tblLayout')
    lay.set(qn('w:type'), 'fixed')
    tblpr.append(lay)
    for el in tblpr.findall(qn('w:tblW')):
        tblpr.remove(el)
    w = OxmlElement('w:tblW')
    w.set(qn('w:w'), '5000')
    w.set(qn('w:type'), 'pct')
    tblpr.append(w)


def _keep_rows(table, keep_last):
    """The rows never split, and each row stays on the page of the next (all of them when ``keep_last``)."""
    rows = list(table.rows)
    for i, row in enumerate(rows):
        trpr = row._tr.get_or_add_trPr()
        trpr.append(OxmlElement('w:cantSplit'))
        if i < len(rows) - 1 or keep_last:
            for cell in row.cells:
                for p in cell.paragraphs:
                    p.paragraph_format.keep_with_next = True


def _keep_next(element):
    """Every paragraph inside a piece of the document stays on the page of what follows."""
    for p in element.iter(qn('w:p')):
        ppr = p.get_or_add_pPr()
        if ppr.find(qn('w:keepNext')) is None:
            ppr.insert(0, OxmlElement('w:keepNext'))


def _no_borders(table):
    tbl = table._tbl
    tblpr = tbl.tblPr
    borders = OxmlElement('w:tblBorders')
    for side in ('top', 'left', 'bottom', 'right', 'insideH', 'insideV'):
        el = OxmlElement(f'w:{side}')
        el.set(qn('w:val'), 'nil')
        borders.append(el)
    tblpr.append(borders)


def _field(paragraph, instr):
    """A Word field (PAGE, NUMPAGES, TOC…) inside a paragraph."""
    run = paragraph.add_run()
    b = OxmlElement('w:fldChar')
    b.set(qn('w:fldCharType'), 'begin')
    t = OxmlElement('w:instrText')
    t.set(qn('xml:space'), 'preserve')
    t.text = instr
    s = OxmlElement('w:fldChar')
    s.set(qn('w:fldCharType'), 'separate')
    txt = OxmlElement('w:t')
    txt.text = '1'
    e = OxmlElement('w:fldChar')
    e.set(qn('w:fldCharType'), 'end')
    for el in (b, t, s, txt, e):
        run._r.append(el)
    return run


class DocxExporter:
    def __init__(self, db, manual_id):
        self.db = db
        self.m = db.manual(manual_id)
        self.lay = layout_with_defaults(self.m['layout'])
        self.lm = self.lay['lang_mode']
        f = self.lay['fonts']
        # a font installed in Windows is written by its name (Word takes it from the system); the program's own
        # fonts keep their earlier stand-ins
        self.font_ar = f['ar'] if f['ar'] not in FONTS or f['ar'] in ('Amiri', 'Cairo', 'Tajawal') else 'Arial'
        self.font_en = f['en'] if f['en'] not in FONTS else 'Calibri'
        self.c = self.lay['colors']
        self._st = {}                # the look of the block being written (colour, size, bold, alignment, font)
        self.doc = Document()

    def label(self, key):
        ar, en = LABELS[key]
        return {'ar': ar, 'en': en}.get(self.lm, f'{en} / {ar}' if self.lm == 'bi_side' else f'{ar} / {en}')

    def title(self, ar, en, sep=' — '):
        ar, en = ar or '', en or ''
        if self.lm == 'ar':
            return ar or en
        if self.lm == 'en':
            return en or ar
        return f'{ar}{sep}{en}' if ar and en else (ar or en)

    # ── text ─────────────────────────────────────────────────────────
    def write_runs(self, paragraph, text, rtl, size=None, bold=False, color=None):
        _set_rtl(paragraph, rtl)
        if not rtl:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        st = dict(self._st)          # the block's own look, as in the PDF; a look for this language only on top
        side = st.get('ar' if rtl else 'en')
        if isinstance(side, dict):
            st.update({k: v for k, v in side.items() if v})
        al = st.get('align')
        if al in ('right', 'left'):
            # Word reads «left» and «right» of a right-to-left paragraph as its start and its end
            phys = {'right': WD_ALIGN_PARAGRAPH.RIGHT, 'left': WD_ALIGN_PARAGRAPH.LEFT}
            paragraph.alignment = phys[{'right': 'left', 'left': 'right'}[al] if rtl else al]
        elif al == 'center':
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        elif al == 'justify':
            paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        try:
            pct = int(st.get('size') or 100)
        except (TypeError, ValueError):
            pct = 100
        if _pt(st.get('pt')):
            size = _pt(st['pt'])
        elif pct != 100 and 50 <= pct <= 300:
            size = (size or float(self.lay['fonts']['size'])) * pct / 100
        bold = bold or bool(st.get('bold'))
        if isinstance(st.get('color'), str) and len(st['color']) == 7:
            color = st['color']
        bg = st.get('bg') if isinstance(st.get('bg'), str) and len(st['bg']) == 7 else None
        bf = block_font(st)
        for t, f in runs(text) if ('<' in (text or '')) else [(text or '', {})]:
            if t == '\n':
                paragraph.add_run().add_break()
                continue
            r = paragraph.add_run(t)
            r.bold = bold or f.get('b') or None
            r.italic = f.get('i') or None
            r.underline = f.get('u') or None
            if f.get('pt') or size:
                r.font.size = Pt(f.get('pt') or size)
            col = f.get('color') or color             # words coloured one by one keep their colour
            if col:
                r.font.color.rgb = _rgb(col)
            if f.get('bg') or bg:
                _run_shade(r, f.get('bg') or bg)
            fam = block_font({'font': f.get('font')}) or bf
            if rtl:
                _run_rtl(r, fam or self.font_ar)
            else:
                r.font.name = fam or self.font_en

    def pair(self, container, ar, en, size=None, bold=False, color=None, style=None):
        """One piece of text in the manual's language mode (side by side = a two-column table without borders)."""
        ar, en = ar or '', en or ''
        if not ar and not en:
            return
        made = []
        if self.lm == 'ar' or (self.lm == 'bi_stack'):
            if ar:
                p = container.add_paragraph(style=style)
                self.write_runs(p, ar, True, size, bold, color)
                made.append(p._p)
            if self.lm == 'bi_stack' and en:
                p = container.add_paragraph(style=style)
                self.write_runs(p, en, False, size, bold, color)
                made.append(p._p)
            return made
        if self.lm == 'en':
            p = container.add_paragraph(style=style)
            self.write_runs(p, en or ar, False, size, bold, color)
            return [p._p]
        t = container.add_table(rows=1, cols=2)
        _no_borders(t)
        t.autofit = True
        pe = t.cell(0, 0).paragraphs[0]
        pa = t.cell(0, 1).paragraphs[0]
        if style:
            pe.style = pa.style = style
        self.write_runs(pe, en, False, size, bold, color)
        self.write_runs(pa, ar, True, size, bold, color)
        return [t._tbl]

    def list_pair(self, ar, en, numbered):
        style = 'List Number' if numbered else 'List Bullet'
        la, le = lines(ar), lines(en)
        if self.lm in ('ar', 'bi_stack'):
            for x in la:
                p = self.doc.add_paragraph(style=style)
                self.write_runs(p, x, True)
            if self.lm == 'bi_stack':
                for x in le:
                    p = self.doc.add_paragraph(style=style)
                    self.write_runs(p, x, False)
            return
        if self.lm == 'en':
            for x in le or la:
                p = self.doc.add_paragraph(style=style)
                self.write_runs(p, x, False)
            return
        t = self.doc.add_table(rows=1, cols=2)
        _no_borders(t)
        for col, items, rtl in ((0, le, False), (1, la, True)):
            cell = t.cell(0, col)
            first = True
            for x in items:
                p = cell.paragraphs[0] if first else cell.add_paragraph()
                first = False
                p.style = style
                self.write_runs(p, x, rtl)

    # ── tables ───────────────────────────────────────────────────────
    def cell_text(self, cell, v, header=False, color=None, size=9, bold=False):
        p = cell.paragraphs[0]
        if isinstance(v, str):
            v = {'ar': v, 'en': ''}
        a, e = (v or {}).get('ar') or '', (v or {}).get('en') or ''
        if color is None:
            color = self.c['table_head_text'] if header else None
        bold = header or bold
        if self.lm == 'en' or (not a and e):
            self.write_runs(p, e or a, False, size, bold, color)
        elif self.lm == 'ar' or not e or a == e:
            self.write_runs(p, a, True, size, bold, color)
        else:
            self.write_runs(p, a, True, size, bold, color)
            self.write_runs(cell.add_paragraph(), e, False, size * 0.95, bold, color)

    def table(self, cols, rows, numbered=False, colors=None, d=None, look=None, keep_next=False):
        """A table as the pages show it: its colours and borders, its font and size, tight cells, a landscape page,
        kept on one page (``d``: the table's data; ``look``: the block's look)."""
        d = d or {}
        look = dict(look or {})
        own = colors or {}
        head = own.get('head') or self.c['table_head']
        head_text = own.get('head_text') or self.c['table_head_text']
        stripe = own.get('stripe') or self.c.get('table_stripe')
        border = own.get('border') or self.c.get('table_border') or self.c.get('box_border')
        text = look.get('color') if isinstance(look.get('color'), str) and len(look['color']) == 7 else \
            (own.get('text') or self.c.get('table_text') or None)
        scale = int(d.get('scale') or 100) / 100
        size = (_pt(look.get('pt')) or float(self.lay['fonts']['size']) * 0.92) * scale
        rows = [r for r in rows if any(((x or {}).get('ar') or (x or {}).get('en')) if isinstance(x, dict) else x for x in r)]
        landscape = d.get('landscape') and self.lay['orientation'] != 'landscape'
        if landscape:
            self.turn(True)
        if d.get('caption_ar') or d.get('caption_en'):
            for el in self.pair(self.doc, d.get('caption_ar'), d.get('caption_en'), bold=True, color=self.c['secondary']) or []:
                _keep_next(el)
        n = len(cols) + (1 if numbered else 0)
        t = self.doc.add_table(rows=1 + len(rows), cols=n)
        t.style = 'Table Grid'
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        if d.get('borders') is False:
            _no_borders(t)
        elif border:
            _borders(t, border)
        _cell_margins(t, *((0.8, 1.2) if d.get('compact') else (1.4, 2.0)))
        if d.get('break_words'):
            _fixed_width(t)
        heads = ([{'ar': 'م', 'en': 'No.'}] if numbered else []) + list(cols)
        if self.lm != 'en':
            tblpr = t._tbl.tblPr
            tblpr.append(OxmlElement('w:bidiVisual'))
        # the size and the colours are given here; the rest of the block's look (font, highlight, one language) stays
        saved = self._st
        self._st = {k: v for k, v in (saved or {}).items() if k not in ('pt', 'size', 'color', 'bold')}
        for sd in ('ar', 'en'):
            if isinstance(self._st.get(sd), dict):
                self._st[sd] = {k: v for k, v in self._st[sd].items() if k not in ('pt', 'color')}
        self._st.update({k: look[k] for k in ('font', 'bg') if look.get(k) and k not in self._st})
        try:
            for j, h in enumerate(heads):
                c = t.cell(0, j)
                _shade(c, head)
                self.cell_text(c, h, header=True, color=head_text, size=size)
            for i, r in enumerate(rows, 1):
                vals = ([str(i)] if numbered else []) + list(r[:len(cols)])
                for j, v in enumerate(vals):
                    if stripe and i % 2 == 0 and stripe.upper() != '#FFFFFF':
                        _shade(t.cell(i, j), stripe)
                    first = d.get('first_col_bold') and j == (1 if numbered else 0)
                    self.cell_text(t.cell(i, j), v, color=text, size=size, bold=bool(first or look.get('bold')))
        finally:
            self._st = saved
        # the header row repeats on every page
        trpr = t.rows[0]._tr.get_or_add_trPr()
        trpr.append(OxmlElement('w:tblHeader'))
        if d.get('keep') or keep_next:
            _keep_rows(t, keep_next)
        elif not d.get('split_rows'):
            for row in t.rows:               # a row is never cut between two pages, as in the PDF
                row._tr.get_or_add_trPr().append(OxmlElement('w:cantSplit'))
        after = self.doc.add_paragraph()
        if keep_next:
            after.paragraph_format.keep_with_next = True
        if landscape:
            self.turn(False)
        return t

    def turn(self, landscape):
        """A new page in the other orientation (a table too wide for the page), or back to the manual's."""
        lay = self.lay
        w, h = PAGE_SIZES.get(lay['page_size'], PAGE_SIZES['A4'])
        sec = self.doc.add_section(WD_SECTION.NEW_PAGE)
        if landscape:
            sec.orientation = WD_ORIENT.LANDSCAPE
            sec.page_width, sec.page_height = Mm(max(w, h)), Mm(min(w, h))
        else:
            sec.orientation = WD_ORIENT.PORTRAIT
            sec.page_width, sec.page_height = Mm(min(w, h)), Mm(max(w, h))

    def write_blocks(self, blocks):
        """The blocks of a section; a sub-heading stays with the table under it, and the tables of one group (and
        the sub-headings between them) stay together on one page, as in the PDF."""
        for i, b in enumerate(blocks):
            nxt = blocks[i + 1] if i + 1 < len(blocks) else None
            g = ((b.get('data') or {}).get('group') or '').strip() if b['kind'] == 'table' else ''
            keep = False
            if b['kind'] == 'heading' and nxt and nxt['kind'] == 'table':
                keep = True
            elif g:
                for later in blocks[i + 1:]:
                    if later['kind'] == 'heading':
                        continue
                    keep = later['kind'] == 'table' and ((later.get('data') or {}).get('group') or '').strip() == g
                    break
            self.block(b, keep)

    # ── document ─────────────────────────────────────────────────────
    def setup(self):
        lay = self.lay
        w, h = PAGE_SIZES.get(lay['page_size'], PAGE_SIZES['A4'])
        sec = self.doc.sections[0]
        if lay['orientation'] == 'landscape':
            sec.orientation = WD_ORIENT.LANDSCAPE
            w, h = h, w
        sec.page_width, sec.page_height = Mm(w), Mm(h)
        mg = lay['margins']
        sec.top_margin, sec.bottom_margin = Mm(mg['top']), Mm(mg['bottom'])
        sec.left_margin, sec.right_margin = Mm(mg['left']), Mm(mg['right'])
        sec.header_distance, sec.footer_distance = Mm(6), Mm(6)
        st = self.doc.styles['Normal']
        st.font.name = self.font_en
        st.font.size = Pt(lay['fonts']['size'])
        st.element.rPr.rFonts.set(qn('w:cs'), self.font_ar)
        for lvl, size in ((1, 18), (2, 14), (3, 12)):
            hs = self.doc.styles[f'Heading {lvl}']
            hs.font.color.rgb = _rgb(self.c['heading'])
            hs.font.size = Pt(size)
            hs.font.name = self.font_en
            hs.element.rPr.rFonts.set(qn('w:cs'), self.font_ar)
        # header: logo + manual title; footer: issue date + page X of Y
        rtl = self.lm != 'en'
        hp = sec.header.paragraphs[0]
        _set_rtl(hp, rtl)
        if self.m.get('logo_id'):
            a = self.db.asset(self.m['logo_id'])
            if a:
                try:
                    hp.add_run().add_picture(io.BytesIO(a['data']), height=Mm(12))
                    hp.add_run('   ')
                except Exception:  # noqa: BLE001 — an image Word cannot embed (SVG…)
                    pass
        r = hp.add_run(self.title(self.m['title_ar'], self.m['title_en'], ' / '))
        r.bold = True
        r.font.color.rgb = _rgb(self.c['primary'])
        if rtl:
            _run_rtl(r, self.font_ar)
        fp = sec.footer.paragraphs[0]
        _set_rtl(fp, rtl)
        fp.add_run(f'{self.label("issue_label")} {self.m.get("issue_date") or ""}        {self.label("page_label")} ')
        _field(fp, 'PAGE')
        fp.add_run(' | ')
        _field(fp, 'NUMPAGES')
        # Word refreshes the table of contents and page fields when the file is opened
        settings = self.doc.settings.element
        upd = OxmlElement('w:updateFields')
        upd.set(qn('w:val'), 'true')
        settings.append(upd)

    def page_break(self):
        self.doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

    def heading(self, s, level):
        p = self.doc.add_paragraph(style=f'Heading {min(level, 3)}')
        self.write_runs(p, self.title(s.get('title_ar'), s.get('title_en')), self.lm != 'en', bold=True,
                        color=self.c['heading'])

    def export(self, path):
        self.setup()
        first = True
        for s, depth in self.db.flat(self.m['id']):
            k = s['kind']
            if (s['new_page'] or k in ('chapter', 'toc')) and not first:
                self.page_break()
            first = False
            fn = getattr(self, 'k_' + k, self.k_text)
            fn(s, depth)
        self.doc.save(path)
        return path

    # kinds -----------------------------------------------------------
    def k_cover(self, s, depth):
        m = self.m
        if m.get('logo_id'):
            a = self.db.asset(m['logo_id'])
            if a:
                try:
                    p = self.doc.add_paragraph()
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    p.add_run().add_picture(io.BytesIO(a['data']), height=Mm(35))
                except Exception:  # noqa: BLE001
                    pass
        for _ in range(3):
            self.doc.add_paragraph()
        for ar, en, size in ((m['title_ar'], m['title_en'], 30), (m.get('subtitle_ar'), m.get('subtitle_en'), 16),
                             (m.get('org_ar'), m.get('org_en'), 14), (m.get('edition_ar'), m.get('edition_en'), 12)):
            if ar or en:
                self.pair(self.doc, ar, en, size, size >= 14, self.c['primary'])
        self.page_break()

    def k_chapter(self, s, depth):
        self.heading(s, 1)
        self.k_text(s, depth, heading=False)

    def k_text(self, s, depth, heading=True):
        if heading:
            self.heading(s, depth + 1)
        self.write_blocks(self.db.blocks(s['id']))

    def k_policy(self, s, depth):
        self.k_text(s, depth)
        if self.lay.get('policy_footer'):
            meta = s.get('meta') or {}
            self.table([{'ar': LABELS['responsible'][0], 'en': LABELS['responsible'][1]}],
                       [[{'ar': meta.get('responsible_ar') or ' ', 'en': meta.get('responsible_en') or ''}]])
            revs = self.db.revisions(s['id'])
            cols = [{'ar': LABELS[k][0], 'en': LABELS[k][1]} for k in ('version', 'date', 'changes', 'by')]
            rows = [[{'ar': r['version'], 'en': ''}, {'ar': r['rev_date'], 'en': ''},
                     {'ar': r['changes_ar'] or '', 'en': r['changes_en'] or ''}, {'ar': r['by_name'] or '', 'en': ''}] for r in revs]
            self.pair(self.doc, LABELS['history'][0], LABELS['history'][1], bold=True, color=self.c['primary'])
            self.table(cols, rows or [[{'ar': '-', 'en': ''}] * 4])

    def k_disclaimer(self, s, depth):
        self.heading(s, 2)
        meta = self.m.get('meta') or {}
        blocks = self.db.blocks(s['id'])
        if blocks:
            self.write_blocks(blocks)
        else:
            self.pair(self.doc, meta.get('disclaimer_ar') or DEFAULT_DISCLAIMER[0], meta.get('disclaimer_en') or DEFAULT_DISCLAIMER[1], bold=True)

    def k_doc_control(self, s, depth):
        self.heading(s, 2)
        meta = self.m.get('meta') or {}
        rows = []
        for key, v in (('prepared', meta.get('prepared_by')), ('reviewed', meta.get('reviewed_by')),
                       ('approved', meta.get('approved_by')), ('issue_no', self.m.get('issue_no')),
                       ('issue_label', self.m.get('issue_date')), ('first_draft', meta.get('first_draft'))):
            rows.append([{'ar': LABELS[key][0].rstrip(':'), 'en': LABELS[key][1].rstrip(':')}, {'ar': v or '', 'en': ''}])
        self.table([{'ar': 'البند', 'en': 'Item'}, {'ar': 'القيمة', 'en': 'Value'}], rows)

    def k_toc(self, s, depth):
        self.heading(s, 1)
        p = self.doc.add_paragraph()
        _field(p, f'TOC \\o "1-{int((s.get("data") or {}).get("depth") or self.lay.get("toc_depth") or 2)}" \\h \\z \\u')

    def k_table(self, s, depth):
        self.heading(s, depth + 1)
        d = s.get('data') or {}
        if d.get('columns'):
            landscape = (s.get('style') or {}).get('orientation') == 'landscape' and self.lay['orientation'] != 'landscape'
            self.table(d['columns'], d.get('rows') or [], d.get('numbered'), d.get('colors'),
                       dict(d, landscape=landscape or d.get('landscape')), d.get('look'))
        self.write_blocks(self.db.blocks(s['id']))

    def k_orgchart(self, s, depth):
        self.heading(s, depth + 1)
        d = s.get('data') or {}
        svg = orgchart.render_svg(self.db.org_tree(self.m['id'], d.get('root_id')), self.lm, self.c,
                                  self.lay['fonts']['ar'], int(d.get('depth') or 0))
        png = svg_to_png(svg)
        if png:
            sec = self.doc.sections[0]
            width = sec.page_width - sec.left_margin - sec.right_margin
            p = self.doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            p.add_run().add_picture(io.BytesIO(png), width=width)
        self.write_blocks(self.db.blocks(s['id']))

    def k_compliance(self, s, depth):
        self.heading(s, depth + 1)
        d = s.get('data') or {}
        cols = [{'ar': LABELS[k][0], 'en': LABELS[k][1]} for k in ('code', 'requirement', 'framework', 'owner', 'frequency', 'evidence', 'status')]
        rows = []
        for c in self.db.controls(self.m['id'], section_id=d.get('section_id')):
            st = CONTROL_STATUSES.get(c['status'], ('', ''))
            rows.append([{'ar': c['code'] or '', 'en': ''}, {'ar': c['title_ar'] or '', 'en': c['title_en'] or ''},
                         {'ar': c['framework'] or '', 'en': ''}, {'ar': c['owner'] or '', 'en': ''},
                         {'ar': c['frequency'] or '', 'en': ''}, {'ar': c['evidence'] or '', 'en': ''},
                         {'ar': st[0], 'en': st[1]}])
        self.table(cols, rows or [[{'ar': '-', 'en': ''}] * 7], True)

    k_links = k_text
    k_image = k_text

    def block(self, b, keep_next=False):
        self._st = b.get('style') or {}
        try:
            self._block(b, keep_next)
        finally:
            self._st = {}

    def _block(self, b, keep_next=False):
        k, d = b['kind'], b.get('data') or {}
        ar, en = b.get('ar') or '', b.get('en') or ''
        if k == 'heading':
            for el in self.pair(self.doc, ar, en, bold=True, color=self.c['secondary']) or []:
                if keep_next:
                    _keep_next(el)
        elif k in ('paragraph', 'quote'):
            self.pair(self.doc, ar, en)
        elif k == 'callout':
            t = self.doc.add_table(rows=1, cols=1)
            _shade(t.cell(0, 0), self.c['callout'])
            cell = t.cell(0, 0)
            if self.lm == 'en':
                self.write_runs(cell.paragraphs[0], en or ar, False)
            else:
                self.write_runs(cell.paragraphs[0], ar or en, True)
                if self.lm in ('bi_side', 'bi_stack') and en:
                    self.write_runs(cell.add_paragraph(), en, False)
            self.doc.add_paragraph()
        elif k in ('bullets', 'numbered'):
            self.list_pair(ar, en, k == 'numbered')
        elif k == 'pagebreak':
            self.page_break()
        elif k == 'table':
            if d.get('columns'):
                self.table(d['columns'], d.get('rows') or [], d.get('numbered'), d.get('colors'), d, b.get('style'), keep_next)
        elif k == 'image':
            a = self.db.asset(int(d['asset_id'])) if d.get('asset_id') else None
            if a:
                data = a['data'] if a['mime'] != 'image/svg+xml' else svg_to_png(a['data'].decode('utf-8', 'ignore'))
                if data:
                    sec = self.doc.sections[0]
                    width = (sec.page_width - sec.left_margin - sec.right_margin) * int(d.get('width') or 100) / 100
                    p = self.doc.add_paragraph()
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    p.add_run().add_picture(io.BytesIO(data), width=int(width))
            if ar or en:
                self.pair(self.doc, ar, en, size=9)
        elif k == 'links':
            for it in d.get('items') or []:
                p = self.doc.add_paragraph(style='List Bullet')
                t = self.title(it.get('title_ar'), it.get('title_en')) or it.get('url') or ''
                self.write_runs(p, f'{t} — {it.get("url") or ""}', self.lm != 'en')


def svg_to_png(svg, scale=2.0):
    """An SVG drawing as PNG bytes (Word cannot show SVG everywhere). Needs a running Qt application."""
    if not svg:
        return None
    try:
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtSvg import QSvgRenderer
    except ImportError:
        return None
    r = QSvgRenderer(QByteArray(svg.encode('utf-8')))
    if not r.isValid():
        return None
    size = r.defaultSize()
    img = QImage(int(size.width() * scale), int(size.height() * scale), QImage.Format_ARGB32)
    img.fill(Qt.white)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    r.render(p, QRectF(0, 0, img.width(), img.height()))
    p.end()
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, 'PNG')
    return bytes(buf.data())


def export_docx(db, manual_id, path):
    return DocxExporter(db, manual_id).export(path)



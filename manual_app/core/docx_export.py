"""The manual as a Word file (.docx) for editing outside the program: the same sections, blocks, tables, images and
organisational chart; page size, margins, header and footer from the layout; Word headings, so Word builds the
table of contents (it is refreshed when the file is opened)."""
import io


from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Mm, Pt, RGBColor

from . import orgchart
from .db import CONTROL_STATUSES
from .html import DEFAULT_DISCLAIMER, LABELS
from .richtext import lines, runs
from .templates import PAGE_SIZES, layout_with_defaults


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
        self.font_ar = self.lay['fonts']['ar'] if self.lay['fonts']['ar'] in ('Amiri', 'Cairo', 'Tajawal') else 'Arial'
        self.font_en = 'Calibri'
        self.c = self.lay['colors']
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
        for t, f in runs(text) if ('<' in (text or '')) else [(text or '', {})]:
            if t == '\n':
                paragraph.add_run().add_break()
                continue
            r = paragraph.add_run(t)
            r.bold = bold or f.get('b') or None
            r.italic = f.get('i') or None
            r.underline = f.get('u') or None
            if size:
                r.font.size = Pt(size)
            col = color or f.get('color')
            if col:
                r.font.color.rgb = _rgb(col)
            if rtl:
                _run_rtl(r, self.font_ar)
            else:
                r.font.name = self.font_en

    def pair(self, container, ar, en, size=None, bold=False, color=None, style=None):
        """One piece of text in the manual's language mode (side by side = a two-column table without borders)."""
        ar, en = ar or '', en or ''
        if not ar and not en:
            return
        if self.lm == 'ar' or (self.lm == 'bi_stack'):
            if ar:
                p = container.add_paragraph(style=style)
                self.write_runs(p, ar, True, size, bold, color)
            if self.lm == 'bi_stack' and en:
                p = container.add_paragraph(style=style)
                self.write_runs(p, en, False, size, bold, color)
            return
        if self.lm == 'en':
            p = container.add_paragraph(style=style)
            self.write_runs(p, en or ar, False, size, bold, color)
            return
        t = container.add_table(rows=1, cols=2)
        _no_borders(t)
        t.autofit = True
        pe = t.cell(0, 0).paragraphs[0]
        pa = t.cell(0, 1).paragraphs[0]
        if style:
            pe.style = pa.style = style
        self.write_runs(pe, en, False, size, bold, color)
        self.write_runs(pa, ar, True, size, bold, color)

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
    def cell_text(self, cell, v, header=False):
        p = cell.paragraphs[0]
        if isinstance(v, str):
            v = {'ar': v, 'en': ''}
        a, e = (v or {}).get('ar') or '', (v or {}).get('en') or ''
        color = self.c['table_head_text'] if header else None
        if self.lm == 'en' or (not a and e):
            self.write_runs(p, e or a, False, 9, header, color)
        elif self.lm == 'ar' or not e or a == e:
            self.write_runs(p, a, True, 9, header, color)
        else:
            self.write_runs(p, a, True, 9, header, color)
            self.write_runs(cell.add_paragraph(), e, False, 8.5, header, color)

    def table(self, cols, rows, numbered=False):
        rows = [r for r in rows if any(((x or {}).get('ar') or (x or {}).get('en')) if isinstance(x, dict) else x for x in r)]
        n = len(cols) + (1 if numbered else 0)
        t = self.doc.add_table(rows=1 + len(rows), cols=n)
        t.style = 'Table Grid'
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        heads = ([{'ar': 'م', 'en': 'No.'}] if numbered else []) + list(cols)
        if self.lm != 'en':
            tblpr = t._tbl.tblPr
            tblpr.append(OxmlElement('w:bidiVisual'))
        for j, h in enumerate(heads):
            c = t.cell(0, j)
            _shade(c, self.c['table_head'])
            self.cell_text(c, h, header=True)
        for i, r in enumerate(rows, 1):
            vals = ([str(i)] if numbered else []) + list(r[:len(cols)])
            for j, v in enumerate(vals):
                self.cell_text(t.cell(i, j), v)
        # the header row repeats on every page
        trpr = t.rows[0]._tr.get_or_add_trPr()
        trpr.append(OxmlElement('w:tblHeader'))
        self.doc.add_paragraph()

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
        for b in self.db.blocks(s['id']):
            self.block(b)

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
            for b in blocks:
                self.block(b)
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
            self.table(d['columns'], d.get('rows') or [], d.get('numbered'))
        for b in self.db.blocks(s['id']):
            self.block(b)

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
        for b in self.db.blocks(s['id']):
            self.block(b)

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

    def block(self, b):
        k, d = b['kind'], b.get('data') or {}
        ar, en = b.get('ar') or '', b.get('en') or ''
        if k == 'heading':
            self.pair(self.doc, ar, en, bold=True, color=self.c['secondary'])
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
                self.table(d['columns'], d.get('rows') or [], d.get('numbered'))
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



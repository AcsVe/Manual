"""The manual as one HTML document — the single source of every output:

* ``print``: paginated by Paged.js (CSS paged media: page size, margins, running header and footer, page counters,
  table-of-contents page numbers, named pages for the cover and chapter dividers) and saved to PDF by the browser
  engine — see pdf.py. The editor's live preview uses the same mode.
* ``web``: one self-contained page (fonts and images inside it) with a side index, search and a language switch —
  the interactive copy that can be sent to staff or put on the intranet.
"""
import base64
import json
import os
import re
import sys
from html import escape, unescape

from . import orgchart
from .db import CONTROL_STATUSES, STATUSES
from .richtext import clean, lines
from .templates import FONTS, FRONT_KINDS, PAGE_SIZES, layout_with_defaults

LABELS = {
    'issue_label': ('تاريخ الإصدار:', 'Issue Date:'), 'page_label': ('صفحة', 'Page'), 'of': ('من', 'of'),
    'responsible': ('المسؤول عن المتابعة والتحديث', 'Responsible to maintain & update'),
    'history': ('سجل التغييرات', 'Change history'), 'version': ('الإصدار', 'Version'), 'date': ('التاريخ', 'Date'),
    'changes': ('التغييرات', 'Changes'), 'by': ('بواسطة', 'By'),
    'prepared': ('إعداد', 'Prepared by'), 'reviewed': ('مراجعة', 'Reviewed by'), 'approved': ('اعتماد', 'Approved by'),
    'issue_no': ('رقم الإصدار', 'Issue #'), 'first_draft': ('المسودة الأولى', 'First draft'),
    'effective': ('تاريخ النفاذ', 'Effective date'), 'next_review': ('المراجعة القادمة', 'Next review'),
    'contents': ('الفهرس', 'Contents'), 'page_no': ('رقم الصفحة', 'Page No.'),
    'disclaimer': ('تنويه:', 'Disclaimer:'), 'draft': ('مسودة', 'DRAFT'), 'search': ('بحث في الدليل…', 'Search the manual…'),
    'code': ('الرمز', 'Code'), 'requirement': ('المتطلب', 'Requirement'), 'framework': ('المرجعية', 'Framework'),
    'owner': ('المسؤول', 'Owner'), 'frequency': ('الدورية', 'Frequency'), 'evidence': ('الدليل', 'Evidence'),
    'status': ('الحالة', 'Status'), 'no': ('م', 'No.'), 'policy_status': ('حالة الوثيقة', 'Document status'),
    'both': ('كلاهما', 'Both'), 'ar': ('العربية', 'Arabic'), 'en': ('English', 'English'),
}
DEFAULT_DISCLAIMER = (
    'يحتوي هذا المستند على معلومات سرية موجهة فقط للفرد (الأفراد) أو الجهة المعنية وأولئك المسؤولين عن إدارته '
    'وتعديله وحفظه. إذا لم تكن المستلم المقصود، فإن هذا إخطار لك بأن أي نشر أو توزيع أو نسخ لهذا المستند ممنوع منعاً '
    'باتاً، ويترتب على الكشف غير المصرح به عواقب قانونية. إذا كنت قد استلمت هذا المستند عن طريق الخطأ، يرجى إبلاغ '
    'المرسل فوراً وإتلاف جميع النسخ.',
    'This document contains confidential information intended only for the individual(s) or entity to whom it is '
    'addressed and those responsible for its management, modification and safeguarding. If you are not the intended '
    'recipient, you are hereby notified that any dissemination, distribution or copying of this document is strictly '
    'prohibited. Unauthorised disclosure will result in legal consequences. If you have received this document in '
    'error, please notify the sender immediately and destroy all copies.')


CHUNK = 520          # characters of one side of a side-by-side piece: the page may break between pieces
PIECE = '\x01'       # between the pieces of one block
GLUE = '\x00'        # after the first piece of a section (kept on the page of the section title)
_SENT = re.compile(r'(?<=[.!?؟؛…:])\s+')


def chunk_html(html, target):
    """Cuts inline HTML into pieces of about ``target`` characters, at line breaks and sentence ends (at word ends
    for a very long sentence); tags open across a cut are closed and opened again."""
    if len(re.sub(r'<[^>]+>', '', html)) <= target * 1.3:
        return [html]
    parts, cur, size, stack = [], [], 0, []

    def cut():
        nonlocal cur, size
        if not size:
            return
        parts.append(''.join(cur) + ''.join(f'</{t}>' for t in reversed([x[0] for x in stack])))
        cur, size = [x[1] for x in stack], 0
    for tok in re.split(r'(<[^>]+>)', html):
        if not tok:
            continue
        if tok.startswith('<'):
            m = re.match(r'<(/?)([a-z0-9]+)', tok)
            name = m.group(2) if m else ''
            if name == 'br':
                if size >= target:
                    cut()
                    continue
                cur.append(tok)
                continue
            if m and m.group(1):
                if stack and stack[-1][0] == name:
                    stack.pop()
            elif m:
                stack.append((name, tok))
            cur.append(tok)
            continue
        for sent in _SENT.split(tok):
            words = sent.split(' ') if len(sent) > target else [sent]
            for j, w in enumerate(words):
                piece = w + (' ' if j < len(words) - 1 else '')
                if size >= target:
                    cut()
                cur.append(piece)
                size += len(piece)
            cur.append(' ')
    if cur:
        rest = ''.join(cur).strip()
        if re.sub(r'<[^>]+>', '', rest).strip():
            parts.append(rest)
        elif parts:
            parts[-1] += rest
    return [re.sub(r'^(\s|<br>)+', '', p) for p in parts] or [html]


def even_pieces(a_parts, e_parts):
    """Both languages in the same number of pieces (the extra ones of the longer side go together at its end)."""
    n = min(len(a_parts), len(e_parts)) or max(len(a_parts), len(e_parts))
    if len(a_parts) > n and len(e_parts):
        a_parts = a_parts[:n - 1] + [' '.join(a_parts[n - 1:])]
    if len(e_parts) > n and len(a_parts):
        e_parts = e_parts[:n - 1] + [' '.join(e_parts[n - 1:])]
    a_parts += [''] * (n - len(a_parts))
    e_parts += [''] * (n - len(e_parts))
    return a_parts, e_parts


_TABLE = re.compile(r'<table class="t[ "][^>]*>.*?</table>', re.S)


def mirror_tables(body):
    """Right-to-left tables written left to right with their cells in reverse order: Paged.js measures where a
    right-to-left table runs over the page wrongly and drops the rows that do not fit, instead of moving them on."""
    import lxml.html

    def flip(m):
        frag = lxml.html.fragment_fromstring(m.group(0))
        for tr in frag.iter('tr'):
            cells = list(tr)
            for c in cells:
                tr.remove(c)
            for c in reversed(cells):
                c.set('dir', 'rtl')
                tr.append(c)
        frag.set('class', frag.get('class', '') + ' mirrored')
        return lxml.html.tostring(frag, encoding='unicode')
    return _TABLE.sub(flip, body)


def app_root():
    return getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def assets_dir():
    return os.path.join(app_root(), 'assets')


def _b64(data, mime):
    return f'data:{mime};base64,' + base64.b64encode(data).decode()


class Renderer:
    """Builds the HTML of one manual. ``embed``: fonts inside the file (web copy) instead of next to it."""

    def __init__(self, db, manual_id, mode='print', embed=False, only=None, workflow=False):
        self.db, self.mode, self.embed = db, mode, embed
        self.m = db.manual(manual_id)
        self.lay = layout_with_defaults(self.m['layout'])
        self.lm = self.lay['lang_mode']
        self.only = set(only) if only else None
        self.workflow = workflow
        self._asset_cache = {}
        self.numbers = {}
        self.pn = self.lay['page_numbers']
        self.front_ids, self.reset_id = set(), None
        self._bref = None             # «section:block» of the block being written (lets the layout check name it)
        self._k = 0
        self._kmap = {}               # every marked text: where it belongs, so text that never prints is found
        self._sid = None

    # ── small helpers ────────────────────────────────────────────────
    def L(self, key):
        ar, en = LABELS[key]
        return {'ar': ar, 'en': en}.get(self.lm, f'{en} / {ar}' if self.lm == 'bi_side' else f'{ar} / {en}')

    def asset_uri(self, asset_id):
        if not asset_id:
            return ''
        if asset_id not in self._asset_cache:
            a = self.db.asset(int(asset_id))
            self._asset_cache[asset_id] = _b64(a['data'], a['mime']) if a else ''
        return self._asset_cache[asset_id]

    def faded_uri(self, asset_id, opacity, fit='cover'):
        """A background image at a given opacity: wrapped in a small SVG (CSS cannot fade a page background)."""
        uri = self.asset_uri(asset_id)
        if not uri:
            return ''
        if float(opacity or 1) >= 0.999 and fit != 'contain':
            return uri
        par = {'cover': 'xMidYMid slice', 'contain': 'xMidYMid meet'}.get(fit, 'xMidYMid slice')
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="1000" height="1000" '
               f'viewBox="0 0 1000 1000" preserveAspectRatio="none"><image width="1000" height="1000" '
               f'preserveAspectRatio="{par}" opacity="{float(opacity):.2f}" href="{uri}" xlink:href="{uri}"/></svg>')
        return 'data:image/svg+xml;base64,' + base64.b64encode(svg.encode()).decode()

    def k(self, html):
        """Marks a piece of text with its length, so the layout check can tell when part of it does not print."""
        if self.mode != 'print':
            return ''
        n = len(re.sub(r'\s+', '', unescape(re.sub(r'<[^>]+>', '', html or ''))))
        if not n:
            return ''
        self._k += 1
        self._kmap[self._k] = [self._bref or f'{self._sid}:', n]
        return f' data-k="{self._k}" data-n="{n}"'

    def pair(self, ar, en, cls='', tag='div', raw=False):
        """One piece of text in the manual's language mode."""
        a = (ar or '') if raw else clean(ar)
        e = (en or '') if raw else clean(en)
        if not a and not e:
            return ''
        if self.lm == 'ar':
            return f'<{tag} class="one ar {cls}" dir="rtl"{self.k(a or e) if not raw else ""}>{a or e}</{tag}>'
        if self.lm == 'en':
            return f'<{tag} class="one en {cls}" dir="ltr"{self.k(e or a) if not raw else ""}>{e or a}</{tag}>'
        if self.lm == 'bi_side' and self.mode == 'print' and tag == 'div' and \
                max(len(re.sub(r'<[^>]+>', '', a)), len(re.sub(r'<[^>]+>', '', e))) > CHUNK * 1.3:
            # a long text side by side goes in pieces: the page can break between them (a page break inside
            # two columns side by side loses or repeats lines), and the two languages stay level piece by piece
            k = max(-(-len(re.sub(r'<[^>]+>', '', a)) // CHUNK), -(-len(re.sub(r'<[^>]+>', '', e)) // CHUNK))
            ap = chunk_html(a, max(200, len(re.sub(r'<[^>]+>', '', a)) // k + 1)) if a else []
            ep = chunk_html(e, max(200, len(re.sub(r'<[^>]+>', '', e)) // k + 1)) if e else []
            ap, ep = even_pieces(ap, ep)
            ref = f' data-b="{self._bref}"' if self._bref else ''
            return PIECE.join(f'<div class="pair {cls}"{ref}><div class="ar" dir="rtl"{self.k(x) if not raw else ""}>{x}</div>'
                              f'<div class="en" dir="ltr"{self.k(y) if not raw else ""}>{y}</div></div>'
                              for x, y in zip(ap, ep))
        ka, ke = (self.k(a), self.k(e)) if not raw else ('', '')
        if self.lm == 'bi_stack':
            return (f'<{tag} class="stack {cls}">' + (f'<div class="ar" dir="rtl"{ka}>{a}</div>' if a else '')
                    + (f'<div class="en" dir="ltr"{ke}>{e}</div>' if e else '') + f'</{tag}>')
        return f'<{tag} class="pair {cls}"><div class="ar" dir="rtl"{ka}>{a}</div><div class="en" dir="ltr"{ke}>{e}</div></{tag}>'

    def title_text(self, s, sep=' / '):
        ar, en = s.get('title_ar') or '', s.get('title_en') or ''
        if self.lm == 'ar':
            return ar or en
        if self.lm == 'en':
            return en or ar
        return f'{ar}{sep}{en}' if ar and en else (ar or en)

    def tokens(self, text, css=True):
        """Header/footer text → a CSS ``content`` value (print) or plain text (web)."""
        m = self.m
        lit = {
            '{title}': self.title_text({'title_ar': m['title_ar'], 'title_en': m['title_en']}),
            '{org}': self.title_text({'title_ar': m.get('org_ar'), 'title_en': m.get('org_en')}),
            '{issue_no}': m.get('issue_no') or '', '{issue_date}': m.get('issue_date') or '',
            '{edition}': self.title_text({'title_ar': m.get('edition_ar'), 'title_en': m.get('edition_en')}),
            '{issue_label}': self.L('issue_label'), '{page_label}': self.L('page_label'), '{of}': self.L('of'),
        }
        dg = self.digits()
        fn = {'{page}': f'counter(page, {dg})', '{pages}': f'counter(pages, {dg})', '{chapter}': 'string(chapter)',
              '{section}': 'string(section)'}
        parts = re.split(r'(\{[a-z_]+\})', text or '')
        if not css:
            return ''.join(lit.get(p, '' if p in fn else p) for p in parts)
        out = []
        for p in parts:
            if not p:
                continue
            if p in fn:
                out.append(fn[p])
            else:
                v = lit.get(p, p)
                out.append('"' + v.replace('\\', '\\\\').replace('"', '\\"') + '"')
        return ' '.join(out) or 'none'

    def digits(self):
        return 'arabic-indic' if self.pn.get('digits') == 'arabic' else 'decimal'

    def front_box(self, text):
        """A header/footer box on a front-matter page when those pages are numbered apart: the page number alone in
        small roman figures, or nothing."""
        if '{page}' not in (text or '') and '{pages}' not in (text or ''):
            return self.tokens(text)
        if self.pn.get('front') == 'roman':
            return 'counter(page, lower-roman)'
        return 'none'

    def plan_numbering(self, flat):
        """Which sections are front matter, and where the page count starts again."""
        front = self.pn.get('front', 'same')
        start = int(self.pn.get('start') or 1)
        lead = []
        for s, _ in flat:
            if s['kind'] not in FRONT_KINDS:
                break
            lead.append(s)
        body = next((s for s, _ in flat if s not in lead), None)
        if front in ('roman', 'hidden'):
            self.front_ids = {s['id'] for s in lead if s['kind'] != 'cover'}
            self.reset_id = body['id'] if body else None
        elif not self.pn.get('count_cover', True) or start != 1:
            after_cover = next((s for s, _ in flat if s['kind'] != 'cover'), None)
            self.reset_id = after_cover['id'] if after_cover else None
        self.skip_cover = not self.pn.get('count_cover', True) or front in ('roman', 'hidden')

    # ── document ─────────────────────────────────────────────────────
    def font_faces(self):
        css = []
        folder = os.path.join(assets_dir(), 'fonts')
        used = {self.lay['fonts']['ar'], self.lay['fonts']['en'], 'Tajawal'}
        for fam in used:
            slug = FONTS.get(fam)
            if not slug:
                continue
            for weight in (400, 700):
                for sub, rng in (('arabic', 'U+0600-06FF,U+0750-077F,U+0870-08FF,U+FB50-FDFF,U+FE70-FEFF,U+200C-200F'),
                                 ('latin', 'U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+2000-206F,U+20AC,U+2122,U+2190-2193,U+2212')):
                    path = os.path.join(folder, f'{slug}-{sub}-{weight}-normal.woff2')
                    if not os.path.isfile(path):
                        continue
                    if self.embed:
                        url = _b64(open(path, 'rb').read(), 'font/woff2')
                    else:
                        url = 'file:///' + path.replace('\\', '/').lstrip('/')
                    css.append(f'@font-face{{font-family:"{fam}";font-weight:{weight};src:url("{url}") format("woff2");'
                               f'unicode-range:{rng}}}')
        if not self.embed or self.needs_symbols:          # check marks, boxes, arrows, stars…: the same on every computer
            for name in ('symbols-2', 'symbols-1', 'symbols-math'):
                path = os.path.join(folder, f'{name}.woff2')
                if os.path.isfile(path):
                    url = _b64(open(path, 'rb').read(), 'font/woff2') if self.embed else \
                        'file:///' + path.replace('\\', '/').lstrip('/')
                    css.append(f'@font-face{{font-family:"MB {name}";src:url("{url}") format("woff2")}}')
        return '\n'.join(css)

    def wave_svg(self, height_mm, flip=False, full=False):
        c = self.lay['colors']
        w, h = 1000, 100
        p1 = 'M0,0 H1000 V55 C780,105 560,20 330,62 C190,88 80,70 0,52 Z'
        p2 = 'M0,0 H1000 V38 C760,88 540,8 320,48 C180,72 70,58 0,40 Z'
        tr = ' transform="translate(1000,0) scale(-1,1)"' if flip else ''
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
               f'<g{tr}><path d="{p1}" fill="{c["secondary"]}" opacity="0.55"/><path d="{p2}" fill="{c["primary"]}"/></g></svg>')
        return 'data:image/svg+xml;base64,' + base64.b64encode(svg.encode()).decode()

    def css(self):
        lay, c, f = self.lay, self.lay['colors'], self.lay['fonts']
        pw, ph = PAGE_SIZES.get(lay['page_size'], PAGE_SIZES['A4'])
        if lay['orientation'] == 'landscape':
            pw, ph = ph, pw
        mg = lay['margins']
        rtl = self.lm != 'en'
        start, end = ('right', 'left') if rtl else ('left', 'right')
        hd, ft = lay['header'], lay['footer']
        header_bg = ''
        hs = hd.get('style')
        hh = float(hd.get('height') or 22)
        if hs == 'wave':
            header_bg = f'url("{self.wave_svg(hh, flip=rtl)}") top left / 100% {hh}mm no-repeat'
        elif hs == 'band':
            header_bg = f'linear-gradient({c["primary"]},{c["primary"]}) top left / 100% {hh * 0.55:.1f}mm no-repeat'
        elif hs == 'image' and hd.get('image_id'):
            header_bg = f'url("{self.asset_uri(hd["image_id"])}") top center / 100% {hh}mm no-repeat'
        layers = []
        if hd.get('logo') and self.m.get('logo_id'):
            logo_h = max(10, hh * 0.62)
            layers.append(f'url("{self.asset_uri(self.m["logo_id"])}") top {hh * 0.15:.1f}mm {start} 8mm / auto {logo_h:.1f}mm no-repeat')
        if header_bg:
            layers.append(header_bg)
        if lay.get('page_bg_id'):
            layers.append(f'url("{self.faded_uri(lay["page_bg_id"], lay.get("page_bg_opacity", 0.06))}") center / cover no-repeat')
        page_bg = ('background:' + ', '.join(layers) + ';') if layers else ''
        head_col = '#ffffff' if hs in ('wave', 'band') else c['primary']
        line_css = f'border-bottom:0.4mm solid {c["primary"]};' if hs == 'line' else ''
        foot_line = f'border-top:0.3mm solid {c["box_border"]};' if ft.get('style') == 'line' else ''

        def box(pos, txt, extra=''):
            content = self.tokens(txt)
            if content == 'none':
                return ''
            return f'@{pos}{{content:{content};{extra}}}'
        hd_extra = f'color:{head_col};font-size:8.5pt;font-weight:700;vertical-align:top;padding-top:{hh * 0.18:.1f}mm;{line_css}'
        ft_extra = f'color:#55607a;font-size:8pt;vertical-align:middle;{foot_line}'
        margin_boxes = ''.join([
            box(f'top-{start}', hd.get('start', ''), hd_extra), box('top-center', hd.get('center', ''), hd_extra),
            box(f'top-{end}', hd.get('end', ''), hd_extra + f'text-align:{end};'),
            box(f'bottom-{start}', ft.get('start', ''), ft_extra), box('bottom-center', ft.get('center', ''), ft_extra),
            box(f'bottom-{end}', ft.get('end', ''), ft_extra + f'text-align:{end};'),
        ])
        front_boxes = ''
        if self.front_ids:
            def fbox(pos, txt, extra=''):
                content = self.front_box(txt)
                return f'@{pos}{{content:{content};{extra}}}'
            front_boxes = '@page front{' + ''.join([
                fbox(f'top-{start}', hd.get('start', ''), hd_extra), fbox('top-center', hd.get('center', ''), hd_extra),
                fbox(f'top-{end}', hd.get('end', ''), hd_extra + f'text-align:{end};'),
                fbox(f'bottom-{start}', ft.get('start', ''), ft_extra), fbox('bottom-center', ft.get('center', ''), ft_extra),
                fbox(f'bottom-{end}', ft.get('end', ''), ft_extra + f'text-align:{end};')]) + '} .front{page:front}'
        reset = f'.pgreset{{counter-reset:page {int(self.pn.get("start") or 1)}}}' if self.reset_id else ''
        cover = lay.get('cover') or {}
        cover_layers = []
        if cover.get('bg_id'):
            cover_layers.append(f'url("{self.faded_uri(cover["bg_id"], cover.get("bg_opacity", 1))}") center / cover no-repeat')
        cover_bg = ('background:' + ', '.join(cover_layers) + ';') if cover_layers else ''
        wm = ''
        if lay.get('watermark'):
            wm = f'.pagedjs_page::after{{content:"{escape(lay["watermark"])}";}}'
        size = f'{pw}mm {ph}mm'
        named = []
        for s, _ in self.db.flat(self.m['id']):
            st = s.get('style') or {}
            if st.get('bg_id') and st.get('bg_mode') == 'page':
                named.append(f'@page bg{s["id"]}{{background:url("{self.faded_uri(st["bg_id"], st.get("bg_opacity", 0.15), st.get("bg_fit", "cover"))}") center / cover no-repeat;}}'
                             f'.pg{s["id"]}{{page:bg{s["id"]}}}')
        return f"""
{self.font_faces()}
@page{{size:{size};margin:{mg['top']}mm {mg['right']}mm {mg['bottom']}mm {mg['left']}mm;{page_bg}{margin_boxes}}}
@page cover{{margin:0;background:none;{cover_bg}@top-left{{content:none}}@top-center{{content:none}}@top-right{{content:none}}
  @bottom-left{{content:none}}@bottom-center{{content:none}}@bottom-right{{content:none}}}}
{''.join(named)}
{front_boxes}
{reset}
:root{{--p:{c['primary']};--s:{c['secondary']};--a:{c['accent']};--t:{c['text']};--h:{c['heading']};
  --th:{c['table_head']};--tht:{c['table_head_text']};--bb:{c['box_border']};--co:{c['callout']}}}
html{{font-family:"{f['ar']}","{f['en']}",Tajawal,"MB symbols-2","MB symbols-1","MB symbols-math",Arial,sans-serif;font-size:{f['size']}pt;line-height:{f['line']};color:var(--t)}}
body{{margin:0}} body.rtl .sec,body.rtl .chapter-page,body.rtl .toc{{direction:rtl}} body.rtl table.t{{direction:rtl}} body.rtl table.t.mirrored{{direction:ltr}}
.en,.en *{{font-family:"{f['en']}","{f['ar']}","MB symbols-2","MB symbols-1","MB symbols-math",Arial,sans-serif}}
.ar{{text-align:justify;direction:rtl}} .en{{text-align:justify;direction:ltr}}
.pair{{display:grid;grid-template-columns:1fr 1fr;column-gap:7mm;align-items:start}}
.pair{{direction:ltr;break-inside:avoid}} .keep{{break-inside:avoid}} .pair>.ar{{grid-column:2;grid-row:1}} .pair>.en{{grid-column:1;grid-row:1}}
.stack>.en{{margin-top:1.5mm;color:#334}}
p,.blk{{margin:0 0 2.2mm}} p,li,.blk{{orphans:2;widows:2}}
.ar,.en,td,th{{overflow-wrap:break-word}} table.t td,table.t th,table.t td *,table.t th *{{overflow-wrap:anywhere}}
.sec{{break-inside:auto}} .newpage{{break-before:page}}
.cover{{page:cover;break-after:page;height:{ph}mm;position:relative;overflow:hidden;color:#fff}}
.chapter-page{{break-before:page;break-after:page;display:flex;flex-direction:column;justify-content:center;min-height:{ph - mg['top'] - mg['bottom'] - 5}mm}}
.chapter-page .ctitle{{font-size:28pt;font-weight:700;color:var(--h);text-align:center;border-top:1.2mm solid var(--a);border-bottom:1.2mm solid var(--a);padding:6mm 0}}
.chapter-page .ctitle .en{{text-align:center}} .chapter-page .ctitle .ar{{text-align:center}}
h1.chap{{string-set:chapter content(text)}}
.stitle{{string-set:section content(text)}}
.frame{{border:{'0.35mm solid var(--bb)' if lay.get('boxes') else '0'};margin:0 0 5mm;{'padding:0 0 2mm' if lay.get('boxes') else ''}}}
.frame>.inner{{padding:{'2.5mm 4mm 1mm' if lay.get('boxes') else '0'}}}
.tbar{{background:{'#eef3fb' if lay.get('boxes') else 'transparent'};border-bottom:{'0.35mm solid var(--bb)' if lay.get('boxes') else '0.6mm solid var(--a)'};
  padding:1.6mm 4mm;margin:0 0 3mm;font-weight:700;color:var(--h);font-size:1.12em;break-after:avoid}}
.tbar .en{{text-align:left}} .tbar .ar{{text-align:right}}
.lvl0>.tbar,.lvl0>.frame>.tbar,.lvl0>.frame>.keep>.tbar,.ptitle.lvl0t{{font-size:1.25em}} .lvl2>.frame>.tbar{{font-size:1.02em}}
.ptitle{{background:var(--p) !important;color:#fff !important;margin:0 !important}}
.num{{color:var(--a);margin-inline-end:2mm}}
.h-sub{{font-weight:700;color:var(--s);margin:3mm 0 1.5mm;break-after:avoid}}
.h-sub .ar,.h-sub .en{{text-decoration:underline;text-decoration-color:var(--a);text-underline-offset:1mm}}
ul,ol{{margin:0 0 2mm;padding-inline-start:6mm}} li{{margin:0 0 .8mm}}
.callout{{background:var(--co);border-inline-start:1.2mm solid var(--a);padding:2.5mm 4mm;margin:0 0 3mm}}
.quote{{border-inline-start:1mm solid var(--s);padding:1mm 4mm;color:#45526a;font-style:italic}}
table.t{{width:100%;border-collapse:collapse;margin:0 0 4mm;font-size:.92em}}
table.t th{{background:var(--th);color:var(--tht);font-weight:700;padding:1.6mm 2mm;border:0.3mm solid var(--bb);text-align:center}}
table.t td{{padding:1.4mm 2mm;border:0.3mm solid var(--bb);vertical-align:top}}
table.t tr:nth-child(even) td{{background:#f6f9fd}} table.t thead{{display:table-header-group}} table.t tr{{break-inside:avoid}}
table.t.split tr{{break-inside:auto}} table.t.compact td,table.t.compact th{{padding:.8mm 1.2mm}}
table.t td.n{{text-align:center;width:7mm;color:#55607a}} table.t td .en{{direction:ltr;text-align:left;color:#334;font-size:.95em}}
table.t .first{{font-weight:700}}
.figure{{text-align:center;margin:0 0 4mm;break-inside:avoid}} .figure img{{max-width:100%;max-height:{ph - mg['top'] - mg['bottom'] - 25}mm}}
.figure .cap{{font-size:.9em;color:#55607a;margin-top:1.5mm}}
.org{{text-align:center}} .org img{{width:auto;height:auto;max-width:100%;max-height:{ph - mg['top'] - mg['bottom'] - 24}mm;object-fit:contain}}
.links a{{color:var(--s)}} .links li{{margin-bottom:1.5mm}}
.meta-table td.k{{background:#eef3fb;font-weight:700;width:22%}}
.history{{margin-top:4mm;break-inside:avoid}} .history .cap{{background:var(--th);color:var(--tht);padding:1.2mm 3mm;font-weight:700}}
.toc a{{color:inherit;text-decoration:none;display:flex;gap:2mm}} .toc .row{{display:flex;align-items:baseline;gap:2mm;margin:0 0 1.3mm}}
.toc .row .lbl{{flex:1}} .toc .row.d0{{font-weight:700;color:var(--h);margin-top:2.2mm}} .toc .row.d1{{padding-inline-start:6mm}}
.toc .row.d2{{padding-inline-start:12mm;font-size:.95em}}
.toc .dots{{flex:1;border-bottom:0.3mm dotted #98a6bd;transform:translateY(-1mm)}}
.toc .pg::after{{content:target-counter(attr(data-ref url), page, {self.digits()})}}
.bg{{position:relative}} .bg>.bgimg{{position:absolute;inset:0;background-size:cover;background-position:center;z-index:0}}
.bg>.inner{{position:relative;z-index:1}}
.status{{display:inline-block;font-size:.8em;padding:.3mm 2mm;border-radius:2mm;background:#fff4e0;color:#8a5a00;margin-inline-start:2mm}}
.draft-mark{{position:relative}} .draft-mark::before{{content:"{self.L('draft')}";position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  font-size:48pt;font-weight:700;color:rgba(180,35,24,.07);transform:rotate(-18deg);pointer-events:none}}
.disclaimer .ar,.disclaimer .en{{font-weight:700;font-size:1.05em}}
{wm}
@media screen{{body{{background:#dfe5ee}} .pagedjs_pages{{display:flex;flex-direction:column;align-items:center;padding:14px 0}}
 .pagedjs_page{{background:#fff;box-shadow:0 2px 12px rgba(0,0,0,.18);margin:0 0 14px}}}}
@media print{{.pagedjs_page{{margin:0;box-shadow:none}}}}
"""

    def web_css(self):
        c = self.lay['colors']
        return f"""
body{{background:#eef2f7}} .layout{{display:flex;min-height:100vh}}
aside{{position:sticky;top:0;height:100vh;overflow:auto;width:320px;background:#fff;border-inline-end:1px solid #d5deea;padding:14px;box-sizing:border-box;flex:none}}
aside .brand{{display:flex;gap:10px;align-items:center;margin-bottom:12px}} aside .brand img{{height:44px}}
aside .brand b{{color:{c['primary']}}} aside input{{width:100%;box-sizing:border-box;padding:8px 10px;border:1px solid #c9d4e3;border-radius:8px;font:inherit}}
aside nav a{{display:block;padding:5px 8px;border-radius:6px;color:#1e293b;text-decoration:none;font-size:.95em}}
aside nav a:hover{{background:#eef3fb}} aside nav a.d0{{font-weight:700;color:{c['primary']};margin-top:6px}} aside nav a.d1{{padding-inline-start:18px}}
aside nav a.d2{{padding-inline-start:30px;font-size:.9em}} aside .langs{{display:flex;gap:6px;margin:10px 0}}
aside .langs button{{flex:1;padding:6px;border:1px solid #c9d4e3;background:#fff;border-radius:6px;cursor:pointer;font:inherit}}
aside .langs button.on{{background:{c['primary']};color:#fff;border-color:{c['primary']}}}
main{{flex:1;padding:24px;min-width:0}} .sheet{{max-width:1100px;margin:0 auto;background:#fff;padding:26px 30px;border-radius:12px;box-shadow:0 2px 14px rgba(0,0,0,.06)}}
.cover{{height:auto;min-height:420px;border-radius:12px;margin-bottom:18px}} .chapter-page{{min-height:0;padding:30px 0}}
.newpage{{margin-top:10px}} mark.hit{{background:#ffe08a}}
body.only-ar .en{{display:none}} body.only-en .ar{{display:none}} body.only-ar .pair,body.only-en .pair{{display:block}}
.toc .pg{{display:none}} .toc .dots{{display:none}}
@media (max-width:820px){{.layout{{display:block}} aside{{position:static;width:auto;height:auto}} .pair{{display:block}} .pair>.en{{margin-top:6px}} main{{padding:10px}} .sheet{{padding:16px}}}}
@media print{{aside{{display:none}} body{{background:#fff}} .sheet{{box-shadow:none}}}}
"""

    # ── sections ─────────────────────────────────────────────────────
    def number_sections(self, flat):
        counters = []
        for s, d in flat:
            if not s['in_toc'] or s['kind'] in ('cover', 'toc', 'disclaimer'):
                continue
            counters = counters[:d + 1]
            while len(counters) < d + 1:
                counters.append(0)
            counters[d] += 1
            self.numbers[s['id']] = '.'.join(str(n) for n in counters)

    def render(self):
        html = self._render()
        return html.replace(GLUE, '').replace(PIECE, '')

    def _render(self):
        flat = self.db.flat(self.m['id'])
        if self.lay.get('numbering'):
            self.number_sections(flat)
        self.flat = flat
        self.skip_cover = False
        if self.mode == 'print':
            self.plan_numbering(flat)
        self.needs_symbols = False
        parts = []
        self._pending = ''
        shown = [(s, d) for s, d in flat if self.only is None or s['id'] in self.only]
        for i, (s, depth) in enumerate(shown):
            self._next_child = i + 1 < len(shown) and shown[i + 1][1] > depth and not shown[i + 1][0]['new_page'] \
                and shown[i + 1][0]['kind'] not in ('chapter', 'toc', 'cover')
            parts.append(self.section(s, depth))
        if self._pending:
            parts.append(self._pending)
        body = '\n'.join(p for p in parts if p)
        if self.mode == 'print' and self.lm != 'en':
            body = mirror_tables(body)
        self.needs_symbols = bool(re.search('[\u2190-\u2bff\U0001F000-\U0001FBFF]', body))
        if self.mode == 'web':
            return self.web_page(body)
        rtl = self.lm != 'en'
        title = escape(self.title_text({'title_ar': self.m['title_ar'], 'title_en': self.m['title_en']}))
        paged = os.path.join(assets_dir(), 'web', 'paged.polyfill.js')
        script = open(paged, encoding='utf-8').read() if os.path.isfile(paged) else ''
        # the page flow stays left-to-right (Paged.js finds where a page overflows reliably only that way);
        # the reading direction is set on the content itself (body.rtl and every Arabic piece)
        return (f'<!DOCTYPE html><html lang="{"ar" if rtl else "en"}" dir="ltr"><head><meta charset="utf-8">'
                f'<title>{title}</title><style>{self.css()}</style></head><body class="{"rtl" if rtl else "ltr"}">{body}'
                f'<script>window.__kmap={json.dumps(self._kmap, separators=(",", ":"))};</script>'
                '<script>window.PagedConfig={auto:true,after:function(f){'
                'var ps=document.querySelectorAll(".pagedjs_page"),skip=0;'
                # «page N of M»: M counts the numbered pages only (no cover or front matter when numbered apart)
                f'ps.forEach(function(p){{if({"true" if self.front_ids else "false"}&&p.classList.contains("pagedjs_front_page"))skip++;'
                f'else if({"true" if self.skip_cover else "false"}&&p.classList.contains("pagedjs_cover_page"))skip++;}});'
                'if(skip){document.querySelectorAll(".pagedjs_pages,:root").forEach(function(e){e.style.setProperty("--pagedjs-page-count",Math.max(1,ps.length-skip));});}'
                'window.__pages=ps.length||1;}};</script>'
                f'<script>{script}</script></body></html>')

    def web_page(self, body):
        rtl = self.lm != 'en'
        m = self.m
        title = escape(self.title_text({'title_ar': m['title_ar'], 'title_en': m['title_en']}))
        nav = []
        for s, d in self.flat:
            if not s['in_toc'] or s['kind'] in ('cover', 'toc') or d > 2:
                continue
            num = self.numbers.get(s['id'])
            nav.append(f'<a class="d{d}" href="#s{s["id"]}">{(num + " ") if num else ""}{escape(self.title_text(s))}</a>')
        logo = f'<img src="{self.asset_uri(m["logo_id"])}" alt="">' if m.get('logo_id') else ''
        langs = ''
        if self.lm in ('bi_side', 'bi_stack'):
            langs = (f'<div class="langs"><button class="on" data-l="both">{LABELS["both"][0]} / {LABELS["both"][1]}</button>'
                     '<button data-l="ar">العربية</button><button data-l="en">English</button></div>')
        js = """
(function(){
 var q=document.getElementById('q'), main=document.querySelector('.sheet');
 var secs=[].slice.call(document.querySelectorAll('.sheet > [id^=s]'));
 function norm(s){return (s||'').toLowerCase().replace(/[أإآ]/g,'ا').replace(/ة/g,'ه').replace(/ى/g,'ي').replace(/[\\u064B-\\u0652\\u0640]/g,'');}
 q&&q.addEventListener('input',function(){var v=norm(q.value.trim());
   secs.forEach(function(s){s.style.display=(!v||norm(s.textContent).indexOf(v)>=0)?'':'none';});
   [].forEach.call(document.querySelectorAll('aside nav a'),function(a){var t=document.querySelector(a.getAttribute('href'));a.style.display=(!t||t.style.display!=='none')?'':'none';});});
 [].forEach.call(document.querySelectorAll('.langs button'),function(b){b.addEventListener('click',function(){
   document.body.classList.remove('only-ar','only-en'); if(b.dataset.l!=='both')document.body.classList.add('only-'+b.dataset.l);
   [].forEach.call(document.querySelectorAll('.langs button'),function(x){x.classList.toggle('on',x===b);});});});
})();"""
        return (f'<!DOCTYPE html><html lang="{"ar" if rtl else "en"}" dir="{"rtl" if rtl else "ltr"}"><head><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>'
                f'<style>{self.css()}{self.web_css()}</style></head><body><div class="layout"><aside>'
                f'<div class="brand">{logo}<b>{title}</b></div><input id="q" type="search" placeholder="{escape(self.L("search"))}" '
                f'aria-label="{escape(self.L("search"))}">{langs}<nav>{"".join(nav)}</nav></aside>'
                f'<main><div class="sheet">{body}</div></main></div><script>{js}</script></body></html>')

    def section(self, s, depth):
        self._sid = s['id']
        kind = s['kind']
        st = s.get('style') or {}
        fn = getattr(self, 'k_' + kind, self.k_text)
        inner = fn(s, depth)
        if inner is None:
            return ''
        if kind in ('cover', 'chapter'):
            return f'<div id="s{s["id"]}" data-sid="{s["id"]}">{inner}</div>' if kind == 'cover' else inner
        num = self.numbers.get(s['id'])
        numh = f'<span class="num">{num}</span>' if num else ''
        status = ''
        if self.workflow and s['status'] != 'approved':
            status = f'<span class="status">{escape(STATUSES.get(s["status"], ("", ""))[0 if self.lm != "en" else 1])}</span>'
        ar, en = escape(s.get('title_ar') or ''), escape(s.get('title_en') or '')
        tbar = '<div class="tbar stitle">' + self.pair(numh + ar + status, numh + en, raw=True) + '</div>'
        if self.mode == 'print' and kind in ('text', 'policy') and not re.sub(r'<[^>]+>|\s', '', inner) \
                and getattr(self, '_next_child', False) and not st.get('bg_id'):
            # a title whose content is its sub-sections goes on the page of the first of them
            self._pending += (f'<div class="tbar stitle ptitle lvl{min(depth, 2)}t" id="s{s["id"]}" data-sid="{s["id"]}">'
                              + self.pair(numh + ar + status, numh + en, raw=True) + '</div>')
            return ''
        pending, self._pending = getattr(self, '_pending', ''), ''
        classes = ['sec', f'lvl{min(depth, 2)}', 'k-' + kind]
        if s['new_page'] or (kind == 'toc'):
            classes.append('newpage')
        if s['id'] in self.front_ids:
            classes.append('front')
        elif st.get('bg_id') and st.get('bg_mode') == 'page':
            classes.append(f'pg{s["id"]}')
        if s['id'] == self.reset_id:
            classes.append('pgreset')
        if self.workflow and self.lay.get('draft_mark') and s['status'] != 'approved':
            classes.append('draft-mark')
        bg = ''
        if st.get('bg_id') and st.get('bg_mode') != 'page':
            classes.append('bg')
            bg = f'<div class="bgimg" style="background-image:url(\'{self.faded_uri(st["bg_id"], st.get("bg_opacity", 0.15), st.get("bg_fit", "cover"))}\')"></div>'
        head = f'{pending}{tbar}<div class="inner">'
        if pending:
            head = f'<div class="keep">{pending}{tbar}</div><div class="inner">'
        if GLUE in inner:                  # the section title never stays alone at the bottom of a page
            first, rest = inner.split(GLUE, 1)
            if first and inner.startswith(first) and len(re.sub(r'<[^>]+>', '', first)) < 1600:
                head = f'<div class="keep">{pending}{tbar}<div class="inner">{first}</div></div><div class="inner">'
                inner = rest
            else:
                inner = inner.replace(GLUE, '')
        return (f'<section class="{" ".join(classes)}" id="s{s["id"]}" data-sid="{s["id"]}"><div class="frame">{bg}{head}'
                f'{inner}</div></div></section>')

    # kinds -----------------------------------------------------------
    def k_cover(self, s, depth):
        m, c = self.m, self.lay['colors']
        cv = self.lay.get('cover') or {}
        rtl = self.lm != 'en'
        wave = ''
        if cv.get('style', 'wave') == 'wave' and not cv.get('bg_id'):
            wave = (f'<svg viewBox="0 0 1000 600" preserveAspectRatio="none" style="position:absolute;inset:0;width:100%;height:100%">'
                    f'<path d="M0,0 H1000 V330 C760,470 560,250 330,360 C190,430 80,410 0,380 Z" fill="{c["secondary"]}" opacity=".5"/>'
                    f'<path d="M0,0 H1000 V290 C760,420 540,210 320,320 C180,390 70,370 0,340 Z" fill="{c["primary"]}"/></svg>')
        elif cv.get('style') == 'band' and not cv.get('bg_id'):
            wave = f'<div style="position:absolute;inset:0 0 45% 0;background:{c["primary"]}"></div>'
        logo = (f'<img src="{self.asset_uri(m["logo_id"])}" alt="" style="position:absolute;top:8%;{"right" if rtl else "left"}:6%;height:16%;'
                'background:#fff;border-radius:3mm;padding:2mm">') if m.get('logo_id') else ''
        title_ar, title_en = escape(m.get('title_ar') or ''), escape(m.get('title_en') or '')
        sub_ar, sub_en = escape(m.get('subtitle_ar') or ''), escape(m.get('subtitle_en') or '')
        ed_ar, ed_en = escape(m.get('edition_ar') or ''), escape(m.get('edition_en') or '')
        org_ar, org_en = escape(m.get('org_ar') or ''), escape(m.get('org_en') or '')
        dark = '#ffffff' if (cv.get('style', 'wave') in ('wave', 'band') and not cv.get('bg_id')) else c['primary']

        def side(ar, en, size, color, weight=700):
            if self.lm == 'ar':
                return f'<div style="font-size:{size}pt;font-weight:{weight};color:{color}">{ar}</div>'
            if self.lm == 'en':
                return f'<div dir="ltr" style="font-size:{size}pt;font-weight:{weight};color:{color}">{en or ar}</div>'
            return (f'<div style="display:flex;direction:ltr;justify-content:space-between;gap:10mm;font-size:{size}pt;font-weight:{weight};color:{color}">'
                    f'<span dir="ltr">{en}</span><span dir="rtl" style="text-align:right">{ar}</span></div>')
        return (f'<div class="cover">{wave}{logo}'
                f'<div style="position:absolute;top:30%;left:6%;right:6%">{side(title_ar, title_en, 30, dark)}'
                f'<div style="height:4mm"></div>{side(sub_ar, sub_en, 15, dark, 400)}</div>'
                f'<div style="position:absolute;bottom:9%;left:6%;right:6%">{side(org_ar, org_en, 14, c["primary"])}'
                f'<div style="height:3mm"></div>{side(ed_ar, ed_en, 12, c["text"], 400)}</div></div>')

    def k_chapter(self, s, depth):
        st = s.get('style') or {}
        num = self.numbers.get(s['id'])
        title = self.pair(((num + ' ') if num else '') + escape(s.get('title_ar') or ''),
                          ((num + ' ') if num else '') + escape(s.get('title_en') or ''), raw=True)
        cls = f'chapter-page pg{s["id"]}' if st.get('bg_id') and st.get('bg_mode') == 'page' else 'chapter-page'
        if s['id'] == self.reset_id:
            cls += ' pgreset'
        bg = ''
        if st.get('bg_id') and st.get('bg_mode') != 'page':
            cls += ' bg'
            bg = f'<div class="bgimg" style="background-image:url(\'{self.faded_uri(st["bg_id"], st.get("bg_opacity", 0.2), st.get("bg_fit", "cover"))}\')"></div>'
        body = self.blocks_html(s)
        if not s['new_page']:
            head = f'<h1 class="chap tbar" style="font-size:1.4em">{title}</h1>'
            if GLUE in body:
                first, body = body.split(GLUE, 1)
                head = f'<div class="keep">{head}{first}</div>'
            return (f'<section class="sec lvl0 k-chapter{" pgreset" if s["id"] == self.reset_id else ""}" id="s{s["id"]}" data-sid="{s["id"]}">'
                    f'{head}{body}</section>')
        return (f'<section class="{cls}" id="s{s["id"]}" data-sid="{s["id"]}">{bg}<div class="inner"><h1 class="chap ctitle">{title}</h1>{body}</div></section>')

    def k_text(self, s, depth):
        return self.blocks_html(s)

    def k_policy(self, s, depth):
        out = [self.blocks_html(s)]
        if self.lay.get('policy_footer'):
            out.append(self.policy_footer(s))
        return ''.join(out)

    def k_disclaimer(self, s, depth):
        meta = self.m.get('meta') or {}
        blocks = self.blocks_html(s)
        if blocks:
            return blocks
        return self.pair(meta.get('disclaimer_ar') or DEFAULT_DISCLAIMER[0], meta.get('disclaimer_en') or DEFAULT_DISCLAIMER[1],
                         'disclaimer')

    def k_doc_control(self, s, depth):
        meta = self.m.get('meta') or {}
        rows = [('prepared', meta.get('prepared_by')), ('reviewed', meta.get('reviewed_by')),
                ('approved', meta.get('approved_by')), ('issue_no', self.m.get('issue_no')),
                ('issue_label', self.m.get('issue_date')), ('first_draft', meta.get('first_draft'))]
        trs = ''.join(f'<tr><td class="k">{escape(self.L(k).rstrip(":"))}</td><td>{escape(v or "")}</td></tr>' for k, v in rows)
        return f'<table class="t meta-table"><tbody>{trs}</tbody></table>' + self.blocks_html(s)

    def k_toc(self, s, depth):
        depth_max = int((s.get('data') or {}).get('depth') or self.lay.get('toc_depth') or 2)
        rows = []
        for x, d in self.flat:
            if not x['in_toc'] or x['kind'] in ('cover', 'toc') or d >= depth_max:
                continue
            num = self.numbers.get(x['id'])
            label = escape(self.title_text(x, '  —  '))
            rows.append(f'<div class="row d{min(d, 2)}"><a class="lbl" href="#s{x["id"]}">{(num + " ") if num else ""}{label}</a>'
                        f'<span class="dots"></span><span class="pg" data-ref="#s{x["id"]}"></span></div>')
        return f'<div class="toc">{"".join(rows)}</div>'

    def k_table(self, s, depth):
        return self.table_html(s.get('data') or {}) + self.blocks_html(s)

    def k_orgchart(self, s, depth):
        d = s.get('data') or {}
        roots = self.db.org_tree(self.m['id'], d.get('root_id'))
        svg = orgchart.render_svg(roots, self.lm, self.lay['colors'], self.lay['fonts']['ar'], int(d.get('depth') or 0),
                                  self.title_text(s))
        if not svg:
            return self.blocks_html(s)
        # an image (not inline SVG): the page layout treats it as one unbreakable piece, scaled to the page
        uri = 'data:image/svg+xml;base64,' + base64.b64encode(self.svg_with_fonts(svg).encode()).decode()
        m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
        w, h = (float(m.group(1)), float(m.group(2))) if m else (800, 500)
        return (f'<div class="org"><img src="{uri}" width="{w:.0f}" height="{h:.0f}" style="aspect-ratio:{w:.0f}/{h:.0f}" '
                f'alt="{escape(self.title_text(s))}"></div>') + self.blocks_html(s)

    def svg_with_fonts(self, svg):
        """An SVG used as an image cannot load fonts from outside: the chart's fonts go inside it."""
        folder = os.path.join(assets_dir(), 'fonts')
        fam = self.lay['fonts']['ar']
        slug = FONTS.get(fam, 'tajawal')
        faces = []
        for weight in (400, 700):
            for sub in ('arabic', 'latin'):
                path = os.path.join(folder, f'{slug}-{sub}-{weight}-normal.woff2')
                if os.path.isfile(path):
                    faces.append(f'@font-face{{font-family:"{fam}";font-weight:{weight};src:url({_b64(open(path, "rb").read(), "font/woff2")})}}')
        if not faces:
            return svg
        i = svg.index('>') + 1
        return svg[:i] + '<style>' + ''.join(faces) + '</style>' + svg[i:]

    def k_compliance(self, s, depth):
        d = s.get('data') or {}
        ctrls = self.db.controls(self.m['id'], section_id=d.get('section_id'))
        en = self.lm == 'en'
        head = ['no', 'code', 'requirement', 'framework', 'owner', 'frequency', 'evidence', 'status']
        th = ''.join(f'<th>{escape(self.L(h))}</th>' for h in head)
        trs = []
        for i, c in enumerate(ctrls, 1):
            req = self.cell({'ar': (c['title_ar'] or '') + (('<br>' + c['requirement_ar']) if c.get('requirement_ar') else ''),
                             'en': (c['title_en'] or '') + (('<br>' + c['requirement_en']) if c.get('requirement_en') else '')})
            stt = CONTROL_STATUSES.get(c['status'], ('', ''))
            trs.append(f'<tr><td class="n">{i}</td><td>{escape(c["code"] or "")}</td><td>{req}</td><td>{escape(c["framework"] or "")}</td>'
                       f'<td>{escape(c["owner"] or "")}</td><td>{escape(c["frequency"] or "")}</td><td>{escape(c["evidence"] or "")}</td>'
                       f'<td>{escape(stt[1] if en else stt[0])}</td></tr>')
        return f'<table class="t"><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table>' + self.blocks_html(s)

    def k_links(self, s, depth):
        return self.blocks_html(s)

    def k_image(self, s, depth):
        return self.blocks_html(s)

    # ── blocks ───────────────────────────────────────────────────────
    def blocks_html(self, s):
        pieces = []                      # (html, kind of block)
        for i, b in enumerate(self.db.blocks(s['id'])):
            self._bref = f'{s["id"]}:{i}'
            h = self.block(b)
            if not h:
                continue
            split = h.split(PIECE) if b['kind'] in ('paragraph', 'bullets', 'numbered', 'heading') else [h.replace(PIECE, '')]
            for j, p in enumerate(split):
                if 'data-b=' not in p[:p.find('>') + 1]:     # every piece names its block (used by the layout check)
                    p = re.sub(r'^<([a-z0-9]+)', lambda m: f'<{m.group(1)} data-b="{self._bref}"', p, count=1)
                pieces.append((p, b['kind'] if j == 0 else 'paragraph'))
        self._bref = None
        if self.mode != 'print':
            return ''.join(p for p, _ in pieces)
        small = ('paragraph', 'bullets', 'numbered', 'quote', 'links')
        out, i = [], 0
        while i < len(pieces):             # a sub-heading stays on the page of what follows it
            p, k = pieces[i]
            if k == 'heading' and i + 1 < len(pieces) and pieces[i + 1][1] in small:
                out.append((f'<div class="keep">{p}{pieces[i + 1][0]}</div>', 'keep'))
                i += 2
                continue
            out.append((p, k))
            i += 1
        if out and out[0][1] in small + ('heading', 'keep', 'callout'):
            return out[0][0] + GLUE + ''.join(p for p, _ in out[1:])
        return ''.join(p for p, _ in out)

    def block(self, b):
        k, d = b['kind'], b.get('data') or {}
        ar, en = b.get('ar') or '', b.get('en') or ''
        if k == 'heading':
            return self.pair(ar, en, 'h-sub')
        if k == 'paragraph':
            return self.pair(ar, en, 'blk')
        if k in ('bullets', 'numbered'):
            tag = 'ul' if k == 'bullets' else 'ol'
            la, le = lines(ar), lines(en)
            if not la and not le:
                return ''
            if self.lm == 'bi_side' and self.mode == 'print':
                return PIECE.join(self.pair(ha, he, 'blk', raw=True) for ha, he in self.list_pieces(tag, la, le))
            ha = f'<{tag}>' + ''.join(f'<li{self.k(clean(x))}>{clean(x)}</li>' for x in la) + f'</{tag}>' if la else ''
            he = f'<{tag}>' + ''.join(f'<li{self.k(clean(x))}>{clean(x)}</li>' for x in le) + f'</{tag}>' if le else ''
            return self.pair(ha, he, 'blk', raw=True)
        if k == 'callout':
            return f'<div class="callout">{self.pair(ar, en)}</div>' if (ar or en) else ''
        if k == 'quote':
            return f'<div class="quote">{self.pair(ar, en)}</div>' if (ar or en) else ''
        if k == 'pagebreak':
            return '<div class="newpage"></div>'
        if k == 'image':
            uri = self.asset_uri(d.get('asset_id'))
            if not uri:
                return ''
            width = int(d.get('width') or 100)
            cap = self.pair(ar, en, 'cap') if (ar or en) else ''
            a = self.db.asset(int(d.get('asset_id')))
            dims = f' width="{a["width"]}" height="{a["height"]}"' if a and a.get('width') and a.get('height') else ''
            return f'<div class="figure"><img src="{uri}"{dims} alt="" style="width:{width}%;height:auto">{cap}</div>'
        if k == 'table':
            return self.table_html(d)
        if k == 'links':
            items = d.get('items') or []
            if not items:
                return ''
            lis = []
            for it in items:
                url = escape(it.get('url') or '', quote=True)
                t = escape(self.title_text({'title_ar': it.get('title_ar'), 'title_en': it.get('title_en')}) or it.get('url') or '')
                note = escape(it.get('note') or '')
                lis.append(f'<li><a href="{url}">{t}</a>' + (f' — <span dir="ltr">{url}</span>' if self.mode == 'print' and url else '')
                           + (f'<div style="color:#55607a">{note}</div>' if note else '') + '</li>')
            return f'<ul class="links">{"".join(lis)}</ul>'
        return self.pair(ar, en, 'blk')

    def list_pieces(self, tag, la, le):
        """A side-by-side list in groups of items, item i of one language level with item i of the other."""
        n = max(len(la), len(le))
        groups, start, size = [], 0, 0
        for i in range(n):
            size += max(len(la[i]) if i < len(la) else 0, len(le[i]) if i < len(le) else 0) + 20
            if size >= CHUNK or i == n - 1:
                groups.append((start, i + 1))
                start, size = i + 1, 0
        out = []
        for a, b in groups:
            st = f' start="{a + 1}"' if tag == 'ol' and a else ''
            ha = (f'<{tag}{st}>' + ''.join(f'<li{self.k(clean(x))}>{clean(x)}</li>' for x in la[a:b]) + f'</{tag}>') if la[a:b] else ''
            he = (f'<{tag}{st}>' + ''.join(f'<li{self.k(clean(x))}>{clean(x)}</li>' for x in le[a:b]) + f'</{tag}>') if le[a:b] else ''
            out.append((ha, he))
        return out

    def cell(self, v):
        if isinstance(v, str):
            return clean(v)
        a, e = clean((v or {}).get('ar') or ''), clean((v or {}).get('en') or '')
        if self.lm == 'ar':
            return a or e
        if self.lm == 'en':
            return e or a
        if a and e and a != e:
            return f'<div class="ar" dir="rtl">{a}</div><div class="en" dir="ltr">{e}</div>'
        return a or e

    def table_html(self, d):
        cols = d.get('columns') or []
        rows = d.get('rows') or []
        if not cols:
            return ''
        numbered = d.get('numbered')
        th = (f'<th>{escape(self.L("no"))}</th>' if numbered else '') + ''.join(f'<th>{self.cell(c)}</th>' for c in cols)
        trs = []
        for i, r in enumerate(rows, 1):
            if not any(((x or {}).get('ar') or (x or {}).get('en')) if isinstance(x, dict) else x for x in r):
                continue
            tds = ''.join(f'<td class="{"first" if j == 0 and d.get("first_col_bold") else ""}"{self.k(c)}>{c}</td>'
                          for j, c in ((j, self.cell(x)) for j, x in enumerate(r[:len(cols)])))
            trs.append(f'<tr>{"<td class=n>" + str(i) + "</td>" if numbered else ""}{tds}</tr>')
        cap = ''
        if d.get('caption_ar') or d.get('caption_en'):
            cap = f'<div class="h-sub">{self.pair(d.get("caption_ar"), d.get("caption_en"))}</div>'
        cls = 't' + (' split' if d.get('split_rows') else '') + (' compact' if d.get('compact') else '')
        scale = int(d.get('scale') or 100)
        attrs = (f' style="font-size:{0.92 * scale / 100:.3f}em"' if scale != 100 else '') + \
            (f' data-b="{self._bref}"' if self._bref else '')
        return f'{cap}<table class="{cls}"{attrs}><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table>'

    def policy_footer(self, s):
        meta = s.get('meta') or {}
        out = []
        resp = self.title_text({'title_ar': meta.get('responsible_ar'), 'title_en': meta.get('responsible_en')})
        info = []
        if meta.get('effective_date'):
            info.append(f'{escape(self.L("effective"))}: {escape(meta["effective_date"])}')
        if s.get('next_review'):
            info.append(f'{escape(self.L("next_review"))}: {escape(s["next_review"])}')
        out.append(f'<table class="t"><tbody><tr><td class="k" style="width:30%;background:#eef3fb;font-weight:700">'
                   f'{escape(self.L("responsible"))}</td><td>{escape(resp or "")}</td></tr>'
                   + (f'<tr><td colspan="2" style="color:#55607a">{" · ".join(info)}</td></tr>' if info else '')
                   + '</tbody></table>')
        revs = self.db.revisions(s['id'])
        body = ''.join(f'<tr><td>{escape(r["version"])}</td><td>{escape(r["rev_date"])}</td>'
                       f'<td>{self.cell({"ar": r["changes_ar"], "en": r["changes_en"]})}</td><td>{escape(r["by_name"] or "")}</td></tr>'
                       for r in revs) or '<tr><td>&nbsp;</td><td></td><td></td><td></td></tr>'
        out.append(f'<div class="history"><div class="cap">{escape(self.L("history"))}</div><table class="t"><thead><tr>'
                   f'<th>{escape(self.L("version"))}</th><th>{escape(self.L("date"))}</th><th>{escape(self.L("changes"))}</th>'
                   f'<th>{escape(self.L("by"))}</th></tr></thead><tbody>{body}</tbody></table></div>')
        return ''.join(out)


def build_html(db, manual_id, mode='print', embed=None, only=None, workflow=False):
    return Renderer(db, manual_id, mode, embed=(mode == 'web') if embed is None else embed, only=only,
                    workflow=workflow).render()

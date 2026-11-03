"""Bringing an existing manual in: Word (.docx), a web page (.html) or a PDF.

Each importer produces the same structure — a list of sections ``{'level', 'title_ar', 'title_en', 'blocks'}`` —
that ``add_to_manual`` then writes into a manual (under a chosen section). Everything imported is ordinary content
that can be edited afterwards.

* Word: headings (Heading 1–3 / Title) start sections; paragraphs, lists, tables, images and links come over with
  their bold/italic/underline; a two-column table whose one column is Arabic and the other English (the common
  layout of bilingual manuals) becomes Arabic/English pairs.
* HTML: h1–h3 start sections; p, lists, tables, images (embedded or next to the file) and links.
* PDF: the text of every page with its position and size: large or bold short lines become headings, an English
  column on the left and an Arabic one on the right become pairs, the repeated header and footer are dropped, and the
  Arabic letters are put back in reading order. Pages chosen by the user can also come in as images (charts, scans).
"""
import base64

import os
import re
import unicodedata
from html import escape as _escape


def escape(text, quote=False):
    """Text as HTML without turning quotes into character references (they are plain text)."""
    return _escape(text, quote=quote)


AR = re.compile(r'[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]')
LATIN = re.compile(r'[A-Za-z]')


def is_arabic(text):
    a = len(AR.findall(text or ''))
    lat = len(LATIN.findall(text or ''))
    return a > 0 and a >= lat


def _new(level, title_ar='', title_en=''):
    return {'level': level, 'title_ar': title_ar, 'title_en': title_en, 'blocks': []}


def _title_split(text):
    """«Arabic — English» or a single-language title → (ar, en)."""
    text = (text or '').strip()
    parts = [p.strip() for p in re.split(r'\s+[—–/|]\s+|\t+', text) if p.strip()]
    if len(parts) >= 2:
        ar = ' '.join(p for p in parts if is_arabic(p))
        en = ' '.join(p for p in parts if not is_arabic(p))
        return ar, en
    return (text, '') if is_arabic(text) else ('', text)


def _add_text(sec, kind, text, html=None):
    """Adds text to the right side: an Arabic piece fills an open English one of the same kind and vice versa."""
    html = html if html is not None else escape(text)
    side = 'ar' if is_arabic(text) else 'en'
    other = 'en' if side == 'ar' else 'ar'
    b = sec['blocks'][-1] if sec['blocks'] else None
    if b and b['kind'] == kind and not b.get(side) and b.get(other) and kind != 'table':
        b[side] = html
    else:
        sec['blocks'].append({'kind': kind, side: html, other: ''})


# ── Word ─────────────────────────────────────────────────────────────────────────────────────────────
def _docx_inline(p):
    from docx.oxml.ns import qn
    out = []
    for child in p._p.iterchildren():
        tag = child.tag.split('}')[-1]
        if tag == 'r':
            out.append(_docx_run_html(child))
        elif tag == 'hyperlink':
            rid = child.get(qn('r:id'))
            href = ''
            if rid and rid in p.part.rels:
                href = p.part.rels[rid].target_ref
            inner = ''.join(_docx_run_html(r) for r in child.iterchildren() if r.tag.split('}')[-1] == 'r')
            out.append(f'<a href="{escape(href, quote=True)}">{inner}</a>' if href.startswith(('http', 'mailto')) else inner)
    return ''.join(out).strip()


def _docx_run_html(r):
    from docx.oxml.ns import qn
    text = ''.join((t.text or '') if t.tag.split('}')[-1] == 't' else ('\n' if t.tag.split('}')[-1] in ('br', 'cr') else
                   ('\t' if t.tag.split('}')[-1] == 'tab' else '')) for t in r.iter() if t.tag.split('}')[-1] in ('t', 'br', 'cr', 'tab'))
    if not text:
        return ''
    h = escape(text).replace('\n', '<br>')
    rpr = r.find(qn('w:rPr'))
    if rpr is not None:
        def on(tag):
            el = rpr.find(qn(f'w:{tag}'))
            return el is not None and el.get(qn('w:val')) not in ('0', 'false', 'none')
        if on('b') or on('bCs'):
            h = f'<b>{h}</b>'
        if on('i') or on('iCs'):
            h = f'<i>{h}</i>'
        if on('u'):
            h = f'<u>{h}</u>'
    return h


def _docx_images(p, doc):
    from docx.oxml.ns import qn
    out = []
    for blip in p._p.iter(qn('a:blip')):
        rid = blip.get(qn('r:embed'))
        if rid and rid in doc.part.related_parts:
            part = doc.part.related_parts[rid]
            out.append((part.blob, part.content_type))
    return out



def _key(text):
    """Comparable form of a title: letters only, word order ignored (converted files sometimes reverse Arabic words)."""
    t = unicodedata.normalize('NFKC', text or '').lower()
    t = re.sub(r'[\u064B-\u0652\u0640\uf0b7•●▪:：\-–—_.,;()\[\]"\'’]', ' ', t)
    for a, b in (('أ', 'ا'), ('إ', 'ا'), ('آ', 'ا'), ('ة', 'ه'), ('ى', 'ي')):
        t = t.replace(a, b)
    words = sorted(w for w in t.split() if w)
    return ' '.join(words)


def _index_entries(doc):
    """Titles listed in the document's own index table (title | page | title), with their level. Only the index
    at the start of the document counts (later tables with numbers are content)."""
    entries = []
    for t in _front_tables(doc):
        rows = [[c.text.strip() for c in r.cells] for r in t.rows]
        if len(rows) < 4 or len(rows[0]) < 2:
            continue
        nums = sum(1 for r in rows if any(re.fullmatch(r'\d{1,4}', c) for c in r))
        if nums < len(rows) / 3:
            continue
        for r in rows:
            cells = [c for c in r if c and not re.fullmatch(r'\d{1,4}', c)]
            if not cells or any(k in ' '.join(cells) for k in ('Page No', 'رقم الصفحة')):
                continue
            ar = next((c for c in cells if is_arabic(c)), '')
            en = next((c for c in cells if not is_arabic(c)), '')
            sub = ar.startswith(('\uf0b7', '•')) or en.startswith(('\uf0b7', '•'))
            has_page = any(re.fullmatch(r'\d{1,4}', c) for c in r)
            entries.append({'ar': re.sub(r'^[\uf0b7•\s]+', '', ar), 'en': re.sub(r'^[\uf0b7•\s]+', '', en),
                            'level': 2 if sub else 1, 'chapter': not has_page})
    return entries


def import_docx(path):
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    doc = Document(path)
    sections = [_new(1, *_title_split(os.path.splitext(os.path.basename(path))[0]))]
    images = []
    body = doc.element.body
    entries = _index_entries(doc)
    lookup = {}
    for i, e in enumerate(entries):
        for k in {_key(e['ar']), _key(e['en'])}:
            if k and len(k) > 3:
                lookup.setdefault(k, []).append(i)
    current_entry = [None]
    last_hit = [-1]

    def match_title(text):
        """Index entry that ``text`` is the title of (in the index order), 'same' for the current one, or None."""
        if not lookup or len(text) >= 160:
            return None
        cands = list(lookup.get(_key(text), []))
        if '\t' in text:
            for x in text.split('\t'):
                cands += lookup.get(_key(x), [])
        if not cands:
            return None
        if current_entry[0] in cands:
            return 'same'
        ahead = sorted(c for c in cands if c > last_hit[0])
        if ahead and ahead[0] - last_hit[0] <= 12:
            current_entry[0] = last_hit[0] = ahead[0]
            return ahead[0]
        return None
    # the elements themselves are kept: lxml reuses the identity of an element nobody holds
    index_tables = [t._tbl for t in _front_tables(doc)]
    for child in body.iterchildren():
        tag = child.tag.split('}')[-1]
        if tag == 'p':
            p = Paragraph(child, doc)
            for blob, mime in _docx_images(p, doc):
                images.append((blob, mime))
                sections[-1]['blocks'].append({'kind': 'image', 'ar': '', 'en': '', 'data': {'asset': len(images) - 1, 'width': 80}})
            text = p.text.strip()
            if not text:
                continue
            style = (p.style.name if p.style is not None else '') or ''
            # a paragraph that is one of the titles in the document's index starts that section
            m = match_title(text)
            if m == 'same':
                continue
            if m is not None:
                e = entries[m]
                sections.append(_new(e['level'], e['ar'], e['en']))
                continue
            bold_runs = [r for r in p.runs if r.text.strip()]
            big_bold = bold_runs and all(r.bold for r in bold_runs) and len(text) < 90 and \
                any((r.font.size and r.font.size.pt >= 13) for r in bold_runs)
            if big_bold and 'Heading' not in style:
                _add_text(sections[-1], 'heading', text, escape(text))
                continue
            m = re.match(r'(Heading|عنوان)\s*(\d)', style)
            if style == 'Title' or m:
                level = 1 if style == 'Title' else min(int(m.group(2)), 3)
                ar, en = _title_split(text)
                cur = sections[-1]
                if not cur['blocks'] and cur['level'] == level and (not cur['title_ar'] or not cur['title_en']) and \
                        ((ar and not cur['title_ar']) or (en and not cur['title_en'])) and len(sections) > 1:
                    cur['title_ar'] = cur['title_ar'] or ar          # a heading repeated in the other language
                    cur['title_en'] = cur['title_en'] or en
                else:
                    sections.append(_new(level, ar, en))
                    current_entry[0] = None
                continue
            html = _docx_inline(p) or escape(text)
            is_list = 'List' in style or p._p.pPr is not None and p._p.pPr.numPr is not None
            if is_list:
                kind = 'numbered' if 'Number' in style else 'bullets'
                b = sections[-1]['blocks'][-1] if sections[-1]['blocks'] else None
                side = 'ar' if is_arabic(text) else 'en'
                if b and b['kind'] == kind:
                    b[side] = (b.get(side) + '\n' if b.get(side) else '') + html
                else:
                    sections[-1]['blocks'].append({'kind': kind, side: html, ('en' if side == 'ar' else 'ar'): ''})
            else:
                _add_text(sections[-1], 'paragraph', text, html)
        elif tag == 'tbl':
            t = Table(child, doc)
            if any(t._tbl is x for x in index_tables):
                continue                                       # the old index: the program builds its own
            rows = [[c for c in r.cells] for r in t.rows]
            if not rows:
                continue
            ncols = max(len(r) for r in rows)
            if ncols == 2 and _bilingual_columns(rows):
                for r in rows:
                    _pair_cells(sections, r[0], r[1], doc, match_title, entries)
                continue
            cols = [{'ar': c.text.strip(), 'en': ''} if is_arabic(c.text) else {'ar': '', 'en': c.text.strip()} for c in rows[0]]
            data_rows = []
            for r in rows[1:]:
                data_rows.append([{'ar': c.text.strip(), 'en': ''} if is_arabic(c.text) else {'ar': '', 'en': c.text.strip()} for c in r])
            sections[-1]['blocks'].append({'kind': 'table', 'ar': '', 'en': '',
                                           'data': {'columns': cols, 'rows': data_rows, 'numbered': False}})
    if len(sections) > 1 and not sections[0]['blocks']:
        sections.pop(0)
    sections, images = drop_decorations(sections, images)
    return merge_language_runs(sections), images


def drop_decorations(sections, images):
    """Images repeated on many pages (header bands, the logo of every page of a converted PDF) and tiny glyphs
    (bullet arrows) are dropped; identical images are kept once."""
    import hashlib
    from collections import Counter
    keys = [hashlib.md5(b).hexdigest() for b, _ in images]
    counts = Counter(keys)
    keep, remap = [], {}
    for i, (b, m) in enumerate(images):
        w, h = image_size(b) if m != 'image/svg+xml' else (100, 100)
        if counts[keys[i]] >= 3 or (w and h and (w < 40 or h < 24)):
            continue
        if keys[i] in remap.values():
            remap[i] = next(j for j, k in remap.items() if k == keys[i])
            continue
        remap[i] = keys[i]
    index = {}
    for i, k in remap.items():
        if isinstance(k, str):
            index[i] = len(keep)
            keep.append(images[i])
    for i, k in remap.items():
        if not isinstance(k, str):
            index[i] = index[k]
    for sec in sections:
        out = []
        for b in sec['blocks']:
            if b['kind'] == 'image':
                a = (b.get('data') or {}).get('asset')
                if a not in index:
                    continue
                b = dict(b, data=dict(b['data'], asset=index[a]))
            out.append(b)
        sec['blocks'] = out
    return sections, keep


def merge_language_runs(sections):
    """In a converted bilingual document the English column often comes first and the Arabic one after it:
    «Purpose, Scope» then «الغاية، النطاق». A run of English-only sections followed by a run of Arabic-only sections
    of the same level (or the reverse) is joined pairwise into bilingual sections."""
    def lang(s):
        if s['title_ar'] and not s['title_en']:
            return 'ar'
        if s['title_en'] and not s['title_ar']:
            return 'en'
        return None
    out, i = [], 0
    while i < len(sections):
        a = sections[i]
        la = lang(a)
        if not la:
            out.append(a)
            i += 1
            continue
        j = i
        while j < len(sections) and lang(sections[j]) == la and sections[j]['level'] == a['level']:
            j += 1
        k = j
        other = 'en' if la == 'ar' else 'ar'
        while k < len(sections) and lang(sections[k]) == other and sections[k]['level'] == a['level']:
            k += 1
        first, second = sections[i:j], sections[j:k]
        if not second:
            out.extend(first)
            i = j
            continue
        n = min(len(first), len(second))
        out.extend(first[:len(first) - n])
        for x, y in zip(first[len(first) - n:], second[:n]):
            ar_s, en_s = (x, y) if la == 'ar' else (y, x)
            merged = _new(x['level'], ar_s['title_ar'], en_s['title_en'])
            merged['blocks'] = _zip_blocks(ar_s['blocks'], en_s['blocks'])
            out.append(merged)
        out.extend(second[n:])
        i = k
    return out


def _zip_blocks(ar_blocks, en_blocks):
    """Pairs the Arabic blocks with the English ones in order (same kinds side by side, the rest as they are)."""
    out = []
    ia = ie = 0
    while ia < len(ar_blocks) or ie < len(en_blocks):
        a = ar_blocks[ia] if ia < len(ar_blocks) else None
        e = en_blocks[ie] if ie < len(en_blocks) else None
        if a and e and a['kind'] == e['kind'] and a['kind'] in ('paragraph', 'heading', 'bullets', 'numbered', 'quote') \
                and a.get('ar') and not a.get('en') and e.get('en') and not e.get('ar'):
            out.append(dict(a, en=e['en']))
            ia += 1
            ie += 1
        elif a and (not e or ia * max(1, len(en_blocks)) <= ie * max(1, len(ar_blocks))):
            out.append(a)
            ia += 1
        else:
            out.append(e)
            ie += 1
    return out


def _front_tables(doc):
    """The index tables at the start: consecutive number-bearing tables before the first long text."""
    out, started = [], False
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    for child in doc.element.body.iterchildren():
        tag = child.tag.split('}')[-1]
        if tag == 'tbl':
            t = Table(child, doc)
            if _is_index_table(t):
                out.append(t)
                started = True
            elif started:
                break
        elif tag == 'p' and started and len(Paragraph(child, doc).text.strip()) > 200:
            break
    return out


def _is_index_table(t):
    rows = [[c.text.strip() for c in r.cells] for r in t.rows]
    if len(rows) < 4:
        return False
    nums = sum(1 for r in rows if any(re.fullmatch(r'\d{1,4}', c) for c in r))
    return nums >= len(rows) / 3


def _bilingual_columns(rows):
    a = sum(len(AR.findall(r[0].text)) for r in rows if len(r) > 1)
    b = sum(len(AR.findall(r[1].text)) for r in rows if len(r) > 1)
    la = sum(len(LATIN.findall(r[0].text)) for r in rows if len(r) > 1)
    lb = sum(len(LATIN.findall(r[1].text)) for r in rows if len(r) > 1)
    return (a > la and lb > b) or (b > lb and la > a)


def _pair_cells(sections, c1, c2, doc, match_title=None, entries=()):
    ar_cell, en_cell = (c1, c2) if is_arabic(c1.text) else (c2, c1)
    pa = [p for p in ar_cell.paragraphs if p.text.strip()]
    pe = [p for p in en_cell.paragraphs if p.text.strip()]
    if match_title:                     # titles from the document's index start sections, in either column
        def split(ps):
            groups, cur = [], []
            for p in ps:
                m = match_title(p.text.strip())
                if m is not None and m != 'same':
                    groups.append((cur, None))
                    cur = []
                    groups.append(([], m))
                elif m == 'same':
                    continue
                else:
                    cur.append(p)
            groups.append((cur, None))
            return groups
        # English column first (it decides the sections), the Arabic column is matched to the same titles
        ge = split(pe)
        title_ids = [m for _, m in ge if m is not None]
        if title_ids:
            # the Arabic titles are the same entries: drop them from the Arabic column
            keys = {_key(entries[i]['ar']) for i in title_ids}
            pa_groups, cur = [], []
            for p in pa:
                if _key(p.text) in keys:
                    pa_groups.append(cur)
                    cur = []
                else:
                    cur.append(p)
            pa_groups.append(cur)
            k = 0
            for g, m in ge:
                if m is not None:
                    e = entries[m]
                    sections.append(_new(e['level'], e['ar'], e['en']))
                    continue
                ga = pa_groups[k] if k < len(pa_groups) else []
                k += 1
                _pair_paragraphs(sections[-1], ga, g)
            for rest in pa_groups[k:]:
                _pair_paragraphs(sections[-1], rest, [])
            return
    _pair_paragraphs(sections[-1], pa, pe)


def _pair_paragraphs(sec, pa, pe):
    for i in range(max(len(pa), len(pe))):
        a = pa[i] if i < len(pa) else None
        e = pe[i] if i < len(pe) else None
        ref = a if a is not None else e
        runs_ = [r for r in ref.runs if r.text.strip()]
        bold = runs_ and all(r.bold for r in runs_) and len(ref.text) < 90
        kind = 'heading' if bold else 'paragraph'
        sec['blocks'].append({'kind': kind, 'ar': _docx_inline(a) if a else '', 'en': _docx_inline(e) if e else ''})


# ── HTML ─────────────────────────────────────────────────────────────────────────────────────────────
def import_html(path):
    import lxml.html
    raw = open(path, 'rb').read()
    m = re.search(rb'charset=["\']?([\w-]+)', raw[:4096], re.I)
    try:
        text = raw.decode(m.group(1).decode() if m else 'utf-8')
    except (LookupError, UnicodeDecodeError):
        text = raw.decode('utf-8', 'replace')          # pages without a declared encoding are read as UTF-8
    text = re.sub(r'^\s*<\?xml[^>]*>', '', text)
    root = lxml.html.fromstring(text)
    for bad in root.xpath('//script|//style|//nav|//noscript|//aside|//input'):
        bad.drop_tree()
    title = (root.findtext('.//title') or os.path.splitext(os.path.basename(path))[0]).strip()
    sections = [_new(1, *_title_split(title))]
    images = []
    folder = os.path.dirname(os.path.abspath(path))
    body = root.find('.//body') if root.find('.//body') is not None else root

    def inline(el):
        from .richtext import clean
        return clean(lxml.html.tostring(el, encoding='unicode'))

    def img(el):
        src = el.get('src') or ''
        data = mime = None
        if src.startswith('data:'):
            m = re.match(r'data:([^;]+);base64,(.*)', src, re.S)
            if m:
                mime, data = m.group(1), base64.b64decode(m.group(2))
        elif not re.match(r'^[a-z]+://', src):
            p = os.path.join(folder, src.split('?')[0])
            if os.path.isfile(p):
                data = open(p, 'rb').read()
                ext = os.path.splitext(p)[1].lower()
                mime = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif',
                        '.svg': 'image/svg+xml', '.webp': 'image/webp'}.get(ext)
        if data and mime:
            images.append((data, mime))
            sections[-1]['blocks'].append({'kind': 'image', 'ar': '', 'en': escape(el.get('alt') or ''),
                                           'data': {'asset': len(images) - 1, 'width': 80}})

    def walk(el):
        for ch in el:
            tag = ch.tag if isinstance(ch.tag, str) else ''
            text = ' '.join((ch.text_content() if tag else '').split())
            cls = (ch.get('class') or '') if tag else ''
            if tag in ('h1', 'h2', 'h3', 'h4') or (tag in ('div', 'span') and re.search(r'\b(tbar|title|heading)\b', cls)
                                                     and text and len(text) < 160):
                if text:
                    if tag.startswith('h'):
                        level = min(int(tag[1]), 3)
                    else:
                        level = 1 if 'lvl0' in (ch.getparent().getparent().get('class') or '') else 2
                    parts = [' '.join(x.text_content().split()) for x in ch.iter() if isinstance(x.tag, str)
                             and x.get('dir') in ('rtl', 'ltr') and x.text_content().strip()]
                    ar = ' '.join(x for x in parts if is_arabic(x))
                    en = ' '.join(x for x in parts if not is_arabic(x))
                    sections.append(_new(level, *((ar, en) if parts else _title_split(text))))
            elif tag in ('p', 'blockquote', 'pre'):
                for im in ch.iter('img'):
                    img(im)
                if text:
                    _add_text(sections[-1], 'quote' if tag == 'blockquote' else 'paragraph', text, inline(ch))
            elif tag in ('ul', 'ol'):
                items = [' '.join(li.text_content().split()) for li in ch.findall('li')]
                items = [i for i in items if i]
                if items:
                    _add_text(sections[-1], 'bullets' if tag == 'ul' else 'numbered', ' '.join(items), '\n'.join(escape(i) for i in items))
            elif tag == 'table':
                rows = [[' '.join(c.text_content().split()) for c in tr.findall('./th') + tr.findall('./td')]
                        for tr in ch.iter('tr')]
                rows = [r for r in rows if any(r)]
                if rows:
                    def cell(v):
                        return {'ar': v, 'en': ''} if is_arabic(v) else {'ar': '', 'en': v}
                    sections[-1]['blocks'].append({'kind': 'table', 'ar': '', 'en': '',
                                                   'data': {'columns': [cell(v) for v in rows[0]],
                                                            'rows': [[cell(v) for v in r] for r in rows[1:]]}})
            elif tag == 'img':
                img(ch)
            elif tag in ('div', 'section', 'article', 'main', 'header', 'footer', 'span', 'body', 'figure', 'aside'):
                if any(isinstance(c.tag, str) and c.tag in ('p', 'h1', 'h2', 'h3', 'h4', 'ul', 'ol', 'table', 'div', 'section', 'img', 'figure', 'main', 'article', 'aside', 'header', 'footer')
                       for c in ch):
                    walk(ch)
                elif text:
                    _add_text(sections[-1], 'paragraph', text, inline(ch))
    walk(body)
    if len(sections) > 1 and not sections[0]['blocks']:
        sections.pop(0)
    return sections, images


# ── PDF ──────────────────────────────────────────────────────────────────────────────────────────────
_LATIN_RUN = re.compile(r'[0-9A-Za-z][0-9A-Za-z.,:/\-%#&@()\'’]*(?:\s+[0-9A-Za-z.,:/\-%#&@()\'’]+)*')


def fix_arabic(text):
    """Arabic taken from a PDF: presentation forms → letters, visual order → reading order, broken lam-alef."""
    t = unicodedata.normalize('NFKC', text)
    if is_arabic(t) and _looks_reversed(t):
        t = t[::-1]
        t = _LATIN_RUN.sub(lambda m: m.group(0)[::-1], t)
        t = t.translate(str.maketrans('()[]{}', ')(][}{'))
    for a, b in (('األ', 'الأ'), ('اإل', 'الإ'), ('اآل', 'الآ'), ('اال', 'الا'), ('إال', 'إلا')):
        t = t.replace(a, b)
    t = re.sub(r'(?<![؀-ۿ])ال(?![؀-ۿ])', 'لا', t)
    return re.sub(r'\s+', ' ', t).strip()


def slanted(chars):
    """Most letters of a line turned (a diagonal watermark): pdfminer's «upright» is false only past 90°."""
    def turned(c):
        a, b, cc, d = c.matrix[:4]
        return not c.upright or abs(b) > 0.08 * max(abs(a), 1e-6) or abs(cc) > 0.08 * max(abs(d), 1e-6)
    return bool(chars) and sum(1 for c in chars if turned(c)) > len(chars) / 2


PAGE_NO_RE = re.compile(r'(Page|P a g e|صفحة|الصفحة)?\s*[-–]?\s*\d+\s*[-–]?\s*((\||/|من|of)\s*\d+)?', re.I)

_LTR = re.compile(r'[A-Za-z0-9٠-٩۰-۹@#%&_+=]')
_MIRROR = str.maketrans('()[]{}<>«»', ')(][}{><»«')


def line_from_chars(chars):
    """A PDF line put in reading order from where each letter actually sits on the page, not from the order the
    file stores them in (some files keep Arabic in display order, others in reading order; the positions are the
    same in both). Each stored glyph stays whole, so a lam-alef ligature keeps its two letters in their order.
    ``chars``: [(x0, x1, size, text)]."""
    if not chars:
        return ''
    cells = sorted(chars, key=lambda c: (round(c[0], 1), c[1]))
    units = []                                   # visual order, left to right, with spaces from the gaps
    prev = None
    for x0, x1, size, txt in cells:
        if prev is not None and x0 - prev > max(1.0, size * 0.18) and units and units[-1] != ' ':
            units.append(' ')
        if txt.strip() or not units or units[-1] != ' ':
            units.append(txt if txt.strip() else ' ')
        prev = max(prev or x1, x1)
    vis = ''.join(units)
    if not AR.search(vis):
        return re.sub(r'\s+', ' ', vis).strip()
    units.reverse()                              # right to left …
    out, i = [], 0
    while i < len(units):                        # … except runs of Latin letters and digits, which read left to right
        u = units[i]
        if _LTR.search(u):
            j = i
            while j + 1 < len(units) and (_LTR.search(units[j + 1]) or (units[j + 1] in '.,:/-' and j + 2 < len(units)
                                                                       and _LTR.search(units[j + 2]))
                                          or (units[j + 1] == ' ' and j + 2 < len(units) and LATIN.search(units[j + 2])
                                              and LATIN.search(u))):
                j += 1
            out.extend(reversed(units[i:j + 1]))
            i = j + 1
        else:
            out.append(u.translate(_MIRROR) if len(u) == 1 else u)
            i += 1
    text = unicodedata.normalize('NFKC', ''.join(out))
    return re.sub(r'\s+', ' ', text).strip()


def merge_line_pieces(frags):
    """Pieces of one printed line that the PDF reader split apart (around numbers or brackets inside Arabic text) are
    joined again; an English column beside an Arabic one stays apart."""
    frags = sorted(frags, key=lambda f: (-round(f['y1'], 0), f['x0']))
    out = []
    for f in frags:
        size = max(c.size for c in f['chars'])
        joined = False
        for g in out:
            gsize = max(c.size for c in g['chars'])
            same_line = abs(g['y0'] - f['y0']) < 0.45 * max(size, gsize) and abs(g['y1'] - f['y1']) < 0.6 * max(size, gsize)
            gap = max(f['x0'] - g['x1'], g['x0'] - f['x1'])
            if not same_line or gap > 3.5 * max(size, gsize):
                continue
            a_f, a_g = bool(AR.search(f['raw'])), bool(AR.search(g['raw']))
            l_f, l_g = bool(LATIN.search(f['raw'])), bool(LATIN.search(g['raw']))
            if (a_f and l_g and not a_g) or (a_g and l_f and not a_f):
                if gap > 1.2 * max(size, gsize):            # an English column beside an Arabic one
                    continue
            g['chars'] = g['chars'] + f['chars']
            g['x0'], g['x1'] = min(g['x0'], f['x0']), max(g['x1'], f['x1'])
            g['y0'], g['y1'] = min(g['y0'], f['y0']), max(g['y1'], f['y1'])
            g['raw'] = g['raw'] + ' ' + f['raw']
            joined = True
            break
        if not joined:
            out.append(dict(f))
    return out


_COMMON = ('ال', 'في', 'من', 'على', 'إلى', 'الى', 'أن', 'عن', 'مع', 'هذا', 'هذه')


def _looks_reversed(t):
    words = re.findall(r'[؀-ۿ]+', t)
    if not words:
        return False
    fwd = sum(1 for w in words if w.startswith('ال') or w in _COMMON)
    rev = sum(1 for w in words if w.endswith('لا') or w[::-1] in _COMMON)
    return rev > fwd


def import_pdf(path, pages=None, image_pages=(), auto_images=True, page_looks=None, drop=None):
    """pages: page numbers (1-based) to read (None = all); image_pages: pages brought in as pictures.
    ``page_looks``: {page: design key} (pdf_look): where the design changes inside a section, a page break that
    carries the new design is put in, and every section notes the design of its first page («_look»).
    ``auto_images``: a page with almost no text (a scan, a drawing, a chart) comes in as a whole-page picture, so
    nothing on it is lost and a scanned file opens as it is."""
    image_pages = set(image_pages or ())
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTChar, LTTextContainer, LTTextLine
    lines_by_page = []
    sizes = []
    want = [p - 1 for p in pages] if pages else None
    for pno, pg in enumerate(extract_pages(path, page_numbers=want, laparams=LAParams(line_margin=0.4)), 1):
        W, H = pg.width, pg.height
        frags = []
        for el in pg:
            if not isinstance(el, LTTextContainer):
                continue
            for ln in el:
                if not isinstance(ln, LTTextLine):
                    continue
                chars = [c for c in ln if isinstance(c, LTChar)]
                if slanted(chars):
                    continue                    # علامة مائية مائلة: تبقى في تصميم الصفحة لا في النص
                if chars and ln.get_text().strip():
                    frags.append({'x0': ln.x0, 'x1': ln.x1, 'y0': ln.y0, 'y1': ln.y1, 'chars': chars, 'raw': ln.get_text()})
        out = []
        for f in merge_line_pieces(frags):
            chars, raw = f['chars'], f['raw'].strip()
            size = round(max(c.size for c in chars), 1)
            bold = sum(1 for c in chars if 'bold' in c.fontname.lower()) > len(chars) / 2
            if re.fullmatch(r'(\S\s){3,}\S?.*', raw):          # «P a g e  7» → «Page 7»
                raw = re.sub(r'(?<=\S) (?=\S)', '', raw)
            if AR.search(raw):
                text = line_from_chars([(c.x0, c.x1, c.size, c.get_text()) for c in chars]) or fix_arabic(raw)
            else:
                text = re.sub(r'\s+', ' ', raw)
            out.append({'x0': f['x0'] / W, 'x1': f['x1'] / W, 'y': 1 - f['y1'] / H, 'size': size, 'bold': bold, 'text': text,
                        'lh': size / H})
            sizes.append(size)
        out.sort(key=lambda r: (round(r['y'], 3), -r['x1'] if is_arabic(r['text']) else r['x0']))
        real = pages[pno - 1] if pages else pno
        if auto_images and sum(len(r['text']) for r in out) < 60:
            image_pages.add(real)
        lines_by_page.append((real, out))
    if not sizes and not image_pages:
        return [], []
    sizes = sizes or [10]
    body = sorted(sizes)[len(sizes) // 2]
    # header and footer: lines in the top/bottom band that repeat on many pages
    from collections import Counter
    rep = Counter()
    for _, ls in lines_by_page:
        for r in ls:
            if r['y'] < 0.12 or r['y'] > 0.9:
                rep[re.sub(r'\d+', '#', r['text'])] += 1
    many = max(2, len(lines_by_page) // 3)
    fname = _title_split(os.path.splitext(os.path.basename(path))[0])
    first_sec = _new(1, '', '')
    first_sec['_untitled'] = fname
    sections = [first_sec]
    images = []

    def weight(sec):
        return len(sec['blocks']) + len(sec.get('title_ar') or '') + len(sec.get('title_en') or '') + \
            sum(len(b.get('ar') or '') + len(b.get('en') or '') for b in sec['blocks'])

    # a page whose text ends well above where the pages' text usually ends was broken there on purpose: the page
    # after it starts a new page here too
    ends = {}
    for pno, ls in lines_by_page:
        body_ls = [r for r in ls if 0.12 <= r['y'] <= 0.9]
        if body_ls and pno not in image_pages:
            ends[pno] = max(r['y'] for r in body_ls)
    usual = sorted(ends.values())[int(len(ends) * 0.9)] if len(ends) >= 3 else None
    limit = max(0.73, (usual or 0) - 0.15)
    early = {pno for pno, y in ends.items() if y < limit}
    state = {'look': None, 'break': False}

    def add_block(blk):
        """Adds a block to the current section; the first block of a page whose design differs from the page
        before it comes after a page break that carries the design (or starts the section with it)."""
        sec = sections[-1]
        key = state.get('want')
        if state['break']:
            state['break'] = False
            if sec['blocks'] and sec['blocks'][-1]['kind'] != 'pagebreak' and (key is None or key == state['look']):
                sec['blocks'].append({'kind': 'pagebreak', 'ar': '', 'en': ''})
            elif not sec['blocks']:
                sec['_new_page'] = True
        if key is not None:
            if not sec['blocks']:
                sec.setdefault('_look', key)
            elif key != state['look']:
                sec['blocks'].append({'kind': 'pagebreak', 'ar': '', 'en': '', 'style': {'page_look': key}})
            state['look'] = key
            state['want'] = None
        sec['blocks'].append(blk)

    def one_page(pno, ls):
        state['want'] = (page_looks or {}).get(pno)
        if pno in image_pages:
            png = render_pdf_page(path, pno)
            if png:
                images.append((png, 'image/png'))
                state['want'] = None             # a whole page as it is: no design of the pages around it
                first = len(sections) == 1 and not sections[0]['blocks']
                into = sections[-1]
                if not into['blocks'] and into.get('_untitled') and len(sections) > 1:
                    into = sections[-2]              # more whole pages straight after the cover stay with it
                into['blocks'].append({'kind': 'image', 'ar': '', 'en': '', 'data': {'asset': len(images) - 1, 'width': 100},
                                               'style': {'fullpage': True}})
                if first and pno != lines_by_page[-1][0]:
                    # the file opens with this page (its cover): what follows has its own section, with no printed
                    # heading unless the page has one
                    nxt = _new(1, '', '')
                    nxt['_untitled'] = fname
                    sections.append(nxt)
            return
        ls = [r for r in ls if not ((r['y'] < 0.12 or r['y'] > 0.9) and rep[re.sub(r'\d+', '#', r['text'])] >= many)]
        ls = [r for r in ls if not PAGE_NO_RE.fullmatch(r['text'])]
        gone = (drop or {}).get(pno)
        if gone:                                 # part of the page design (pdf_look): stays in the picture
            ls = [r for r in ls if not any(re.sub(r'\s+', '', r['text']) == t and abs(r['y'] - y) < 0.012 for t, y in gone)]
        # paragraphs: consecutive lines of the same language, size and column
        para = None
        for r in ls:
            ar = is_arabic(r['text'])
            heading = r['size'] >= body * 1.18 or (r['bold'] and len(r['text']) < 70 and r['size'] >= body)
            big = r['size'] >= body * 1.45
            if big:
                ar_t, en_t = (r['text'], '') if ar else ('', r['text'])
                cur = sections[-1]
                if not cur['blocks'] and ((ar_t and not cur['title_ar']) or (en_t and not cur['title_en'])) and \
                        (len(sections) > 1 or cur.get('_untitled')):
                    cur['title_ar'] = cur['title_ar'] or ar_t
                    cur['title_en'] = cur['title_en'] or en_t
                else:
                    sections.append(_new(1 if r['size'] >= body * 1.7 else 2, ar_t, en_t))
                    if state['break']:
                        sections[-1]['_new_page'] = True
                        state['break'] = False
                    if state.get('want') is not None or state['look'] is not None:
                        sections[-1]['_look'] = state['want'] if state.get('want') is not None else state['look']
                        state['look'] = sections[-1]['_look']
                        state['want'] = None
                para = None
                continue
            kind = 'heading' if heading else 'paragraph'
            bullet = re.match(r'^[•●▪◦\-–]\s*', r['text'])
            text = r['text'][bullet.end():] if bullet else r['text']
            if bullet:
                kind = 'bullets'
            side = 'ar' if ar else 'en'
            # the next line of the same paragraph: no wider gap than its lines so far (a paragraph break leaves more)
            dy = r['y'] - para['y'] if para else 0
            pitch = para.get('pitch') if para else None
            if para and para['kind'] == kind == 'paragraph' and para['side'] == side and para['size'] == r['size'] \
                    and 0 < dy and (dy <= pitch * 1.3 if pitch else dy <= r['lh'] * 2.0):
                para['block'][side] += ' ' + text
                para['pitch'] = pitch or dy
                para['y'] = r['y']
                continue
            if para and kind == 'bullets' and para['kind'] == 'bullets' and para['side'] == side:
                para['block'][side] += '\n' + text
                para['y'] = r['y']
                continue
            # a line at the same height in the other language completes the open block (side-by-side layout)
            blk = None
            for b in reversed(sections[-1]['blocks'][-4:]):
                if b['kind'] == kind and not b.get(side) and b.get('ar' if side == 'en' else 'en') and \
                        abs(b.get('_y', -1) - r['y']) < 0.03:
                    blk = b
                    break
            if blk is None:
                blk = {'kind': kind, 'ar': '', 'en': '', '_y': r['y']}
                add_block(blk)
            blk[side] = escape(text)
            para = {'kind': kind, 'side': side, 'size': r['size'], 'y': r['y'], 'block': blk}

    prev = None
    for pno, ls in lines_by_page:
        before = {id(x): weight(x) for x in sections}
        state['break'] = prev in early
        one_page(pno, ls)
        prev = pno
        for x in sections:                       # من أي صفحات جاء كل قسم (لتصميم صفحاته واتجاهها)
            d = weight(x) - before.get(id(x), 0)
            if d > 0:
                x.setdefault('_pages', Counter())[pno] += d
    for s in sections:
        for b in s['blocks']:
            b.pop('_y', None)
    sections = [s for s in sections if s['blocks'] or s.get('title_ar') or s.get('title_en') or s is sections[0]]
    if len(sections) > 1 and not sections[0]['blocks']:
        sections.pop(0)
    return sections, images


def render_pdf_page(path, page_no, dpi=150):
    """One page of a PDF as PNG bytes (Qt's PDF module)."""
    try:
        from PySide6.QtCore import QBuffer, QIODevice, QSize
        from PySide6.QtPdf import QPdfDocument
    except ImportError:
        return None
    doc = QPdfDocument()
    if doc.load(path) != QPdfDocument.Error.None_:
        return None
    if not 1 <= page_no <= doc.pageCount():
        return None
    pt = doc.pagePointSize(page_no - 1)
    img = _on_white(doc.render(page_no - 1, QSize(int(pt.width() * dpi / 72), int(pt.height() * dpi / 72))))
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, 'PNG')
    return bytes(buf.data())


def _on_white(img):
    """A drawn PDF page has a see-through ground; paper is white."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    out = QImage(img.size(), QImage.Format_RGB32)
    out.fill(Qt.white)
    p = QPainter(out)
    p.drawImage(0, 0, img)
    p.end()
    return out


def import_images(paths):
    """Pictures (a scanned page, a poster, a chart): each one a whole page."""
    sec = _new(1, *_title_split(os.path.splitext(os.path.basename(paths[0]))[0]))
    images = []
    mimes = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.bmp': 'image/bmp', '.gif': 'image/gif',
             '.webp': 'image/webp'}
    for p in paths:
        with open(p, 'rb') as f:
            images.append((f.read(), mimes.get(os.path.splitext(p)[1].lower(), 'image/png')))
        sec['blocks'].append({'kind': 'image', 'ar': '', 'en': '', 'data': {'asset': len(images) - 1, 'width': 100},
                              'style': {'fullpage': True}})
    return [sec], images


def import_text(path):
    """A plain text file: an empty line separates paragraphs; each goes to the side of its language."""
    for enc in ('utf-8-sig', 'cp1256', 'latin-1'):
        try:
            with open(path, encoding=enc) as f:
                text = f.read()
            break
        except UnicodeDecodeError:
            continue
    sec = _new(1, *_title_split(os.path.splitext(os.path.basename(path))[0]))
    for para in re.split(r'\n\s*\n', text):
        para = para.strip()
        if para:
            sec['blocks'].append({'kind': 'paragraph', 'ar': escape(para) if is_arabic(para) else '',
                                  'en': '' if is_arabic(para) else escape(para)})
    return [sec], []


OPENABLE = {'.docx': 'Word', '.pdf': 'PDF', '.html': 'HTML', '.htm': 'HTML', '.txt': 'TXT', '.png': 'PNG',
            '.jpg': 'JPG', '.jpeg': 'JPG', '.bmp': 'BMP', '.gif': 'GIF', '.webp': 'WEBP'}


def read_any(path, pdf_pages=None, image_pages=(), page_looks=None, drop=None):
    """Any supported file: (sections, images). Raises ValueError with a readable reason."""
    ext = os.path.splitext(path)[1].lower()
    if ext == '.doc':
        raise ValueError('صيغة Word القديمة (.doc) غير مقروءة: احفظ الملف من Word بصيغة .docx ثم افتحه.\n'
                         'The old Word format (.doc) cannot be read: save it from Word as .docx, then open it.')
    if ext not in OPENABLE:
        raise ValueError('نوع الملف غير مدعوم. الأنواع المدعومة: Word (.docx) وPDF وصفحة ويب (.html) ونص (.txt) والصور.\n'
                         'Unsupported file type. Supported: Word (.docx), PDF, web page (.html), text (.txt) and pictures.')
    if ext == '.docx':
        return import_docx(path)
    if ext in ('.html', '.htm'):
        return import_html(path)
    if ext == '.pdf':
        return import_pdf(path, pdf_pages, image_pages, page_looks=page_looks, drop=drop)
    if ext == '.txt':
        return import_text(path)
    return import_images([path])


def file_orientation(path):
    """The direction most pages of the file have ('portrait' or 'landscape'), or None when it cannot be told."""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == '.pdf':
            from pdfminer.pdfpage import PDFPage
            wide = tall = 0
            with open(path, 'rb') as f:
                for i, pg in enumerate(PDFPage.get_pages(f)):
                    if i >= 60:
                        break
                    x0, y0, x1, y1 = pg.mediabox
                    w, h = abs(x1 - x0), abs(y1 - y0)
                    if (pg.attrs.get('Rotate') or 0) % 180:
                        w, h = h, w
                    wide, tall = wide + (w > h), tall + (w <= h)
            return None if not (wide or tall) else ('landscape' if wide > tall else 'portrait')
        if ext == '.docx':
            from docx import Document
            sec = Document(path).sections[0]
            return 'landscape' if sec.page_width > sec.page_height else 'portrait'
        if ext in ('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.webp'):
            with open(path, 'rb') as f:
                w, h = image_size(f.read())
            return None if not w else ('landscape' if w > h else 'portrait')
    except Exception:  # noqa: BLE001 — the default direction is kept
        return None
    return None


def pdf_page_count(path):
    try:
        from pdfminer.pdfpage import PDFPage
        with open(path, 'rb') as f:
            return sum(1 for _ in PDFPage.get_pages(f))
    except Exception:   # noqa: BLE001
        return 0


# ── writing into a manual ────────────────────────────────────────────────────────────────────────────
def image_size(data):
    try:
        from PySide6.QtGui import QImage
        img = QImage()
        img.loadFromData(data)
        return (img.width(), img.height()) if not img.isNull() else (None, None)
    except ImportError:
        return None, None


def add_to_manual(db, manual_id, sections, images, parent_id=None, kind='text'):
    """Writes imported sections under ``parent_id``; levels become the tree. Returns the new section ids."""
    asset_ids = []
    for i, (data, mime) in enumerate(images):
        w, h = image_size(data) if mime != 'image/svg+xml' else (None, None)
        asset_ids.append(db.add_asset(f'imported-{i + 1}', data, mime, 'image', w, h))
    stack = [(0, parent_id)]
    created = []
    for s in sections:
        lvl = max(1, int(s.get('level') or 1))
        while stack and stack[-1][0] >= lvl:
            stack.pop()
        parent = stack[-1][1] if stack else parent_id
        row = {'manual_id': manual_id, 'parent_id': parent, 'kind': kind,
               'title_ar': s.get('title_ar') or '', 'title_en': s.get('title_en') or '', 'title_placeholder': None}
        if s.get('_new_page'):
            row['new_page'] = 1
        if s.get('_untitled') and not (row['title_ar'] or row['title_en']):
            # pages without a heading: the file name names them in the contents, and nothing is printed above them
            row['title_ar'], row['title_en'] = s['_untitled']
            row['style'] = {'no_title': True}
        sid = db.save_section(row)
        blocks = []
        for b in s['blocks']:
            b = dict(b)
            d = dict(b.get('data') or {})
            if 'asset' in d:
                d['asset_id'] = asset_ids[d.pop('asset')]
            b['data'] = d
            blocks.append(b)
        db.replace_blocks(sid, blocks)
        created.append(sid)
        stack.append((lvl, sid))
    return created

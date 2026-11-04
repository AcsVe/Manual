"""Font, size, text colour and highlight applied to more than one block at once — the formatting bar's «apply to»:
the block, the section, chosen sections, a range of pages or the whole manual, with optional filters (paragraphs
only, sub-headings or tables; Arabic or English only). ``plan`` counts what will change before anything does,
``apply`` writes it and returns what ``doctor.undo`` needs to put everything back.

A look is {'font', 'pt', 'color', 'bg'} (any of them). For both languages it is kept in the block's style itself;
for one language under ``style['ar']`` / ``style['en']``. A table section keeps it in ``data['look']``. The PDF, the
preview and Word read the same keys (``html.side_look``, ``docx_export.write_runs``)."""
from .html import LOOK_KEYS
from .tablefit import snapshot

SCOPES = {
    'selection': ('النص المحدد', 'The selected text'),
    'block': ('الكتلة', 'The block'),
    'section': ('القسم', 'The section'),
    'sections': ('أقسام مختارة…', 'Chosen sections…'),
    'pages': ('نطاق صفحات', 'A range of pages'),
    'manual': ('الدليل كله', 'The whole manual'),
}
KINDS = {
    'all': ('كل المحتوى', 'All the content'),
    'paragraphs': ('الفقرات فقط', 'Paragraphs only'),
    'headings': ('العناوين فقط', 'Sub-headings only'),
    'tables': ('الجداول فقط', 'Tables only'),
}
LANGS = {'both': ('العربي والإنجليزي', 'Arabic and English'), 'ar': ('العربي فقط', 'Arabic only'),
         'en': ('الإنجليزي فقط', 'English only')}
PARAGRAPH_KINDS = ('paragraph', 'bullets', 'numbered', 'callout', 'quote')
TEXT_KINDS = ('heading',) + PARAGRAPH_KINDS
KIND_FILTER = {'all': TEXT_KINDS + ('table',), 'paragraphs': PARAGRAPH_KINDS, 'headings': ('heading',),
               'tables': ('table',)}


def section_ids(db, manual_id, scope, current=None, chosen=None):
    """The sections a scope reaches (pages are worked out from the measured layout: see ``page_refs``)."""
    if scope in ('block', 'section'):
        return [current] if current else []
    if scope == 'sections':
        return list(chosen or [])
    return [s['id'] for s, _d in db.flat(manual_id, active_only=False)]


def page_refs(pmap, first, last):
    """(block refs {(sid, index)}, sections {sid}) with something on pages ``first``…``last`` of a measured layout
    (``pdf.AUDIT_JS``'s ``pmap``, one entry per page)."""
    blocks, sections = set(), set()
    for page in (pmap or [])[max(0, first - 1):max(0, last)]:
        for r in page.get('b') or []:
            try:
                sid, b = r.split(':')
                blocks.add((int(sid), int(b)))
            except ValueError:
                continue
        sections.update(int(x) for x in page.get('s') or [])
    return blocks, sections


def targets(db, manual_id, scope, kinds='all', current=None, block=None, chosen=None, pages=None):
    """What a scope and a filter reach: [('b', sid, index)] for blocks and [('s', sid)] for table sections.
    ``block``: the block index for the «block» scope; ``pages``: the (blocks, sections) of ``page_refs``."""
    allowed = KIND_FILTER.get(kinds, KIND_FILTER['all'])
    out = []
    sids = section_ids(db, manual_id, scope, current, chosen)
    if scope == 'pages' and pages is not None:
        sids = sorted({sid for sid, _b in pages[0]} | set(pages[1]))
    for sid in sids:
        s = db.section(sid)
        if not s:
            continue
        if s['kind'] == 'table' and 'table' in allowed and scope != 'block' and \
                (scope != 'pages' or pages is None or sid in pages[1]):
            out.append(('s', sid))
        for i, b in enumerate(db.blocks(sid)):
            if scope == 'block' and i != block:
                continue
            if b['kind'] not in allowed:
                continue
            if b['kind'] == 'table' and not (b.get('data') or {}).get('columns'):
                continue
            if scope == 'pages' and pages is not None and (sid, i) not in pages[0]:
                continue
            out.append(('b', sid, i))
    return out


def set_look(style, look, lang='both'):
    """A block's style with the look on it. For both languages the look is the block's own and any look kept for
    one language only is dropped for the same keys (the latest choice shows); for one language it goes under it.
    An empty value («as the manual») removes that key."""
    st = dict(style or {})
    if lang in ('ar', 'en'):
        side = dict(st.get(lang) or {})
        for k, v in look.items():
            if v in (None, ''):
                side.pop(k, None)
            else:
                side[k] = v
        if side:
            st[lang] = side
        else:
            st.pop(lang, None)
        return st
    for k, v in look.items():
        if v in (None, ''):
            st.pop(k, None)
        else:
            st[k] = v
        if k == 'pt':
            st.pop('size', None)           # a size in points replaces a size in per cent
        for sd in ('ar', 'en'):
            if isinstance(st.get(sd), dict):
                st[sd] = {x: y for x, y in st[sd].items() if x != k}
                if not st[sd]:
                    st.pop(sd)
    return st


def plan(db, refs):
    """How many blocks and table sections, in how many sections, will change."""
    blocks = sum(1 for r in refs if r[0] == 'b')
    tables = sum(1 for r in refs if r[0] == 's')
    sections = len({r[1] for r in refs})
    return {'blocks': blocks, 'tables': tables, 'sections': sections, 'total': blocks + tables}


def apply(db, manual_id, refs, look, lang='both'):
    """Writes the look on every target. Returns (how many changed, undo data for ``doctor.undo``)."""
    look = {k: v for k, v in (look or {}).items() if k in LOOK_KEYS}
    if not refs or not look:
        return 0, None
    undo = snapshot(db, manual_id, {r[1] for r in refs})
    by_sec = {}
    for r in refs:
        by_sec.setdefault(r[1], []).append(r)
    n = 0
    for sid, rs in by_sec.items():
        idx = {r[2] for r in rs if r[0] == 'b'}
        if idx:
            bl = [dict(b) for b in db.blocks(sid)]
            for i in idx:
                if i < len(bl):
                    bl[i]['style'] = set_look(bl[i].get('style'), look, lang)
                    n += 1
            db.replace_blocks(sid, [{k: v for k, v in b.items() if k not in ('id', 'section_id', 'sort')} for b in bl])
        if any(r[0] == 's' for r in rs):
            s = db.section(sid)
            data = dict(s.get('data') or {})
            data['look'] = set_look(data.get('look'), look, lang)
            db.save_section({'data': data}, sid)
            n += 1
    db.audit('format_apply', manual=manual_id, changed=n)
    return n, undo

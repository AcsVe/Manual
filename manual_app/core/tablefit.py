"""Tables that do not fit the page: measured after the pages are laid out, and made to fit in steps that stop at the
first one that is enough — tighter cells, then a smaller font, then long words broken, then a landscape page of
their own. Also «fix all the tables» of the checker page: the plan shown before anything changes, and one undo for
the whole run (``snapshot`` keeps what was there; ``doctor.undo`` puts it back).

A table is named by a reference: ``('b', section id, block index)`` for a table block, ``('s', section id)`` for a
table section (its table in the section's data)."""
import copy

from .templates import layout_with_defaults

STEPS = ('compact', 'smaller', 'break', 'landscape')
STEP_NAMES = {
    'compact': ('تضييق الخلايا', 'Tighter cells'),
    'smaller': ('تصغير الخط', 'Smaller font'),
    'break': ('كسر الكلمات الطويلة', 'Long words broken'),
    'landscape': ('صفحة أفقية', 'Landscape page'),
}
SMALL_SCALE = 80             # the table's font, in % of the manual's table font, at the «smaller» step


def has_step(d, step, sec_style=None):
    if step == 'compact':
        return bool(d.get('compact'))
    if step == 'smaller':
        return int(d.get('scale') or 100) <= SMALL_SCALE
    if step == 'break':
        return bool(d.get('break_words'))
    if step == 'landscape':
        return bool(d.get('landscape')) or (sec_style or {}).get('orientation') == 'landscape'
    return False


def level(d, sec_style=None):
    """How many steps the table has taken (0–4): the first step not taken counts."""
    for i, step in enumerate(STEPS):
        if not has_step(d, step, sec_style):
            return i
    return len(STEPS)


def next_step(d, layout, sec_style=None):
    """The next step not taken yet, or None (a landscape page needs a portrait manual)."""
    for step in STEPS:
        if has_step(d, step, sec_style):
            continue
        if step == 'landscape' and layout_with_defaults(layout)['orientation'] == 'landscape':
            return None
        return step
    return None


def apply_step(d, step):
    """One step on a table's data (a table section's landscape page is set on the section: see ``step_table``)."""
    if step == 'compact':
        d['compact'] = True
    elif step == 'smaller':
        d['scale'] = min(int(d.get('scale') or 100), SMALL_SCALE)
    elif step == 'break':
        d['break_words'] = True
    elif step == 'landscape':
        d['landscape'] = True


def set_level(d, n):
    """The table's fitting as chosen by hand in the editor: the first ``n`` steps on, the others off."""
    on = STEPS[:n]
    d['compact'] = 'compact' in on or None
    d['break_words'] = 'break' in on or None
    d['landscape'] = 'landscape' in on or None
    if 'smaller' in on:
        d['scale'] = min(int(d.get('scale') or 100), SMALL_SCALE)
    elif int(d.get('scale') or 100) == SMALL_SCALE:
        d['scale'] = 100
    for k in ('compact', 'break_words', 'landscape'):
        if not d.get(k):
            d.pop(k, None)
    if d.get('scale') == 100:
        d.pop('scale', None)


# ── a table in the database ────────────────────────────────────────────
def table_of(db, ref):
    """(data, section) of a referenced table; None when it is gone."""
    if ref[0] == 'b':
        bl = db.blocks(ref[1])
        if ref[2] < len(bl) and bl[ref[2]]['kind'] == 'table':
            return bl[ref[2]].get('data') or {}, db.section(ref[1])
        return None
    s = db.section(ref[1])
    return ((s.get('data') or {}), s) if s and s['kind'] == 'table' else None


def step_table(db, manual_id, ref):
    """The next step on one table, written to the database. Returns the step taken, or None when none is left."""
    got = table_of(db, ref)
    if not got:
        return None
    d, sec = got
    lay = db.manual(manual_id)['layout']
    st = (sec.get('style') or {}) if ref[0] == 's' else None
    step = next_step(d, lay, st)
    if step is None:
        return None
    if ref[0] == 'b':
        bl = [dict(b) for b in db.blocks(ref[1])]
        data = dict(bl[ref[2]].get('data') or {})
        apply_step(data, step)
        bl[ref[2]]['data'] = data
        db.replace_blocks(ref[1], [{k: v for k, v in b.items() if k not in ('id', 'section_id', 'sort')} for b in bl])
    elif step == 'landscape':
        db.save_section({'style': dict(st, orientation='landscape')}, ref[1])
    else:
        data = dict(d)
        apply_step(data, step)
        db.save_section({'data': data}, ref[1])
    return step


def fit(db, manual_id, refs, measure, progress=None):
    """Makes the referenced tables fit, step by step: after each step the pages are measured again
    (``measure(section ids)`` → the references of the tables still cut off) and a table that fits stops there.
    Returns ({ref: last step taken}, [refs still cut off after the last step])."""
    pending = list(dict.fromkeys(refs))
    taken = {}
    for _round in STEPS:
        if not pending:
            break
        moved = []
        for ref in pending:
            step = step_table(db, manual_id, ref)
            if step:
                taken[ref] = step
                moved.append(ref)
        if progress:
            progress(_round, len(moved))
        if not moved:
            break
        still = set(measure(sorted({r[1] for r in moved})))
        pending = [r for r in moved if r in still]
    return taken, pending


def clipped_refs(db, audit):
    """The tables a page measurement (``pdf.audit_blocking``) found cut off: wider than the page, or a word wider
    than its cell."""
    out = []
    for it in audit.get('items') or []:
        if it.get('t') not in ('x', 'cell'):
            continue
        if it.get('b'):
            sid, b = (int(v) for v in it['b'].split(':'))
            bl = db.blocks(sid)
            if b < len(bl) and bl[b]['kind'] == 'table':
                out.append(('b', sid, b))
        elif it.get('sid') and (db.section(it['sid']) or {}).get('kind') == 'table':
            out.append(('s', it['sid']))
    return list(dict.fromkeys(out))


def measure_clipped(db, manual_id, sids=None, timeout_s=300, progress=None, workflow=False):
    """Lays out the given sections (all when None) and returns the tables cut off in them."""
    from .html import build_html
    from .pdf import audit_blocking, page_size_mm
    html = build_html(db, manual_id, 'print', only=sids, workflow=workflow)
    audit = audit_blocking(html, page_size_mm(db.manual(manual_id)), timeout_s, progress)
    return clipped_refs(db, audit)


def ref_of(issue):
    return ('b', issue['sid'], issue['b']) if issue.get('b') is not None else ('s', issue['sid'])


# ── one undo for a whole run ─────────────────────────────────────────────
def snapshot(db, manual_id, sids):
    """What the sections hold now, in the form ``doctor.undo`` puts back."""
    undo = {'manual': manual_id, 'blocks': {}, 'sections': {}, 'layout': None, 'new_sections': [], 'assets': {}}
    for sid in sorted(set(sids)):
        s = db.section(sid)
        if not s:
            continue
        undo['blocks'][sid] = copy.deepcopy(db.blocks(sid))
        undo['sections'][sid] = {'data': copy.deepcopy(s.get('data')), 'style': copy.deepcopy(s.get('style')),
                                 'new_page': s.get('new_page')}
    return undo


def table_sections(db, manual_id):
    """The sections that hold a table (a table section, or a table block)."""
    out = []
    for s, _d in db.flat(manual_id):
        if s['kind'] == 'table' or any(b['kind'] == 'table' for b in db.blocks(s['id'])):
            out.append(s['id'])
    return out


def plan(issues):
    """«Fix all the tables»: what will change, before anything does — {rule: count} of the table points with a fix,
    and the number of tables they touch."""
    counts, tables = {}, set()
    for x in issues:
        if x['cat'] == 'tables' and x.get('fix') and not x.get('locked'):
            counts[x['rule']] = counts.get(x['rule'], 0) + 1
            tables.add(ref_of(x))
    return counts, tables

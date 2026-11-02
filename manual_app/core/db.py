"""Local SQLite database (one file in the data folder). Schema changes are numbered migrations applied at start-up;
nothing is ever dropped.

Model
-----
* manuals   — one row per manual (the school manual, a teacher handbook…): titles, issue data and the layout (JSON).
* sections  — the manual's tree (parent_id). ``kind`` says how a section is drawn: cover, disclaimer, doc_control,
              toc, chapter (a divider page), text, policy, table, orgchart, compliance, links, image.
              ``meta`` holds the policy fields (responsible, prepared/reviewed/approved by, dates…),
              ``data`` the kind's own data (table columns/rows, org-chart root…), ``style`` the backgrounds.
* blocks    — the content of a section: heading, paragraph, bullets, numbered, table, image, callout, links,
              quote, pagebreak — each with an Arabic and an English side.
* assets    — images (logos, backgrounds, pictures) stored inside the database, so a backup holds everything.
* org_units — the organisational structure (a tree of units and positions) drawn as charts.
* controls  — the compliance register: requirements, owners, evidence, status and review dates.
* revisions — the change history of every section (printed at its end).
* users / approvals — the optional workflow (prepare → review → approve)."""
import json
import os
import shutil
import sqlite3
from datetime import date, datetime

MIGRATIONS = [
    # 1 — initial schema
    """
    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS manuals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title_ar TEXT NOT NULL, title_en TEXT, subtitle_ar TEXT, subtitle_en TEXT,
        org_ar TEXT, org_en TEXT, logo_id INTEGER, issue_no TEXT, issue_date TEXT, edition_ar TEXT, edition_en TEXT,
        confidential INTEGER NOT NULL DEFAULT 0, layout TEXT NOT NULL DEFAULT '{}', meta TEXT NOT NULL DEFAULT '{}',
        is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS sections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        manual_id INTEGER NOT NULL REFERENCES manuals(id),
        parent_id INTEGER REFERENCES sections(id),
        sort INTEGER NOT NULL DEFAULT 0, kind TEXT NOT NULL DEFAULT 'text', code TEXT,
        title_ar TEXT, title_en TEXT, in_toc INTEGER NOT NULL DEFAULT 1, new_page INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'draft', version TEXT NOT NULL DEFAULT '1.0',
        review_date TEXT, next_review TEXT,
        meta TEXT NOT NULL DEFAULT '{}', data TEXT NOT NULL DEFAULT '{}', style TEXT NOT NULL DEFAULT '{}',
        is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS ix_sections_manual ON sections (manual_id, parent_id, sort);
    CREATE TABLE IF NOT EXISTS blocks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        section_id INTEGER NOT NULL REFERENCES sections(id),
        sort INTEGER NOT NULL DEFAULT 0, kind TEXT NOT NULL DEFAULT 'paragraph',
        ar TEXT, en TEXT, data TEXT NOT NULL DEFAULT '{}', style TEXT NOT NULL DEFAULT '{}');
    CREATE INDEX IF NOT EXISTS ix_blocks_section ON blocks (section_id, sort);
    CREATE TABLE IF NOT EXISTS assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'image', mime TEXT NOT NULL, data BLOB NOT NULL,
        width INTEGER, height INTEGER, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS org_units (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        manual_id INTEGER NOT NULL REFERENCES manuals(id),
        parent_id INTEGER REFERENCES org_units(id),
        sort INTEGER NOT NULL DEFAULT 0, kind TEXT NOT NULL DEFAULT 'position',
        name_ar TEXT NOT NULL, name_en TEXT, holder TEXT, color TEXT, link TEXT NOT NULL DEFAULT 'solid',
        summary_ar TEXT, summary_en TEXT, is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS controls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        manual_id INTEGER NOT NULL REFERENCES manuals(id),
        section_id INTEGER REFERENCES sections(id),
        code TEXT, title_ar TEXT NOT NULL, title_en TEXT, requirement_ar TEXT, requirement_en TEXT,
        framework TEXT, owner TEXT, frequency TEXT, evidence TEXT, status TEXT NOT NULL DEFAULT 'open',
        last_review TEXT, next_review TEXT, notes TEXT, is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS revisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        section_id INTEGER NOT NULL REFERENCES sections(id),
        version TEXT NOT NULL, rev_date TEXT NOT NULL, changes_ar TEXT, changes_en TEXT, by_name TEXT,
        created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, username TEXT NOT NULL UNIQUE, password TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'author', is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS approvals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        section_id INTEGER NOT NULL REFERENCES sections(id),
        action TEXT NOT NULL, by_name TEXT, note TEXT, at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, action TEXT NOT NULL, details TEXT);
    """,
]

SECTION_KINDS = {
    'cover': ('صفحة الغلاف', 'Cover page'),
    'disclaimer': ('تنويه السرية', 'Confidentiality notice'),
    'doc_control': ('توثيق إعداد الدليل', 'Document control'),
    'toc': ('الفهرس', 'Table of contents'),
    'chapter': ('باب (صفحة فاصلة)', 'Chapter (divider page)'),
    'text': ('محتوى', 'Content'),
    'policy': ('سياسة وإجراءات', 'Policy & procedures'),
    'table': ('جدول / مصفوفة / خطة', 'Table / matrix / plan'),
    'orgchart': ('هيكل تنظيمي', 'Organisational chart'),
    'compliance': ('سجل الالتزام', 'Compliance register'),
    'links': ('روابط ومراجع', 'Links & references'),
    'image': ('صفحة صورة', 'Image page'),
}
BLOCK_KINDS = {
    'heading': ('عنوان فرعي', 'Sub-heading'), 'paragraph': ('فقرة', 'Paragraph'),
    'bullets': ('قائمة نقطية', 'Bulleted list'), 'numbered': ('قائمة مرقّمة', 'Numbered list'),
    'table': ('جدول', 'Table'), 'image': ('صورة', 'Image'), 'callout': ('مربع تنبيه', 'Callout box'),
    'links': ('روابط', 'Links'), 'quote': ('اقتباس', 'Quote'), 'pagebreak': ('فاصل صفحة', 'Page break'),
}
STATUSES = {'draft': ('مسودة', 'Draft'), 'review': ('قيد المراجعة', 'In review'),
            'approved': ('معتمد', 'Approved'), 'archived': ('مؤرشف', 'Archived')}
CONTROL_STATUSES = {'open': ('لم يُقيَّم', 'Not assessed'), 'compliant': ('ملتزم', 'Compliant'),
                    'partial': ('التزام جزئي', 'Partially compliant'), 'non': ('غير ملتزم', 'Non-compliant'),
                    'na': ('لا ينطبق', 'Not applicable')}
ROLES = {'admin': ('مدير', 'Administrator'), 'author': ('معِدّ', 'Author'), 'reviewer': ('مراجِع', 'Reviewer'),
         'approver': ('معتمِد', 'Approver'), 'viewer': ('اطّلاع فقط', 'Viewer')}


def now():
    return datetime.now().isoformat(timespec='seconds')


def today():
    return date.today().isoformat()


def _j(v, default):
    if v is None or v == '':
        return default
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except ValueError:
        return default


class Database:
    def __init__(self, path):
        self.path = path
        folder = os.path.dirname(os.path.abspath(path))
        os.makedirs(folder, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys = ON')
        self.conn.execute('PRAGMA journal_mode = WAL')
        self._migrate()

    def _migrate(self):
        self.conn.execute('CREATE TABLE IF NOT EXISTS schema_version (v INTEGER NOT NULL)')
        row = self.conn.execute('SELECT v FROM schema_version').fetchone()
        current = row['v'] if row else 0
        for i, sql in enumerate(MIGRATIONS, 1):
            if i > current:
                self.conn.executescript(sql)
                self.conn.execute('DELETE FROM schema_version')
                self.conn.execute('INSERT INTO schema_version (v) VALUES (?)', (i,))
                self.conn.commit()

    def close(self):
        try:
            self.conn.close()
        except sqlite3.Error:
            pass

    # ── settings / audit ─────────────────────────────────────────────
    def get(self, key, default=None):
        r = self.conn.execute('SELECT value FROM settings WHERE key = ?', (key,)).fetchone()
        return r['value'] if r and r['value'] is not None else default

    def set(self, key, value):
        self.conn.execute('INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value',
                          (key, None if value is None else str(value)))
        self.conn.commit()

    def audit(self, action, **details):
        self.conn.execute('INSERT INTO audit (at, action, details) VALUES (?, ?, ?)',
                          (now(), action, json.dumps(details, ensure_ascii=False)))
        self.conn.commit()

    def audit_rows(self, limit=500):
        return [dict(r) for r in self.conn.execute('SELECT * FROM audit ORDER BY id DESC LIMIT ?', (limit,))]

    # ── generic helpers ──────────────────────────────────────────────
    @staticmethod
    def _row(r, json_cols=()):
        if r is None:
            return None
        d = dict(r)
        for c in json_cols:
            if c in d:
                d[c] = _j(d[c], [] if c == 'rows' else {})
        return d

    def _save(self, table, data, row_id=None, json_cols=(), stamp=True):
        data = dict(data)
        for c in json_cols:
            if c in data and not isinstance(data[c], str):
                data[c] = json.dumps(data[c], ensure_ascii=False)
        cols = [r['name'] for r in self.conn.execute(f'PRAGMA table_info({table})')]
        if stamp and 'updated_at' in cols:
            data['updated_at'] = now()
        data = {k: v for k, v in data.items() if k in cols and k != 'id'}
        if row_id:
            if data:
                self.conn.execute(f'UPDATE {table} SET {", ".join(f"{k} = ?" for k in data)} WHERE id = ?',
                                  (*data.values(), row_id))
        else:
            if 'created_at' in cols:
                data.setdefault('created_at', now())
            if 'updated_at' in cols:
                data.setdefault('updated_at', now())
            cur = self.conn.execute(f'INSERT INTO {table} ({", ".join(data)}) VALUES ({", ".join("?" * len(data))})',
                                    tuple(data.values()))
            row_id = cur.lastrowid
        self.conn.commit()
        return row_id

    def set_active(self, table, ids, active):
        if not ids:
            return
        self.conn.execute(f'UPDATE {table} SET is_active = ? WHERE id IN ({",".join("?" * len(ids))})',
                          (1 if active else 0, *ids))
        self.conn.commit()

    # ── manuals ──────────────────────────────────────────────────────
    def manuals(self, active_only=False):
        q = 'SELECT * FROM manuals' + (' WHERE is_active = 1' if active_only else '') + ' ORDER BY updated_at DESC'
        out = []
        for r in self.conn.execute(q):
            d = self._row(r, ('layout', 'meta'))
            d['sections'] = self.conn.execute('SELECT COUNT(*) FROM sections WHERE manual_id = ? AND is_active = 1',
                                              (r['id'],)).fetchone()[0]
            out.append(d)
        return out

    def manual(self, manual_id):
        return self._row(self.conn.execute('SELECT * FROM manuals WHERE id = ?', (manual_id,)).fetchone(),
                         ('layout', 'meta'))

    def save_manual(self, data, manual_id=None):
        mid = self._save('manuals', data, manual_id, ('layout', 'meta'))
        self.audit('manual_saved', id=mid, title=data.get('title_ar'))
        return mid

    def touch_manual(self, manual_id):
        self.conn.execute('UPDATE manuals SET updated_at = ? WHERE id = ?', (now(), manual_id))
        self.conn.commit()

    def delete_manual(self, manual_id):
        """Deletes a manual with everything in it (sections, blocks, org chart, register, history)."""
        sids = [r[0] for r in self.conn.execute('SELECT id FROM sections WHERE manual_id = ?', (manual_id,))]
        if sids:
            ph = ','.join('?' * len(sids))
            for t in ('blocks', 'revisions', 'approvals'):
                self.conn.execute(f'DELETE FROM {t} WHERE section_id IN ({ph})', sids)
        self.conn.execute('DELETE FROM controls WHERE manual_id = ?', (manual_id,))
        self.conn.execute('UPDATE sections SET parent_id = NULL WHERE manual_id = ?', (manual_id,))
        self.conn.execute('DELETE FROM sections WHERE manual_id = ?', (manual_id,))
        self.conn.execute('UPDATE org_units SET parent_id = NULL WHERE manual_id = ?', (manual_id,))
        self.conn.execute('DELETE FROM org_units WHERE manual_id = ?', (manual_id,))
        self.conn.execute('DELETE FROM manuals WHERE id = ?', (manual_id,))
        self.conn.commit()
        self.audit('manual_deleted', id=manual_id)

    def duplicate_manual(self, manual_id, title_suffix=' (نسخة)'):
        """A full copy (sections, blocks, org chart, register) — e.g. to start the next edition."""
        m = self.manual(manual_id)
        new = dict(m)
        new.pop('id')
        new['title_ar'] = (m['title_ar'] or '') + title_suffix
        nid = self._save('manuals', new, None, ('layout', 'meta'))
        unit_map = {}
        for u in self.org_units(manual_id):
            d = {k: u[k] for k in u if k not in ('id', 'children')}
            d['manual_id'], d['parent_id'] = nid, None
            unit_map[u['id']] = self._save('org_units', d)
        for u in self.org_units(manual_id):
            if u['parent_id']:
                self.conn.execute('UPDATE org_units SET parent_id = ? WHERE id = ?', (unit_map[u['parent_id']], unit_map[u['id']]))
        sec_map = {}
        for s in self.sections(manual_id, active_only=False):
            d = {k: s[k] for k in s if k not in ('id',)}
            d['manual_id'], d['parent_id'] = nid, None
            if s['kind'] == 'orgchart' and s['data'].get('root_id') in unit_map:
                d['data'] = dict(s['data'], root_id=unit_map[s['data']['root_id']])
            sid = self._save('sections', d, None, ('meta', 'data', 'style'))
            sec_map[s['id']] = sid
            for b in self.blocks(s['id']):
                bd = {k: b[k] for k in b if k != 'id'}
                bd['section_id'] = sid
                self._save('blocks', bd, None, ('data', 'style'))
            for r in self.revisions(s['id']):
                rd = {k: r[k] for k in r if k != 'id'}
                rd['section_id'] = sid
                self._save('revisions', rd)
        for s in self.sections(manual_id, active_only=False):
            if s['parent_id']:
                self.conn.execute('UPDATE sections SET parent_id = ? WHERE id = ?', (sec_map[s['parent_id']], sec_map[s['id']]))
        for c in self.controls(manual_id, active_only=False):
            cd = {k: c[k] for k in c if k != 'id'}
            cd['manual_id'], cd['section_id'] = nid, sec_map.get(c['section_id'])
            self._save('controls', cd)
        self.conn.commit()
        return nid

    # ── sections ─────────────────────────────────────────────────────
    def sections(self, manual_id, active_only=True):
        q = 'SELECT * FROM sections WHERE manual_id = ?' + (' AND is_active = 1' if active_only else '') + ' ORDER BY sort, id'
        return [self._row(r, ('meta', 'data', 'style')) for r in self.conn.execute(q, (manual_id,))]

    def section(self, section_id):
        return self._row(self.conn.execute('SELECT * FROM sections WHERE id = ?', (section_id,)).fetchone(),
                         ('meta', 'data', 'style'))

    def tree(self, manual_id, active_only=True):
        """The sections as a nested list in reading order: [{…, 'children': […]}]."""
        rows = self.sections(manual_id, active_only)
        by_parent = {}
        for r in rows:
            r['children'] = []
            by_parent.setdefault(r['parent_id'], []).append(r)
        ids = {r['id'] for r in rows}

        def build(pid):
            out = by_parent.get(pid, [])
            for r in out:
                r['children'] = build(r['id'])
            return out
        roots = build(None)
        # a section whose parent was removed or deactivated stays reachable at the top level
        roots += [r for r in rows if r['parent_id'] and r['parent_id'] not in ids]
        return roots

    def flat(self, manual_id, active_only=True):
        """Reading order with depth: [(section, depth)]."""
        out = []

        def walk(nodes, depth):
            for n in nodes:
                out.append((n, depth))
                walk(n['children'], depth + 1)
        walk(self.tree(manual_id, active_only), 0)
        return out

    def save_section(self, data, section_id=None):
        if not section_id and 'sort' not in data:
            r = self.conn.execute('SELECT COALESCE(MAX(sort), 0) + 10 FROM sections WHERE manual_id = ? AND parent_id IS ?',
                                  (data['manual_id'], data.get('parent_id'))).fetchone()
            data = dict(data, sort=r[0])
        sid = self._save('sections', data, section_id, ('meta', 'data', 'style'))
        s = self.section(sid)
        self.touch_manual(s['manual_id'])
        return sid

    def section_has_children(self, section_id):
        return bool(self.conn.execute('SELECT 1 FROM sections WHERE parent_id = ? LIMIT 1', (section_id,)).fetchone())

    def delete_sections(self, ids):
        """Deletes sections that have no sub-sections; returns the ids that were kept (they have sub-sections)."""
        kept = [i for i in ids if self.section_has_children(i)]
        gone = [i for i in ids if i not in kept]
        if gone:
            ph = ','.join('?' * len(gone))
            for t in ('blocks', 'revisions', 'approvals'):
                self.conn.execute(f'DELETE FROM {t} WHERE section_id IN ({ph})', gone)
            self.conn.execute(f'UPDATE controls SET section_id = NULL WHERE section_id IN ({ph})', gone)
            self.conn.execute(f'DELETE FROM sections WHERE id IN ({ph})', gone)
            self.conn.commit()
            self.audit('sections_deleted', ids=gone)
        return kept

    def move_section(self, section_id, parent_id, before_id=None):
        """Puts a section under ``parent_id`` (None = top level), before ``before_id`` (None = at the end)."""
        s = self.section(section_id)
        p = parent_id
        while p:                                   # never inside itself or one of its own sub-sections
            if p == section_id:
                return False
            p = (self.section(p) or {}).get('parent_id')
        sibs = [r for r in self.sections(s['manual_id'], active_only=False)
                if r['parent_id'] == parent_id and r['id'] != section_id]
        idx = next((i for i, r in enumerate(sibs) if r['id'] == before_id), len(sibs))
        sibs.insert(idx, {'id': section_id})
        for i, r in enumerate(sibs):
            self.conn.execute('UPDATE sections SET sort = ?, parent_id = ? WHERE id = ?', ((i + 1) * 10, parent_id, r['id']))
        self.conn.commit()
        self.touch_manual(s['manual_id'])
        return True

    def shift_section(self, section_id, delta):
        """Moves a section one place up (-1) or down (+1) among its siblings."""
        s = self.section(section_id)
        sibs = [r for r in self.sections(s['manual_id'], active_only=False) if r['parent_id'] == s['parent_id']]
        i = next(i for i, r in enumerate(sibs) if r['id'] == section_id)
        j = i + delta
        if not 0 <= j < len(sibs):
            return False
        sibs[i], sibs[j] = sibs[j], sibs[i]
        for k, r in enumerate(sibs):
            self.conn.execute('UPDATE sections SET sort = ? WHERE id = ?', ((k + 1) * 10, r['id']))
        self.conn.commit()
        return True

    def set_status(self, ids, status, by_name='', note=''):
        for i in ids:
            self.conn.execute('UPDATE sections SET status = ?, updated_at = ? WHERE id = ?', (status, now(), i))
            self.conn.execute('INSERT INTO approvals (section_id, action, by_name, note, at) VALUES (?, ?, ?, ?, ?)',
                              (i, status, by_name, note, now()))
        self.conn.commit()

    def approvals(self, section_id):
        return [dict(r) for r in self.conn.execute('SELECT * FROM approvals WHERE section_id = ? ORDER BY id', (section_id,))]

    # ── blocks ───────────────────────────────────────────────────────
    def blocks(self, section_id):
        return [self._row(r, ('data', 'style')) for r in
                self.conn.execute('SELECT * FROM blocks WHERE section_id = ? ORDER BY sort, id', (section_id,))]

    def save_block(self, data, block_id=None):
        if not block_id and 'sort' not in data:
            r = self.conn.execute('SELECT COALESCE(MAX(sort), 0) + 10 FROM blocks WHERE section_id = ?',
                                  (data['section_id'],)).fetchone()
            data = dict(data, sort=r[0])
        bid = self._save('blocks', data, block_id, ('data', 'style'), stamp=False)
        sec = self.conn.execute('SELECT section_id FROM blocks WHERE id = ?', (bid,)).fetchone()
        self.conn.execute('UPDATE sections SET updated_at = ? WHERE id = ?', (now(), sec[0]))
        self.conn.commit()
        return bid

    def replace_blocks(self, section_id, blocks):
        """Saves the whole content of a section at once (the editor's «save»)."""
        self.conn.execute('DELETE FROM blocks WHERE section_id = ?', (section_id,))
        for i, b in enumerate(blocks):
            b = dict(b, section_id=section_id, sort=(i + 1) * 10)
            b.pop('id', None)
            self._save('blocks', b, None, ('data', 'style'), stamp=False)
        self.conn.execute('UPDATE sections SET updated_at = ? WHERE id = ?', (now(), section_id))
        self.conn.commit()

    def delete_blocks(self, ids):
        if ids:
            self.conn.execute(f'DELETE FROM blocks WHERE id IN ({",".join("?" * len(ids))})', ids)
            self.conn.commit()

    # ── revisions ────────────────────────────────────────────────────
    def revisions(self, section_id):
        return [dict(r) for r in self.conn.execute('SELECT * FROM revisions WHERE section_id = ? ORDER BY rev_date, id',
                                                   (section_id,))]

    def add_revision(self, section_id, version, changes_ar, changes_en='', by_name='', rev_date=None):
        rid = self._save('revisions', {'section_id': section_id, 'version': version, 'rev_date': rev_date or today(),
                                       'changes_ar': changes_ar, 'changes_en': changes_en, 'by_name': by_name})
        self.conn.execute('UPDATE sections SET version = ?, review_date = ?, updated_at = ? WHERE id = ?',
                          (version, rev_date or today(), now(), section_id))
        self.conn.commit()
        return rid

    def delete_revisions(self, ids):
        if ids:
            self.conn.execute(f'DELETE FROM revisions WHERE id IN ({",".join("?" * len(ids))})', ids)
            self.conn.commit()

    # ── assets ───────────────────────────────────────────────────────
    def assets(self, kind=None):
        q = 'SELECT id, name, kind, mime, width, height, created_at, LENGTH(data) AS size FROM assets'
        rows = self.conn.execute(q + (' WHERE kind = ?' if kind else '') + ' ORDER BY id DESC', (kind,) if kind else ())
        return [dict(r) for r in rows]

    def asset(self, asset_id):
        r = self.conn.execute('SELECT * FROM assets WHERE id = ?', (asset_id,)).fetchone()
        return dict(r) if r else None

    def add_asset(self, name, data, mime, kind='image', width=None, height=None):
        return self._save('assets', {'name': name, 'data': data, 'mime': mime, 'kind': kind,
                                     'width': width, 'height': height}, stamp=False)

    ASSET_KEYS = ('asset_id', 'image_id', 'bg_id', 'page_bg_id')
    ASSET_PLACES = (('manuals', ('layout',)), ('sections', ('style', 'data')), ('blocks', ('data', 'style')))

    @classmethod
    def _asset_refs(cls, obj, asset_id, path=()):
        """The paths inside a JSON value that hold ``asset_id`` under one of the image keys (exact match only)."""
        out = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in cls.ASSET_KEYS and v is not None and str(v) == str(asset_id):
                    out.append(path + (k,))
                elif isinstance(v, (dict, list)):
                    out += cls._asset_refs(v, asset_id, path + (k,))
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                out += cls._asset_refs(v, asset_id, path + (i,))
        return out

    def asset_uses(self, asset_id):
        """Every place an image is used: [(table, row id, column, path inside the value)]."""
        hits = [('manuals', r['id'], 'logo_id', ()) for r in
                self.conn.execute('SELECT id FROM manuals WHERE logo_id = ?', (asset_id,))]
        for t, cols in self.ASSET_PLACES:
            needle = f'%{asset_id}%'
            where = ' OR '.join(f'{c} LIKE ?' for c in cols)
            for r in self.conn.execute(f'SELECT id, {", ".join(cols)} FROM {t} WHERE {where}', [needle] * len(cols)):
                for c in cols:
                    for path in self._asset_refs(_j(r[c], {}), asset_id):
                        hits.append((t, r['id'], c, path))
        return hits

    def asset_in_use(self, asset_id):
        """Where an image is used (to protect it from deletion)."""
        return [(t, rid) for t, rid, _c, _p in self.asset_uses(asset_id)]

    def asset_use_names(self, asset_id):
        """Readable places, for the message shown before an image is taken out of use: (Arabic, English)."""
        out = []
        for t, rid, c, path in self.asset_uses(asset_id):
            if t == 'manuals':
                m = self.manual(rid) or {}
                where = {'logo_id': ('الشعار', 'the logo')}.get(c) or (
                    ('خلفية الصفحات', 'the page background') if 'page_bg' in str(path) or 'page_bg_id' in path else
                    ('خلفية الغلاف', 'the cover background') if 'cover' in path else
                    ('صورة الترويسة', 'the header image') if 'header' in path else ('التصميم', 'the design'))
                out.append((f'{m.get("title_ar") or m.get("title_en") or ""}: {where[0]}',
                            f'{m.get("title_en") or m.get("title_ar") or ""}: {where[1]}'))
            else:
                sid = rid if t == 'sections' else (self.conn.execute('SELECT section_id FROM blocks WHERE id = ?', (rid,)).fetchone() or [None])[0]
                s = self.section(sid) if sid else None
                title = (s or {}).get('title_ar') or (s or {}).get('title_en') or ''
                kind = ('خلفية القسم', 'section background') if t == 'sections' and c == 'style' else ('صورة في القسم', 'image in the section')
                out.append((f'{kind[0]} «{title}»', f'{kind[1]} «{(s or {}).get("title_en") or title}»'))
        return out

    def detach_asset(self, asset_id):
        """Takes an image out of every place that uses it: the logo and the header image are cleared, a background
        is removed, and an image block is deleted (an empty image would print a hole)."""
        uses = self.asset_uses(asset_id)
        for t, rid, c, path in uses:
            if c == 'logo_id':
                self.conn.execute('UPDATE manuals SET logo_id = NULL WHERE id = ?', (rid,))
                continue
            if t == 'blocks' and c == 'data' and path == ('asset_id',):
                self.conn.execute('DELETE FROM blocks WHERE id = ?', (rid,))
                continue
            row = self.conn.execute(f'SELECT {c} FROM {t} WHERE id = ?', (rid,)).fetchone()
            if row is None:
                continue
            val = _j(row[0], {})
            parent = val
            for k in path[:-2]:
                parent = parent[k]
            last, key = (path[-2] if len(path) > 1 else None), path[-1]
            holder = parent[last] if last is not None else parent
            if key == 'asset_id' and last in ('bg', 'page_bg') and isinstance(holder, dict):
                if holder.get('color'):
                    holder['asset_id'] = None          # the colour of that background stays
                else:
                    parent[last] = None
            else:
                holder[key] = None
            self.conn.execute(f'UPDATE {t} SET {c} = ? WHERE id = ?', (json.dumps(val, ensure_ascii=False), rid))
        self.conn.commit()
        return len(uses)

    def clear_table_colors(self, manual_id):
        """Removes the colours of their own from every table of a manual (they follow the design again)."""
        n = 0
        for s in self.sections(manual_id):
            d = s.get('data') or {}
            if isinstance(d, dict) and d.pop('colors', None) is not None:
                self.conn.execute('UPDATE sections SET data = ? WHERE id = ?', (json.dumps(d, ensure_ascii=False), s['id']))
                n += 1
            for b in self.conn.execute("SELECT id, data FROM blocks WHERE section_id = ? AND kind = 'table'", (s['id'],)).fetchall():
                bd = _j(b['data'], {})
                if bd.pop('colors', None) is not None:
                    self.conn.execute('UPDATE blocks SET data = ? WHERE id = ?', (json.dumps(bd, ensure_ascii=False), b['id']))
                    n += 1
        self.conn.commit()
        return n

    def delete_assets(self, ids, detach=False):
        """Deletes the images; one in use is kept unless ``detach`` (then it is first taken out of use)."""
        if detach:
            for i in ids:
                self.detach_asset(i)
        kept = [i for i in ids if self.asset_in_use(i)]
        gone = [i for i in ids if i not in kept]
        if gone:
            self.conn.execute(f'DELETE FROM assets WHERE id IN ({",".join("?" * len(gone))})', gone)
            self.conn.commit()
        return kept

    # ── org units ────────────────────────────────────────────────────
    def org_units(self, manual_id, active_only=False):
        q = 'SELECT * FROM org_units WHERE manual_id = ?' + (' AND is_active = 1' if active_only else '') + ' ORDER BY sort, id'
        return [dict(r) for r in self.conn.execute(q, (manual_id,))]

    def org_tree(self, manual_id, root_id=None, active_only=True):
        rows = self.org_units(manual_id, active_only)
        by_parent = {}
        for r in rows:
            r['children'] = []
            by_parent.setdefault(r['parent_id'], []).append(r)
        for r in rows:
            r['children'] = by_parent.get(r['id'], [])
        if root_id:
            return [r for r in rows if r['id'] == root_id]
        ids = {r['id'] for r in rows}
        return [r for r in rows if not r['parent_id'] or r['parent_id'] not in ids]

    def save_unit(self, data, unit_id=None):
        if not unit_id and 'sort' not in data:
            r = self.conn.execute('SELECT COALESCE(MAX(sort), 0) + 10 FROM org_units WHERE manual_id = ? AND parent_id IS ?',
                                  (data['manual_id'], data.get('parent_id'))).fetchone()
            data = dict(data, sort=r[0])
        return self._save('org_units', data, unit_id, stamp=False)

    def delete_units(self, ids):
        kept = [i for i in ids if self.conn.execute('SELECT 1 FROM org_units WHERE parent_id = ? LIMIT 1', (i,)).fetchone()]
        gone = [i for i in ids if i not in kept]
        if gone:
            self.conn.execute(f'DELETE FROM org_units WHERE id IN ({",".join("?" * len(gone))})', gone)
            self.conn.commit()
        return kept

    # ── compliance register ──────────────────────────────────────────
    def controls(self, manual_id, active_only=True, section_id=None):
        q = 'SELECT * FROM controls WHERE manual_id = ?'
        p = [manual_id]
        if active_only:
            q += ' AND is_active = 1'
        if section_id:
            q += ' AND section_id = ?'
            p.append(section_id)
        return [dict(r) for r in self.conn.execute(q + ' ORDER BY code, id', p)]

    def control(self, control_id):
        r = self.conn.execute('SELECT * FROM controls WHERE id = ?', (control_id,)).fetchone()
        return dict(r) if r else None

    def save_control(self, data, control_id=None):
        return self._save('controls', data, control_id)

    def delete_controls(self, ids):
        if ids:
            self.conn.execute(f'DELETE FROM controls WHERE id IN ({",".join("?" * len(ids))})', ids)
            self.conn.commit()

    def due_reviews(self, manual_id, within_days=30):
        """Sections and controls whose next review date is past or within ``within_days``."""
        from datetime import timedelta
        limit = (date.today() + timedelta(days=within_days)).isoformat()
        secs = [s for s in self.sections(manual_id) if s.get('next_review') and s['next_review'] <= limit]
        ctrls = [c for c in self.controls(manual_id) if c.get('next_review') and c['next_review'] <= limit]
        return secs, ctrls

    # ── users (workflow) ─────────────────────────────────────────────
    def users(self):
        return [dict(r) for r in self.conn.execute('SELECT * FROM users ORDER BY name')]

    def save_user(self, data, user_id=None):
        data = dict(data)
        if data.get('password'):
            data['password'] = hash_password(data['password'])
        elif user_id:
            data.pop('password', None)
        return self._save('users', data, user_id, stamp=False)

    def check_user(self, username, password):
        r = self.conn.execute('SELECT * FROM users WHERE username = ? AND is_active = 1', (username.strip(),)).fetchone()
        if r and verify_password(password, r['password']):
            return dict(r)
        return None

    def delete_users(self, ids, current_id=None):
        """Never the current user nor the last active administrator."""
        admins = [u['id'] for u in self.users() if u['role'] == 'admin' and u['is_active']]
        kept = [i for i in ids if i == current_id or (i in admins and len([a for a in admins if a not in ids]) == 0)]
        gone = [i for i in ids if i not in kept]
        if gone:
            self.conn.execute(f'DELETE FROM users WHERE id IN ({",".join("?" * len(gone))})', gone)
            self.conn.commit()
        return kept

    # ── statistics for the dashboard ─────────────────────────────────
    def stats(self, manual_id):
        secs = self.sections(manual_id)
        st = {k: 0 for k in STATUSES}
        for s in secs:
            st[s['status']] = st.get(s['status'], 0) + 1
        ctrls = self.controls(manual_id)
        cs = {k: 0 for k in CONTROL_STATUSES}
        for c in ctrls:
            cs[c['status']] = cs.get(c['status'], 0) + 1
        due_s, due_c = self.due_reviews(manual_id)
        return {'sections': len(secs), 'policies': sum(1 for s in secs if s['kind'] == 'policy'),
                'status': st, 'controls': len(ctrls), 'control_status': cs,
                'units': len(self.org_units(manual_id, True)), 'due_sections': len(due_s), 'due_controls': len(due_c)}

    # ── backup ───────────────────────────────────────────────────────
    def backup(self, folder, keep=30):
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f'manuals-{datetime.now().strftime("%Y-%m-%d_%H%M%S")}.db')
        dst = sqlite3.connect(path)
        self.conn.backup(dst)
        dst.close()
        olds = sorted(f for f in os.listdir(folder) if f.startswith('manuals-') and f.endswith('.db'))
        for f in olds[:-keep]:
            try:
                os.remove(os.path.join(folder, f))
            except OSError:
                pass
        return path

    def restore(self, source):
        test = sqlite3.connect(source)
        try:
            test.execute('SELECT COUNT(*) FROM manuals').fetchone()
        finally:
            test.close()
        safety = self.backup(os.path.join(os.path.dirname(self.path), 'backups'))
        self.conn.close()
        shutil.copyfile(source, self.path)
        for ext in ('-wal', '-shm'):
            try:
                os.remove(self.path + ext)
            except OSError:
                pass
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self._migrate()
        return safety


def hash_password(pw):
    import hashlib
    import secrets
    salt = secrets.token_hex(8)
    return f'pbkdf2${salt}$' + hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 120000).hex()


def verify_password(pw, stored):
    import hashlib
    import hmac
    try:
        _, salt, h = stored.split('$', 2)
    except ValueError:
        return False
    return hmac.compare_digest(hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 120000).hex(), h)

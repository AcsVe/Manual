"""The list of manuals: create one from a starter structure or from an existing file (Word, web page, PDF), open,
copy (to start the next edition), archive and delete. Also the import dialog used by the editor."""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QVBoxLayout, QWidget)

from ..core import importer
from ..core.templates import DEFAULT_LAYOUT, LANG_MODES, STARTERS
from .common import DataTable, L, confirm, error, info
from .theme import SizedDialog, button, card, field, fit, form_grid, hint, ltr, name_buttons


class NewManualDialog(SizedDialog):
    """A new manual: only a starting structure is chosen; every other detail is optional and can be changed later in
    «التصميم». The page direction is not asked here: each section may have its own."""

    def __init__(self, parent, ctx):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(L('دليل جديد', 'New manual'))
        self.starter = QComboBox()
        for k, ((ar, en), _) in STARTERS.items():
            self.starter.addItem(L(ar, en), k)
        self.starter.setCurrentIndex(max(0, self.starter.findData('blank')))
        self.title_ar = QLineEdit()
        self.title_ar.setPlaceholderText(L('دليل جديد', 'New manual'))
        self.title_en = ltr(QLineEdit())
        self.org_ar = QLineEdit(ctx.db.get('org_ar') or '')
        self.org_en = ltr(QLineEdit(ctx.db.get('org_en') or ''))
        self.lang = QComboBox()
        for k, (ar, en) in LANG_MODES.items():
            self.lang.addItem(L(ar, en), k)
        for w, n in ((self.starter, 420), (self.lang, 320)):
            fit(w, n)
        open_file = button(L('فتح ملف موجود بدلاً من ذلك…', 'Open an existing file instead…'), 'folder')
        open_file.clicked.connect(self._open_file)
        g = form_grid()
        field(g, 0, 0, L('يبدأ من', 'Start from'), self.starter)
        field(g, 1, 0, L('عنوان الدليل', 'Manual title'), self.title_ar)
        self.more = QCheckBox(L('بيانات إضافية (اختيارية)', 'More details (optional)'))
        g.addWidget(self.more, 2, 1)
        extra = QWidget()
        eg = form_grid()
        eg.setContentsMargins(0, 0, 0, 0)
        field(eg, 0, 0, L('العنوان بالإنجليزية', 'English title'), self.title_en)
        field(eg, 1, 0, L('اسم المؤسسة بالعربية', 'Organisation (Arabic)'), self.org_ar)
        field(eg, 2, 0, L('اسم المؤسسة بالإنجليزية', 'Organisation (English)'), self.org_en)
        field(eg, 3, 0, L('لغة الدليل', 'Manual language'), self.lang)
        eg.setColumnStretch(1, 1)
        extra.setLayout(eg)
        extra.setVisible(False)
        self.more.toggled.connect(extra.setVisible)
        self.more.toggled.connect(lambda _v: self.adjustSize())
        g.addWidget(extra, 3, 0, 1, 2)
        g.setColumnStretch(1, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(L('إنشاء', 'Create'))
        bb.button(QDialogButtonBox.Cancel).setText(L('إلغاء', 'Cancel'))
        name_buttons(bb)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(g)
        lay.addWidget(hint(L('كل ما سبق يُعدَّل لاحقاً من «التصميم»، واتجاه الصفحة (عمودي أو أفقي) يُختار لكل قسم من المحرر.',
                             'All of this can be changed later in «Design», and the page direction (portrait or landscape) is chosen per section in the editor.')))
        lay.addWidget(open_file, 0, Qt.AlignLeading)
        lay.addWidget(bb)
        self.resize(600, 260)
        self.result_id = None

    def _open_file(self):
        mid = open_file(self, self.ctx)
        if mid:
            self.result_id = mid
            self.accept()

    def _ok(self):
        title_ar = self.title_ar.text().strip()
        title_en = self.title_en.text().strip()
        if not title_ar and not title_en:
            title_ar, title_en = 'دليل جديد', 'New manual'
        layout = dict(DEFAULT_LAYOUT, lang_mode=self.lang.currentData(), orientation='portrait')
        fields = {'title_ar': title_ar, 'title_en': title_en,
                  'org_ar': self.org_ar.text().strip(), 'org_en': self.org_en.text().strip(), 'layout': layout,
                  'issue_date': __import__('datetime').date.today().isoformat()}
        self.ctx.db.set('org_ar', fields['org_ar'])
        self.ctx.db.set('org_en', fields['org_en'])
        from ..core.templates import create_from_starter
        self.result_id = create_from_starter(self.ctx.db, self.starter.currentData(), fields)
        self.accept()


class ImportDialog(SizedDialog):
    """Chooses what to bring in from a file and how."""

    def __init__(self, parent, path):
        super().__init__(parent)
        self.path = path
        self.setWindowTitle(L('استيراد', 'Import'))
        ext = os.path.splitext(path)[1].lower()
        self.kind = QComboBox()
        self.kind.addItem(L('محتوى عادي', 'Ordinary content'), 'text')
        self.kind.addItem(L('سياسات وإجراءات (مع سجل التغييرات)', 'Policies & procedures (with change history)'), 'policy')
        fit(self.kind, 360)
        g = form_grid()
        field(g, 0, 0, L('الملف', 'File'), QLabel(os.path.basename(path)))
        field(g, 1, 0, L('تُضاف الأقسام كـ', 'Sections are added as'), self.kind)
        self.pages = self.image_pages = None
        notes = L('العناوين تصبح أقساماً، والفقرات والقوائم والجداول والصور تنتقل كما هي، وكل شيء قابل للتعديل بعد الاستيراد.',
                  'Headings become sections; paragraphs, lists, tables and images come over as they are, and everything can be edited afterwards.')
        if ext == '.pdf':
            n = importer.pdf_page_count(path)
            self.pages = ltr(QLineEdit(f'1-{n}' if n else ''), 160)
            self.image_pages = ltr(QLineEdit(), 160)
            self.image_pages.setPlaceholderText('12, 13')
            field(g, 2, 0, L(f'الصفحات المقروءة (من {n})', f'Pages to read (of {n})'), self.pages)
            field(g, 3, 0, L('صفحات تُستورد صوراً', 'Pages imported as images'), self.image_pages)
            notes = L('ملف PDF لا يحمل هيكلاً: تُستنتج العناوين من حجم الخط، ويُفصل العمود الإنجليزي عن العربي حسب موقعه، ويُحذف الترويس والتذييل المتكرر. '
                      'راجع النتيجة بعد الاستيراد، واستورد صفحات الرسوم والهيكل التنظيمي صوراً. ملف Word الأصلي يعطي نتيجة أدق.',
                      'A PDF carries no structure: headings are inferred from the font size, the English column is separated from the Arabic one by position, '
                      'and the repeated header and footer are dropped. Review the result, and import chart pages as images. The original Word file gives a more accurate result.')
        g.setColumnStretch(1, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(L('استيراد', 'Import'))
        bb.button(QDialogButtonBox.Cancel).setText(L('إلغاء', 'Cancel'))
        name_buttons(bb)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(hint(notes))
        lay.addLayout(g)
        lay.addWidget(bb)
        self.resize(620, 300)

    @staticmethod
    def parse_pages(text):
        out = []
        for part in (text or '').replace('،', ',').split(','):
            part = part.strip()
            if not part:
                continue
            if '-' in part:
                a, b = part.split('-', 1)
                if a.strip().isdigit() and b.strip().isdigit():
                    out.extend(range(int(a), int(b) + 1))
            elif part.isdigit():
                out.append(int(part))
        return out


FILE_FILTER = ('ملفات مدعومة / Supported files (*.docx *.pdf *.html *.htm *.txt *.png *.jpg *.jpeg *.bmp *.gif *.webp);;'
               'Word (*.docx);;PDF (*.pdf);;HTML (*.html *.htm);;Text (*.txt);;Pictures (*.png *.jpg *.jpeg *.bmp *.gif *.webp)')


def _bring_in(parent, ctx, mid, parent_sid, path, kind='text', pages=None, image_pages=(), page_looks=None, drop=None):  # noqa: PLR0913
    """Reads ``path`` into manual ``mid`` (under ``parent_sid``), tidies it with the checker's safe fixes and returns
    (section ids, the summary text, the points left, the sections as read) — or None after telling what went wrong."""
    QGuiApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        secs, imgs = importer.read_any(path, pages, image_pages, page_looks=page_looks, drop=drop)
        if not secs:
            raise ValueError(L('لم يُعثر في الملف على نص ولا صفحات.', 'Nothing was found in the file.'))
        ids = importer.add_to_manual(ctx.db, mid, secs, imgs, parent_sid, kind)
        from ..core import doctor
        prefs = doctor.load_prefs(ctx.db)
        tidied = 0
        if prefs.get('auto_import'):            # the checker's safe fixes on what came in
            rules = [r for r in doctor.AUTO_ON_IMPORT if r not in (prefs.get('disabled') or [])]
            tidied = doctor.autofix_sections(ctx.db, mid, ids, rules)
        left = [x for x in doctor.check(ctx.db, mid, prefs, ctx.workflow, only=set(ids)) if x['sev'] in ('error', 'warning')]
    except Exception as e:  # noqa: BLE001 — a damaged or protected file
        QGuiApplication.restoreOverrideCursor()
        error(parent, L('تعذّر فتح الملف:', 'The file cannot be opened:') + f'\n{e}')
        return None
    QGuiApplication.restoreOverrideCursor()
    blocks = sum(1 for s in secs for b in s['blocks'] if b.get('kind') != 'pagebreak')
    pics = sum(1 for s in secs for b in s['blocks'] if b.get('kind') == 'image' and (b.get('style') or {}).get('fullpage'))
    ctx.db.audit('import', file=os.path.basename(path), sections=len(ids), tidied=tidied)
    text = L(f'استُورد {len(ids)} قسماً و{blocks} كتلة و{len(imgs)} صورة.', f'Imported {len(ids)} sections, {blocks} blocks and {len(imgs)} images.')
    if pics:
        text += L(f' {pics} صفحة أُدخلت صفحاتٍ كاملة كما هي (الغلاف، والصفحات الفاصلة، والصفحات الممسوحة ضوئياً أو التي لا يُقرأ نصها).',
                  f' {pics} page(s) came in whole, as they are (the cover, divider pages, scanned pages or pages whose text cannot be read).')
    if tidied:
        text += L(f' ضبط المدقق {tidied} موضعاً تلقائياً.', f' The checker tidied {tidied} place(s).')
    return ids, text, left, secs


def _report(parent, ctx, text, left):
    if left and confirm(parent, text + L(f'\n\nبقيت {len(left)} ملاحظة (أخطاء وتحذيرات) تحتاج إلى مراجعة. هل تريد عرضها في المدقق؟',
                                          f'\n\n{len(left)} point(s) (errors and warnings) need a look. Show them in the checker?')):
        if ctx.window:                      # after the caller has opened the manual
            from PySide6.QtCore import QTimer
            QTimer.singleShot(400, lambda: ctx.window.open_doctor(run=True))
        return
    info(parent, text + L(' راجعها في المحرر.', ' Review them in the editor.'))


class _Stopped(Exception):
    """Reading the file was stopped from its progress window."""


def _read_pdf(parent, path):
    """Opens a PDF for reading with its look: asks for its password when it has one, mends a damaged file where it
    can, and reads the design of its pages (with a progress window). Returns (path to read, look or None, temporary
    file or None), or None when the file is not opened (no password given, stopped, unreadable)."""
    from PySide6.QtWidgets import QInputDialog, QLineEdit as _Edit, QProgressDialog
    from ..core import pdf_look
    password = None
    for attempt in range(4):
        try:
            QGuiApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                use, tmp, note = pdf_look.prepare(path, password)
            finally:
                QGuiApplication.restoreOverrideCursor()
            break
        except pdf_look.PdfPasswordError:
            if attempt == 3:
                error(parent, L('كلمة المرور غير صحيحة، فلم يُفتح الملف.', 'The password is not correct; the file was not opened.'))
                return None
            msg = L('الملف محمي بكلمة مرور. اكتب كلمة المرور لفتحه:', 'The file is protected by a password. Type the password to open it:')
            if attempt:
                msg = L('كلمة المرور غير صحيحة. اكتبها مرة أخرى:', 'The password is not correct. Type it again:')
            password, ok = QInputDialog.getText(parent, os.path.basename(path), msg, _Edit.Password)
            if not ok:
                return None
        except ValueError as e:
            error(parent, L('تعذّر فتح الملف:', 'The file cannot be opened:') + f'\n{e}')
            return None
    if note == 'pictures':                       # its text cannot be read: every page comes in as it is
        return use, {'pictures': True, 'n': importer.pdf_page_count(use) or 0}, tmp
    box = QProgressDialog(L('قراءة تصميم صفحات الملف…', 'Reading the design of the pages…'), L('إيقاف', 'Stop'), 0, 100, parent)
    box.setWindowTitle(os.path.basename(path))
    box.setWindowModality(Qt.WindowModal)
    box.setMinimumDuration(400)

    def progress(done, total):
        box.setMaximum(max(1, total))
        box.setValue(done)
        QGuiApplication.processEvents()
        if box.wasCanceled():
            raise _Stopped()
    try:
        look = pdf_look.analyse(use, progress)
    except _Stopped:
        box.close()
        if tmp:
            os.remove(tmp)
        return None
    except Exception:  # noqa: BLE001 — the text is still read, without the look
        look = None
    box.close()
    return use, look, tmp


def _bring_in_pdf(parent, ctx, mid, parent_sid, path, mode, kind='text', pages=None, image_pages=()):  # noqa: PLR0913
    """A PDF with its look (pdf_look): mode «manual» for a manual opened from the file, «sections» for a file
    imported into a manual. Returns what _bring_in returns, or None."""
    from ..core import pdf_look
    read = _read_pdf(parent, path)
    if not read:
        return None
    use, look, tmp = read
    try:
        if look and look.get('pictures'):
            all_pages = set(pages or range(1, look['n'] + 1))
            return _bring_in(parent, ctx, mid, parent_sid, use, kind, pages, all_pages)
        keys = pdf_look.page_keys(look) if look else None
        shown = set(image_pages or ()) | (look['image_pages'] if look else set())
        done = _bring_in(parent, ctx, mid, parent_sid, use, kind, pages, shown, keys,
                         pdf_look.drop_lines(look) if look else None)
        if done and look:
            levels = [(sid, int(sec.get('level') or 1), sec) for sid, sec in zip(done[0], done[3])]
            try:
                QGuiApplication.setOverrideCursor(Qt.WaitCursor)
                pdf_look.apply(ctx.db, mid, look, levels, mode,
                               name=L('تصميم صفحات الملف الأصلي', 'Design of the original pages'))
            finally:
                QGuiApplication.restoreOverrideCursor()
        return done
    finally:
        pdf_look.close(look)
        if tmp and os.path.exists(tmp):
            os.remove(tmp)


def import_into(parent, ctx, mid, parent_sid):
    """Asks for a file and imports it under ``parent_sid`` of manual ``mid``. Returns True when something was added.
    A PDF keeps the design of its pages on the sections it brings in."""
    path, _ = QFileDialog.getOpenFileName(parent, L('استيراد ملف', 'Import a file'), '', FILE_FILTER)
    if not path:
        return False
    d = ImportDialog(parent, path)
    if not d.exec():
        return False
    if os.path.splitext(path)[1].lower() == '.pdf':
        pages = d.parse_pages(d.pages.text()) or None
        image_pages = set(d.parse_pages(d.image_pages.text()))
        done = _bring_in_pdf(parent, ctx, mid, parent_sid, path, 'sections', d.kind.currentData(), pages, image_pages)
    else:
        done = _bring_in(parent, ctx, mid, parent_sid, path, d.kind.currentData())
    if not done:
        return False
    _report(parent, ctx, done[1], done[2])
    return True


def _fit_languages(db, mid, ids):
    """The language display of a manual opened from a file follows its content: Arabic only, English only, the two
    side by side when the file pairs them, otherwise each paragraph in its own language at full width."""
    import re
    ar = en = pairs = total = 0
    for sid in ids:
        for b in db.blocks(sid):
            a = re.sub(r'<[^>]+>|\s', '', b.get('ar') or '')
            e = re.sub(r'<[^>]+>|\s', '', b.get('en') or '')
            if not (a or e):
                continue
            total += 1
            ar += len(a)
            en += len(e)
            pairs += bool(a and e)
    if not total:
        return
    mode = 'ar' if not en else 'en' if not ar else 'bi_side' if pairs >= total * 0.3 else 'bi_stack'
    from ..core.templates import layout_with_defaults
    lay = layout_with_defaults(db.manual(mid)['layout'])
    if lay.get('lang_mode') != mode:
        lay['lang_mode'] = mode
        db.save_manual({'layout': lay}, mid)


def open_file(parent, ctx, path=None):
    """Opens any supported file as a new manual at once, with no questions: the title is the file name, the page
    direction follows the file, the rest takes the usual settings (all changeable later). A PDF keeps its look: its
    cover, the design of its pages, its margins, page size and page numbers. Returns the new manual."""
    if not path:
        path, _ = QFileDialog.getOpenFileName(parent, L('فتح ملف', 'Open a file'), ctx.db.get('last_dir') or '', FILE_FILTER)
        if not path:
            return None
    ctx.db.set('last_dir', os.path.dirname(path))
    from ..core.templates import create_from_starter
    name = os.path.splitext(os.path.basename(path))[0]
    ar = importer.is_arabic(name)
    layout = dict(DEFAULT_LAYOUT, orientation=importer.file_orientation(path) or 'portrait')
    fields = {'title_ar': name if ar else '', 'title_en': '' if ar else name, 'layout': layout,
              'org_ar': ctx.db.get('org_ar') or '', 'org_en': ctx.db.get('org_en') or '',
              'issue_date': __import__('datetime').date.today().isoformat()}
    mid = create_from_starter(ctx.db, 'blank', fields)
    is_pdf = os.path.splitext(path)[1].lower() == '.pdf'
    done = _bring_in_pdf(parent, ctx, mid, None, path, 'manual') if is_pdf else _bring_in(parent, ctx, mid, None, path)
    if not done:
        ctx.db.delete_manual(mid)
        return None
    _fit_languages(ctx.db, mid, done[0])
    if is_pdf:                          # the file's own first page (its cover, or its first page of text) opens it
        ctx.db.delete_sections([s['id'] for s in ctx.db.sections(mid) if s['kind'] == 'cover'])
    ctx.manual_id = mid
    if ctx.window:
        ctx.window.open_editor()
    _report(parent, ctx, done[1], done[2])
    return mid


class ManualsTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.db = ctx, ctx.db
        new = button(L('دليل جديد…', 'New manual…'), 'plus', 'primary')
        new.clicked.connect(self.new)
        opener = button(L('فتح ملف…', 'Open a file…'), 'folder',
                        tip=L('Word أو PDF أو صفحة ويب أو نص أو صورة: يصبح دليلاً جديداً مباشرة',
                              'Word, PDF, web page, text or picture: it becomes a new manual at once'))
        opener.clicked.connect(lambda: open_file(self, self.ctx) and self.reload())
        self.table = DataTable(
            [(L('العنوان', 'Title'), 'text'), (L('العنوان بالإنجليزية', 'English title'), 'text'),
             (L('المؤسسة', 'Organisation'), 'text'), (L('الأقسام', 'Sections'), 'num'),
             (L('تاريخ الإصدار', 'Issue date'), 'text'), (L('آخر تعديل', 'Last change'), 'text'),
             (L('الحالة', 'Status'), 'select')],
            [(L('فتح في المحرر', 'Open in the editor'), self.open_ids, False, 'edit'),
             (L('نسخة جديدة منه', 'Copy it'), self.copy, False, 'copy'),
             (L('تفعيل', 'Activate'), lambda ids: self._active(ids, True), False, 'on'),
             (L('أرشفة', 'Archive'), lambda ids: self._active(ids, False), False, 'off'),
             (L('حذف', 'Delete'), self.delete, True, 'trash')],
            export_name='manuals', title=L('الأدلة', 'Manuals'))
        self.table.activated.connect(lambda i: self.open_ids([i]))
        top = QHBoxLayout()
        top.addWidget(new)
        top.addWidget(opener)
        top.addStretch(1)
        box = card(L('الأدلة', 'Manuals'))
        bl = QVBoxLayout(box)
        bl.addWidget(hint(L('كل دليل مستقل: أقسامه وهيكله التنظيمي وسجل التزامه وتصميمه. انقر نقراً مزدوجاً لفتح دليل في المحرر.',
                            'Each manual is independent: its sections, organisational chart, compliance register and design. Double-click to open one in the editor.')))
        bl.addLayout(top)
        bl.addWidget(self.table, 1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 14)
        lay.addWidget(box, 1)
        self.reload()

    def reload(self):
        rows = []
        cur = self.ctx.manual_id
        for m in self.db.manuals():
            st = L('نشط', 'Active') if m['is_active'] else L('مؤرشف', 'Archived')
            if m['id'] == cur:
                st = L('مفتوح الآن', 'Open now')
            rows.append((m['id'], [m['title_ar'] or '', m['title_en'] or '', m.get('org_ar') or m.get('org_en') or '',
                                   (m['sections'], m['sections']), m.get('issue_date') or '', (m['updated_at'] or '')[:16].replace('T', ' '), st]))
        self.table.set_rows(rows)

    def new(self):
        d = NewManualDialog(self, self.ctx)
        if d.exec() and d.result_id:
            self.reload()
            if self.ctx.manual_id != d.result_id:        # a file opened from the dialog is already open
                self.open_ids([d.result_id])

    def open_ids(self, ids):
        if ids:
            self.ctx.manual_id = ids[0]
            self.ctx.window.open_editor()

    def copy(self, ids):
        for i in ids:
            self.db.duplicate_manual(i, L(' (نسخة)', ' (copy)'))
        self.reload()

    def _active(self, ids, on):
        self.db.set_active('manuals', ids, on)
        self.reload()

    def delete(self, ids):
        if not ids:
            return
        names = '، '.join((self.db.manual(i) or {}).get('title_ar') or '' for i in ids)
        if not confirm(self, L(f'حذف نهائي لـ {len(ids)} دليل مع كل أقسامها وهيكلها وسجلها؟\n{names}\n\nتبقى النسخ الاحتياطية السابقة. الأرشفة بديل يحفظ الدليل.',
                               f'Permanently delete {len(ids)} manual(s) with all their sections, chart and register?\n{names}\n\nEarlier backups are kept. Archiving is an alternative that keeps the manual.')):
            return
        self.db.backup(self.db.get('backup_dir') or os.path.join(self.ctx.data_dir, 'backups'))
        for i in ids:
            self.db.delete_manual(i)
        if self.ctx.manual_id not in [m['id'] for m in self.db.manuals()]:
            self.db.set('current_manual', '')
        self.reload()
        self.ctx.window.manual_changed()


"""The list of manuals: create one from a starter structure or from an existing file (Word, web page, PDF), open,
copy (to start the next edition), archive and delete. Also the import dialog used by the editor."""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QComboBox, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                               QVBoxLayout, QWidget)

from ..core import importer
from ..core.templates import DEFAULT_LAYOUT, LANG_MODES, STARTERS
from .common import DataTable, L, confirm, error, info
from .theme import SizedDialog, button, card, field, fit, form_grid, hint, ltr, name_buttons


class NewManualDialog(SizedDialog):
    def __init__(self, parent, ctx):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(L('دليل جديد', 'New manual'))
        self.starter = QComboBox()
        for k, ((ar, en), _) in STARTERS.items():
            self.starter.addItem(L(ar, en), k)
        self.starter.addItem(L('من ملف موجود (Word أو صفحة ويب أو PDF)…', 'From an existing file (Word, web page or PDF)…'), 'file')
        self.title_ar = QLineEdit()
        self.title_en = ltr(QLineEdit())
        self.org_ar = QLineEdit(ctx.db.get('org_ar') or '')
        self.org_en = ltr(QLineEdit(ctx.db.get('org_en') or ''))
        self.lang = QComboBox()
        for k, (ar, en) in LANG_MODES.items():
            self.lang.addItem(L(ar, en), k)
        self.orient = QComboBox()
        self.orient.addItem(L('أفقي', 'Landscape'), 'landscape')
        self.orient.addItem(L('عمودي', 'Portrait'), 'portrait')
        for w, n in ((self.starter, 420), (self.lang, 320), (self.orient, 160)):
            fit(w, n)
        g = form_grid()
        field(g, 0, 0, L('يبدأ من', 'Start from'), self.starter)
        field(g, 1, 0, L('عنوان الدليل بالعربية *', 'Arabic title *'), self.title_ar)
        field(g, 2, 0, L('عنوان الدليل بالإنجليزية', 'English title'), self.title_en)
        field(g, 3, 0, L('اسم المؤسسة بالعربية', 'Organisation (Arabic)'), self.org_ar)
        field(g, 4, 0, L('اسم المؤسسة بالإنجليزية', 'Organisation (English)'), self.org_en)
        field(g, 5, 0, L('لغة الدليل', 'Manual language'), self.lang)
        field(g, 6, 0, L('اتجاه الصفحة', 'Page orientation'), self.orient)
        g.setColumnStretch(1, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(L('إنشاء', 'Create'))
        bb.button(QDialogButtonBox.Cancel).setText(L('إلغاء', 'Cancel'))
        name_buttons(bb)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(hint(L('الهيكل المبدئي قابل للتعديل بالكامل: أضف الأقسام أو احذفها أو أعد ترتيبها في المحرر.',
                             'The starting structure is fully editable: add, delete or reorder sections in the editor.')))
        lay.addLayout(g)
        lay.addWidget(bb)
        self.resize(640, 420)
        self.result_id = None

    def _ok(self):
        if not self.title_ar.text().strip() and not self.title_en.text().strip():
            error(self, L('اكتب عنوان الدليل.', 'Enter the manual title.'))
            return
        layout = dict(DEFAULT_LAYOUT, lang_mode=self.lang.currentData(), orientation=self.orient.currentData())
        fields = {'title_ar': self.title_ar.text().strip(), 'title_en': self.title_en.text().strip(),
                  'org_ar': self.org_ar.text().strip(), 'org_en': self.org_en.text().strip(), 'layout': layout,
                  'issue_date': __import__('datetime').date.today().isoformat()}
        self.ctx.db.set('org_ar', fields['org_ar'])
        self.ctx.db.set('org_en', fields['org_en'])
        from ..core.templates import create_from_starter
        key = self.starter.currentData()
        if key == 'file':
            mid = create_from_starter(self.ctx.db, 'blank', fields)
            if not import_into(self, self.ctx, mid, None):
                self.ctx.db.delete_manual(mid)
                return
        else:
            mid = create_from_starter(self.ctx.db, key, fields)
        self.result_id = mid
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


def import_into(parent, ctx, mid, parent_sid):
    """Asks for a file and imports it under ``parent_sid`` of manual ``mid``. Returns True when something was added."""
    path, _ = QFileDialog.getOpenFileName(parent, L('استيراد ملف', 'Import a file'), '',
                                          L('ملفات مدعومة', 'Supported files') + ' (*.docx *.html *.htm *.pdf)')
    if not path:
        return False
    d = ImportDialog(parent, path)
    if not d.exec():
        return False
    ext = os.path.splitext(path)[1].lower()
    QGuiApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        if ext == '.docx':
            secs, imgs = importer.import_docx(path)
        elif ext in ('.html', '.htm'):
            secs, imgs = importer.import_html(path)
        elif ext == '.pdf':
            pages = d.parse_pages(d.pages.text()) or None
            secs, imgs = importer.import_pdf(path, pages, set(d.parse_pages(d.image_pages.text())))
        else:
            raise ValueError(L('نوع الملف غير مدعوم. الأنواع المدعومة: Word (.docx) وصفحة ويب (.html) وPDF.',
                               'Unsupported file type. Supported: Word (.docx), web page (.html) and PDF.'))
        if not secs:
            raise ValueError(L('لم يُعثر على نص في الملف (قد يكون صوراً ممسوحة ضوئياً).', 'No text was found in the file (it may be scanned images).'))
        ids = importer.add_to_manual(ctx.db, mid, secs, imgs, parent_sid, d.kind.currentData())
    except Exception as e:  # noqa: BLE001 — a damaged or protected file
        QGuiApplication.restoreOverrideCursor()
        error(parent, L('تعذّر الاستيراد:', 'The import failed:') + f'\n{e}')
        return False
    QGuiApplication.restoreOverrideCursor()
    blocks = sum(len(s['blocks']) for s in secs)
    ctx.db.audit('import', file=os.path.basename(path), sections=len(ids))
    info(parent, L(f'استُورد {len(ids)} قسماً و{blocks} كتلة و{len(imgs)} صورة. راجعها في المحرر.',
                   f'Imported {len(ids)} sections, {blocks} blocks and {len(imgs)} images. Review them in the editor.'))
    return True


class ManualsTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.db = ctx, ctx.db
        new = button(L('دليل جديد…', 'New manual…'), 'plus', 'primary')
        new.clicked.connect(self.new)
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


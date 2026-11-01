"""Producing the manual: PDF ready to print, a Word file to edit elsewhere, and the interactive copy (one HTML file
with a side index, search and a language switch) to send to staff or put on the intranet."""
import os
from datetime import date

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QFileDialog, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from ..core.html import build_html
from .common import L, error, info
from .theme import button, card, hint, muted


class ExportTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.db = ctx, ctx.db
        self.mid = None
        self.job = None
        self.approved_only = QCheckBox(L('الأقسام المعتمدة فقط', 'Approved sections only'))
        self.open_after = QCheckBox(L('فتح الملف بعد إنشائه', 'Open the file when it is ready'))
        self.open_after.setChecked(True)
        pdf = button(L('PDF للطباعة…', 'PDF for printing…'), 'pdf', 'primary')
        pdf.clicked.connect(self.export_pdf)
        word = button(L('ملف Word…', 'Word file…'), 'word')
        word.clicked.connect(self.export_docx)
        web = button(L('نسخة تفاعلية (HTML)…', 'Interactive copy (HTML)…'), 'globe')
        web.clicked.connect(self.export_web)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()
        self.state = muted('')
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        row = QHBoxLayout()
        for b in (pdf, word, web):
            row.addWidget(b)
        row.addStretch(1)
        box = card(L('تصدير الدليل', 'Export the manual'))
        bl = QVBoxLayout(box)
        bl.addWidget(hint(L('PDF: الصفحات كما في المعاينة بالترويسة والتذييل وأرقام الصفحات والفهرس، جاهز للطباعة والتوزيع. '
                            'Word: الأقسام والجداول والصور والهيكل بعناوين Word، للتعديل خارج البرنامج (يُحدَّث الفهرس عند فتحه). '
                            'النسخة التفاعلية: ملف واحد يُفتح في أي متصفح، بفهرس جانبي وبحث وتبديل اللغة.',
                            'PDF: the pages as in the preview, with header, footer, page numbers and contents, ready to print and share. '
                            'Word: the sections, tables, images and chart with Word headings, for editing outside the program (the contents refresh when it opens). '
                            'Interactive copy: one file that opens in any browser, with a side index, search and a language switch.')))
        bl.addWidget(self.summary)
        bl.addWidget(self.approved_only)
        bl.addWidget(self.open_after)
        bl.addLayout(row)
        bl.addWidget(self.progress)
        bl.addWidget(self.state)
        inner = QWidget()
        inner.setMaximumWidth(1000)
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.addWidget(box)
        il.addStretch(1)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 14)
        lay.addWidget(inner, 1)

    def load_manual(self, mid):
        self.mid = mid
        self.approved_only.setVisible(self.ctx.workflow)
        if not mid:
            self.summary.setText(L('لا يوجد دليل مفتوح.', 'No manual is open.'))
            return
        st = self.db.stats(mid)
        m = self.db.manual(mid)
        self.summary.setText(L(f'«{m["title_ar"] or m["title_en"]}»: {st["sections"]} قسماً، منها {st["policies"]} سياسة، '
                               f'و{st["units"]} وظيفة في الهيكل، و{st["controls"]} بنداً في سجل الالتزام.',
                               f'«{m["title_en"] or m["title_ar"]}»: {st["sections"]} sections including {st["policies"]} policies, '
                               f'{st["units"]} positions in the chart and {st["controls"]} compliance items.'))

    def _only(self):
        if self.ctx.workflow and self.approved_only.isChecked():
            return [s['id'] for s in self.db.sections(self.mid) if s['status'] == 'approved' or s['kind'] in ('cover', 'toc', 'disclaimer', 'doc_control')]
        return None

    def _allowed(self):
        if not self.mid:
            info(self, L('افتح دليلاً أولاً.', 'Open a manual first.'))
            return False
        if not self.ctx.license().can_export:
            self.ctx.license_blocked(self)
            return self.ctx.license(refresh=True).can_export
        return True

    def _path(self, ext, filt):
        m = self.db.manual(self.mid)
        name = (m['title_en'] or m['title_ar'] or 'manual').strip().replace('/', '-')
        last = self.db.get('export_dir') or os.path.expanduser('~/Documents')
        path, _ = QFileDialog.getSaveFileName(self, L('حفظ', 'Save'), os.path.join(last, f'{name} {date.today().isoformat()}.{ext}'), filt)
        if path:
            self.db.set('export_dir', os.path.dirname(path))
        return path

    def _done(self, path):
        self.progress.hide()
        self.state.setText(L(f'حُفظ: {path}', f'Saved: {path}'))
        self.db.audit('export', manual=self.mid, file=os.path.basename(path))
        if self.open_after.isChecked():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def export_pdf(self):
        if not self._allowed():
            return
        path = self._path('pdf', 'PDF (*.pdf)')
        if not path:
            return
        from ..core.pdf import PdfJob, page_size_mm, write_html
        html = build_html(self.db, self.mid, 'print', only=self._only(), workflow=self.ctx.workflow)
        src = write_html(html, os.path.join(self.ctx.data_dir, 'export'), 'export.html')
        self.job = PdfJob(src, path, page_size_mm(self.db.manual(self.mid)))
        self.job.progress.connect(lambda n: self.state.setText(L(f'جارٍ ترتيب الصفحات… {n}', f'Laying out the pages… {n}')))
        self.job.finished.connect(lambda ok, msg: self._done(path) if ok else (self.progress.hide(), error(self, L('تعذّر إنشاء PDF.', 'The PDF could not be created.') + f'\n{msg}')))
        self.progress.show()
        self.job.start()

    def export_docx(self):
        if not self._allowed():
            return
        path = self._path('docx', 'Word (*.docx)')
        if not path:
            return
        from ..core.docx_export import export_docx
        self.progress.show()
        self.state.setText(L('جارٍ إنشاء ملف Word…', 'Creating the Word file…'))
        self.repaint()
        try:
            export_docx(self.db, self.mid, path)
        except Exception as e:  # noqa: BLE001
            self.progress.hide()
            error(self, L('تعذّر إنشاء ملف Word.', 'The Word file could not be created.') + f'\n{e}')
            return
        self._done(path)

    def export_web(self):
        if not self._allowed():
            return
        path = self._path('html', 'HTML (*.html)')
        if not path:
            return
        try:
            html = build_html(self.db, self.mid, 'web', only=self._only(), workflow=self.ctx.workflow)
            with open(path, 'w', encoding='utf-8') as f:
                f.write(html)
        except OSError as e:
            error(self, str(e))
            return
        self._done(path)

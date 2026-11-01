"""The checker page: runs core.doctor over the open manual (and, when asked, measures the laid-out pages), lists
what it found with its place, and lets the user fix all the safe points at once, the chosen points only, or one
point by hand (the text is edited here, or the place opens in the editor). The last fix can be undone."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QProgressBar, QPushButton, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core import doctor
from ..core.doctor import CATEGORIES, RULES, SEVERITIES
from .common import DataTable, L, norm
from .theme import SizedDialog, a11y, button, card, flow_row, hint, muted, name_buttons

SEV_MARK = {'error': '✖', 'warning': '⚠', 'info': 'ℹ'}


class DoctorSettings(SizedDialog):
    """Which rules run, and what the checker may do by itself."""

    def __init__(self, parent, db):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle(L('إعدادات المدقق', 'Checker settings'))
        p = doctor.load_prefs(db)
        self.before_export = QCheckBox(L('فحص الدليل قبل كل تصدير وعرض الملاحظات إن وُجدت أخطاء أو تحذيرات',
                                         'Check the manual before every export and show the points when there are errors or warnings'))
        self.auto_save = QCheckBox(L('ضبط آمن عند حفظ القسم: العلامات الخفية، ورموز Word، ورموز التعداد المكررة، والمسافات',
                                     'Safe tidying when a section is saved: hidden marks, Word symbols, repeated list markers, spaces'))
        self.auto_import = QCheckBox(L('ضبط آمن بعد الاستيراد: إضافة إلى ما سبق تحويل التعداد اليدوي إلى قوائم، وحذف الكتل الفارغة، '
                                       'وتسوية الجداول، ونقل النص إلى خانة لغته',
                                       'Safe tidying after an import: the above plus typed lists made lists, empty blocks removed, '
                                       'tables evened, text moved to the box of its language'))
        self.layout = QCheckBox(L('قياس الصفحات الفعلية مع كل فحص (أدق وأبطأ)', 'Measure the actual pages with every check (more exact, slower)'))
        for w, k in ((self.before_export, 'before_export'), (self.auto_save, 'auto_save'), (self.auto_import, 'auto_import'),
                     (self.layout, 'layout')):
            w.setChecked(bool(p.get(k)))
        self.digits = QComboBox()
        for k, (ar, en) in (('keep', ('دون توحيد (التنبيه على الخلط داخل النص الواحد فقط)', 'Leave them (note mixing inside one text only)')),
                            ('latin', ('لاتينية (1، 2، 3)', 'Western (1, 2, 3)')), ('arabic', ('عربية مشرقية (١، ٢، ٣)', 'Arabic-Indic (١, ٢, ٣)'))):
            self.digits.addItem(L(ar, en), k)
        self.digits.setCurrentIndex(max(0, self.digits.findData(p.get('text_digits', 'keep'))))
        a11y(self.digits, L('الأرقام داخل النص العربي', 'Digits inside Arabic text'))
        drow = QHBoxLayout()
        drow.addWidget(QLabel(L('الأرقام داخل النص العربي:', 'Digits inside Arabic text:')))
        drow.addWidget(self.digits, 1)
        self.rules = QTreeWidget()
        self.rules.setHeaderLabels([L('القاعدة', 'Rule'), L('الخطورة', 'Severity')])
        a11y(self.rules, L('قواعد الفحص', 'Checking rules'))
        disabled, enabled = set(p.get('disabled') or []), set(p.get('enabled') or [])
        cats = {}
        for code, (cat, sev, _safe, on, title) in RULES.items():
            parent = cats.get(cat)
            if parent is None:
                parent = cats[cat] = QTreeWidgetItem([L(*CATEGORIES[cat]), ''])
                parent.setFlags(parent.flags() | Qt.ItemIsAutoTristate | Qt.ItemIsUserCheckable)
                self.rules.addTopLevelItem(parent)
            it = QTreeWidgetItem([L(*title), L(*SEVERITIES[sev])])
            it.setData(0, Qt.UserRole, code)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Checked if ((on and code not in disabled) or code in enabled) else Qt.Unchecked)
            parent.addChild(it)
        self.rules.expandAll()
        self.rules.resizeColumnToContents(0)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText(L('حفظ', 'Save'))
        bb.button(QDialogButtonBox.Cancel).setText(L('إلغاء', 'Cancel'))
        name_buttons(bb)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        for w in (self.before_export, self.auto_save, self.auto_import, self.layout):
            lay.addWidget(w)
        lay.addLayout(drow)
        lay.addWidget(muted(L('القواعد المفعّلة:', 'Rules in use:')))
        lay.addWidget(self.rules, 1)
        lay.addWidget(bb)
        self.resize(760, 680)

    def _save(self):
        disabled, enabled = [], []
        for i in range(self.rules.topLevelItemCount()):
            cat = self.rules.topLevelItem(i)
            for j in range(cat.childCount()):
                it = cat.child(j)
                code = it.data(0, Qt.UserRole)
                on = it.checkState(0) == Qt.Checked
                if RULES[code][3] and not on:
                    disabled.append(code)
                elif not RULES[code][3] and on:
                    enabled.append(code)
        p = doctor.load_prefs(self.db)
        p.update(disabled=disabled, enabled=enabled, before_export=self.before_export.isChecked(),
                 auto_save=self.auto_save.isChecked(), auto_import=self.auto_import.isChecked(),
                 layout=self.layout.isChecked(), text_digits=self.digits.currentData())
        doctor.save_prefs(self.db, p)
        self.accept()


class DoctorTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.db = ctx, ctx.db
        self.mid = None
        self.issues = []
        self.layout_issues = []
        self.measured = False
        self.undo_data = None
        self.job = None
        self.titles = {}
        self.cur = None

        run = button(L('فحص الدليل', 'Check the manual'), 'shield', 'primary')
        run.clicked.connect(lambda: self.run())
        self.measure = QCheckBox(L('مع قياس الصفحات الفعلية', 'Measuring the actual pages too'))
        self.measure.setToolTip(L('يرتّب الصفحات كما تُطبع ويقيس ما يتجاوز حدودها، وما يبقى وحده في أسفل الصفحة، والصفحات الفارغة',
                                  'Lays out the pages as they print and measures what runs past them, what stays alone at the foot of a page, and blank pages'))
        self.fix_safe = button(L('إصلاح كل الآمن', 'Fix all safe points'), 'check',
                               tip=L('الإصلاحات التي ترتّب النص ولا تغيّر شكل الصفحة', 'Fixes that tidy the text without changing how the page looks'))
        self.fix_safe.clicked.connect(self.fix_all_safe)
        self.undo_btn = button(L('تراجع عن آخر إصلاح', 'Undo the last fix'), 'reset')
        self.undo_btn.clicked.connect(self.undo)
        self.undo_btn.setEnabled(False)
        self.show_hidden = QCheckBox(L('إظهار المخفي', 'Show hidden'))
        self.show_hidden.toggled.connect(lambda _: self.run(measure=False))
        settings = button(L('إعدادات المدقق…', 'Checker settings…'), 'calibrate')
        settings.clicked.connect(self.settings)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setMaximumWidth(220)
        self.progress.hide()
        self.state = muted('')
        top = QHBoxLayout()
        for w in (run, self.measure, self.fix_safe, self.undo_btn):
            top.addWidget(w)
        top.addStretch(1)
        top.addWidget(self.show_hidden)
        top.addWidget(settings)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)

        self.table = DataTable(
            [(L('الخطورة', 'Severity'), 'select'), (L('الفئة', 'Category'), 'select'), (L('الموضع', 'Place'), 'text'),
             (L('الصفحة', 'Page'), 'num'), (L('الملاحظة', 'Point'), 'text'), (L('الإصلاح المقترح', 'Suggested fix'), 'text')],
            [(L('إصلاح المحدد', 'Fix the selected'), self.fix_ids, False, 'check'),
             (L('فتح في المحرر', 'Open in the editor'), lambda ids: ids and self.goto(ids[0]), False, 'edit'),
             (L('إخفاء المحدد', 'Hide the selected'), lambda ids: self.hide(ids, True), False, 'off'),
             (L('إظهار المحدد', 'Show the selected'), lambda ids: self.hide(ids, False), False, 'on')],
            export_name='checker', title=L('ملاحظات المدقق', 'Checker points'))
        self.table.activated.connect(self.goto)
        self.table.selection_changed.connect(lambda ids: self.show_issue(ids[0] if len(ids) == 1 else None))

        # the chosen point
        self.d_title = QLabel()
        self.d_title.setStyleSheet('font-weight:700;font-size:14px')
        self.d_title.setWordWrap(True)
        self.d_where = muted('')
        self.d_where.setWordWrap(True)
        self.d_msg = QLabel()
        self.d_msg.setWordWrap(True)
        self.d_fix = QLabel()
        self.d_fix.setWordWrap(True)
        self.ed_ar = QPlainTextEdit()
        self.ed_ar.setLayoutDirection(Qt.RightToLeft)
        a11y(self.ed_ar, L('النص العربي', 'Arabic text'))
        self.ed_en = QPlainTextEdit()
        self.ed_en.setLayoutDirection(Qt.LeftToRight)
        a11y(self.ed_en, L('النص الإنجليزي', 'English text'))
        self.lab_ar, self.lab_en = muted(L('العربية', 'Arabic')), muted(L('الإنجليزية', 'English'))
        self.after = QLabel()
        self.after.setWordWrap(True)
        self.after.setTextFormat(Qt.PlainText)
        self.save_text = button(L('حفظ التعديل', 'Save the change'), 'save')
        self.save_text.clicked.connect(self.save_manual_edit)
        self.fix_one = button(L('إصلاح هذه', 'Fix this one'), 'check', 'primary')
        self.fix_one.clicked.connect(lambda: self.cur is not None and self.fix_ids([self.cur]))
        self.open_one = button(L('فتح في المحرر', 'Open in the editor'), 'edit')
        self.open_one.clicked.connect(lambda: self.cur is not None and self.goto(self.cur))
        brow = flow_row([self.fix_one, self.save_text, self.open_one])
        detail = card(L('الملاحظة المحددة', 'The chosen point'))
        dl = QVBoxLayout(detail)
        for w in (self.d_title, self.d_where, self.d_msg, self.d_fix, self.after, self.lab_ar, self.ed_ar, self.lab_en, self.ed_en):
            dl.addWidget(w)
        dl.addWidget(brow)
        dl.addStretch(1)
        detail.setMinimumWidth(340)
        self.detail = detail

        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addLayout(self.chips)
        ll.addWidget(self.table, 1)
        split.addWidget(left)
        split.addWidget(detail)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 1)
        split.setSizes([900, 380])

        box = card(L('مدقق الدليل', 'Manual checker'))
        bl = QVBoxLayout(box)
        bl.addWidget(hint(L('يفحص الدليل كاملاً: أبعاد الصفحة والهوامش، وأرقام الصفحات والترويسة والتذييل، والجداول، واتجاه النص ولغته، '
                            'والقوائم والرموز، وفواصل الصفحات، والعناوين، والصور. لا يغيّر شيئاً إلا بأمر منك: أصلح الكل الآمن، أو '
                            'حدّد ما تريد، أو عدّل النص هنا، أو افتح الموضع في المحرر.',
                            'Checks the whole manual: page size and margins, page numbers, header and footer, tables, text direction '
                            'and language, lists and symbols, page breaks, titles and images. It changes nothing unless you say so: '
                            'fix all safe points, choose the ones you want, edit the text here, or open the place in the editor.')))
        bl.addLayout(top)
        prow = QHBoxLayout()
        prow.addWidget(self.progress)
        prow.addWidget(self.state, 1)
        bl.addLayout(prow)
        bl.addWidget(split, 1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 14)
        lay.addWidget(box, 1)
        self.show_issue(None)

    # ── running ──────────────────────────────────────────────────────
    def load_manual(self, mid):
        if mid != self.mid:
            self.issues, self.layout_issues, self.measured, self.undo_data = [], [], False, None
            self.undo_btn.setEnabled(False)
        self.mid = mid
        self.measure.setChecked(bool(doctor.load_prefs(self.db).get('layout')))
        self.fill()

    def prefs(self):
        return dict(doctor.load_prefs(self.db), show_hidden=self.show_hidden.isChecked())

    def run(self, measure=None):
        if not self.mid:
            self.state.setText(L('لا يوجد دليل مفتوح.', 'No manual is open.'))
            return
        ed = self.ctx.window.editor if self.ctx.window else None
        if ed is not None and ed.dirty:
            ed.save(quiet=True)
        self.check_static()
        if measure if measure is not None else self.measure.isChecked():
            self.start_measure()
        else:
            self.fill()

    def check_static(self):
        self.issues = doctor.check(self.db, self.mid, self.prefs(), self.ctx.workflow)
        self.titles = {s['id']: s for s in self.db.sections(self.mid, False)}

    def start_measure(self):
        from ..core.html import build_html
        from ..core.pdf import PdfJob, page_size_mm, write_html
        if self.job:
            return
        html = build_html(self.db, self.mid, 'print', workflow=self.ctx.workflow)
        src = write_html(html, os.path.join(self.ctx.data_dir, 'export'), 'check.html')
        self.job = PdfJob(src, '', page_size_mm(self.db.manual(self.mid)), audit=True)
        self.job.progress.connect(lambda n: self.state.setText(L(f'جارٍ ترتيب الصفحات وقياسها… {n}', f'Laying out and measuring the pages… {n}')))
        self.job.finished.connect(self._measured)
        self.progress.show()
        self.fill()
        self.job.start()

    def _measured(self, ok, msg):
        import json
        self.progress.hide()
        self.job = None
        if not ok:
            self.state.setText(L('تعذّر قياس الصفحات: ', 'The pages could not be measured: ') + msg)
            return
        audit = json.loads(msg)
        self.layout_issues = doctor.from_audit(self.db, self.mid, audit, self.prefs(), self.ctx.workflow)
        self.measured = audit.get('pages')
        self.fill()

    def all_issues(self):
        return self.issues + self.layout_issues

    def fill(self):
        while self.chips.count():
            it = self.chips.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        rows = []
        items = self.all_issues()
        counts = {k: 0 for k in SEVERITIES}
        fixable = 0
        for i, x in enumerate(items):
            counts[x['sev']] += 1
            fixable += bool(x['fix']) and not x['locked']
            fix = L(*x['fix']) if x['fix'] else L('يُصلَح يدوياً', 'Fixed by hand')
            if x['locked']:
                fix = L('القسم معتمد: أعده إلى مسودة أولاً', 'The section is approved: return it to draft first')
            sev = f'{SEV_MARK[x["sev"]]} {L(*SEVERITIES[x["sev"]])}'
            text = L(*x['msg']) + (f' — «{x["sample"]}»' if x.get('sample') else '')
            if x.get('hidden'):
                text = L('(مخفية) ', '(hidden) ') + text
            rows.append((i, [(sev, doctor.SEV_ORDER[x['sev']]), L(*CATEGORIES[x['cat']]),
                             doctor.location(self.db, x, L, self.titles) if self.mid else '',
                             (str(x['page']) if x.get('page') else '', x.get('page') or 0), text, fix]))
        self.table.set_rows(rows)
        self.table.view.sortByColumn(0, Qt.AscendingOrder)       # errors first
        if not self.mid:
            self.state.setText(L('لا يوجد دليل مفتوح.', 'No manual is open.'))
            return
        self._chip(L(f'الكل ({len(items)})', f'All ({len(items)})'), None, None)
        for k in SEVERITIES:
            self._chip(f'{SEV_MARK[k]} {L(*SEVERITIES[k])} ({counts[k]})', 0, f'{SEV_MARK[k]} {L(*SEVERITIES[k])}')
        self.chips.addStretch(1)
        safe = sum(1 for x in items if x['safe'] and not x['locked'])
        self.fix_safe.setText(L(f'إصلاح كل الآمن ({safe})', f'Fix all safe points ({safe})'))
        self.fix_safe.setEnabled(bool(safe) and self.ctx.can('edit'))
        if self.job:
            return
        if not items:
            self.state.setText(L('لم يجد المدقق ما يحتاج إلى إصلاح.', 'The checker found nothing to fix.')
                               + (L(f' (قيست {self.measured} صفحة)', f' ({self.measured} pages measured)') if self.measured else ''))
        else:
            self.state.setText(L(f'{len(items)} ملاحظة، منها {fixable} لها إصلاح جاهز.', f'{len(items)} points, {fixable} with a ready fix.')
                               + (L(f' قيست {self.measured} صفحة.', f' {self.measured} pages measured.') if self.measured else
                                  L(' لم تُقس الصفحات الفعلية.', ' The actual pages were not measured.')))

    def _chip(self, text, col, value):
        b = QPushButton(text)
        b.setProperty('ghost', True)
        b.setCursor(Qt.PointingHandCursor)
        a11y(b, text)

        def go():
            for w in self.table.filter_widgets:
                if isinstance(w, QLineEdit):
                    w.setText('')
                elif isinstance(w, QComboBox):
                    w.setCurrentIndex(0)
            if col is not None:
                w = self.table.filter_widgets[col]
                w.setCurrentIndex(max(0, w.findData(norm(value))))
        b.clicked.connect(go)
        self.chips.addWidget(b)

    # ── one point ────────────────────────────────────────────────────
    def show_issue(self, i):
        items = self.all_issues()
        self.cur = i if i is not None and i < len(items) else None
        x = items[self.cur] if self.cur is not None else None
        for w in (self.d_where, self.d_msg, self.d_fix, self.after, self.lab_ar, self.ed_ar, self.lab_en, self.ed_en,
                  self.save_text, self.fix_one, self.open_one):
            w.setVisible(x is not None)
        if x is None:
            self.d_title.setText(L('اختر ملاحظة من القائمة لعرضها وإصلاحها، أو حدّد عدة ملاحظات وأصلحها معاً.',
                                   'Choose a point in the list to see and fix it, or select several and fix them together.'))
            return
        title = RULES[x['rule']][4]
        self.d_title.setText(f'{SEV_MARK[x["sev"]]} {L(*title)}')
        self.d_where.setText(doctor.location(self.db, x, L, self.titles) + (L(f' — الصفحة {x["page"]}', f' — page {x["page"]}') if x.get('page') else ''))
        self.d_msg.setText(L(*x['msg']))
        self.d_fix.setText((L('الإصلاح: ', 'Fix: ') + L(*x['fix'])) if x['fix'] else L('لا إصلاح آلياً: عدّل النص هنا أو افتح الموضع في المحرر.',
                                                                                     'No automatic fix: edit the text here or open the place in the editor.'))
        self.fix_one.setVisible(bool(x['fix']))
        self.fix_one.setEnabled(not x['locked'] and self.ctx.can('edit'))
        self.open_one.setVisible(bool(x.get('sid')))
        texts = self._texts(x)
        editable = texts is not None
        for w in (self.lab_ar, self.ed_ar, self.lab_en, self.ed_en, self.save_text):
            w.setVisible(editable)
        self.save_text.setEnabled(editable and not x['locked'] and self.ctx.can('edit'))
        self.after.setVisible(False)
        if editable:
            self.ed_ar.setPlainText(texts[0])
            self.ed_en.setPlainText(texts[1])
            preview = self._preview(x)
            if preview is not None:
                self.after.setText(L('بعد الإصلاح: ', 'After the fix: ') + preview)
                self.after.setVisible(True)

    def _paths(self, x):
        """(Arabic path, English path) of a text point, or None."""
        p = x.get('path') or []
        if p and p[-1] in ('ar', 'en'):
            return p[:-1] + ['ar'], p[:-1] + ['en']
        if p and p[0] in ('title_ar', 'title_en'):
            return ['title_ar'], ['title_en']
        if x.get('b') is not None and not p:
            b = self._block(x)
            if b and b.get('kind') in doctor.TEXT_KINDS:
                return ['ar'], ['en']
        return None

    def _block(self, x):
        bl = self.db.blocks(x['sid']) if x.get('sid') else []
        return bl[x['b']] if x.get('b') is not None and x['b'] < len(bl) else None

    def _texts(self, x):
        paths = self._paths(x)
        if not paths or not x.get('sid'):
            return None
        obj = self._block(x) if x.get('b') is not None else self.db.section(x['sid'])
        if obj is None:
            return None
        from ..core.richtext import plain
        try:
            return tuple(plain(doctor.get_path(obj, p) or '') for p in paths)
        except (KeyError, IndexError, TypeError):
            return None

    def _preview(self, x):
        """The text after the fix, for text fixes (worked out on a copy)."""
        if not x['fix'] or not x.get('path') or x['path'][-1] not in ('ar', 'en', 'title_ar', 'title_en'):
            return None
        from ..core.richtext import plain
        fx = doctor.Fixer(self.db, self.mid)
        try:
            fn = getattr(fx, 'fix_' + x['rule'])
            fn(x)
            t = fx.target(x)
            return plain(doctor.get_path(t, x['path']) or '') or L('(فارغ)', '(empty)')
        except (AttributeError, KeyError, IndexError, TypeError, ValueError):
            return None

    def save_manual_edit(self):
        """The text as typed here, written back to its place (the other formatting of that text is replaced)."""
        if self.cur is None:
            return
        x = self.all_issues()[self.cur]
        paths = self._paths(x)
        if not paths:
            return
        from html import escape
        fx = doctor.Fixer(self.db, self.mid)
        from ..core.richtext import plain
        t = fx.target(x)
        for p, ed in zip(paths, (self.ed_ar, self.ed_en)):
            old = doctor.get_path(t, p) or ''
            new = ed.toPlainText().strip()
            if new == plain(old).strip():
                continue                     # unchanged: its formatting is kept
            block = self._block(x) if x.get('b') is not None else None
            if block and block.get('kind') in ('bullets', 'numbered') and len(p) == 1:
                doctor.set_path(t, p, new)            # a list keeps one item per line
            else:
                doctor.set_path(t, p, escape(new, quote=False).replace('\n', '<br>'))
        if x.get('b') is not None:
            fx.bl(x['sid'])
        fx.done = 1
        self.undo_data = fx.commit('doctor_edit')
        self.undo_btn.setEnabled(True)
        self._after_change(L('حُفظ التعديل.', 'The change is saved.'))

    # ── actions ──────────────────────────────────────────────────────
    def fix_ids(self, ids):
        items = self.all_issues()
        chosen = [items[i] for i in ids if i < len(items)]
        self._fix(chosen)

    def fix_all_safe(self):
        self._fix([x for x in self.all_issues() if x['safe'] and not x['locked']])

    def _fix(self, chosen):
        if not chosen or not self.mid or not self.ctx.can('edit'):
            return
        ed = self.ctx.window.editor if self.ctx.window else None
        if ed is not None and ed.dirty:
            ed.save(quiet=True)
        done, skipped, undo = doctor.apply(self.db, self.mid, chosen)
        self.undo_data = undo
        self.undo_btn.setEnabled(True)
        fixed_layout = {x['key'] for x in chosen if x['cat'] == 'layout' and x['fix'] and not x['locked']}
        self.layout_issues = [x for x in self.layout_issues if x['key'] not in fixed_layout]
        text = L(f'أُصلحت {done} ملاحظة.', f'{done} point(s) fixed.')
        if skipped:
            text += L(f' {skipped} بلا إصلاح آلي أو في أقسام معتمدة.', f' {skipped} without an automatic fix or in approved sections.')
        if fixed_layout:
            text += L(' أعد الفحص مع القياس للتأكد من توزيع الصفحات.', ' Check again with measuring to confirm the page layout.')
        self._after_change(text)

    def undo(self):
        if not self.undo_data:
            return
        doctor.undo(self.db, self.undo_data)
        self.undo_data = None
        self.undo_btn.setEnabled(False)
        self.layout_issues = []
        self._after_change(L('أُعيد ما كان قبل آخر إصلاح.', 'The last fix was undone.'))

    def _after_change(self, text):
        self.check_static()
        self.fill()
        self.state.setText(text + ' ' + self.state.text())
        if self.ctx.window:
            w = self.ctx.window
            w.editor.load_manual(self.mid)
            w.design.load_manual(self.mid)

    def hide(self, ids, on):
        items = self.all_issues()
        keys = [items[i]['key'] for i in ids if i < len(items)]
        if keys and self.mid:
            doctor.ignore(self.db, self.mid, keys, on)
            self.check_static()
            if on:
                self.layout_issues = [x for x in self.layout_issues if x['key'] not in keys]
            self.fill()

    def goto(self, i):
        items = self.all_issues()
        if i is None or i >= len(items):
            return
        x = items[i]
        w = self.ctx.window
        if not w:
            return
        if not x.get('sid'):
            w.show_page(w.design)
            return
        w.show_page(w.editor)
        w.editor.goto(x['sid'], x.get('b'), x.get('path'))

    def settings(self):
        if DoctorSettings(self, self.db).exec():
            self.measure.setChecked(bool(doctor.load_prefs(self.db).get('layout')))
            if self.mid:
                self.run(measure=False)


def check_before_export(parent, ctx, mid):
    """True when the export may go on. With problems found, offers to show them on the checker page."""
    p = doctor.load_prefs(ctx.db)
    if not p.get('before_export'):
        return True
    issues = [x for x in doctor.check(ctx.db, mid, p, ctx.workflow) if x['sev'] in ('error', 'warning')]
    if not issues:
        return True
    from PySide6.QtWidgets import QMessageBox
    errors = sum(1 for x in issues if x['sev'] == 'error')
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(L('مدقق الدليل', 'Manual checker'))
    box.setText(L(f'وجد المدقق {errors} خطأ و{len(issues) - errors} تحذيراً قد تظهر في الملف.',
                  f'The checker found {errors} error(s) and {len(issues) - errors} warning(s) that may show in the file.'))
    show = box.addButton(L('عرضها', 'Show them'), QMessageBox.AcceptRole)
    go = box.addButton(L('التصدير على أي حال', 'Export anyway'), QMessageBox.DestructiveRole)
    box.addButton(L('إلغاء', 'Cancel'), QMessageBox.RejectRole)
    box.exec()
    if box.clickedButton() is go:
        return True
    if box.clickedButton() is show and ctx.window:
        ctx.window.open_doctor(run=True)
    return False


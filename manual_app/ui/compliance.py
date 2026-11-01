"""The compliance register of the current manual: each requirement (from a standard, a law, an accreditation body or
the board) with its owner, frequency, evidence, status and review dates, linked to the policy that covers it.
Numbers at the top open the list filtered; items whose review is due are flagged."""
from datetime import date, timedelta

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (QComboBox, QDateEdit, QDialogButtonBox, QHBoxLayout, QLineEdit, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from ..core.db import CONTROL_STATUSES
from .common import DataTable, L, confirm, error
from .theme import SizedDialog, a11y, button, card, field, fit, form_grid, hint, ltr, name_buttons

FREQUENCIES = [('سنوي', 'Annual'), ('نصف سنوي', 'Semi-annual'), ('ربع سنوي', 'Quarterly'), ('شهري', 'Monthly'),
               ('عند الحاجة', 'As needed')]


class ControlDialog(SizedDialog):
    def __init__(self, parent, ctx, mid, control=None):
        super().__init__(parent)
        self.ctx, self.db, self.mid, self.c = ctx, ctx.db, mid, control or {}
        self.setWindowTitle(L('بند التزام', 'Compliance item'))
        c = self.c
        self.code = ltr(QLineEdit(c.get('code') or ''), 140)
        self.title_ar = QLineEdit(c.get('title_ar') or '')
        self.title_en = ltr(QLineEdit(c.get('title_en') or ''))
        self.req_ar = QPlainTextEdit(c.get('requirement_ar') or '')
        self.req_ar.setFixedHeight(70)
        self.req_en = QPlainTextEdit(c.get('requirement_en') or '')
        self.req_en.setFixedHeight(70)
        self.req_en.setLayoutDirection(Qt.LeftToRight)
        self.framework = QComboBox()
        self.framework.setEditable(True)
        used = sorted({x['framework'] for x in self.db.controls(mid, False) if x.get('framework')})
        self.framework.addItems(used or ['CIS', 'ISO 9001', 'ISO 27001', L('وزارة التربية والتعليم', 'Ministry of Education'),
                                         L('مجلس الإدارة', 'Board')])
        self.framework.setCurrentText(c.get('framework') or '')
        self.owner = QLineEdit(c.get('owner') or '')
        self.frequency = QComboBox()
        self.frequency.setEditable(True)
        self.frequency.addItems([L(a, e) for a, e in FREQUENCIES])
        self.frequency.setCurrentText(c.get('frequency') or '')
        self.evidence = QLineEdit(c.get('evidence') or '')
        self.evidence.setPlaceholderText(L('مثلاً: محضر اجتماع، تقرير، سجل', 'e.g. minutes, report, log'))
        self.status = QComboBox()
        for k, (ar, en) in CONTROL_STATUSES.items():
            self.status.addItem(L(ar, en), k)
        self.status.setCurrentIndex(max(0, self.status.findData(c.get('status') or 'open')))
        self.policy = QComboBox()
        self.policy.addItem(L('— بلا ربط —', '— Not linked —'), None)
        for s in self.db.sections(mid):
            if s['kind'] in ('policy', 'text', 'table'):
                self.policy.addItem(s['title_ar'] or s['title_en'] or '', s['id'])
        self.policy.setCurrentIndex(max(0, self.policy.findData(c.get('section_id'))))
        self.last = self._date(c.get('last_review'))
        self.next = self._date(c.get('next_review'))
        self.notes = QLineEdit(c.get('notes') or '')
        for w, n in ((self.framework, 260), (self.frequency, 200), (self.status, 200), (self.policy, 360)):
            fit(w, n)
        g = form_grid()
        field(g, 0, 0, L('الرمز', 'Code'), self.code)
        field(g, 0, 2, L('المرجعية', 'Framework'), self.framework)
        field(g, 1, 0, L('البند بالعربية *', 'Arabic title *'), self.title_ar, 3)
        field(g, 2, 0, L('البند بالإنجليزية', 'English title'), self.title_en, 3)
        field(g, 3, 0, L('المتطلب (عربي)', 'Requirement (Arabic)'), self.req_ar, 3)
        field(g, 4, 0, L('المتطلب (إنجليزي)', 'Requirement (English)'), self.req_en, 3)
        field(g, 5, 0, L('المسؤول', 'Owner'), self.owner)
        field(g, 5, 2, L('الدورية', 'Frequency'), self.frequency)
        field(g, 6, 0, L('الدليل', 'Evidence'), self.evidence)
        field(g, 6, 2, L('الحالة', 'Status'), self.status)
        field(g, 7, 0, L('السياسة المرتبطة', 'Linked policy'), self.policy, 3)
        field(g, 8, 0, L('آخر مراجعة', 'Last review'), self.last)
        field(g, 8, 2, L('المراجعة القادمة', 'Next review'), self.next)
        field(g, 9, 0, L('ملاحظات', 'Notes'), self.notes, 3)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(3, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText(L('حفظ', 'Save'))
        bb.button(QDialogButtonBox.Cancel).setText(L('إلغاء', 'Cancel'))
        name_buttons(bb)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(g)
        lay.addWidget(bb)
        self.resize(820, 600)

    def _date(self, v):
        d = QDateEdit()
        d.setCalendarPopup(True)
        d.setDisplayFormat('yyyy-MM-dd')
        d.setMinimumDate(QDate(2000, 1, 1))
        d.setSpecialValueText(L('بلا موعد', 'No date'))
        d.setDate(QDate.fromString(v, 'yyyy-MM-dd') if v else d.minimumDate())
        fit(d, 150)
        return d

    def _val(self, d):
        return None if d.date() == d.minimumDate() else d.date().toString('yyyy-MM-dd')

    def _save(self):
        if not self.title_ar.text().strip() and not self.title_en.text().strip():
            error(self, L('اكتب البند.', 'Enter the item.'))
            return
        data = {'manual_id': self.mid, 'code': self.code.text().strip(), 'title_ar': self.title_ar.text().strip(),
                'title_en': self.title_en.text().strip(), 'requirement_ar': self.req_ar.toPlainText().strip(),
                'requirement_en': self.req_en.toPlainText().strip(), 'framework': self.framework.currentText().strip(),
                'owner': self.owner.text().strip(), 'frequency': self.frequency.currentText().strip(),
                'evidence': self.evidence.text().strip(), 'status': self.status.currentData(),
                'section_id': self.policy.currentData(), 'last_review': self._val(self.last),
                'next_review': self._val(self.next), 'notes': self.notes.text().strip()}
        self.db.save_control(data, self.c.get('id'))
        self.accept()


class ComplianceTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.db = ctx, ctx.db
        self.mid = None
        new = button(L('بند جديد…', 'New item…'), 'plus', 'primary')
        new.clicked.connect(lambda: self.edit(None))
        self.stats = QHBoxLayout()
        self.table = DataTable(
            [(L('الرمز', 'Code'), 'text'), (L('البند', 'Item'), 'text'), (L('المرجعية', 'Framework'), 'select'),
             (L('المسؤول', 'Owner'), 'select'), (L('الدورية', 'Frequency'), 'select'), (L('الحالة', 'Status'), 'select'),
             (L('السياسة', 'Policy'), 'select'), (L('المراجعة القادمة', 'Next review'), 'text'),
             (L('التفعيل', 'Active'), 'select')],
            [(L('ملتزم', 'Compliant'), lambda ids: self._status(ids, 'compliant'), False, 'check'),
             (L('التزام جزئي', 'Partial'), lambda ids: self._status(ids, 'partial'), False, 'flag'),
             (L('غير ملتزم', 'Non-compliant'), lambda ids: self._status(ids, 'non'), False, 'cancel'),
             (L('تفعيل', 'Activate'), lambda ids: self._active(ids, True), False, 'on'),
             (L('تعطيل', 'Deactivate'), lambda ids: self._active(ids, False), False, 'off'),
             (L('حذف', 'Delete'), self.delete, True, 'trash')],
            export_name='compliance', title=L('سجل الالتزام', 'Compliance register'))
        self.table.activated.connect(lambda i: self.edit(i))
        top = QHBoxLayout()
        top.addWidget(new)
        top.addStretch(1)
        box = card(L('سجل الالتزام', 'Compliance register'))
        bl = QVBoxLayout(box)
        bl.addWidget(hint(L('يُطبع السجل في الدليل في أي قسم من نوع «سجل الالتزام»، كاملاً أو للسياسة المرتبطة فقط. انقر رقماً لعرض بنوده.',
                            'The register prints in the manual in any section of type «Compliance register», whole or for the linked policy only. Click a number to list its items.')))
        bl.addLayout(top)
        bl.addLayout(self.stats)
        bl.addWidget(self.table, 1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 14)
        lay.addWidget(box, 1)

    def load_manual(self, mid):
        self.mid = mid
        self.reload()

    def reload(self):
        while self.stats.count():
            it = self.stats.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        rows = []
        if not self.mid:
            self.table.set_rows([])
            return
        secs = {s['id']: (s['title_ar'] or s['title_en'] or '') for s in self.db.sections(self.mid, False)}
        limit = (date.today() + timedelta(days=30)).isoformat()
        counts = {k: 0 for k in CONTROL_STATUSES}
        due = 0
        ctrls = self.db.controls(self.mid, active_only=False)
        for c in ctrls:
            st = CONTROL_STATUSES.get(c['status'], ('', ''))
            if c['is_active']:
                counts[c['status']] = counts.get(c['status'], 0) + 1
            nr = c.get('next_review') or ''
            flag = ' ⚠' if nr and nr <= limit and c['is_active'] else ''
            if flag:
                due += 1
            rows.append((c['id'], [c.get('code') or '', c['title_ar'] or c['title_en'] or '', c.get('framework') or '',
                                   c.get('owner') or '', c.get('frequency') or '', L(*st), secs.get(c.get('section_id'), ''),
                                   (nr + flag, nr), L('مفعّل', 'Active') if c['is_active'] else L('معطّل', 'Inactive')]))
        self.table.set_rows(rows)
        self._chip(L(f'الكل ({len(ctrls)})', f'All ({len(ctrls)})'), None, None)
        for k, (ar, en) in CONTROL_STATUSES.items():
            self._chip(f'{L(ar, en)} ({counts.get(k, 0)})', 5, L(ar, en))
        self._chip(L(f'مراجعته مستحقة ({due})', f'Review due ({due})'), 7, '⚠')
        self.stats.addStretch(1)

    def _chip(self, text, col, value):
        b = QPushButton(text)
        b.setProperty('ghost', True)
        b.setCursor(Qt.PointingHandCursor)
        a11y(b, text)

        def go():
            for i, w in enumerate(self.table.filter_widgets):
                if isinstance(w, QLineEdit):
                    w.setText('')
                elif isinstance(w, QComboBox):
                    w.setCurrentIndex(0)
            if col is None:
                return
            w = self.table.filter_widgets[col]
            if isinstance(w, QComboBox):
                from .common import norm
                i = w.findData(norm(value))
                w.setCurrentIndex(max(0, i))
            else:
                w.setText(value)
        b.clicked.connect(go)
        self.stats.addWidget(b)

    def edit(self, cid):
        if not self.mid:
            return
        if ControlDialog(self, self.ctx, self.mid, self.db.control(cid) if cid else None).exec():
            self.reload()

    def _status(self, ids, st):
        for i in ids:
            self.db.save_control({'status': st, 'last_review': date.today().isoformat()}, i)
        self.reload()

    def _active(self, ids, on):
        self.db.set_active('controls', ids, on)
        self.reload()

    def delete(self, ids):
        if ids and confirm(self, L(f'حذف {len(ids)} بند؟', f'Delete {len(ids)} item(s)?')):
            self.db.delete_controls(ids)
            self.reload()

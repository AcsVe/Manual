"""Shared UI pieces: language, the data table (sticky header, a filter under every column, sorting, multi-select
with a bulk-action bar, export), message boxes."""
import csv
import os

from PySide6.QtCore import Qt, QItemSelectionModel, QSortFilterProxyModel, QModelIndex, Signal
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMessageBox, QTableView, QVBoxLayout, QWidget)

_LANG = {'lang': 'ar'}


def set_lang(lang):
    _LANG['lang'] = 'en' if lang == 'en' else 'ar'


def lang():
    return _LANG['lang']


def L(ar, en):
    return en if _LANG['lang'] == 'en' else ar


def norm(v):
    s = str(v or '').lower().strip()
    for a, b in (('أ', 'ا'), ('إ', 'ا'), ('آ', 'ا'), ('ة', 'ه'), ('ى', 'ي'), ('ـ', '')):
        s = s.replace(a, b)
    return s.translate(str.maketrans('٠١٢٣٤٥٦٧٨٩', '0123456789'))


def info(parent, text):
    QMessageBox.information(parent, L('تنبيه', 'Notice'), text)


def error(parent, text):
    QMessageBox.warning(parent, L('خطأ', 'Error'), text)


def confirm(parent, text):
    return QMessageBox.question(parent, L('تأكيد', 'Confirm'), text,
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes


SORT_ROLE = Qt.UserRole + 1
ID_ROLE = Qt.UserRole + 2


class _Proxy(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.filters = {}
        self.search = ''
        self.setSortRole(SORT_ROLE)

    def set_filter(self, col, text):
        self.filters[col] = norm(text)
        self.invalidateFilter()

    def set_search(self, text):
        self.search = norm(text)
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        m = self.sourceModel()
        for col, f in self.filters.items():
            if not f:
                continue
            v = norm(m.index(row, col, parent).data(Qt.DisplayRole))
            if f.startswith('='):
                if v != f[1:]:
                    return False
            elif f not in v:
                return False
        if self.search:
            text = ' '.join(norm(m.index(row, c, parent).data(Qt.DisplayRole)) for c in range(m.columnCount()))
            if self.search not in text:
                return False
        return True


class FilterHeader(QHeaderView):
    """Column titles with a filter box under each title, inside the header itself — so the filters stay under
    their columns when columns are resized, reordered or scrolled, and stay visible (sticky) with the header."""

    def __init__(self, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.editors = []
        self.setSectionsClickable(True)
        self.setHighlightSections(False)
        self.sectionResized.connect(self.adjust)
        self.sectionMoved.connect(self.adjust)

    def set_editors(self, editors):
        for e in editors:
            e.setParent(self)
            e.show()
        self.editors = editors
        self.adjust()

    def _extra(self):
        from .theme import control_height
        return (control_height(self.editors[0] if self.editors else self, compact=True) + 8) if self.editors else 0

    def sizeHint(self):
        s = super().sizeHint()
        s.setHeight(s.height() + self._extra())
        return s

    def updateGeometries(self):
        if self.editors:
            self.setViewportMargins(0, 0, 0, self._extra())
        else:
            self.setViewportMargins(0, 0, 0, 0)
        super().updateGeometries()
        self.adjust()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.adjust()

    def adjust(self, *_):
        top = self.height() - self._extra() + 2
        for i, e in enumerate(self.editors):
            if self.isSectionHidden(i):
                e.hide()
                continue
            e.show()
            e.setGeometry(self.sectionViewportPosition(i) + 3, top + 1, max(10, self.sectionSize(i) - 6), self._extra() - 8)


class DataTable(QWidget):
    """columns: [(title, kind)] with kind 'text' | 'num' | 'select' (filter as a list of values with counts).
    rows: [(id, [values…])]. actions: [(label, callback(ids), danger[, icon])] shown on the bulk bar.
    title: what the table lists (its accessible name)."""
    activated = Signal(int)          # double-click → id
    selection_changed = Signal(list)

    def __init__(self, columns, actions=(), parent=None, export_name='export', title=None):
        from .theme import a11y, button, icon
        super().__init__(parent)
        self.columns = columns
        self.export_name = export_name
        self.model = QStandardItemModel(0, len(columns))
        self.model.setHorizontalHeaderLabels([c[0] for c in columns])
        self.proxy = _Proxy()
        self.proxy.setSourceModel(self.model)
        self.view = QTableView()
        self.header = FilterHeader(self.view)
        self.view.setHorizontalHeader(self.header)
        self.view.setModel(self.proxy)
        self.view.setSortingEnabled(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.setAlternatingRowColors(True)
        self.view.setShowGrid(False)
        self.view.setWordWrap(False)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(32)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.view.horizontalHeader().setStretchLastSection(True)
        self.view.horizontalHeader().setDefaultAlignment(Qt.AlignLeading | Qt.AlignVCenter)
        self.view.doubleClicked.connect(self._double)
        self.view.selectionModel().selectionChanged.connect(lambda *_: self._sel_changed())
        title = title or L('القائمة', 'List')
        a11y(self.view, title, L('جدول: انقر نقراً مزدوجاً على سطر لفتحه، وحدّد عدة أسطر للإجراءات الجماعية.',
                                 'Table: double-click a row to open it; select several rows for bulk actions.'))

        top = QHBoxLayout()
        top.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText(L('بحث في كل الأعمدة…', 'Search all columns…'))
        self.search.addAction(icon('search', '#64748b'), QLineEdit.LeadingPosition)
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(420)
        a11y(self.search, L('بحث في ', 'Search ') + title)
        self.search.textChanged.connect(self._search)
        self.count = QLabel()
        self.count.setProperty('chip', True)
        a11y(self.count, L('عدد الأسطر', 'Row count'))
        top.addWidget(self.search, 1)
        top.addWidget(self.count)
        top.addStretch(1)
        export = button(L('تصدير Excel', 'Export to Excel'), 'export',
                        tip=L('تصدير الأسطر الظاهرة إلى ملف Excel', 'Export the rows shown to an Excel file'))
        export.clicked.connect(self.export)
        top.addWidget(export)

        # one filter box under every column title (inside the header, so it follows the column)
        self.filter_widgets = []
        for i, (title_i, kind) in enumerate(columns):
            if kind == 'select':
                w = QComboBox()
                w.setSizeAdjustPolicy(QComboBox.AdjustToContents)
                w.addItem(L('الكل', 'All'), '')
                w.currentIndexChanged.connect(lambda _i, c=i, ww=w: self._filter(c, ('=' + ww.currentData()) if ww.currentData() else ''))
            elif kind == 'none':
                w = QLabel()
            else:
                w = QLineEdit()
                w.setPlaceholderText(L('تصفية…', 'Filter…'))
                w.textChanged.connect(lambda t, c=i: self._filter(c, t))
            w.setProperty('compact', True)
            a11y(w, L('تصفية العمود: ', 'Filter column: ') + title_i)
            self.filter_widgets.append(w)
        self.header.set_editors(self.filter_widgets)
        self.view.horizontalScrollBar().valueChanged.connect(self.header.adjust)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.sel_label = QLabel(L('لم يُحدَّد شيء', 'Nothing selected'))
        self.sel_label.setProperty('muted', True)
        all_btn = button(L('تحديد الكل', 'Select all'), 'select_all', 'ghost')
        all_btn.clicked.connect(self.view.selectAll)
        none_btn = button(L('إلغاء التحديد', 'Clear selection'), 'select_none', 'ghost')
        none_btn.clicked.connect(self.view.clearSelection)
        bar.addWidget(all_btn)
        bar.addWidget(none_btn)
        bar.addWidget(self.sel_label)
        bar.addStretch(1)
        self.action_buttons = []
        for act in actions:
            label, cb, danger = act[:3]
            b = button(label, act[3] if len(act) > 3 else None, 'danger' if danger else 'secondary')
            b.setEnabled(False)
            b.clicked.connect(lambda _=False, f=cb: f(self.selected_ids()))
            bar.addWidget(b)
            self.action_buttons.append(b)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addLayout(top)
        lay.addWidget(self.view, 1)
        lay.addLayout(bar)

    # ── data ─────────────────────────────────────────────────────────
    def set_rows(self, rows):
        selected = set(self.selected_ids())
        self.view.setSortingEnabled(False)
        self.model.removeRows(0, self.model.rowCount())
        values_per_col = [{} for _ in self.columns]
        for rid, values in rows:
            items = []
            for c, v in enumerate(values):
                shown, sort = (v if isinstance(v, tuple) else (v, v))
                it = QStandardItem('' if shown is None else str(shown))
                it.setData(sort if sort is not None else '', SORT_ROLE)
                it.setData(rid, ID_ROLE)
                if self.columns[c][1] == 'num':
                    it.setTextAlignment(Qt.AlignCenter)
                items.append(it)
                if self.columns[c][1] == 'select' and shown not in (None, ''):
                    values_per_col[c][str(shown)] = values_per_col[c].get(str(shown), 0) + 1
            self.model.appendRow(items)
        for c, w in enumerate(self.filter_widgets):
            if isinstance(w, QComboBox):
                cur = w.currentData()
                w.blockSignals(True)
                w.clear()
                w.addItem(L(f'الكل ({len(rows)})', f'All ({len(rows)})'), '')
                for v in sorted(values_per_col[c]):
                    w.addItem(f'{v} ({values_per_col[c][v]})', norm(v))
                i = w.findData(cur)
                w.setCurrentIndex(i if i >= 0 else 0)
                w.blockSignals(False)
        self.view.setSortingEnabled(True)
        self.view.resizeColumnsToContents()
        for c, w in enumerate(self.filter_widgets):       # a filter is never narrower than what it shows
            need = (w.sizeHint().width() + 8) if isinstance(w, QComboBox) else 96
            if self.header.sectionSize(c) < need:
                self.header.resizeSection(c, need)
        if selected:
            sm = self.view.selectionModel()
            for r in range(self.proxy.rowCount()):
                if self.proxy.index(r, 0).data(ID_ROLE) in selected:
                    sm.select(self.proxy.index(r, 0), QItemSelectionModel.Select | QItemSelectionModel.Rows)
        self._update_count()
        self.header.adjust()

    def selected_ids(self):
        rows = {i.row() for i in self.view.selectionModel().selectedRows()}
        return [self.proxy.index(r, 0).data(ID_ROLE) for r in sorted(rows)]

    def visible_ids(self):
        return [self.proxy.index(r, 0).data(ID_ROLE) for r in range(self.proxy.rowCount())]

    def column_sum(self, col):
        from decimal import Decimal
        total = Decimal(0)
        for r in range(self.proxy.rowCount()):
            v = self.proxy.index(r, col).data(SORT_ROLE)
            try:
                total += Decimal(str(v))
            except Exception:  # noqa: BLE001
                pass
        return total

    # ── behaviour ────────────────────────────────────────────────────
    def _filter(self, col, text):
        self.proxy.set_filter(col, text)
        self._update_count()

    def _search(self, text):
        self.proxy.set_search(text)
        self._update_count()

    def _update_count(self):
        shown, total = self.proxy.rowCount(), self.model.rowCount()
        self.count.setText(L(f'الإجمالي: {total}', f'Total: {total}') if shown == total
                           else L(f'الظاهر: {shown} من {total}', f'Shown: {shown} of {total}'))
        self._sel_changed()

    def _sel_changed(self):
        ids = self.selected_ids()
        total = self.proxy.rowCount()
        self.sel_label.setText(L(f'المحدد: {len(ids)} من {total}', f'Selected: {len(ids)} of {total}') if ids
                               else L('لم يُحدَّد شيء', 'Nothing selected'))
        for b in self.action_buttons:
            b.setEnabled(bool(ids))
        self.selection_changed.emit(ids)

    def _double(self, index: QModelIndex):
        rid = index.data(ID_ROLE)
        if rid is not None:
            self.activated.emit(rid)

    def export(self):
        path, _ = QFileDialog.getSaveFileName(self, L('تصدير', 'Export'), f'{self.export_name}.xlsx',
                                              'Excel (*.xlsx);;CSV (*.csv)')
        if not path:
            return
        headers = [c[0] for c in self.columns]
        rows = [[self.proxy.index(r, c).data(Qt.DisplayRole) for c in range(len(self.columns))]
                for r in range(self.proxy.rowCount())]
        try:
            if path.lower().endswith('.csv'):
                with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                    w = csv.writer(f)
                    w.writerow(headers)
                    w.writerows(rows)
            else:
                from openpyxl import Workbook
                wb = Workbook()
                ws = wb.active
                ws.sheet_view.rightToLeft = lang() == 'ar'
                ws.append(headers)
                for r in rows:
                    ws.append(r)
                ws.freeze_panes = 'A2'
                ws.auto_filter.ref = ws.dimensions
                wb.save(path)
        except OSError as e:
            error(self, str(e))
            return
        info(self, L(f'صُدِّر {len(rows)} سطراً إلى:\n{path}', f'Exported {len(rows)} rows to:\n{path}'))
        try:
            os.startfile(path)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass

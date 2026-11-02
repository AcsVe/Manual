"""The editor of one manual: the tree of sections on one side, the selected section (its properties and its blocks,
each with an Arabic and an English side) in the middle, and the live preview of the printed pages on the other side.
Changes are saved automatically when another section is opened and before the preview is refreshed."""
import os

from PySide6.QtCore import QDate, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDateEdit, QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QLineEdit, QMenu, QScrollArea, QSizePolicy, QSpinBox, QSplitter,
                               QTableWidget, QTableWidgetItem, QTextEdit, QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ..core.db import BLOCK_KINDS, SECTION_KINDS, STATUSES
from ..core.richtext import clean
from ..core import backgrounds as BG, doctor
from ..core.templates import BLOCK_ALIGN, TABLE_PRESETS, layout_with_defaults, policy_blocks, table_data
from .common import L, confirm, error, info
from .library import asset_pixmap, pick_asset
from .theme import SizedDialog, a11y, size_tree, button, card, field, fit, form_grid, hint, icon, flow_row, icon_button, ltr, muted, name_buttons

KIND_ICONS = {'cover': 'book', 'disclaimer': 'shield', 'doc_control': 'check', 'toc': 'list', 'chapter': 'folder',
              'text': 'text', 'policy': 'flag', 'table': 'table', 'orgchart': 'org', 'compliance': 'shield',
              'links': 'link', 'image': 'image'}
TEXT_KINDS = ('heading', 'paragraph', 'bullets', 'numbered', 'callout', 'quote')
PLACEHOLDERS = {
    'heading': (('العنوان الفرعي بالعربية', 'Arabic sub-heading'), ('العنوان الفرعي بالإنجليزية', 'English sub-heading')),
    'paragraph': (('النص بالعربية', 'Arabic text'), ('النص بالإنجليزية', 'English text')),
    'bullets': (('بند في كل سطر', 'One item per line'), ('One item per line', 'One item per line')),
    'numbered': (('بند في كل سطر', 'One item per line'), ('One item per line', 'One item per line')),
    'callout': (('نص التنبيه بالعربية', 'Arabic note'), ('Note in English', 'Note in English')),
    'quote': (('الاقتباس بالعربية', 'Arabic quote'), ('Quote in English', 'Quote in English')),
}


# ── rich text ───────────────────────────────────────────────────────────────────────────────────────
class RichEdit(QTextEdit):
    """A text box for one side of a block: bold/italic/underline/colour/links, stored as safe HTML."""
    focused = Signal(object)

    def __init__(self, rtl, placeholder=''):
        super().__init__()
        self.setAcceptRichText(True)
        self.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        opt = self.document().defaultTextOption()
        opt.setTextDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
        opt.setAlignment(Qt.AlignRight if rtl else Qt.AlignLeft)
        self.document().setDefaultTextOption(opt)
        self.setPlaceholderText(placeholder)
        self.setMinimumHeight(70)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.document().contentsChanged.connect(self._fit)
        a11y(self, placeholder)

    def _fit(self):
        h = int(self.document().size().height()) + 14
        self.setFixedHeight(max(70, min(h, 420)))

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.focused.emit(self)

    def insertFromMimeData(self, source):          # pasted text keeps only the formatting the manual uses
        if source.hasHtml():
            self.insertHtml(clean(source.html()))
        else:
            super().insertFromMimeData(source)

    def set_value(self, html):
        html = html or ''
        if '<' in html:
            self.setHtml(html)
        else:
            self.setPlainText(html)
        self._fit()

    def value(self):
        if not self.toPlainText().strip():
            return ''
        return clean(self.toHtml())


SYMBOLS = (
    (('علامات', 'Marks'), (('✓', ('صح', 'Check')), ('✔', ('صح غامق', 'Heavy check')), ('✗', ('خطأ', 'Cross')),
                           ('☐', ('مربع فارغ', 'Empty box')), ('☑', ('مربع مؤشَّر', 'Checked box')), ('☒', ('مربع مشطوب', 'Crossed box')),
                           ('★', ('نجمة', 'Star')), ('⚠', ('تنبيه', 'Warning')), ('ℹ', ('معلومة', 'Information')))),
    (('نقاط وأشكال', 'Bullets and shapes'), (('•', ('نقطة', 'Bullet')), ('▪', ('مربع صغير', 'Small square')), ('■', ('مربع', 'Square')),
                                             ('●', ('دائرة', 'Circle')), ('○', ('دائرة فارغة', 'Empty circle')), ('◆', ('معيّن', 'Diamond')),
                                             ('❖', ('زخرفة', 'Ornament')), ('➢', ('رأس سهم', 'Arrowhead')), ('►', ('مثلث', 'Triangle')))),
    (('أسهم', 'Arrows'), (('←', ('يسار', 'Left')), ('→', ('يمين', 'Right')), ('↑', ('أعلى', 'Up')), ('↓', ('أسفل', 'Down')),
                         ('↔', ('اتجاهان', 'Both ways')), ('⇐', ('يسار مزدوج', 'Double left')), ('⇒', ('يمين مزدوج', 'Double right')))),
    (('رياضيات ووحدات', 'Maths and units'), (('±', ('زائد أو ناقص', 'Plus or minus')), ('×', ('ضرب', 'Times')), ('÷', ('قسمة', 'Divide')),
                                             ('≤', ('أصغر أو يساوي', 'Less or equal')), ('≥', ('أكبر أو يساوي', 'Greater or equal')),
                                             ('≠', ('لا يساوي', 'Not equal')), ('≈', ('يقارب', 'About')), ('°', ('درجة', 'Degree')),
                                             ('٪', ('نسبة مئوية عربية', 'Arabic percent')), ('%', ('نسبة مئوية', 'Percent')), ('‰', ('في الألف', 'Per mille')))),
    (('قانونية وعملات', 'Legal and currency'), (('©', ('حقوق النشر', 'Copyright')), ('®', ('علامة مسجلة', 'Registered')),
                                                ('™', ('علامة تجارية', 'Trade mark')), ('§', ('مادة', 'Section')), ('¶', ('فقرة', 'Paragraph')),
                                                ('€', ('يورو', 'Euro')), ('$', ('دولار', 'Dollar')), ('£', ('جنيه', 'Pound')))),
    (('ترقيم عربي', 'Arabic punctuation'), (('،', ('فاصلة', 'Comma')), ('؛', ('فاصلة منقوطة', 'Semicolon')),
                                            ('؟', ('علامة استفهام', 'Question mark')), ('«', ('قوس اقتباس فاتح', 'Opening quote')),
                                            ('»', ('قوس اقتباس غالق', 'Closing quote')), ('ـ', ('تطويل', 'Tatweel')))),
)


class FormatBar(QWidget):
    """Bold, italic, underline, colour and link for the text box that has the focus."""

    def __init__(self):
        super().__init__()
        self.target = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        for text, tip, fn in (('B', L('غامق', 'Bold'), self.bold), ('I', L('مائل', 'Italic'), self.italic),
                              ('U', L('تسطير', 'Underline'), self.underline)):
            b = QToolButton()
            b.setText(text)
            f = b.font()
            f.setBold(text == 'B')
            f.setItalic(text == 'I')
            f.setUnderline(text == 'U')
            b.setFont(f)
            b.setToolTip(tip)
            a11y(b, tip)
            b.clicked.connect(fn)
            lay.addWidget(b)
        col = icon_button('palette', L('لون النص', 'Text colour'))
        col.clicked.connect(self.color)
        link = icon_button('link', L('رابط', 'Link'))
        link.clicked.connect(self.link)
        plain = icon_button('reset', L('إزالة التنسيق', 'Clear formatting'))
        plain.clicked.connect(self.plain)
        sym = QToolButton()
        sym.setText('Ω')
        sym.setToolTip(L('إدراج رمز', 'Insert a symbol'))
        a11y(sym, L('إدراج رمز', 'Insert a symbol'))
        menu = QMenu(sym)
        for (ar, en), chars in SYMBOLS:
            sub = menu.addMenu(L(ar, en))
            for ch, (nar, nen) in chars:
                sub.addAction(f'{ch}    {L(nar, nen)}', lambda c=ch: self.insert(c))
        sym.setMenu(menu)
        sym.setPopupMode(QToolButton.InstantPopup)
        for b in (col, link, plain, sym):
            lay.addWidget(b)
        lay.addStretch(1)

    def insert(self, ch):
        if self.target:
            self.target.insertPlainText(ch)
            self.target.setFocus()

    def set_target(self, ed):
        self.target = ed

    def _merge(self, fmt):
        if not self.target:
            return
        c = self.target.textCursor()
        if not c.hasSelection():
            c.select(QTextCursor.WordUnderCursor)
        c.mergeCharFormat(fmt)
        self.target.mergeCurrentCharFormat(fmt)

    def bold(self):
        f = QTextCharFormat()
        cur = self.target.currentCharFormat().fontWeight() if self.target else 400
        f.setFontWeight(QFont.Normal if cur >= QFont.Bold else QFont.Bold)
        self._merge(f)

    def italic(self):
        f = QTextCharFormat()
        f.setFontItalic(not (self.target and self.target.currentCharFormat().fontItalic()))
        self._merge(f)

    def underline(self):
        f = QTextCharFormat()
        f.setFontUnderline(not (self.target and self.target.currentCharFormat().fontUnderline()))
        self._merge(f)

    def color(self):
        c = QColorDialog.getColor(QColor('#0B3D91'), self, L('لون النص', 'Text colour'))
        if c.isValid():
            f = QTextCharFormat()
            f.setForeground(c)
            self._merge(f)

    def link(self):
        if not self.target:
            return
        url, ok = QInputDialog.getText(self, L('رابط', 'Link'), L('عنوان الرابط (يبدأ بـ https://)', 'Link address (starts with https://)'))
        if ok and url.strip():
            c = self.target.textCursor()
            text = c.selectedText() or url.strip()
            c.insertHtml(f'<a href="{url.strip()}">{text}</a>')

    def plain(self):
        if self.target:
            c = self.target.textCursor()
            c.setCharFormat(QTextCharFormat())


# ── tables and links ────────────────────────────────────────────────────────────────────────────────
class ColumnsDialog(SizedDialog):
    def __init__(self, parent, columns):
        super().__init__(parent)
        self.setWindowTitle(L('أعمدة الجدول', 'Table columns'))
        self.t = QTableWidget(len(columns), 2)
        self.t.setHorizontalHeaderLabels([L('العنوان بالعربية', 'Arabic title'), L('العنوان بالإنجليزية', 'English title')])
        self.t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        for i, c in enumerate(columns):
            self.t.setItem(i, 0, QTableWidgetItem(c.get('ar') or ''))
            self.t.setItem(i, 1, QTableWidgetItem(c.get('en') or ''))
        a11y(self.t, L('أعمدة الجدول', 'Table columns'))
        add = button(L('إضافة عمود', 'Add a column'), 'plus')
        add.clicked.connect(lambda: self.t.insertRow(self.t.rowCount()))
        rem = button(L('حذف العمود المحدد', 'Delete the selected column'), 'trash', 'danger')
        rem.clicked.connect(lambda: self.t.removeRow(self.t.currentRow()) if self.t.currentRow() >= 0 else None)
        up = icon_button('up', L('تحريك لأعلى', 'Move up'))
        up.clicked.connect(lambda: self._move(-1))
        down = icon_button('down', L('تحريك لأسفل', 'Move down'))
        down.clicked.connect(lambda: self._move(1))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(L('حفظ', 'Save'))
        bb.button(QDialogButtonBox.Cancel).setText(L('إلغاء', 'Cancel'))
        name_buttons(bb)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        row = QHBoxLayout()
        for b in (add, rem, up, down):
            row.addWidget(b)
        row.addStretch(1)
        lay = QVBoxLayout(self)
        lay.addLayout(row)
        lay.addWidget(self.t)
        lay.addWidget(bb)
        self.resize(560, 420)
        self.order = list(range(len(columns)))

    def _move(self, d):
        r = self.t.currentRow()
        j = r + d
        if r < 0 or not 0 <= j < self.t.rowCount():
            return
        for c in range(2):
            a, b = self.t.takeItem(r, c), self.t.takeItem(j, c)
            self.t.setItem(r, c, b)
            self.t.setItem(j, c, a)
        self.order[r], self.order[j] = self.order[j], self.order[r]
        self.t.setCurrentCell(j, 0)

    def columns(self):
        out = []
        for i in range(self.t.rowCount()):
            a = self.t.item(i, 0).text().strip() if self.t.item(i, 0) else ''
            e = self.t.item(i, 1).text().strip() if self.t.item(i, 1) else ''
            out.append({'ar': a, 'en': e, '_src': self.order[i] if i < len(self.order) else None})
        return out


class TableEditor(QWidget):
    """A table with an Arabic and an English layer (switched above the grid): columns, rows, presets."""
    changed = Signal()

    def __init__(self, data=None):
        super().__init__()
        self.data = data or table_data('custom')
        self.layer = 'ar'
        self.lang = QComboBox()
        self.lang.addItem(L('النص العربي', 'Arabic text'), 'ar')
        self.lang.addItem(L('النص الإنجليزي', 'English text'), 'en')
        self.lang.currentIndexChanged.connect(self._switch)
        fit(self.lang, 170)
        a11y(self.lang, L('لغة الخلايا المعروضة', 'Language of the cells shown'))
        self.preset = QComboBox()
        for k, ((ar, en), _) in TABLE_PRESETS.items():
            self.preset.addItem(L(ar, en), k)
        self.preset.setCurrentIndex(max(0, self.preset.findData(self.data.get('preset', 'custom'))))
        self.preset.activated.connect(self._preset)
        a11y(self.preset, L('نوع الجدول', 'Table type'))
        self.numbered = QCheckBox(L('ترقيم الأسطر', 'Number the rows'))
        self.numbered.setChecked(bool(self.data.get('numbered')))
        self.numbered.toggled.connect(lambda v: (self.data.update(numbered=v), self.changed.emit()))
        self.bold = QCheckBox(L('العمود الأول غامق', 'First column bold'))
        self.bold.setChecked(bool(self.data.get('first_col_bold')))
        self.bold.toggled.connect(lambda v: (self.data.update(first_col_bold=v), self.changed.emit()))
        self.grid = QTableWidget()
        self.grid.setWordWrap(True)
        self.grid.verticalHeader().setDefaultSectionSize(30)
        self.grid.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.grid.horizontalHeader().setStretchLastSection(True)
        self.grid.horizontalHeader().sectionDoubleClicked.connect(lambda _i: self.edit_columns())
        self.grid.itemChanged.connect(self._cell)
        self.grid.setMinimumHeight(180)
        a11y(self.grid, L('خلايا الجدول', 'Table cells'))
        cols = button(L('الأعمدة…', 'Columns…'), 'table')
        cols.clicked.connect(self.edit_columns)
        addr = button(L('إضافة سطر', 'Add a row'), 'plus')
        addr.clicked.connect(self.add_row)
        delr = button(L('حذف الأسطر المحددة', 'Delete selected rows'), 'trash', 'danger')
        delr.clicked.connect(self.del_rows)
        up = icon_button('up', L('تحريك السطر لأعلى', 'Move the row up'))
        up.clicked.connect(lambda: self.move_row(-1))
        down = icon_button('down', L('تحريك السطر لأسفل', 'Move the row down'))
        down.clicked.connect(lambda: self.move_row(1))
        paste = button(L('لصق من Excel', 'Paste from Excel'), 'import')
        paste.clicked.connect(self.paste)
        self.preset.setMinimumContentsLength(10)
        self.preset.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(flow_row([self.preset, self.lang, self.numbered, self.bold]))
        lay.addWidget(self.grid)
        lay.addWidget(flow_row([cols, addr, delr, up, down, paste]))
        self.fill()

    def fill(self):
        self.grid.blockSignals(True)
        cols = self.data.get('columns') or []
        rows = self.data.get('rows') or []
        self.grid.setColumnCount(len(cols))
        self.grid.setRowCount(len(rows))
        self.grid.setHorizontalHeaderLabels([(c.get(self.layer) or c.get('ar') or c.get('en') or '') for c in cols])
        for i, r in enumerate(rows):
            for j in range(len(cols)):
                v = r[j] if j < len(r) else {}
                self.grid.setItem(i, j, QTableWidgetItem((v or {}).get(self.layer) or ''))
        self.grid.blockSignals(False)
        self.grid.resizeRowsToContents()

    def _switch(self):
        self.layer = self.lang.currentData()
        self.fill()

    def _cell(self, it):
        rows = self.data.setdefault('rows', [])
        while len(rows) <= it.row():
            rows.append([{'ar': '', 'en': ''} for _ in self.data['columns']])
        r = rows[it.row()]
        while len(r) <= it.column():
            r.append({'ar': '', 'en': ''})
        r[it.column()] = dict(r[it.column()] or {}, **{self.layer: it.text()})
        self.changed.emit()

    def edit_columns(self):
        d = ColumnsDialog(self, self.data.get('columns') or [])
        if not d.exec():
            return
        new = d.columns()
        rows = []
        for r in self.data.get('rows') or []:
            rows.append([(r[c['_src']] if c['_src'] is not None and c['_src'] < len(r) else {'ar': '', 'en': ''}) for c in new])
        self.data['columns'] = [{'ar': c['ar'], 'en': c['en']} for c in new]
        self.data['rows'] = rows
        self.fill()
        self.changed.emit()

    def _preset(self):
        key = self.preset.currentData()
        filled = any(((x or {}).get('ar') or (x or {}).get('en')) for r in self.data.get('rows') or [] for x in r)
        if filled and not confirm(self, L('تُستبدل أعمدة الجدول بأعمدة النوع المختار، وتبقى الخلايا المكتوبة في مكانها. متابعة؟',
                                          'The columns are replaced by those of the chosen type; the cells written stay in place. Continue?')):
            self.preset.setCurrentIndex(max(0, self.preset.findData(self.data.get('preset', 'custom'))))
            return
        new = table_data(key)
        if key != 'custom' or not self.data.get('columns'):
            self.data['columns'] = new['columns']
        self.data['preset'] = key
        n = len(self.data['columns'])
        self.data['rows'] = [(r + [{'ar': '', 'en': ''}] * n)[:n] for r in self.data.get('rows') or []] or new['rows']
        self.fill()
        self.changed.emit()

    def add_row(self):
        self.data.setdefault('rows', []).append([{'ar': '', 'en': ''} for _ in self.data.get('columns') or []])
        self.fill()
        self.grid.setCurrentCell(self.grid.rowCount() - 1, 0)
        self.changed.emit()

    def del_rows(self):
        rows = sorted({i.row() for i in self.grid.selectedIndexes()}, reverse=True)
        for r in rows:
            if r < len(self.data.get('rows') or []):
                del self.data['rows'][r]
        self.fill()
        self.changed.emit()

    def move_row(self, d):
        r = self.grid.currentRow()
        rows = self.data.get('rows') or []
        j = r + d
        if r < 0 or not 0 <= j < len(rows):
            return
        rows[r], rows[j] = rows[j], rows[r]
        self.fill()
        self.grid.setCurrentCell(j, self.grid.currentColumn())
        self.changed.emit()

    def paste(self):
        from PySide6.QtGui import QGuiApplication
        text = QGuiApplication.clipboard().text()
        if not text.strip():
            info(self, L('انسخ الخلايا من Excel أولاً.', 'Copy the cells in Excel first.'))
            return
        lines_ = [ln.split('\t') for ln in text.rstrip('\n').split('\n')]
        n = len(self.data.get('columns') or [])
        if not n:
            self.data['columns'] = [{'ar': f'العمود {i + 1}', 'en': f'Column {i + 1}'} for i in range(max(len(x) for x in lines_))]
            n = len(self.data['columns'])
        for ln in lines_:
            row = [{'ar': '', 'en': ''} for _ in range(n)]
            for j, v in enumerate(ln[:n]):
                row[j][self.layer] = v.strip()
            self.data.setdefault('rows', []).append(row)
        self.fill()
        self.changed.emit()

    def value(self):
        return self.data


class LinksEditor(QWidget):
    changed = Signal()

    def __init__(self, items):
        super().__init__()
        self.t = QTableWidget(0, 4)
        self.t.setHorizontalHeaderLabels([L('العنوان بالعربية', 'Arabic title'), L('العنوان بالإنجليزية', 'English title'),
                                          L('الرابط', 'Address'), L('ملاحظة', 'Note')])
        self.t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.t.setMinimumHeight(150)
        a11y(self.t, L('الروابط', 'Links'))
        for it in items or []:
            self.add(it)
        self.t.itemChanged.connect(lambda *_: self.changed.emit())
        add = button(L('إضافة رابط', 'Add a link'), 'plus')
        add.clicked.connect(lambda: (self.add({}), self.changed.emit()))
        rem = button(L('حذف المحدد', 'Delete selected'), 'trash', 'danger')
        rem.clicked.connect(self.remove)
        row = QHBoxLayout()
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.t)
        lay.addLayout(row)

    def add(self, it):
        r = self.t.rowCount()
        self.t.insertRow(r)
        for c, k in enumerate(('title_ar', 'title_en', 'url', 'note')):
            self.t.setItem(r, c, QTableWidgetItem(it.get(k) or ''))

    def remove(self):
        for r in sorted({i.row() for i in self.t.selectedIndexes()}, reverse=True):
            self.t.removeRow(r)
        self.changed.emit()

    def value(self):
        out = []
        for r in range(self.t.rowCount()):
            d = {k: (self.t.item(r, c).text().strip() if self.t.item(r, c) else '')
                 for c, k in enumerate(('title_ar', 'title_en', 'url', 'note'))}
            if any(d.values()):
                out.append(d)
        return out


# ── one block ───────────────────────────────────────────────────────────────────────────────────────
class BlockWidget(QFrame):
    changed = Signal()
    remove = Signal(object)
    move = Signal(object, int)
    focused = Signal(object)
    insert_after = Signal(object)

    def __init__(self, ctx, block):
        super().__init__()
        self.ctx, self.db = ctx, ctx.db
        self.block = dict(block)
        self.setObjectName('block')
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet('QFrame#block{background:#ffffff;border:1px solid #d5deea;border-radius:10px}')
        self.kind = QComboBox()
        for k, (ar, en) in BLOCK_KINDS.items():
            self.kind.addItem(icon(_block_icon(k), '#64748b'), L(ar, en), k)
        self.kind.setCurrentIndex(max(0, self.kind.findData(block.get('kind', 'paragraph'))))
        self.kind.currentIndexChanged.connect(self._kind_changed)
        fit(self.kind, 190)
        a11y(self.kind, L('نوع الكتلة', 'Block type'))
        self.align = QComboBox()
        for k, (ar, en) in BLOCK_ALIGN.items():
            self.align.addItem(L(ar, en), k)
        self.align.setCurrentIndex(max(0, self.align.findData((block.get('style') or {}).get('align', ''))))
        self.align.currentIndexChanged.connect(self.changed.emit)
        fit(self.align, 150)
        a11y(self.align, L('محاذاة النص', 'Text alignment'))
        add = icon_button('plus', L('إضافة كتلة بعد هذه الكتلة', 'Add a block after this one'))
        add.clicked.connect(lambda: self.insert_after.emit(self))
        up = icon_button('up', L('تحريك لأعلى', 'Move up'))
        up.clicked.connect(lambda: self.move.emit(self, -1))
        down = icon_button('down', L('تحريك لأسفل', 'Move down'))
        down.clicked.connect(lambda: self.move.emit(self, 1))
        rm = icon_button('trash', L('حذف الكتلة', 'Delete the block'), 'danger')
        rm.clicked.connect(lambda: self.remove.emit(self))
        # every control at the reading start, so a narrow pane never hides them
        head = flow_row([self.kind, self.align, add, up, down, rm], 6)
        self.body = QVBoxLayout()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(6)
        lay.addWidget(head)
        lay.addLayout(self.body)
        self._build()

    def _clear(self):
        while self.body.count():
            it = self.body.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                _clear_layout(it.layout())

    def _build(self):
        self._clear()
        k = self.block.get('kind', 'paragraph')
        d = self.block.get('data') or {}
        self.ar = self.en = self.table = self.links = None
        if k in TEXT_KINDS:
            (par, pen) = PLACEHOLDERS[k]
            self.ar = RichEdit(True, L(*par))
            self.en = RichEdit(False, L(*pen) if isinstance(pen, tuple) else pen)
            self.ar.set_value(self.block.get('ar'))
            self.en.set_value(self.block.get('en'))
            for e in (self.ar, self.en):
                e.textChanged.connect(self.changed.emit)
                e.focused.connect(self.focused.emit)
            row = QHBoxLayout()
            row.setSpacing(8)
            # Arabic at the reading start, English beside it, as in the printed pages
            if self.layoutDirection() == Qt.RightToLeft:
                row.addWidget(self.ar, 1)
                row.addWidget(self.en, 1)
            else:
                row.addWidget(self.en, 1)
                row.addWidget(self.ar, 1)
            self.body.addLayout(row)
        elif k == 'table':
            self.table = TableEditor(dict(d) if d.get('columns') else table_data('custom'))
            self.table.changed.connect(self.changed.emit)
            self.body.addWidget(self.table)
        elif k == 'links':
            self.links = LinksEditor(d.get('items') or [])
            self.links.changed.connect(self.changed.emit)
            self.body.addWidget(self.links)
        elif k == 'image':
            st = self.block.get('style') or {}
            self.thumb = QLabel()
            self.thumb.setFixedSize(QSize(180, 120))
            self.thumb.setAlignment(Qt.AlignCenter)
            self.thumb.setStyleSheet('background:#f1f5f9;border-radius:8px')
            a11y(self.thumb, L('الصورة', 'Image'))
            self.asset_id = d.get('asset_id')
            self._thumb()
            pick = button(L('اختيار صورة…', 'Choose an image…'), 'image')
            pick.clicked.connect(self._pick)
            from_pdf = button(L('صفحة من ملف PDF…', 'A page of a PDF file…'), 'pdf')
            from_pdf.clicked.connect(self._from_pdf)
            drop = button(L('إزالة الصورة', 'Remove the image'), 'close', 'danger')
            drop.clicked.connect(self._drop)
            self.width = QSpinBox()
            self.width.setRange(10, 100)
            self.width.setSuffix(' %')
            self.width.setValue(int(d.get('width') or 100))
            self.width.valueChanged.connect(self.changed.emit)
            fit(self.width, 110)
            self.fullpage = QCheckBox(L('صفحة كاملة (تملأ الورقة دون هوامش، وتأخذ اتجاه الصورة)',
                                        'A whole page (fills the sheet without margins, turned as the image)'))
            self.fullpage.setChecked(bool(st.get('fullpage')))
            self.fullpage.toggled.connect(lambda v: (self.width.setEnabled(not v), self.changed.emit()))
            self.width.setEnabled(not self.fullpage.isChecked())
            self.cap_ar = QLineEdit(self.block.get('ar') or '')
            self.cap_ar.setPlaceholderText(L('التعليق بالعربية (اختياري)', 'Arabic caption (optional)'))
            self.cap_en = ltr(QLineEdit(self.block.get('en') or ''))
            self.cap_en.setPlaceholderText(L('التعليق بالإنجليزية (اختياري)', 'English caption (optional)'))
            for e in (self.cap_ar, self.cap_en):
                e.textChanged.connect(self.changed.emit)
            g = form_grid()
            field(g, 0, 0, L('العرض من عرض الصفحة', 'Width of the page width'), self.width)
            g.addWidget(self.fullpage, 1, 0, 1, 2)
            field(g, 2, 0, L('التعليق بالعربية', 'Arabic caption'), self.cap_ar)
            field(g, 3, 0, L('التعليق بالإنجليزية', 'English caption'), self.cap_en)
            self.fullpage.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            g.setColumnStretch(1, 1)
            self.body.addWidget(flow_row([self.thumb, pick, from_pdf, drop]))
            self.body.addLayout(g)
        elif k == 'pagebreak':
            self.body.addWidget(muted(L('تبدأ الكتلة التالية في صفحة جديدة.', 'The next block starts on a new page.')))
        self.align.setVisible(k in TEXT_KINDS or k == 'image')
        size_tree(self)

    def _thumb(self):
        pm = asset_pixmap(self.db, self.asset_id, 170)
        if pm.isNull():
            self.thumb.setText(L('لا توجد صورة', 'No image'))
        else:
            self.thumb.setPixmap(pm)

    def _pick(self):
        aid = pick_asset(self, self.db)
        if aid:
            self.asset_id = aid
            self._thumb()
            self.changed.emit()

    def _drop(self):
        self.asset_id = None
        self._thumb()
        self.changed.emit()

    def _from_pdf(self):
        path, _ = QFileDialog.getOpenFileName(self, L('ملف PDF', 'PDF file'), '', 'PDF (*.pdf)')
        if not path:
            return
        from ..core import importer
        n = importer.pdf_page_count(path) or 9999
        page, ok = QInputDialog.getInt(self, L('رقم الصفحة', 'Page number'),
                                       L('رقم الصفحة المطلوبة من الملف', 'The page of the file to use'), 1, 1, n)
        if not ok:
            return
        data = importer.render_pdf_page(path, page, 170)
        if not data:
            error(self, L('تعذّرت قراءة هذه الصفحة من الملف.', 'This page of the file cannot be read.'))
            return
        from PySide6.QtGui import QImage
        img = QImage()
        img.loadFromData(data)
        name = f'{os.path.splitext(os.path.basename(path))[0]} — {L("صفحة", "page")} {page}.png'
        self.asset_id = self.db.add_asset(name, data, 'image/png', 'image', img.width(), img.height())
        if not self.fullpage.isChecked() and confirm(self, L('هل تُعرض الصفحة صفحةً كاملة في الدليل (دون هوامش)؟',
                                                            'Show the page as a whole page of the manual (no margins)?')):
            self.fullpage.setChecked(True)
        self._thumb()
        self.changed.emit()

    def _kind_changed(self):
        cur = self.value()
        new = self.kind.currentData()
        self.block = dict(cur, kind=new)
        if new == 'table' and not (cur.get('data') or {}).get('columns'):
            self.block['data'] = table_data('custom')
        self._build()
        self.changed.emit()

    def value(self):
        k = self.block.get('kind', 'paragraph')
        style = dict(self.block.get('style') or {})
        if self.align.currentData():
            style['align'] = self.align.currentData()
        else:
            style.pop('align', None)
        if k == 'image':
            style['fullpage'] = self.fullpage.isChecked()
        out = {'kind': k, 'ar': '', 'en': '', 'data': {}, 'style': style}
        if self.ar is not None:
            out['ar'], out['en'] = self.ar.value(), self.en.value()
        elif self.table is not None:
            out['data'] = self.table.value()
        elif self.links is not None:
            out['data'] = {'items': self.links.value()}
        elif k == 'image':
            out['data'] = {'asset_id': self.asset_id, 'width': self.width.value()}
            out['ar'], out['en'] = self.cap_ar.text().strip(), self.cap_en.text().strip()
        return out


def _block_icon(k):
    return {'heading': 'text', 'paragraph': 'text', 'bullets': 'list', 'numbered': 'list', 'table': 'table',
            'image': 'image', 'callout': 'flag', 'links': 'link', 'quote': 'text', 'pagebreak': 'new'}.get(k, 'text')


def _clear_layout(lay):
    while lay.count():
        it = lay.takeAt(0)
        if it.widget():
            it.widget().deleteLater()
        elif it.layout():
            _clear_layout(it.layout())


# ── the section's own properties ────────────────────────────────────────────────────────────────────
class SectionForm(QWidget):
    changed = Signal()

    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.db = ctx, ctx.db
        self.section = None
        self.title_ar = QLineEdit()
        self.title_ar.setPlaceholderText(L('العنوان بالعربية', 'Arabic title'))
        self.title_en = ltr(QLineEdit())
        self.title_en.setPlaceholderText(L('العنوان بالإنجليزية', 'English title'))
        self.kind = QComboBox()
        for k, (ar, en) in SECTION_KINDS.items():
            self.kind.addItem(icon(KIND_ICONS[k], '#64748b'), L(ar, en), k)
        fit(self.kind, 230)
        self.code = ltr(QLineEdit(), 120)
        self.code.setPlaceholderText('HR-01')
        self.new_page = QCheckBox(L('يبدأ في صفحة جديدة', 'Starts on a new page'))
        self.in_toc = QCheckBox(L('يظهر في الفهرس', 'Listed in the contents'))
        self.next_review = QDateEdit()
        self.next_review.setCalendarPopup(True)
        self.next_review.setDisplayFormat('yyyy-MM-dd')
        self.next_review.setSpecialValueText(L('بلا موعد', 'No date'))
        self.next_review.setMinimumDate(QDate(2000, 1, 1))
        fit(self.next_review, 150)
        self.status = QLabel()
        self.status.setProperty('chip', True)
        a11y(self.status, L('حالة القسم', 'Section status'))
        # page direction and background
        self.orientation = QComboBox()
        self.orientation.addItem(L('كإعداد الدليل', 'As the manual'), '')
        self.orientation.addItem(L('عمودي (Portrait)', 'Portrait'), 'portrait')
        self.orientation.addItem(L('أفقي (Landscape)', 'Landscape'), 'landscape')
        fit(self.orientation, 190)
        self.bg_label = QLabel(L('بلا خلفية', 'No background'))
        self.bg_label.setProperty('muted', True)
        self.bg_label.setWordWrap(True)
        bg_pick = button(L('الخلفية…', 'Background…'), 'image')
        bg_pick.clicked.connect(self._pick_bg)
        bg_clear = icon_button('close', L('إزالة الخلفية', 'Remove the background'))
        bg_clear.clicked.connect(self._clear_bg)
        self.bg = None
        # policy fields
        self.resp_ar = QLineEdit()
        self.resp_ar.setPlaceholderText(L('مثلاً: مدير الموارد البشرية', 'e.g. مدير الموارد البشرية'))
        self.resp_en = ltr(QLineEdit())
        self.resp_en.setPlaceholderText('HR Manager')
        self.effective = ltr(QLineEdit(), 130)
        self.effective.setPlaceholderText('2026-12-31')
        # kind-specific
        self.org_root = QComboBox()
        fit(self.org_root, 260)
        self.org_depth = QSpinBox()
        self.org_depth.setRange(0, 10)
        self.org_depth.setSpecialValueText(L('كل المستويات', 'All levels'))
        fit(self.org_depth, 140)
        self.ctrl_policy = QComboBox()
        fit(self.ctrl_policy, 300)
        self.toc_depth = QSpinBox()
        self.toc_depth.setRange(1, 4)
        fit(self.toc_depth, 90)

        g = form_grid()
        field(g, 0, 0, L('العنوان بالعربية', 'Arabic title'), self.title_ar)
        field(g, 1, 0, L('العنوان بالإنجليزية', 'English title'), self.title_en)
        field(g, 2, 0, L('نوع القسم', 'Section type'), self.kind)
        field(g, 3, 0, L('الرمز', 'Code'), self.code)
        g.addWidget(flow_row([self.new_page, self.in_toc, self.status]), 4, 1)
        field(g, 5, 0, L('موعد المراجعة القادمة', 'Next review'), self.next_review)
        field(g, 6, 0, L('اتجاه صفحات القسم', 'Page direction'), self.orientation)
        bgr = QHBoxLayout()
        bgr.addWidget(bg_pick)
        bgr.addWidget(bg_clear)
        bgr.addWidget(self.bg_label, 1)
        field(g, 7, 0, L('الخلفية', 'Background'), bgr)
        g.setColumnStretch(1, 1)
        self.policy_box = card(L('بيانات السياسة', 'Policy details'))
        pg = form_grid()
        field(pg, 0, 0, L('المسؤول عن المتابعة والتحديث (عربي)', 'Responsible to maintain & update (Arabic)'), self.resp_ar)
        field(pg, 1, 0, L('المسؤول عن المتابعة والتحديث (إنجليزي)', 'Responsible to maintain & update (English)'), self.resp_en)
        field(pg, 2, 0, L('تاريخ النفاذ', 'Effective date'), self.effective)
        pg.setColumnStretch(1, 1)
        self.policy_box.setLayout(pg)
        self.org_box = card(L('الهيكل المعروض', 'Chart shown'))
        og = form_grid()
        field(og, 0, 0, L('يبدأ من', 'Starts from'), self.org_root)
        field(og, 1, 0, L('عدد المستويات', 'Levels'), self.org_depth)
        og.addWidget(hint(L('يُعدَّل الهيكل نفسه من صفحة «الهيكل التنظيمي».', 'The structure itself is edited on the «Organisational chart» page.')), 2, 1)
        og.setColumnStretch(2, 1)
        self.org_box.setLayout(og)
        self.ctrl_box = card(L('بنود السجل المعروضة', 'Register items shown'))
        cg = form_grid()
        field(cg, 0, 0, L('الخاصة بـ', 'Belonging to'), self.ctrl_policy)
        cg.addWidget(hint(L('تُدار البنود من صفحة «سجل الالتزام».', 'The items are managed on the «Compliance register» page.')), 1, 1)
        cg.setColumnStretch(2, 1)
        self.ctrl_box.setLayout(cg)
        self.toc_box = card(L('الفهرس', 'Contents'))
        tg = form_grid()
        field(tg, 0, 0, L('عدد المستويات في الفهرس', 'Levels in the contents'), self.toc_depth)
        tg.setColumnStretch(2, 1)
        self.toc_box.setLayout(tg)
        self.table_box = card(L('الجدول', 'Table'))
        self.table_lay = QVBoxLayout(self.table_box)
        self.table = None

        box = card(L('القسم', 'Section'))
        box.setLayout(g)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(box)
        for b in (self.policy_box, self.org_box, self.ctrl_box, self.toc_box, self.table_box):
            lay.addWidget(b)
        for w in (self.title_ar, self.title_en, self.code, self.resp_ar, self.resp_en, self.effective):
            w.textChanged.connect(self.changed.emit)
        for w in (self.new_page, self.in_toc):
            w.toggled.connect(self.changed.emit)
        for w in (self.kind, self.orientation, self.org_root, self.ctrl_policy):
            w.currentIndexChanged.connect(self.changed.emit)
        for w in (self.org_depth, self.toc_depth):
            w.valueChanged.connect(self.changed.emit)
        self.next_review.dateChanged.connect(self.changed.emit)
        self.kind.currentIndexChanged.connect(self._kind_boxes)

    def load(self, s):
        self.section = s
        widgets = (self.title_ar, self.title_en, self.kind, self.code, self.new_page, self.in_toc, self.next_review,
                   self.orientation, self.resp_ar, self.resp_en, self.effective,
                   self.org_root, self.org_depth, self.ctrl_policy, self.toc_depth)
        for w in widgets:
            w.blockSignals(True)
        self.title_ar.setText(s.get('title_ar') or '')
        self.title_en.setText(s.get('title_en') or '')
        self.kind.setCurrentIndex(max(0, self.kind.findData(s['kind'])))
        self.code.setText(s.get('code') or '')
        self.new_page.setChecked(bool(s['new_page']))
        self.in_toc.setChecked(bool(s['in_toc']))
        if s.get('next_review'):
            self.next_review.setDate(QDate.fromString(s['next_review'], 'yyyy-MM-dd'))
        else:
            self.next_review.setDate(self.next_review.minimumDate())
        st = s.get('style') or {}
        self.bg = BG.of_section(st)
        self.orientation.setCurrentIndex(max(0, self.orientation.findData(st.get('orientation', ''))))
        self._bg_text()
        meta = s.get('meta') or {}
        self.resp_ar.setText(meta.get('responsible_ar') or '')
        self.resp_en.setText(meta.get('responsible_en') or '')
        self.effective.setText(meta.get('effective_date') or '')
        d = s.get('data') or {}
        self.org_root.clear()
        self.org_root.addItem(L('الهيكل كاملاً', 'The whole structure'), None)
        for u in self.db.org_units(s['manual_id'], True):
            self.org_root.addItem(u['name_ar'] + (f' — {u["name_en"]}' if u.get('name_en') else ''), u['id'])
        self.org_root.setCurrentIndex(max(0, self.org_root.findData(d.get('root_id'))))
        self.org_depth.setValue(int(d.get('depth') or 0))
        self.ctrl_policy.clear()
        self.ctrl_policy.addItem(L('كل البنود', 'All items'), None)
        for x in self.db.sections(s['manual_id']):
            if x['kind'] == 'policy':
                self.ctrl_policy.addItem(x['title_ar'] or x['title_en'], x['id'])
        self.ctrl_policy.setCurrentIndex(max(0, self.ctrl_policy.findData(d.get('section_id'))))
        self.toc_depth.setValue(int(d.get('depth') or 2))
        for w in widgets:
            w.blockSignals(False)
        stt = STATUSES.get(s['status'], ('', ''))
        self.status.setText(L(stt[0], stt[1]) + f' · {L("الإصدار", "Version")} {s.get("version") or "1.0"}')
        self.status.setVisible(True)
        if self.table is not None:
            self.table.deleteLater()
            self.table = None
        if s['kind'] == 'table':
            self.table = TableEditor(dict(d) if d.get('columns') else table_data('custom'))
            self.table.changed.connect(self.changed.emit)
            self.table_lay.addWidget(self.table)
        self._kind_boxes()

    def _kind_boxes(self):
        k = self.kind.currentData()
        self.policy_box.setVisible(k == 'policy')
        self.org_box.setVisible(k == 'orgchart')
        self.ctrl_box.setVisible(k == 'compliance')
        self.toc_box.setVisible(k == 'toc')
        self.table_box.setVisible(k == 'table' and self.table is not None)

    def _bg_text(self):
        a = self.db.asset(self.bg['asset_id']) if self.bg and self.bg.get('asset_id') else None
        self.bg_label.setText(BG.summary(self.bg, L, a['name'] if a else None))

    def _landscape(self):
        o = self.orientation.currentData()
        if not o:
            lay = layout_with_defaults((self.db.manual(self.section['manual_id']) or {}).get('layout'))
            o = lay.get('orientation', 'portrait')
        return o == 'landscape'

    def _pick_bg(self):
        from .background import edit_background
        ok, bg = edit_background(self, self.db, self.bg, L('خلفية القسم', 'Section background'), True, self._landscape())
        if ok:
            self.bg = bg
            self._bg_text()
            self.changed.emit()

    def _clear_bg(self):
        self.bg = None
        self._bg_text()
        self.changed.emit()

    def value(self):
        s = self.section
        d = dict(s.get('data') or {})
        k = self.kind.currentData()
        if k == 'orgchart':
            d.update(root_id=self.org_root.currentData(), depth=self.org_depth.value())
        elif k == 'compliance':
            d.update(section_id=self.ctrl_policy.currentData())
        elif k == 'toc':
            d.update(depth=self.toc_depth.value())
        elif k == 'table':
            d = self.table.value() if self.table is not None else table_data('custom')
        nr = self.next_review.date()
        meta = dict(s.get('meta') or {}, responsible_ar=self.resp_ar.text().strip(), responsible_en=self.resp_en.text().strip(),
                    effective_date=self.effective.text().strip())
        style = {k: v for k, v in (s.get('style') or {}).items() if k not in ('bg_id', 'bg_mode', 'bg_opacity', 'bg_fit')}
        style['bg'] = self.bg
        if self.orientation.currentData():
            style['orientation'] = self.orientation.currentData()
        else:
            style.pop('orientation', None)
        return {'title_ar': self.title_ar.text().strip(), 'title_en': self.title_en.text().strip(), 'kind': k,
                'code': self.code.text().strip(), 'new_page': int(self.new_page.isChecked()),
                'in_toc': int(self.in_toc.isChecked()),
                'next_review': None if nr == self.next_review.minimumDate() else nr.toString('yyyy-MM-dd'),
                'meta': meta, 'style': style, 'data': d}


# ── preview ─────────────────────────────────────────────────────────────────────────────────────────
class Preview(QWidget):
    """The printed pages, laid out by the same engine as the PDF."""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.view = None
        self.scope = QComboBox()
        self.scope.addItem(L('القسم الحالي', 'This section'), 'section')
        self.scope.addItem(L('الدليل كاملاً', 'The whole manual'), 'all')
        fit(self.scope, 160)
        a11y(self.scope, L('ما تعرضه المعاينة', 'What the preview shows'))
        refresh = icon_button('reprint', L('تحديث المعاينة', 'Refresh the preview'))
        self.auto = QCheckBox(L('تحديث تلقائي', 'Update automatically'))
        self.auto.setChecked(True)
        self.state = muted('')
        top = QHBoxLayout()
        top.addWidget(self.scope)
        top.addWidget(refresh)
        top.addWidget(self.auto)
        top.addStretch(1)
        top.addWidget(self.state)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.addLayout(top)
        self.holder = QLabel(L('تظهر هنا صفحات الدليل كما ستُطبع.', 'The manual pages show here as they will print.'))
        self.holder.setAlignment(Qt.AlignCenter)
        self.holder.setProperty('muted', True)
        self.lay.addWidget(self.holder, 1)
        self.refresh_btn = refresh

    def _zoom(self):
        if self.view is not None and self.page_w:
            px = self.page_w * 96 / 25.4 + 40
            self.view.setZoomFactor(max(0.25, min(1.5, (self.view.width() - 24) / px)))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._zoom()

    def show_html(self, html, page_w=None):
        self.page_w = page_w or getattr(self, 'page_w', None)
        if self.view is None:
            try:
                from PySide6.QtWebEngineWidgets import QWebEngineView
                from ..core.pdf import settings_for
            except ImportError:
                self.holder.setText(L('المعاينة غير متاحة على هذا الجهاز.', 'The preview is not available on this computer.'))
                return
            self.view = QWebEngineView()
            settings_for(self.view.page())
            self.view.loadFinished.connect(lambda _ok: self._zoom())
            a11y(self.view, L('معاينة الصفحات', 'Page preview'))
            self.lay.replaceWidget(self.holder, self.view)
            self.holder.hide()
        from ..core.pdf import write_html
        path = write_html(html, os.path.join(self.ctx.data_dir, 'preview'), 'preview.html')
        self.view.load(QUrl.fromLocalFile(path))
        self.state.setText('')


# ── the editor page ─────────────────────────────────────────────────────────────────────────────────
class EditorTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.db = ctx, ctx.db
        self.mid = None
        self.sid = None
        self.dirty = False
        self.blocks = []
        # tree
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setDragDropMode(QAbstractItemView.InternalMove)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.currentItemChanged.connect(self._open)
        self.tree.model().rowsMoved.connect(lambda *_: QTimer.singleShot(0, self._tree_moved))
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        a11y(self.tree, L('أقسام الدليل', 'Manual sections'), L('اسحب لإعادة الترتيب أو لنقل قسم تحت قسم آخر',
                                                                  'Drag to reorder or to move a section under another'))
        self.search = QLineEdit()
        self.search.setPlaceholderText(L('بحث في الأقسام…', 'Search the sections…'))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter_tree)
        self.count = QLabel()
        self.count.setProperty('chip', True)
        add = button(L('قسم', 'Section'), 'plus', 'primary', tip=L('إضافة قسم بعد المحدد', 'Add a section after the selected one'))
        add.clicked.connect(lambda: self._add_menu(False))
        sub = button(L('قسم فرعي', 'Sub-section'), 'indent', tip=L('إضافة قسم تحت المحدد', 'Add a section under the selected one'))
        sub.clicked.connect(lambda: self._add_menu(True))
        up = icon_button('up', L('تحريك لأعلى', 'Move up'))
        up.clicked.connect(lambda: self._shift(-1))
        down = icon_button('down', L('تحريك لأسفل', 'Move down'))
        down.clicked.connect(lambda: self._shift(1))
        outd = icon_button('outdent', L('رفع مستوى القسم', 'Move one level up'))
        outd.clicked.connect(self._outdent)
        imp = icon_button('import', L('استيراد ملف تحت القسم المحدد', 'Import a file under the selected section'))
        imp.clicked.connect(self.import_here)
        dele = icon_button('trash', L('حذف الأقسام المحددة', 'Delete the selected sections'), 'danger')
        dele.clicked.connect(self.delete_sections)
        tb = flow_row([add, sub, up, down, outd, imp, dele], 4)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        sr = QHBoxLayout()
        sr.addWidget(self.search, 1)
        sr.addWidget(self.count)
        ll.addLayout(sr)
        ll.addWidget(tb)
        ll.addWidget(self.tree, 1)

        # middle: the section
        self.form = SectionForm(ctx)
        self.form.changed.connect(self._touch)
        self.fmt = FormatBar()
        self.block_list = QVBoxLayout()
        self.block_list.setSpacing(8)
        add_block = button(L('إضافة كتلة', 'Add a block'), 'plus')
        add_block.clicked.connect(lambda: self._add_block_menu())
        self.save_btn = button(L('حفظ', 'Save'), 'save', 'primary', tip='Ctrl+S')
        self.save_btn.clicked.connect(self.save)
        self.rev_btn = button(L('إصدار جديد…', 'New version…'), 'flag',
                              tip=L('يسجّل التغيير في سجل التغييرات المطبوع ويرفع رقم الإصدار', 'Records the change in the printed change history and raises the version'))
        self.rev_btn.clicked.connect(self.new_revision)
        self.wf_review = button(L('إرسال للمراجعة', 'Send for review'), 'export')
        self.wf_review.clicked.connect(lambda: self.set_status('review'))
        self.wf_approve = button(L('اعتماد', 'Approve'), 'check')
        self.wf_approve.clicked.connect(lambda: self.set_status('approved'))
        self.wf_back = button(L('إعادة إلى مسودة', 'Back to draft'), 'reset')
        self.wf_back.clicked.connect(lambda: self.set_status('draft'))
        self.saved_label = muted('')
        self.check_btn = button(L('فحص الدليل', 'Check the manual'), 'shield',
                                tip=L('يفحص الدليل كاملاً: الهوامش والجداول واتجاه النص والقوائم والرموز وفواصل الصفحات وأرقامها',
                                      'Checks the whole manual: margins, tables, text direction, lists, symbols, page breaks and numbers'))
        self.check_btn.clicked.connect(lambda: self.ctx.window and self.ctx.window.open_doctor(run=True))
        self.preview_btn = button(L('المعاينة', 'Preview'), 'preview', tip=L('إظهار المعاينة أو إخفاؤها لتتسع مساحة التحرير',
                                                                       'Show or hide the preview to widen the editing area'))
        self.preview_btn.setCheckable(True)
        self.preview_btn.setChecked(True)
        self.preview_btn.toggled.connect(self._toggle_preview)
        actions = flow_row([self.save_btn, self.rev_btn, self.wf_review, self.wf_approve, self.wf_back, self.check_btn,
                            self.preview_btn, self.saved_label])
        content = QWidget()
        cl = QVBoxLayout(content)
        cl.setContentsMargins(4, 0, 4, 10)
        cl.addWidget(self.form)
        blocks_box = card(L('المحتوى', 'Content'))
        bl = QVBoxLayout(blocks_box)
        bl.addLayout(self.block_list)
        bl.addWidget(add_block, 0, Qt.AlignLeading)
        self.blocks_box = blocks_box
        cl.addWidget(blocks_box)
        cl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(420)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)     # the content follows the pane width
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(content)
        self.empty = QLabel(L('اختر قسماً من القائمة لتعديله، أو أضف قسماً جديداً.', 'Choose a section from the list to edit it, or add a new one.'))
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setProperty('muted', True)
        mid = QWidget()
        ml = QVBoxLayout(mid)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.addWidget(actions)
        # the formatting bar stays above the content, whichever block is being written
        fmt_box = QFrame()
        fmt_box.setObjectName('fmtbar')
        fmt_box.setStyleSheet('QFrame#fmtbar{background:#f1f5fb;border:1px solid #d5deea;border-radius:8px}')
        fl = QHBoxLayout(fmt_box)
        fl.setContentsMargins(6, 3, 6, 3)
        fl.addWidget(self.fmt)
        self.fmt_box = fmt_box
        ml.addWidget(fmt_box)
        ml.addWidget(self.empty)
        ml.addWidget(scroll, 1)
        self.scroll = scroll

        self.preview = Preview(ctx)
        self.preview.refresh_btn.clicked.connect(lambda: self.refresh_preview(force=True))
        self.preview.scope.currentIndexChanged.connect(lambda: self.refresh_preview(force=True))
        self._ptimer = QTimer(self)
        self._ptimer.setSingleShot(True)
        self._ptimer.setInterval(1800)
        self._ptimer.timeout.connect(self.refresh_preview)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(mid)
        split.addWidget(self.preview)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 5)
        split.setStretchFactor(2, 4)
        split.setSizes([260, 900, 380])
        split.setCollapsible(1, False)
        self.split = split
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 10)
        self.title = QLabel()
        self.title.setStyleSheet('font-size:15px;font-weight:700;color:#0847B0')
        lay.addWidget(self.title)
        lay.addWidget(split, 1)
        QShortcut(QKeySequence.Save, self, activated=self.save)
        self._show_editor(False)

    def showEvent(self, e):
        super().showEvent(e)
        if getattr(self, '_pending_preview', False):
            QTimer.singleShot(150, lambda: self.refresh_preview(force=True))

    # ── loading ──────────────────────────────────────────────────────
    def load_manual(self, mid):
        if self.dirty:
            self.save(quiet=True)
        self.mid = mid
        self.sid = None
        m = self.db.manual(mid) if mid else None
        self.title.setText((m['title_ar'] or m['title_en'] or '') if m else L('لا يوجد دليل مفتوح — أنشئ دليلاً من صفحة «الأدلة».',
                                                                            'No manual is open — create one on the «Manuals» page.'))
        self.reload_tree()
        self._show_editor(False)
        self._perms()
        if m:
            self.refresh_preview(force=True)

    def reload_tree(self, select=None):
        self.tree.blockSignals(True)
        self.tree.clear()
        items = {}
        n = 0
        if self.mid:
            for s, depth in self.db.flat(self.mid, active_only=False):
                it = QTreeWidgetItem([self._label(s)])
                it.setData(0, Qt.UserRole, s['id'])
                it.setIcon(0, icon(KIND_ICONS.get(s['kind'], 'text'), '#0847B0' if s['kind'] == 'chapter' else '#64748b'))
                if s['status'] == 'approved':
                    it.setToolTip(0, L('معتمد', 'Approved'))
                parent = items.get(s['parent_id'])
                (parent.addChild(it) if parent else self.tree.addTopLevelItem(it))
                items[s['id']] = it
                n += 1
        self.tree.expandAll()
        self.count.setText(L(f'الأقسام: {n}', f'Sections: {n}'))
        self.tree.blockSignals(False)
        target = select or self.sid
        if target and target in items:
            self.tree.setCurrentItem(items[target])

    def _label(self, s):
        t = (s.get('title_ar') or '') if L('a', 'b') == 'a' else (s.get('title_en') or '')
        t = t or s.get('title_ar') or s.get('title_en') or L('(بلا عنوان)', '(untitled)')
        mark = {'review': ' ◔', 'approved': ' ✓'}.get(s['status'], '') if self.ctx.workflow else ''
        return t + mark

    def _filter_tree(self, text):
        from .common import norm
        q = norm(text)

        def walk(it):
            show = not q or q in norm(it.text(0))
            for i in range(it.childCount()):
                show = walk(it.child(i)) or show
            it.setHidden(not show)
            return show
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    def _show_editor(self, on):
        self.scroll.setVisible(on)
        self.fmt_box.setVisible(on)
        self.empty.setVisible(not on)

    def _toggle_preview(self, on):
        self.preview.setVisible(on)
        if on:
            self.refresh_preview(force=True)

    def _open(self, cur, prev):
        if self.dirty and self.sid:
            self.save(quiet=True)
        if cur is None:
            self._show_editor(False)
            return
        sid = cur.data(0, Qt.UserRole)
        s = self.db.section(sid)
        if not s:
            return
        self.sid = sid
        self.form.load(s)
        _clear_layout(self.block_list)
        self.blocks = []
        for b in self.db.blocks(sid):
            self._append_block(b)
        has_blocks = s['kind'] not in ('cover', 'toc')
        self.blocks_box.setVisible(has_blocks)
        self.dirty = False
        self.saved_label.setText('')
        self._show_editor(True)
        size_tree(self.scroll)
        self._perms()
        if self.preview.scope.currentData() == 'section':
            self.refresh_preview(force=True)

    def _reload_blocks(self):
        _clear_layout(self.block_list)
        self.blocks = []
        for b in self.db.blocks(self.sid):
            self._append_block(b)
        size_tree(self.scroll)

    def goto(self, sid, b=None, path=None):
        """Opens a section and brings one of its blocks into view (used by the checker)."""
        if self.dirty:
            self.save(quiet=True)
        self.reload_tree(select=sid)
        if self.sid != sid or b is None or b >= len(self.blocks):
            return
        w = self.blocks[b]
        side = (path or ['ar'])[-1] if path and path[-1] in ('ar', 'en') else 'ar'
        target = getattr(w, side, None)

        def show():
            self.scroll.ensureWidgetVisible(w, 40, 80)
            w.setProperty('flash', True)
            w.style().unpolish(w)
            w.style().polish(w)
            if target is not None and hasattr(target, 'setFocus'):
                target.setFocus()
            QTimer.singleShot(2500, lambda: (w.setProperty('flash', False), w.style().unpolish(w), w.style().polish(w)))
        QTimer.singleShot(60, show)

    def _append_block(self, b, at=None):
        w = BlockWidget(self.ctx, b)
        w.changed.connect(self._touch)
        w.remove.connect(self._remove_block)
        w.move.connect(self._move_block)
        w.insert_after.connect(lambda src: self._add_block_menu(self.blocks.index(src) + 1))
        w.focused.connect(self.fmt.set_target)
        if at is None:
            self.block_list.addWidget(w)
            self.blocks.append(w)
        else:
            self.block_list.insertWidget(at, w)
            self.blocks.insert(at, w)
        return w

    # ── editing ──────────────────────────────────────────────────────
    def _touch(self):
        self.dirty = True
        self.saved_label.setText(L('تعديلات غير محفوظة', 'Unsaved changes'))
        if self.preview.auto.isChecked():
            self._ptimer.start()

    def save(self, quiet=False):
        if not self.sid or not self.ctx.can('edit'):
            return
        data = self.form.value()
        self.db.save_section(data, self.sid)
        blocks = [w.value() for w in self.blocks]
        fixed = 0
        prefs = doctor.load_prefs(self.db)
        if prefs.get('auto_save'):                 # the checker's safe text fixes, when the user turned them on
            rules = [r for r in doctor.AUTO_ON_SAVE if r not in (prefs.get('disabled') or [])]
            lm = layout_with_defaults(self.db.manual(self.mid)['layout'])['lang_mode']
            blocks, fixed = doctor.autofix_blocks(blocks, lm, rules)
        self.db.replace_blocks(self.sid, blocks)
        if fixed:
            self._reload_blocks()
        self.dirty = False
        self.saved_label.setText(L(f'حُفظ، وضُبط {fixed} موضعاً', f'Saved; {fixed} place(s) tidied') if fixed else L('حُفظ', 'Saved'))
        it = self.tree.currentItem()
        if it:
            it.setText(0, self._label(self.db.section(self.sid)))
            it.setIcon(0, icon(KIND_ICONS.get(data['kind'], 'text'), '#64748b'))
        if self.ctx.window and not quiet:
            self.ctx.window.statusBar().showMessage(L('حُفظ القسم', 'Section saved'), 2500)

    def _add_block_menu(self, at=None):
        m = QMenu(self)
        for k, (ar, en) in BLOCK_KINDS.items():
            a = m.addAction(icon(_block_icon(k), '#64748b'), L(ar, en))
            a.triggered.connect(lambda _=False, kk=k: self.add_block(kk, at))
        m.exec(self.cursor().pos())

    def add_block(self, kind, at=None):
        b = {'kind': kind, 'ar': '', 'en': '', 'data': table_data('custom') if kind == 'table' else {}}
        w = self._append_block(b, at)
        self._touch()
        QTimer.singleShot(50, lambda: self.scroll.ensureWidgetVisible(w))

    def _remove_block(self, w):
        v = w.value()
        if (v.get('ar') or v.get('en') or v.get('data')) and not confirm(self, L('حذف هذه الكتلة؟', 'Delete this block?')):
            return
        self.blocks.remove(w)
        w.setParent(None)
        w.deleteLater()
        self._touch()

    def _move_block(self, w, d):
        i = self.blocks.index(w)
        j = i + d
        if not 0 <= j < len(self.blocks):
            return
        self.blocks.pop(i)
        self.blocks.insert(j, w)
        self.block_list.removeWidget(w)
        self.block_list.insertWidget(j, w)
        self._touch()

    # ── sections ─────────────────────────────────────────────────────
    def _add_menu(self, child):
        if not self.mid:
            info(self, L('أنشئ دليلاً أولاً من صفحة «الأدلة».', 'Create a manual first on the «Manuals» page.'))
            return
        m = QMenu(self)
        for k, (ar, en) in SECTION_KINDS.items():
            a = m.addAction(icon(KIND_ICONS[k], '#64748b'), L(ar, en))
            a.triggered.connect(lambda _=False, kk=k: self.add_section(kk, child))
        m.exec(self.cursor().pos())

    def add_section(self, kind, child=False):
        if self.dirty:
            self.save(quiet=True)
        cur = self.db.section(self.sid) if self.sid else None
        parent = (cur['id'] if child else cur['parent_id']) if cur else None
        ar, en = SECTION_KINDS[kind]
        data = {'manual_id': self.mid, 'parent_id': parent, 'kind': kind, 'title_ar': ar, 'title_en': en,
                'new_page': 1 if kind in ('chapter', 'toc', 'orgchart') else 0, 'in_toc': 0 if kind in ('cover', 'toc') else 1}
        if kind == 'table':
            data['data'] = table_data('custom')
        sid = self.db.save_section(data)
        if cur and not child:
            sibs = [s for s in self.db.sections(self.mid, False) if s['parent_id'] == parent and s['id'] != sid]
            idx = next((i for i, s in enumerate(sibs) if s['id'] == cur['id']), len(sibs) - 1)
            before = sibs[idx + 1]['id'] if idx + 1 < len(sibs) else None
            self.db.move_section(sid, parent, before)
        if kind == 'policy':
            self.db.replace_blocks(sid, policy_blocks())
        elif kind in ('text', 'chapter'):
            self.db.replace_blocks(sid, [] if kind == 'chapter' else [{'kind': 'paragraph', 'ar': '', 'en': ''}])
        self.sid = sid
        self.reload_tree(select=sid)
        self.form.title_ar.setFocus()
        self.form.title_ar.selectAll()

    def _tree_moved(self):
        """After a drag in the tree: every section takes the parent and order it now has."""
        def walk(parent_item, parent_id):
            for i in range(parent_item.childCount() if parent_item else self.tree.topLevelItemCount()):
                it = parent_item.child(i) if parent_item else self.tree.topLevelItem(i)
                sid = it.data(0, Qt.UserRole)
                self.db.conn.execute('UPDATE sections SET parent_id = ?, sort = ? WHERE id = ?', (parent_id, (i + 1) * 10, sid))
                walk(it, sid)
        walk(None, None)
        self.db.conn.commit()
        self._preview_soon()

    def _shift(self, d):
        if self.sid and self.db.shift_section(self.sid, d):
            self.reload_tree(select=self.sid)
            self._preview_soon()

    def _outdent(self):
        s = self.db.section(self.sid) if self.sid else None
        if not s or not s['parent_id']:
            return
        parent = self.db.section(s['parent_id'])
        sibs = [x for x in self.db.sections(self.mid, False) if x['parent_id'] == parent['parent_id']]
        idx = next(i for i, x in enumerate(sibs) if x['id'] == parent['id'])
        before = sibs[idx + 1]['id'] if idx + 1 < len(sibs) else None
        self.db.move_section(self.sid, parent['parent_id'], before)
        self.reload_tree(select=self.sid)
        self._preview_soon()

    def selected_ids(self):
        return [it.data(0, Qt.UserRole) for it in self.tree.selectedItems()]

    def delete_sections(self):
        ids = self.selected_ids()
        if not ids or not self.ctx.can('edit'):
            return
        if not confirm(self, L(f'حذف {len(ids)} قسم بمحتواها وسجل تغييراتها؟', f'Delete {len(ids)} section(s) with their content and change history?')):
            return
        kept = self.db.delete_sections(ids)
        self.sid = None
        self.dirty = False
        self.reload_tree()
        self._show_editor(False)
        if kept:
            info(self, L(f'لم يُحذف {len(kept)} قسم لأن تحتها أقساماً فرعية: احذف الأقسام الفرعية أولاً أو انقلها.',
                         f'{len(kept)} section(s) were kept because they have sub-sections: delete or move those first.'))
        self._preview_soon()

    def _menu(self, pos):
        m = QMenu(self)
        m.addAction(icon('plus', '#64748b'), L('إضافة قسم بعده', 'Add a section after it'), lambda: self._add_menu(False))
        m.addAction(icon('indent', '#64748b'), L('إضافة قسم فرعي', 'Add a sub-section'), lambda: self._add_menu(True))
        m.addAction(icon('import', '#64748b'), L('استيراد ملف تحته…', 'Import a file under it…'), self.import_here)
        m.addSeparator()
        m.addAction(icon('trash', '#b42318'), L('حذف', 'Delete'), self.delete_sections)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def import_here(self):
        if not self.mid:
            return
        from .manuals import import_into
        if self.dirty:
            self.save(quiet=True)
        if import_into(self, self.ctx, self.mid, self.sid):
            self.reload_tree()
            self._preview_soon()

    # ── versions and workflow ────────────────────────────────────────
    def new_revision(self):
        if not self.sid:
            return
        self.save(quiet=True)
        d = RevisionDialog(self, self.db.section(self.sid), self.ctx.user_name())
        if d.exec():
            v = d.value()
            self.db.add_revision(self.sid, v['version'], v['changes_ar'], v['changes_en'], v['by'], v['date'])
            self.form.load(self.db.section(self.sid))
            self._preview_soon()

    def set_status(self, status):
        ids = self.selected_ids() or ([self.sid] if self.sid else [])
        if not ids:
            return
        need = {'review': 'edit', 'approved': 'approve', 'draft': 'review'}[status]
        if not self.ctx.can(need):
            error(self, L('ليست لديك صلاحية هذا الإجراء.', 'You are not allowed to do this.'))
            return
        note = ''
        if status == 'draft':
            note, ok = QInputDialog.getText(self, L('إعادة إلى مسودة', 'Back to draft'), L('الملاحظات للمعِدّ:', 'Notes for the author:'))
            if not ok:
                return
        if self.dirty:
            self.save(quiet=True)
        self.db.set_status(ids, status, self.ctx.user_name(), note)
        self.reload_tree(select=self.sid)
        if self.sid:
            self.form.load(self.db.section(self.sid))
        self._preview_soon()

    def _perms(self):
        wf = self.ctx.workflow
        for b in (self.wf_review, self.wf_approve, self.wf_back):
            b.setVisible(wf)
        self.wf_approve.setEnabled(self.ctx.can('approve'))
        self.wf_back.setEnabled(self.ctx.can('review'))
        editable = self.ctx.can('edit')
        self.save_btn.setEnabled(editable)
        self.rev_btn.setEnabled(editable)
        self.form.setEnabled(editable)
        self.blocks_box.setEnabled(editable)

    # ── preview ──────────────────────────────────────────────────────
    def _preview_soon(self):
        if self.preview.auto.isChecked():
            self._ptimer.start()

    def refresh_preview(self, force=False):
        if not self.mid or (not force and not self.preview.auto.isChecked()):
            return
        if not self.isVisible() or not self.preview.isVisible() and not self.preview_btn.isChecked():
            self._pending_preview = self.isVisible() is False
            return
        if not self.isVisible():
            self._pending_preview = True           # drawn when the editor is shown
            return
        self._pending_preview = False
        if self.dirty:
            self.save(quiet=True)
        from ..core.html import build_html
        only = None
        if self.preview.scope.currentData() == 'section' and self.sid:
            only = [self.sid]
        try:
            html = build_html(self.db, self.mid, 'print', only=only, workflow=self.ctx.workflow)
        except Exception as e:  # noqa: BLE001 — a preview must never take the editor down
            self.preview.state.setText(str(e)[:120])
            return
        from ..core.pdf import page_size_mm
        self.preview.show_html(html, page_size_mm(self.db.manual(self.mid))[0])


class RevisionDialog(SizedDialog):
    def __init__(self, parent, section, by):
        super().__init__(parent)
        self.setWindowTitle(L('إصدار جديد', 'New version'))
        cur = section.get('version') or '1.0'
        try:
            major, minor = cur.split('.')[:2]
            nxt = f'{major}.{int(minor) + 1}'
        except ValueError:
            nxt = cur + '.1'
        self.version = ltr(QLineEdit(nxt), 100)
        self.date = QDateEdit(QDate.currentDate())
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat('yyyy-MM-dd')
        fit(self.date, 140)
        self.ch_ar = QTextEdit()
        self.ch_ar.setPlaceholderText(L('ما الذي تغيّر (بالعربية)', 'What changed (Arabic)'))
        self.ch_ar.setFixedHeight(80)
        self.ch_en = QTextEdit()
        self.ch_en.setPlaceholderText(L('ما الذي تغيّر (بالإنجليزية)', 'What changed (English)'))
        self.ch_en.setFixedHeight(80)
        self.ch_en.setLayoutDirection(Qt.LeftToRight)
        self.by = QLineEdit(by or '')
        g = form_grid()
        field(g, 0, 0, L('رقم الإصدار', 'Version'), self.version)
        field(g, 1, 0, L('التاريخ', 'Date'), self.date)
        field(g, 2, 0, L('التغييرات (عربي)', 'Changes (Arabic)'), self.ch_ar)
        field(g, 3, 0, L('التغييرات (إنجليزي)', 'Changes (English)'), self.ch_en)
        field(g, 4, 0, L('بواسطة', 'By'), self.by)
        g.setColumnStretch(1, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(L('تسجيل', 'Record'))
        bb.button(QDialogButtonBox.Cancel).setText(L('إلغاء', 'Cancel'))
        name_buttons(bb)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(hint(L(f'الإصدار الحالي: {cur}. يظهر التغيير في جدول «سجل التغييرات» في نهاية القسم.',
                             f'Current version: {cur}. The change shows in the «Change history» table at the end of the section.')))
        lay.addLayout(g)
        lay.addWidget(bb)
        self.resize(560, 420)

    def _ok(self):
        if not self.version.text().strip() or not (self.ch_ar.toPlainText().strip() or self.ch_en.toPlainText().strip()):
            error(self, L('اكتب رقم الإصدار ووصف التغيير.', 'Enter the version and a description of the change.'))
            return
        self.accept()

    def value(self):
        return {'version': self.version.text().strip(), 'date': self.date.date().toString('yyyy-MM-dd'),
                'changes_ar': self.ch_ar.toPlainText().strip(), 'changes_en': self.ch_en.toPlainText().strip(),
                'by': self.by.text().strip()}

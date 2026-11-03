"""The editor of one manual: the tree of sections on one side, the selected section (its properties and its blocks,
each with an Arabic and an English side) in the middle, and the live preview of the printed pages on the other side.
Changes are saved automatically when another section is opened and before the preview is refreshed."""
import os

from PySide6.QtCore import QDate, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDateEdit, QDialogButtonBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QLineEdit, QMenu, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter,
                               QTableWidget, QTableWidgetItem, QTextEdit, QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ..core.db import BLOCK_KINDS, SECTION_KINDS, STATUSES
from ..core.richtext import clean
from ..core import backgrounds as BG, doctor
from ..core.templates import BLOCK_ALIGN, TABLE_COLORS, TABLE_PRESETS, TABLE_THEMES, layout_with_defaults, policy_blocks, table_data
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

    extra_menu = None                 # set by the block: adds its own actions under cut, copy and paste

    def contextMenuEvent(self, e):    # noqa: N802 (Qt name)
        m = self.createStandardContextMenu()
        if self.extra_menu:
            m.addSeparator()
            self.extra_menu(m)
        m.exec(e.globalPos())

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


class TableColorsDialog(SizedDialog):
    """The colours of a table: a ready set or each colour by itself, for this table only or every table."""

    def __init__(self, parent, own, design):
        super().__init__(parent)
        self.setWindowTitle(L('ألوان الجدول', 'Table colours'))
        self.design = design                      # the manual's colours, keyed like TABLE_COLORS
        self.values = dict(design, **{k: v for k, v in (own or {}).items() if v})
        self.theme = QComboBox()
        self.theme.addItem(L('اختيار مجموعة جاهزة…', 'Choose a ready set…'), '')
        self.theme.addItem(L('ألوان الدليل (من التصميم)', 'The manual colours (from the design)'), 'design')
        for k, ((ar, en), _v) in TABLE_THEMES.items():
            self.theme.addItem(L(ar, en), k)
        self.theme.activated.connect(self._theme)
        fit(self.theme, 280)
        self.buttons = {}
        g = form_grid()
        field(g, 0, 0, L('مجموعة ألوان', 'Colour set'), self.theme)
        for i, (k, (_dk, (ar, en))) in enumerate(TABLE_COLORS.items(), 1):
            b = ltr(QPushButton(), 120)
            b.clicked.connect(lambda _=False, kk=k: self._pick(kk))
            self.buttons[k] = b
            field(g, i, 0, L(ar, en), b)
        self.sample = QLabel()
        self.sample.setMinimumHeight(90)
        self.sample.setAlignment(Qt.AlignLeading | Qt.AlignVCenter)
        a11y(self.sample, L('شكل الجدول بهذه الألوان', 'The table in these colours'))
        g.addWidget(self.sample, len(TABLE_COLORS) + 1, 1)
        self.scope = QComboBox()
        self.scope.addItem(L('هذا الجدول فقط', 'This table only'), 'one')
        self.scope.addItem(L('كل جداول الدليل (تصبح ألوان الدليل)', 'Every table of the manual (becomes the manual colours)'), 'all')
        fit(self.scope, 330)
        field(g, len(TABLE_COLORS) + 2, 0, L('تُطبَّق على', 'Applies to'), self.scope)
        g.setColumnStretch(1, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(L('تطبيق', 'Apply'))
        bb.button(QDialogButtonBox.Cancel).setText(L('إلغاء', 'Cancel'))
        name_buttons(bb)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(g)
        lay.addWidget(bb)
        self._paint()

    def _theme(self, i):
        k = self.theme.itemData(i)
        if k == 'design':
            self.values = dict(self.design)
        elif k:
            self.values = dict(TABLE_THEMES[k][1])
        self._paint()

    def _pick(self, k):
        c = QColorDialog.getColor(QColor(self.values.get(k) or '#ffffff'), self, L(*TABLE_COLORS[k][1]))
        if c.isValid():
            self.values[k] = c.name().upper()
            self._paint()

    def _paint(self):
        for k, b in self.buttons.items():
            c = self.values.get(k) or '#ffffff'
            light = QColor(c).lightness() > 150
            b.setText('')                        # the colour itself, its code only on hover
            b.setToolTip(c.upper())
            b.setStyleSheet(f'background:{c};color:{"#1e293b" if light else "#ffffff"};border:1px solid #c9d4e3;border-radius:6px')
        v = self.values
        cell = f'border:1px solid {v["border"]};padding:3px 10px;color:{v["text"]}'
        rows = ''.join(f'<tr><td style="{cell};background:{v["stripe"] if i % 2 else "#ffffff"}">{L("خلية", "Cell")} {i}</td>'
                       f'<td style="{cell};background:{v["stripe"] if i % 2 else "#ffffff"}">…</td></tr>' for i in (1, 2, 3))
        self.sample.setText(f'<table cellspacing="0" style="border-collapse:collapse"><tr>'
                            f'<th style="background:{v["head"]};color:{v["head_text"]};border:1px solid {v["border"]};padding:3px 10px">'
                            f'{L("العمود الأول", "First column")}</th><th style="background:{v["head"]};color:{v["head_text"]};'
                            f'border:1px solid {v["border"]};padding:3px 10px">{L("العمود الثاني", "Second column")}</th></tr>{rows}</table>')

    def result_colors(self):
        """Only the colours that differ from the manual's are kept on a single table."""
        if self.scope.currentData() == 'all':
            return 'all', dict(self.values)
        return 'one', {k: v for k, v in self.values.items() if v and v.upper() != (self.design.get(k) or '').upper()}


class TableEditor(QWidget):
    """A table with an Arabic and an English layer (switched above the grid): columns, rows, presets, colours."""
    changed = Signal()
    colors_for_all = Signal(dict)
    design_colors = None                 # set by the editor: the manual's table colours

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
        colors = button(L('ألوان الجدول…', 'Table colours…'), 'palette')
        colors.clicked.connect(self.edit_colors)
        self.preset.setMinimumContentsLength(10)
        self.preset.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(flow_row([self.preset, self.lang, self.numbered, self.bold]))
        lay.addWidget(self.grid)
        lay.addWidget(flow_row([cols, addr, delr, up, down, paste, colors]))
        self.fill()

    def edit_colors(self):
        design = TableEditor.design_colors or {k: TABLE_THEMES['blue'][1][k] for k in TABLE_COLORS}
        d = TableColorsDialog(self, self.data.get('colors'), design)
        if not d.exec():
            return
        scope, colors = d.result_colors()
        if scope == 'all':
            self.data.pop('colors', None)
            self.changed.emit()
            self.colors_for_all.emit(colors)
        else:
            if colors:
                self.data['colors'] = colors
            else:
                self.data.pop('colors', None)
            self.changed.emit()

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
    table_colors = Signal(dict)

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
        self.align.currentIndexChanged.connect(lambda *_: self.changed.emit())
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
        self.ar = self.en = self.table = self.links = self.orient = self.head = None
        if k in TEXT_KINDS:
            (par, pen) = PLACEHOLDERS[k]
            self.ar = RichEdit(True, L(*par))
            self.en = RichEdit(False, L(*pen) if isinstance(pen, tuple) else pen)
            self.ar.set_value(self.block.get('ar'))
            self.en.set_value(self.block.get('en'))
            for e in (self.ar, self.en):
                e.textChanged.connect(lambda *_: self.changed.emit())
                e.focused.connect(self.focused.emit)
                e.extra_menu = self.fill_menu
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
            self.table.changed.connect(lambda *_: self.changed.emit())
            self.table.colors_for_all.connect(self.table_colors.emit)
            self.body.addWidget(self.table)
        elif k == 'links':
            self.links = LinksEditor(d.get('items') or [])
            self.links.changed.connect(lambda *_: self.changed.emit())
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
            self.width.valueChanged.connect(lambda *_: self.changed.emit())
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
                e.textChanged.connect(lambda *_: self.changed.emit())
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
            from .inspector import HEADS, ORIENTS
            self.head = QComboBox()
            for key, (ar, en) in HEADS.items():
                self.head.addItem(L(ar, en), key)
            self.head.setCurrentIndex(max(0, self.head.findData((self.block.get('style') or {}).get('head', ''))))
            self.head.currentIndexChanged.connect(lambda *_: self.changed.emit())
            fit(self.head, 200)
            self.orient = QComboBox()
            for key, (ar, en) in ORIENTS.items():
                self.orient.addItem(L(ar, en), key)
            self.orient.setCurrentIndex(max(0, self.orient.findData((self.block.get('style') or {}).get('orient', ''))))
            self.orient.currentIndexChanged.connect(lambda *_: self.changed.emit())
            fit(self.orient, 160)
            g = form_grid()
            field(g, 0, 0, L('اتجاه الصفحات بعده', 'Direction of the pages after it'), self.orient)
            field(g, 1, 0, L('ترويسة الصفحات بعده', 'Header of the pages after it'), self.head)
            g.setColumnStretch(2, 1)
            note = muted(L('تبدأ الكتلة التالية في صفحة جديدة. الاتجاه والترويسة المختاران هنا يسريان على الصفحات التالية حتى الفاصل القادم.',
                           'The next block starts on a new page. The direction and header chosen here apply to the next pages, up to the next break.'))
            note.setWordWrap(True)
            self.body.addWidget(note)
            self.body.addLayout(g)
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

    def fill_menu(self, m):
        """The block's actions, for a right click on it (also under cut, copy and paste in its text boxes)."""
        m.addAction(icon('plus', '#334155'), L('إضافة كتلة بعدها', 'Add a block after it'), lambda: self.insert_after.emit(self))
        m.addAction(icon('up', '#334155'), L('تحريك لأعلى', 'Move up'), lambda: self.move.emit(self, -1))
        m.addAction(icon('down', '#334155'), L('تحريك لأسفل', 'Move down'), lambda: self.move.emit(self, 1))
        if self.align.isVisible():
            sub = m.addMenu(L('المحاذاة', 'Alignment'))
            for i in range(self.align.count()):
                a = sub.addAction(self.align.itemText(i), lambda i=i: self.align.setCurrentIndex(i))
                a.setCheckable(True)
                a.setChecked(i == self.align.currentIndex())
        kinds = m.addMenu(L('تحويل إلى', 'Change into'))
        for i in range(self.kind.count()):
            if i != self.kind.currentIndex():
                kinds.addAction(self.kind.itemIcon(i), self.kind.itemText(i), lambda i=i: self.kind.setCurrentIndex(i))
        m.addSeparator()
        m.addAction(icon('trash', '#b42318'), L('حذف الكتلة', 'Delete the block'), lambda: self.remove.emit(self))

    def contextMenuEvent(self, e):    # noqa: N802 (Qt name)
        m = QMenu(self)
        self.fill_menu(m)
        m.exec(e.globalPos())

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
        if k == 'pagebreak' and getattr(self, 'orient', None) is not None:
            for key, combo in (('orient', self.orient), ('head', self.head)):
                if combo.currentData():
                    style[key] = combo.currentData()
                else:
                    style.pop(key, None)
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


def _alive(w):
    """False once Qt has deleted the widget (a delayed step must not touch it then)."""
    from shiboken6 import isValid
    return w is not None and isValid(w)


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
    table_colors = Signal(dict)

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
        self.orientation.addItem(L('عمودي', 'Portrait'), 'portrait')
        self.orientation.addItem(L('أفقي', 'Landscape'), 'landscape')
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
            w.textChanged.connect(lambda *_: self.changed.emit())
        for w in (self.new_page, self.in_toc):
            w.toggled.connect(lambda *_: self.changed.emit())
        for w in (self.kind, self.orientation, self.org_root, self.ctrl_policy):
            w.currentIndexChanged.connect(lambda *_: self.changed.emit())
        for w in (self.org_depth, self.toc_depth):
            w.valueChanged.connect(lambda *_: self.changed.emit())
        self.next_review.dateChanged.connect(lambda *_: self.changed.emit())
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
            self.table.changed.connect(lambda *_: self.changed.emit())
            self.table.colors_for_all.connect(self.table_colors.emit)
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
# a click on the pages names what was clicked; the page script reports it through the console
PICK_JS = r"""
(function(){if(window.__mbPick)return;window.__mbPick=1;
var st=document.createElement('style');st.textContent='[data-b]:hover,[data-cv]:hover,[data-sid]:hover>.frame{outline:2px dashed #0C67EC;outline-offset:1px;cursor:pointer}'
 +'.pagedjs_margin:hover{outline:2px dashed #F28C28;cursor:pointer} .mb-picked{outline:2px solid #F28C28 !important;outline-offset:1px}';
document.head.appendChild(st);
function span(p){var bs=p?p.querySelectorAll('[data-b]'):[];return bs.length?' '+bs[0].getAttribute('data-b')+' '+bs[bs.length-1].getAttribute('data-b'):'';}
function mark(el){document.querySelectorAll('.mb-picked').forEach(function(x){x.classList.remove('mb-picked')});if(el)el.classList.add('mb-picked');}
document.addEventListener('click',function(e){var t=e.target,side=t.closest('.en')?'en':'ar';
 var c=t.closest('[data-cv]');if(c){mark(c);console.log('MBPICK c '+c.getAttribute('data-cv'));return;}
 if(t.closest('.cover')){mark(t.closest('.cover'));console.log('MBPICK p cover');return;}
 var b=t.closest('[data-b]');if(b){mark(b);console.log('MBPICK b '+b.getAttribute('data-b')+' '+side);return;}
 var m=t.closest('.pagedjs_margin');if(m){mark(m);console.log('MBPICK m '+(m.className.indexOf('bottom')>=0?'footer':'header')+span(t.closest('.pagedjs_page')));return;}
 var p=t.closest('.pagedjs_page');
 if(p){var bs=p.querySelectorAll('[data-b]');mark(p.querySelector('.pagedjs_pagebox'));
  var ar=p.querySelector('.pagedjs_area').getBoundingClientRect();
  if(e.clientY<ar.top){console.log('MBPICK m header'+span(p));return;}
  if(e.clientY>ar.bottom){console.log('MBPICK m footer'+span(p));return;}
  console.log('MBPICK p page '+(bs.length?bs[0].getAttribute('data-b'):'')+' '+(bs.length?bs[bs.length-1].getAttribute('data-b'):''));return;}
},true);})();
"""


def _picking_page(parent, on_pick):
    from PySide6.QtWebEngineCore import QWebEnginePage

    class Page(QWebEnginePage):
        def javaScriptConsoleMessage(self, level, message, line, source):    # noqa: N802 (Qt name)
            if message.startswith('MBPICK '):
                on_pick(message[7:])

    return Page(parent)


class Preview(QWidget):
    """The printed pages, laid out by the same engine as the PDF. A click on a block, a section, the header or the
    footer reports it (``picked``) so its editor opens."""
    picked = Signal(str)

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
        from .inspector import Inspector
        self.inspector = Inspector(ctx)
        self.inspector.setMaximumHeight(340)
        self.lay.addWidget(self.inspector)
        self.holder = QLabel(L('تظهر هنا صفحات الدليل كما ستُطبع. اضغط على أي جزء منها لتغييره.',
                               'The manual pages show here as they will print. Click any part to change it.'))
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

    def _click_at(self, pos):
        z = self.view.zoomFactor() or 1
        x, y = pos.x() / z, pos.y() / z
        self.view.page().runJavaScript(
            f"(function(){{var t=document.elementFromPoint({x:.0f},{y:.0f});if(t)t.dispatchEvent(new MouseEvent('click',"
            f"{{bubbles:true,clientX:{x:.0f},clientY:{y:.0f}}}));}})()")

    def _menu(self, pos):
        m = QMenu(self)
        m.addAction(icon('edit', '#334155'), L('تعديل هذا الجزء', 'Change this part'), lambda: self._click_at(pos))
        m.addAction(icon('reprint', '#334155'), L('تحديث المعاينة', 'Refresh the preview'), self.refresh_btn.click)
        if self.inspector.isVisible():
            m.addAction(icon('close', '#334155'), L('إغلاق لوحة التعديل', 'Close the panel'), self.inspector.hide)
        m.addSeparator()
        m.addAction(L('تكبير', 'Zoom in'), lambda: self.view.setZoomFactor(min(3.0, self.view.zoomFactor() * 1.15)))
        m.addAction(L('تصغير', 'Zoom out'), lambda: self.view.setZoomFactor(max(0.25, self.view.zoomFactor() / 1.15)))
        m.addAction(L('ملاءمة العرض', 'Fit the width'), self._zoom)
        m.exec(self.view.mapToGlobal(pos))

    def _arm(self, tries=0):
        """Paged.js lays the pages out after the load; the click script is added once they exist."""
        if self.view is None:
            return

        def ready(n):
            if n:
                self.view.page().runJavaScript(PICK_JS)
                if getattr(self, '_scroll_back', None):
                    self.view.page().runJavaScript(f'window.scrollTo(0,{int(self._scroll_back)})')
            elif tries < 40:
                QTimer.singleShot(250, lambda: self._arm(tries + 1))
        self.view.page().runJavaScript("document.querySelectorAll('.pagedjs_page').length", 0, ready)

    def show_html(self, html, page_w=None):
        import hashlib
        digest = hashlib.md5(html.encode('utf-8', 'surrogatepass')).hexdigest()
        if self.view is not None and digest == getattr(self, '_digest', None):
            return                                  # nothing changed: the pages are not laid out again
        self._digest = digest
        self.page_w = page_w or getattr(self, 'page_w', None)
        if self.view is None:
            try:
                from PySide6.QtWebEngineWidgets import QWebEngineView
                from ..core.pdf import settings_for
            except ImportError:
                self.holder.setText(L('المعاينة غير متاحة على هذا الجهاز.', 'The preview is not available on this computer.'))
                return
            self.view = QWebEngineView()
            self.view.setPage(_picking_page(self.view, self.picked.emit))
            # right click: the program's own menu (the browser one would offer «reload», «view source»…)
            self.view.setContextMenuPolicy(Qt.CustomContextMenu)
            self.view.customContextMenuRequested.connect(self._menu)
            settings_for(self.view.page())
            self.view.loadFinished.connect(lambda _ok: self._zoom())
            self.view.loadFinished.connect(lambda _ok: self._arm())
            a11y(self.view, L('معاينة الصفحات', 'Page preview'))
            self.lay.replaceWidget(self.holder, self.view)
            self.holder.hide()
        from ..core.pdf import write_html
        path = write_html(html, os.path.join(self.ctx.data_dir, 'preview'), 'preview.html')
        self._scroll_back = None
        if self.view.url().isValid() and not self.view.url().isEmpty():
            self.view.page().runJavaScript('window.scrollY', 0, lambda y: setattr(self, '_scroll_back', y))
        url = QUrl.fromLocalFile(path)
        url.setQuery(f'v={digest}')          # a new address for new content: the engine never shows a kept old copy
        self.view.load(url)
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
        self.form.table_colors.connect(self.colors_for_all_tables)
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
        self.preview.picked.connect(self.picked)
        self.preview.inspector.changed.connect(self._inspected)
        self.preview.inspector.before_change = lambda: self.dirty and self.save(quiet=True)
        self.preview.inspector.open_block.connect(lambda sid, i: self.goto(sid, i))
        self.preview.scope.currentIndexChanged.connect(lambda: self.refresh_preview(force=True))
        self._ptimer = QTimer(self)
        self._ptimer.setSingleShot(True)
        self._ptimer.setInterval(2500)
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
        self._design_table_colors()
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
        # the blocks are built with the box hidden: added to a shown layout, each one lays the window out again
        box = self.blocks_box
        box.setUpdatesEnabled(False)
        box.hide()
        _clear_layout(self.block_list)
        self.blocks = []
        for b in self.db.blocks(self.sid):
            self._append_block(b)
        size_tree(self.scroll)
        box.show()
        box.setUpdatesEnabled(True)

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

        def flash(on):
            if _alive(w):
                w.setProperty('flash', on)
                w.style().unpolish(w)
                w.style().polish(w)

        def show():
            if not _alive(w):                  # the blocks were drawn again meanwhile
                return
            self.scroll.ensureWidgetVisible(w, 40, 80)
            w.setProperty('flash', True)
            w.style().unpolish(w)
            w.style().polish(w)
            if target is not None and hasattr(target, 'setFocus'):
                target.setFocus()
            QTimer.singleShot(2500, lambda: flash(False))
        QTimer.singleShot(60, show)

    def _append_block(self, b, at=None):
        w = BlockWidget(self.ctx, b)
        w.changed.connect(self._touch)
        w.remove.connect(self._remove_block)
        w.move.connect(self._move_block)
        w.insert_after.connect(lambda src: self._add_block_menu(self.blocks.index(src) + 1))
        w.table_colors.connect(self.colors_for_all_tables)
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
        QTimer.singleShot(50, lambda: _alive(w) and self.scroll.ensureWidgetVisible(w))

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

    def picked(self, what):
        """A click on the preview: its settings open on the preview itself; a block also opens here for its text."""
        if self.dirty:
            self.save(quiet=True)
        parts = what.split()
        try:
            if parts[0] == 'b':
                sid, i = parts[1].split(':')
                if int(sid) != self.sid:
                    self.goto(int(sid), int(i) if i else None, [parts[2]] if len(parts) > 2 else None)
            elif parts[0] == 's' and int(parts[1]) != self.sid:
                self.goto(int(parts[1]))
        except (IndexError, ValueError):
            pass
        self.preview.inspector.show_for(what)
        self._widen_preview()

    def _widen_preview(self):
        """The panel needs room: the preview column grows to at least 560 pixels (the tree gives way first)."""
        sizes = self.split.sizes()
        if len(sizes) == 3 and sizes[2] < 560:
            need = 560 - sizes[2]
            take_tree = min(need, max(0, sizes[0] - 200))
            sizes = [sizes[0] - take_tree, max(420, sizes[1] - (need - take_tree)), 560]
            self.split.setSizes(sizes)

    def _inspected(self, sid):
        """The panel on the preview changed something: what is open here is drawn again from the saved data."""
        if sid and sid == self.sid:
            self.dirty = False
            keep, self.sid = self.sid, None
            self.reload_tree(select=keep)
        if not sid and self.ctx.window:
            self.ctx.window.design.load_manual(self.mid, keep_history=True)
        self.refresh_preview(force=True)

    def _design_table_colors(self):
        m = self.db.manual(self.mid) if self.mid else None
        c = layout_with_defaults(m['layout'] if m else None)['colors']
        TableEditor.design_colors = {k: c.get(dk) or TABLE_THEMES['blue'][1][k] for k, (dk, _n) in TABLE_COLORS.items()}

    def colors_for_all_tables(self, colors):
        """The colours become the manual's table colours, and no table keeps colours of its own."""
        if not self.mid:
            return
        self.save(quiet=True)
        m = self.db.manual(self.mid)
        lay = layout_with_defaults(m['layout'])
        for k, (dk, _n) in TABLE_COLORS.items():
            if colors.get(k):
                lay['colors'][dk] = colors[k]
        self.db.save_manual({'layout': lay}, self.mid)
        n = self.db.clear_table_colors(self.mid)
        self._design_table_colors()
        if self.sid:
            sid, self.sid = self.sid, None
            self.reload_tree(select=sid)          # the open section is drawn again without its own colours
        self.refresh_preview(force=True)
        info(self, L(f'طُبّقت الألوان على كل جداول الدليل، وأُزيلت الألوان الخاصة من {n} جدولاً.',
                     f'The colours apply to every table of the manual; {n} table(s) lost colours of their own.'))

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
            html = build_html(self.db, self.mid, 'print', only=only, workflow=self.ctx.workflow, draft=True)
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

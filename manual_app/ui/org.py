"""The organisational structure of the current manual: a tree of units and positions (drag to move), each with its
Arabic and English name, the person holding it, a colour and the kind of reporting line; the chart is drawn live."""
from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QComboBox, QDialogButtonBox,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea, QSplitter,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core import orgchart
from ..core.templates import layout_with_defaults
from .common import L, confirm, error, info
from .theme import SizedDialog, a11y, button, card, field, fit, form_grid, hint, icon, icon_button, ltr, name_buttons


class BulkDialog(SizedDialog):
    """Adds many positions at once: one per line, indented under the one above (two spaces or a tab per level)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(L('إضافة دفعة واحدة', 'Add many at once'))
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText('المدير العام | General Manager\n  مدير المدرسة | School Principal\n    منسق المرحلة | Stage Coordinator\n  المدير المالي | Finance Manager')
        a11y(self.text, L('الوظائف', 'Positions'))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(L('إضافة', 'Add'))
        bb.button(QDialogButtonBox.Cancel).setText(L('إلغاء', 'Cancel'))
        name_buttons(bb)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(hint(L('سطر لكل وحدة أو وظيفة: الاسم العربي ثم «|» ثم الاسم الإنجليزي (اختياري). المسافة في بداية السطر تجعله تابعاً للسطر الذي فوقه.',
                             'One line per unit or position: the Arabic name, then «|», then the English name (optional). Leading spaces make a line report to the one above.')))
        lay.addWidget(self.text, 1)
        lay.addWidget(bb)
        self.resize(560, 420)

    def items(self):
        out = []
        for ln in self.text.toPlainText().split('\n'):
            if not ln.strip():
                continue
            indent = len(ln.replace('\t', '  ')) - len(ln.replace('\t', '  ').lstrip(' '))
            parts = [p.strip() for p in ln.strip().split('|')]
            out.append((indent // 2, parts[0], parts[1] if len(parts) > 1 else ''))
        return out


class OrgTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.db = ctx, ctx.db
        self.mid = None
        self.uid = None
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setDragDropMode(QAbstractItemView.InternalMove)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.currentItemChanged.connect(self._open)
        self.tree.model().rowsMoved.connect(lambda *_: QTimer.singleShot(0, self._moved))
        a11y(self.tree, L('الوحدات والوظائف', 'Units and positions'), L('اسحب لنقل وظيفة تحت أخرى', 'Drag to move a position under another'))
        self.count = QLabel()
        self.count.setProperty('chip', True)
        add = button(L('وظيفة', 'Position'), 'plus', 'primary', tip=L('إضافة على مستوى المحدد', 'Add at the level of the selected one'))
        add.clicked.connect(lambda: self.add(False))
        sub = button(L('تابعة', 'Reporting'), 'indent', tip=L('إضافة تحت المحدد', 'Add under the selected one'))
        sub.clicked.connect(lambda: self.add(True))
        bulk = button(L('دفعة…', 'Many…'), 'list')
        bulk.clicked.connect(self.bulk)
        up = icon_button('up', L('تحريك لأعلى', 'Move up'))
        up.clicked.connect(lambda: self._shift(-1))
        down = icon_button('down', L('تحريك لأسفل', 'Move down'))
        down.clicked.connect(lambda: self._shift(1))
        dele = icon_button('trash', L('حذف المحدد', 'Delete selected'), 'danger')
        dele.clicked.connect(self.delete)
        tb = QHBoxLayout()
        for w in (add, sub, bulk, up, down, dele):
            tb.addWidget(w)
        tb.addStretch(1)
        tb.addWidget(self.count)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addLayout(tb)
        ll.addWidget(self.tree, 1)

        self.name_ar = QLineEdit()
        self.name_en = ltr(QLineEdit())
        self.holder = QLineEdit()
        self.holder.setPlaceholderText(L('اسم شاغل الوظيفة (اختياري)', 'Holder\'s name (optional)'))
        self.kind = QComboBox()
        self.kind.addItem(L('وظيفة', 'Position'), 'position')
        self.kind.addItem(L('وحدة إدارية / لجنة', 'Unit / committee'), 'unit')
        fit(self.kind, 200)
        self.link = QComboBox()
        self.link.addItem(L('ارتباط مباشر (خط متصل)', 'Direct (solid line)'), 'solid')
        self.link.addItem(L('ارتباط استشاري (خط متقطع)', 'Advisory (dashed line)'), 'dashed')
        fit(self.link, 260)
        self.color = QPushButton(L('تلقائي', 'Automatic'))
        self.color.clicked.connect(self._color)
        a11y(self.color, L('لون المربع', 'Box colour'))
        self.color_value = None
        clear_color = icon_button('close', L('اللون التلقائي', 'Automatic colour'))
        clear_color.clicked.connect(lambda: self._set_color(None))
        self.active = QCheckBox(L('ظاهر في الهيكل', 'Shown in the chart'))
        self.summary_ar = QPlainTextEdit()
        self.summary_ar.setFixedHeight(70)
        self.summary_ar.setPlaceholderText(L('المهام باختصار (عربي)', 'Duties in brief (Arabic)'))
        self.summary_en = QPlainTextEdit()
        self.summary_en.setFixedHeight(70)
        self.summary_en.setLayoutDirection(Qt.LeftToRight)
        self.summary_en.setPlaceholderText(L('المهام باختصار (إنجليزي)', 'Duties in brief (English)'))
        save = button(L('حفظ', 'Save'), 'save', 'primary')
        save.clicked.connect(self.save)
        g = form_grid()
        field(g, 0, 0, L('الاسم بالعربية *', 'Arabic name *'), self.name_ar)
        field(g, 1, 0, L('الاسم بالإنجليزية', 'English name'), self.name_en)
        field(g, 2, 0, L('شاغل الوظيفة', 'Holder'), self.holder)
        field(g, 3, 0, L('النوع', 'Kind'), self.kind)
        field(g, 4, 0, L('خط الارتباط', 'Reporting line'), self.link)
        cr = QHBoxLayout()
        cr.addWidget(self.color)
        cr.addWidget(clear_color)
        cr.addStretch(1)
        field(g, 5, 0, L('اللون', 'Colour'), cr)
        g.addWidget(self.active, 6, 1)
        field(g, 7, 0, L('المهام (عربي)', 'Duties (Arabic)'), self.summary_ar)
        field(g, 8, 0, L('المهام (إنجليزي)', 'Duties (English)'), self.summary_en)
        g.addWidget(save, 9, 1, Qt.AlignLeading)
        g.setColumnStretch(1, 1)
        self.form = card(L('الوظيفة المحددة', 'Selected position'))
        self.form.setLayout(g)

        from PySide6.QtSvgWidgets import QSvgWidget
        self.svg = QSvgWidget()
        a11y(self.svg, L('الهيكل التنظيمي', 'Organisational chart'))
        self.svg_scroll = QScrollArea()
        self.svg_scroll.setWidget(self.svg)
        self.svg_scroll.setAlignment(Qt.AlignCenter)
        chart = card(L('الهيكل كما يُطبع', 'The chart as printed'))
        cl = QVBoxLayout(chart)
        cl.addWidget(hint(L('يظهر الهيكل في الدليل في أي قسم من نوع «هيكل تنظيمي»، كاملاً أو بدءاً من وحدة محددة. الوظائف التي لا يتبعها أحد تُسرد عمودياً تحت وحدتها.',
                            'The chart appears in the manual in any section of type «Organisational chart», whole or from a chosen unit. Positions with nobody under them are listed in a column under their unit.')))
        cl.addWidget(self.svg_scroll, 1)

        right = QSplitter(Qt.Vertical)
        right.addWidget(self.form)
        right.addWidget(chart)
        right.setSizes([380, 420])
        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.setSizes([360, 900])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 14)
        lay.addWidget(split, 1)
        self.form.setEnabled(False)

    def load_manual(self, mid):
        self.mid = mid
        self.uid = None
        self.reload()

    def reload(self, select=None):
        self.tree.blockSignals(True)
        self.tree.clear()
        items = {}
        n = 0
        if self.mid:
            def add(nodes, parent):
                nonlocal n
                for u in nodes:
                    it = QTreeWidgetItem([u['name_ar'] + (f'  ({u["name_en"]})' if u.get('name_en') else '')])
                    it.setData(0, Qt.UserRole, u['id'])
                    it.setIcon(0, icon('org' if u['kind'] == 'unit' else 'users', '#64748b' if u['is_active'] else '#c0c8d4'))
                    (parent.addChild(it) if parent else self.tree.addTopLevelItem(it))
                    items[u['id']] = it
                    n += 1
                    add(u['children'], it)
            add(self.db.org_tree(self.mid, active_only=False), None)
        self.tree.expandAll()
        self.tree.blockSignals(False)
        self.count.setText(L(f'الإجمالي: {n}', f'Total: {n}'))
        target = select or self.uid
        if target in items:
            self.tree.setCurrentItem(items[target])
        self.draw()

    def draw(self):
        if not self.mid:
            self.svg.load(QByteArray(b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>'))
            return
        m = self.db.manual(self.mid)
        lay = layout_with_defaults(m['layout'])
        svg = orgchart.render_svg(self.db.org_tree(self.mid), lay['lang_mode'], lay['colors'], lay['fonts']['ar'])
        if not svg:
            svg = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>'
        self.svg.load(QByteArray(svg.encode('utf-8')))
        size = self.svg.renderer().defaultSize()
        self.svg.setFixedSize(size)

    def _open(self, cur, prev):
        if cur is None:
            self.form.setEnabled(False)
            return
        u = next((x for x in self.db.org_units(self.mid) if x['id'] == cur.data(0, Qt.UserRole)), None)
        if not u:
            return
        self.uid = u['id']
        self.name_ar.setText(u['name_ar'] or '')
        self.name_en.setText(u.get('name_en') or '')
        self.holder.setText(u.get('holder') or '')
        self.kind.setCurrentIndex(max(0, self.kind.findData(u['kind'])))
        self.link.setCurrentIndex(max(0, self.link.findData(u.get('link') or 'solid')))
        self._set_color(u.get('color'))
        self.active.setChecked(bool(u['is_active']))
        self.summary_ar.setPlainText(u.get('summary_ar') or '')
        self.summary_en.setPlainText(u.get('summary_en') or '')
        self.form.setEnabled(self.ctx.can('edit'))

    def _set_color(self, c):
        self.color_value = c
        self.color.setText(c or L('تلقائي', 'Automatic'))
        self.color.setStyleSheet(f'background:{c};color:#fff' if c else '')

    def _color(self):
        c = QColorDialog.getColor(QColor(self.color_value or '#0B3D91'), self, L('لون المربع', 'Box colour'))
        if c.isValid():
            self._set_color(c.name())

    def save(self):
        if not self.uid:
            return
        if not self.name_ar.text().strip():
            error(self, L('اكتب الاسم بالعربية.', 'Enter the Arabic name.'))
            return
        self.db.save_unit({'name_ar': self.name_ar.text().strip(), 'name_en': self.name_en.text().strip(),
                           'holder': self.holder.text().strip(), 'kind': self.kind.currentData(),
                           'link': self.link.currentData(), 'color': self.color_value,
                           'is_active': int(self.active.isChecked()), 'summary_ar': self.summary_ar.toPlainText().strip(),
                           'summary_en': self.summary_en.toPlainText().strip()}, self.uid)
        self.reload(select=self.uid)

    def add(self, child):
        if not self.mid:
            info(self, L('افتح دليلاً أولاً.', 'Open a manual first.'))
            return
        cur = next((x for x in self.db.org_units(self.mid) if x['id'] == self.uid), None)
        parent = (cur['id'] if child else cur['parent_id']) if cur else None
        uid = self.db.save_unit({'manual_id': self.mid, 'parent_id': parent, 'name_ar': L('وظيفة جديدة', 'New position'),
                                 'name_en': '' if L('a', 'b') == 'a' else 'New position'})
        self.uid = uid
        self.reload(select=uid)
        self.name_ar.setFocus()
        self.name_ar.selectAll()

    def bulk(self):
        if not self.mid:
            return
        d = BulkDialog(self)
        if not d.exec():
            return
        base = None
        if self.uid:
            base = self.uid
        stack = [(-1, base)]
        n = 0
        for level, ar, en in d.items():
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else base
            uid = self.db.save_unit({'manual_id': self.mid, 'parent_id': parent, 'name_ar': ar, 'name_en': en})
            stack.append((level, uid))
            n += 1
        self.reload()
        info(self, L(f'أُضيفت {n} وظيفة.', f'{n} position(s) added.'))

    def _shift(self, d):
        cur = next((x for x in self.db.org_units(self.mid) if x['id'] == self.uid), None)
        if not cur:
            return
        sibs = [x for x in self.db.org_units(self.mid) if x['parent_id'] == cur['parent_id']]
        i = next(i for i, x in enumerate(sibs) if x['id'] == cur['id'])
        j = i + d
        if not 0 <= j < len(sibs):
            return
        sibs[i], sibs[j] = sibs[j], sibs[i]
        for k, x in enumerate(sibs):
            self.db.conn.execute('UPDATE org_units SET sort = ? WHERE id = ?', ((k + 1) * 10, x['id']))
        self.db.conn.commit()
        self.reload(select=self.uid)

    def _moved(self):
        def walk(parent_item, parent_id):
            for i in range(parent_item.childCount() if parent_item else self.tree.topLevelItemCount()):
                it = parent_item.child(i) if parent_item else self.tree.topLevelItem(i)
                uid = it.data(0, Qt.UserRole)
                self.db.conn.execute('UPDATE org_units SET parent_id = ?, sort = ? WHERE id = ?', (parent_id, (i + 1) * 10, uid))
                walk(it, uid)
        walk(None, None)
        self.db.conn.commit()
        self.draw()

    def delete(self):
        ids = [it.data(0, Qt.UserRole) for it in self.tree.selectedItems()]
        if not ids or not confirm(self, L(f'حذف {len(ids)} وظيفة؟', f'Delete {len(ids)} position(s)?')):
            return
        kept = self.db.delete_units(ids)
        self.uid = None
        self.reload()
        if kept:
            info(self, L(f'لم تُحذف {len(kept)} لأن وظائف أخرى تتبعها: انقلها أو احذفها أولاً، أو أخفِها من الهيكل.',
                         f'{len(kept)} kept because other positions report to them: move or delete those first, or hide them from the chart.'))

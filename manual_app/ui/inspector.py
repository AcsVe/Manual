"""The panel that opens on the preview when a part of a page is clicked: the part's own settings, applied at once
(as on the cheque layout board). Cover texts, logo and shape; header and footer; a block (colour, size, alignment,
the direction of the page it starts); a whole page (its direction, for that page only or from it on); a section.
Every change can be undone with «تراجع»."""
import copy

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QSpinBox, QVBoxLayout, QWidget)

from ..core.db import BLOCK_KINDS
from ..core.templates import BLOCK_ALIGN, HEADER_STYLES, layout_with_defaults
from .common import L, confirm
from .theme import a11y, button, field, fit, flow_row, form_grid, icon_button, ltr, muted, size_tree

COVER_PARTS = {'title': (('عنوان الدليل', 'Manual title'), ('title_ar', 'title_en'), 30),
               'subtitle': (('العنوان الفرعي', 'Subtitle'), ('subtitle_ar', 'subtitle_en'), 15),
               'org': (('اسم المؤسسة', 'Organisation'), ('org_ar', 'org_en'), 14),
               'edition': (('النسخة', 'Edition'), ('edition_ar', 'edition_en'), 12)}
ORIENTS = {'': ('دون تغيير', 'No change'), 'portrait': ('عمودي', 'Portrait'), 'landscape': ('أفقي', 'Landscape'),
           'section': ('كاتجاه القسم', 'As the section')}


class ColorButton(QPushButton):
    """A colour, or «تلقائي» (the design colour) when none is set."""
    picked = Signal(object)

    def __init__(self, name, value=None):
        super().__init__()
        self.name, self.value = name, value
        self.clicked.connect(self._pick)
        a11y(self, name)
        fit(self, 120)
        self._paint()

    def _pick(self):
        c = QColorDialog.getColor(QColor(self.value or '#0B3D91'), self, self.name)
        if c.isValid():
            self.value = c.name().upper()
            self._paint()
            self.picked.emit(self.value)

    def reset(self):
        self.value = None
        self._paint()
        self.picked.emit(None)

    def _paint(self):
        if self.value:
            light = QColor(self.value).lightness() > 150
            self.setText('‎' + self.value)
            self.setStyleSheet(f'background:{self.value};color:{"#1e293b" if light else "#ffffff"};'
                               'border:1px solid #c9d4e3;border-radius:6px')
        else:
            self.setText(L('تلقائي', 'Automatic'))
            self.setStyleSheet('')


class Inspector(QFrame):
    """``changed(sid)``: something was written (sid: the section whose blocks changed, or 0 for the manual)."""
    changed = Signal(int)
    open_block = Signal(int, int)

    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.db = ctx, ctx.db
        self.undo_stack = []
        self.setObjectName('inspector')
        self.setStyleSheet('QFrame#inspector{background:#ffffff;border:1px solid #9FB3D1;border-radius:10px}')
        self.title = QLabel()
        self.title.setStyleSheet('font-weight:700;color:#0847B0')
        self.undo_btn = button(L('تراجع', 'Undo'), 'reset', tip=L('يعيد آخر تغيير من هذه اللوحة', 'Undoes the last change made here'))
        self.undo_btn.clicked.connect(self.undo)
        close = icon_button('close', L('إغلاق اللوحة', 'Close the panel'))
        close.clicked.connect(self.hide)
        top = QHBoxLayout()
        top.addWidget(self.title, 1)
        top.addWidget(self.undo_btn)
        top.addWidget(close)
        self.body = QWidget()
        self.body_lay = QVBoxLayout(self.body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(self.body)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.addLayout(top)
        lay.addWidget(scroll, 1)
        self.setMinimumHeight(300)
        self.hide()
        self._refresh_undo()

    # ── state ────────────────────────────────────────────────────────
    @property
    def mid(self):
        return self.ctx.manual_id

    def manual(self):
        return self.db.manual(self.mid)

    def lay(self):
        return layout_with_defaults(self.manual()['layout'])

    before_change = None          # set by the page holding the panel: saves what is being typed there first

    def _snapshot(self, sid=None):
        if self.before_change:
            self.before_change()
        m = self.manual()
        snap = {'manual': {k: copy.deepcopy(m.get(k)) for k in ('layout', 'logo_id', 'title_ar', 'title_en', 'subtitle_ar',
                                                                 'subtitle_en', 'org_ar', 'org_en', 'edition_ar', 'edition_en')}}
        if sid:
            s = self.db.section(sid)
            snap['sid'] = sid
            snap['section'] = {k: copy.deepcopy(s.get(k)) for k in ('title_ar', 'title_en', 'style')}
            snap['blocks'] = [{k: copy.deepcopy(b.get(k)) for k in ('kind', 'ar', 'en', 'data', 'style')} for b in self.db.blocks(sid)]
        self.undo_stack.append(snap)
        del self.undo_stack[:-40]
        self._refresh_undo()

    def _refresh_undo(self):
        self.undo_btn.setEnabled(bool(self.undo_stack))

    def undo(self):
        if not self.undo_stack:
            return
        snap = self.undo_stack.pop()
        self.db.save_manual(snap['manual'], self.mid)
        sid = snap.get('sid') or 0
        if sid:
            self.db.save_section(snap['section'], sid)
            self.db.replace_blocks(sid, snap['blocks'])
        self._refresh_undo()
        self.changed.emit(sid)
        self.show_for(self.current) if getattr(self, 'current', None) else None

    def set_layout(self, fn):
        """Changes the manual's design: ``fn(layout)`` edits it in place."""
        self._snapshot()
        lay = self.lay()
        fn(lay)
        self.db.save_manual({'layout': lay}, self.mid)
        self.changed.emit(0)

    def set_manual(self, **fields):
        self._snapshot()
        self.db.save_manual(fields, self.mid)
        self.changed.emit(0)

    def set_blocks(self, sid, fn):
        """Changes a section's blocks: ``fn(blocks)`` edits the list in place."""
        self._snapshot(sid)
        blocks = [{k: b.get(k) for k in ('kind', 'ar', 'en', 'data', 'style')} for b in self.db.blocks(sid)]
        fn(blocks)
        self.db.replace_blocks(sid, blocks)
        self.changed.emit(sid)

    # ── showing ──────────────────────────────────────────────────────
    def _clear(self):
        while self.body_lay.count():
            it = self.body_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def show_for(self, what):
        """``what`` as the page reports it: «c title», «m header», «b 12:3 ar», «p page 12:3 12:7», «s 12»…"""
        if not self.mid:
            return
        self.current = what
        self._clear()
        parts = what.split()
        kind = parts[0] if parts else ''
        try:
            if kind == 'c' and parts[1] in COVER_PARTS:
                self._cover_text(parts[1])
            elif kind == 'c' and parts[1] == 'logo':
                self._logo()
            elif kind == 'c' and parts[1] == 'shape' or what == 'p cover':
                self._cover()
            elif kind == 'm':
                self._margin(parts[1])
            elif kind == 'b':
                sid, i = parts[1].split(':')
                self._block(int(sid), int(i))
            elif kind == 'p':
                self._page(parts[2] if len(parts) > 2 else '', parts[3] if len(parts) > 3 else '')
            elif kind == 's':
                self._section(int(parts[1]))
            else:
                return
        except (IndexError, ValueError, TypeError):
            return
        self.body_lay.addStretch(1)
        size_tree(self.body)
        self.show()

    def _head(self, text):
        self.title.setText(text)

    def _form(self, rows):
        """rows: (label, widget or layout); returns the box holding them."""
        box = QWidget()
        g = form_grid(8)
        g.setContentsMargins(0, 0, 0, 0)
        for i, (lab, w) in enumerate(rows):
            if lab is None:
                g.addWidget(w, i, 1) if isinstance(w, QWidget) else g.addLayout(w, i, 1)
            else:
                field(g, i, 0, lab, w)
        g.setColumnStretch(1, 1)
        box.setLayout(g)
        self.body_lay.addWidget(box)
        return box

    def _color_row(self, name, value, on_pick):
        b = ColorButton(name, value)
        b.picked.connect(on_pick)
        auto = icon_button('reset', L('اللون التلقائي', 'Automatic colour'))
        auto.clicked.connect(b.reset)
        row = QHBoxLayout()
        row.addWidget(b)
        row.addWidget(auto)
        row.addStretch(1)
        return row

    # ── cover ────────────────────────────────────────────────────────
    def _cover_item(self, lay, key):
        cv = lay.setdefault('cover', {})
        items = cv.setdefault('items', {})
        return items.setdefault(key, {})

    def _cover_text(self, key):
        (ar_name, en_name), (f_ar, f_en), default = COVER_PARTS[key]
        self._head(L('الغلاف: ', 'Cover: ') + L(ar_name, en_name))
        m, lay = self.manual(), self.lay()
        it = ((lay.get('cover') or {}).get('items') or {}).get(key) or {}
        t_ar, t_en = QLineEdit(m.get(f_ar) or ''), ltr(QLineEdit(m.get(f_en) or ''))
        t_ar.editingFinished.connect(lambda: t_ar.text().strip() != (self.manual().get(f_ar) or '') and
                                     self.set_manual(**{f_ar: t_ar.text().strip()}))
        t_en.editingFinished.connect(lambda: t_en.text().strip() != (self.manual().get(f_en) or '') and
                                     self.set_manual(**{f_en: t_en.text().strip()}))
        size = QSpinBox()
        size.setRange(6, 90)
        size.setSuffix(' pt')
        size.setValue(int(it.get('size') or default))
        fit(size, 100)
        size.editingFinished.connect(lambda: self.set_layout(lambda l: self._cover_item(l, key).update(size=size.value())))
        bold = QCheckBox(L('غامق', 'Bold'))
        bold.setChecked(bool(it.get('bold', key in ('title', 'org'))))
        bold.toggled.connect(lambda v: self.set_layout(lambda l: self._cover_item(l, key).update(bold=v)))
        hide = QCheckBox(L('إخفاء من الغلاف', 'Hide from the cover'))
        hide.setChecked(bool(it.get('hidden')))
        hide.toggled.connect(lambda v: self.set_layout(lambda l: self._cover_item(l, key).update(hidden=v)))
        clear = button(L('حذف النص', 'Delete the text'), 'trash', 'danger')
        clear.clicked.connect(lambda: (t_ar.setText(''), t_en.setText(''), self.set_manual(**{f_ar: '', f_en: ''})))
        self._form([(L('النص بالعربية', 'Arabic text'), t_ar), (L('النص بالإنجليزية', 'English text'), t_en),
                    (L('اللون', 'Colour'), self._color_row(L('لون النص', 'Text colour'), it.get('color'),
                                                           lambda v: self.set_layout(lambda l: self._cover_item(l, key).update(color=v)))),
                    (L('الحجم', 'Size'), size), (None, flow_row([bold, hide, clear]))])

    def _logo(self):
        self._head(L('الغلاف: الشعار', 'Cover: logo'))
        lay = self.lay()
        it = ((lay.get('cover') or {}).get('items') or {}).get('logo') or {}
        size = QSpinBox()
        size.setRange(4, 60)
        size.setSuffix(' %')
        size.setValue(int(it.get('size') or 16))
        fit(size, 100)
        size.editingFinished.connect(lambda: self.set_layout(lambda l: self._cover_item(l, 'logo').update(size=size.value())))
        hide = QCheckBox(L('إخفاء من الغلاف (يبقى في الترويسة)', 'Hide from the cover (stays in the header)'))
        hide.setChecked(bool(it.get('hidden')))
        hide.toggled.connect(lambda v: self.set_layout(lambda l: self._cover_item(l, 'logo').update(hidden=v)))
        change = button(L('تغيير الشعار…', 'Change the logo…'), 'image')
        change.clicked.connect(self._change_logo)
        drop = button(L('إزالة الشعار من الدليل', 'Remove the logo from the manual'), 'trash', 'danger')
        drop.clicked.connect(lambda: self.set_manual(logo_id=None) or self.show_for('p cover'))
        self._form([(L('الارتفاع من الصفحة', 'Height of the page'), size), (None, hide), (None, flow_row([change, drop]))])

    def _change_logo(self):
        from .library import pick_asset
        aid = pick_asset(self, self.db, 'logo', L('الشعار', 'Logo'))
        if aid:
            self.set_manual(logo_id=aid)

    def _cover(self):
        self._head(L('الغلاف', 'Cover'))
        lay = self.lay()
        cv = lay.get('cover') or {}
        items = cv.get('items') or {}
        shape = QComboBox()
        for k in ('wave', 'band', 'none'):
            shape.addItem(L(*HEADER_STYLES[k]), k)
        shape.setCurrentIndex(max(0, shape.findData(cv.get('style', 'wave'))))
        fit(shape, 180)
        shape.currentIndexChanged.connect(lambda: self.set_layout(lambda l: l['cover'].update(style=shape.currentData())))
        drop = button(L('إزالة الشكل الملوّن', 'Remove the coloured shape'), 'trash', 'danger')
        drop.clicked.connect(lambda: shape.setCurrentIndex(shape.findData('none')))
        rows = [(L('الشكل', 'Shape'), shape), (None, drop),
                (L('لون الشكل', 'Shape colour'), self._color_row(L('لون الشكل', 'Shape colour'), cv.get('shape1'),
                                                                 lambda v: self.set_layout(lambda l: l['cover'].update(shape1=v)))),
                (L('اللون الثاني', 'Second colour'), self._color_row(L('اللون الثاني', 'Second colour'), cv.get('shape2'),
                                                                     lambda v: self.set_layout(lambda l: l['cover'].update(shape2=v))))]
        shows = []
        for key, ((ar, en), _f, _d) in list(COVER_PARTS.items()) + [('logo', (('الشعار', 'Logo'), None, None))]:
            cb = QCheckBox(L(ar, en))
            cb.setChecked(not (items.get(key) or {}).get('hidden'))
            cb.toggled.connect(lambda v, k=key: self.set_layout(lambda l: self._cover_item(l, k).update(hidden=not v)))
            shows.append(cb)
        rows.append((L('يظهر على الغلاف', 'Shown on the cover'), flow_row(shows)))
        bg = button(L('خلفية الغلاف…', 'Cover background…'), 'image')
        bg.clicked.connect(self._cover_bg)
        rows.append((L('الخلفية', 'Background'), bg))
        self._form(rows)
        self.body_lay.addWidget(muted(L('اضغط على أي نص في الغلاف لتغيير كتابته أو لونه أو حجمه.',
                                        'Click any text on the cover to change its wording, colour or size.')))

    def _cover_bg(self):
        from ..core import backgrounds as BG
        from .background import edit_background
        lay = self.lay()
        ok, bg = edit_background(self, self.db, BG.of_cover(lay), L('خلفية الغلاف', 'Cover background'), False,
                                 lay['orientation'] == 'landscape')
        if ok:
            self.set_layout(lambda l: (l['cover'].update(bg=bg, bg_id=None)))

    # ── header and footer ────────────────────────────────────────────
    def _margin(self, which):
        lay = self.lay()
        if which == 'footer':
            self._head(L('التذييل', 'Footer'))
            ft = lay['footer']
            style = QComboBox()
            style.addItem(L('خط فاصل', 'Separator line'), 'line')
            style.addItem(L('بدون', 'None'), 'none')
            style.setCurrentIndex(max(0, style.findData(ft.get('style', 'line'))))
            fit(style, 160)
            style.currentIndexChanged.connect(lambda: self.set_layout(lambda l: l['footer'].update(style=style.currentData())))
            rows = [(L('الشكل', 'Style'), style),
                    (L('لون النص', 'Text colour'), self._color_row(L('لون نص التذييل', 'Footer text colour'), ft.get('text_color'),
                                                                   lambda v: self.set_layout(lambda l: l['footer'].update(text_color=v))))]
            rows += self._texts('footer', ft)
            self._form(rows)
            return
        self._head(L('الترويسة', 'Header'))
        hd = lay['header']
        style = QComboBox()
        for k, (ar, en) in HEADER_STYLES.items():
            style.addItem(L(ar, en), k)
        style.setCurrentIndex(max(0, style.findData(hd.get('style', 'wave'))))
        fit(style, 160)
        style.currentIndexChanged.connect(lambda: self.set_layout(lambda l: l['header'].update(style=style.currentData())))
        drop = button(L('إزالة الشكل الملوّن', 'Remove the coloured shape'), 'trash', 'danger')
        drop.clicked.connect(lambda: style.setCurrentIndex(style.findData('none')))
        height = QSpinBox()
        height.setRange(8, 60)
        height.setSuffix(L(' مم', ' mm'))
        height.setValue(int(hd.get('height') or 22))
        fit(height, 100)
        height.editingFinished.connect(lambda: self.set_layout(lambda l: l['header'].update(height=height.value())))
        logo = QCheckBox(L('الشعار في الترويسة', 'Logo in the header'))
        logo.setChecked(bool(hd.get('logo')))
        logo.toggled.connect(lambda v: self.set_layout(lambda l: l['header'].update(logo=v)))
        rows = [(L('الشكل', 'Style'), style), (None, drop), (L('الارتفاع', 'Height'), height),
                (L('لون الشكل', 'Shape colour'), self._color_row(L('لون الترويسة', 'Header colour'), hd.get('color1'),
                                                                 lambda v: self.set_layout(lambda l: l['header'].update(color1=v)))),
                (L('اللون الثاني', 'Second colour'), self._color_row(L('اللون الثاني', 'Second colour'), hd.get('color2'),
                                                                     lambda v: self.set_layout(lambda l: l['header'].update(color2=v)))),
                (L('لون النص', 'Text colour'), self._color_row(L('لون نص الترويسة', 'Header text colour'), hd.get('text_color'),
                                                               lambda v: self.set_layout(lambda l: l['header'].update(text_color=v)))),
                (None, logo)]
        rows += self._texts('header', hd)
        self._form(rows)

    def _texts(self, which, data):
        out = []
        for k, (ar, en) in (('start', ('النص في البداية', 'Text at the start')), ('center', ('النص في الوسط', 'Text in the centre')),
                            ('end', ('النص في النهاية', 'Text at the end'))):
            e = QLineEdit(data.get(k) or '')
            e.setPlaceholderText(L('مثلاً: صفحة {page} من {pages}', 'e.g. Page {page} of {pages}'))
            e.editingFinished.connect(lambda e=e, k=k: e.text() != (self.lay()[which].get(k) or '') and
                                      self.set_layout(lambda l: l[which].update({k: e.text()})))
            out.append((L(ar, en), e))
        return out

    # ── blocks, pages and sections ───────────────────────────────────
    def _block(self, sid, i):
        blocks = self.db.blocks(sid)
        if not 0 <= i < len(blocks):
            return
        b = blocks[i]
        st = b.get('style') or {}
        s = self.db.section(sid) or {}
        self._head(L(*BLOCK_KINDS.get(b['kind'], ('كتلة', 'Block'))) + ' — ' + (s.get('title_ar') or s.get('title_en') or ''))

        def set_style(**kw):
            def fn(bl):
                stl = dict(bl[i].get('style') or {})
                for k, v in kw.items():
                    if v in (None, '', 100) and k in ('color', 'align', 'size'):
                        stl.pop(k, None)
                    else:
                        stl[k] = v
                bl[i]['style'] = stl
            self.set_blocks(sid, fn)
        rows = []
        if b['kind'] not in ('pagebreak', 'image'):
            size = QSpinBox()
            size.setRange(50, 300)
            size.setSuffix(' %')
            size.setValue(int(st.get('size') or 100))
            fit(size, 100)
            size.editingFinished.connect(lambda: set_style(size=size.value()))
            bold = QCheckBox(L('غامق', 'Bold'))
            bold.setChecked(bool(st.get('bold')))
            bold.toggled.connect(lambda v: set_style(bold=v))
            rows += [(L('لون النص', 'Text colour'), self._color_row(L('لون النص', 'Text colour'), st.get('color'),
                                                                    lambda v: set_style(color=v))),
                     (L('حجم النص', 'Text size'), size), (None, bold)]
        if b['kind'] not in ('pagebreak',):
            align = QComboBox()
            for k, (ar, en) in BLOCK_ALIGN.items():
                align.addItem(L(ar, en), k)
            align.setCurrentIndex(max(0, align.findData(st.get('align', ''))))
            fit(align, 150)
            align.currentIndexChanged.connect(lambda: set_style(align=align.currentData()))
            rows.append((L('المحاذاة', 'Alignment'), align))
        if b['kind'] == 'image':
            full = QCheckBox(L('صفحة كاملة', 'A whole page'))
            full.setChecked(bool(st.get('fullpage')))
            full.toggled.connect(lambda v: set_style(fullpage=v))
            rows.append((None, full))
        if b['kind'] == 'pagebreak':
            o = QComboBox()
            for k, (ar, en) in ORIENTS.items():
                o.addItem(L(ar, en), k)
            o.setCurrentIndex(max(0, o.findData(st.get('orient', ''))))
            fit(o, 160)
            o.currentIndexChanged.connect(lambda: set_style(orient=o.currentData() or None))
            rows.append((L('اتجاه الصفحات بعده', 'Direction of the pages after it'), o))
        else:
            o = QComboBox()
            for k, (ar, en) in ORIENTS.items():
                o.addItem(L(ar, en), k)
            fit(o, 160)
            o.activated.connect(lambda _i: o.currentData() and self.turn_from(sid, i, o.currentData(), None))
            rows.append((L('صفحة جديدة من هنا باتجاه', 'A new page from here, turned'), o))
        edit = button(L('تحرير النص في المحرر', 'Edit the text in the editor'), 'edit')
        edit.clicked.connect(lambda: self.open_block.emit(sid, i))
        dele = button(L('حذف الكتلة', 'Delete the block'), 'trash', 'danger')
        dele.clicked.connect(lambda: confirm(self, L('حذف هذه الكتلة؟', 'Delete this block?')) and
                             (self.set_blocks(sid, lambda bl: bl.pop(i)), self.hide()))
        rows.append((None, flow_row([edit, dele])))
        self._form(rows)

    def turn_from(self, sid, first, orient, last_sid_i):
        """Pages turned from block ``first`` of section ``sid``: a page break asking for ``orient`` goes before it
        (or the page break already there is changed); with ``last_sid_i`` (the last block of the page) a page break
        back to the section's direction goes after that block, so only that page is turned."""
        def fn(bl):
            end = None
            if last_sid_i:
                ls, li = last_sid_i
                if ls == sid and li + 1 < len(bl):
                    end = li + 1
            if end is not None:
                if bl[end]['kind'] == 'pagebreak':
                    bl[end]['style'] = dict(bl[end].get('style') or {}, orient='section')
                else:
                    bl.insert(end, {'kind': 'pagebreak', 'ar': '', 'en': '', 'data': {}, 'style': {'orient': 'section'}})
            if first > 0 and bl[first - 1]['kind'] == 'pagebreak':
                bl[first - 1]['style'] = dict(bl[first - 1].get('style') or {}, orient=orient)
            elif bl[first]['kind'] == 'pagebreak':
                bl[first]['style'] = dict(bl[first].get('style') or {}, orient=orient)
            else:
                bl.insert(first, {'kind': 'pagebreak', 'ar': '', 'en': '', 'data': {}, 'style': {'orient': orient}})
        self.set_blocks(sid, fn)

    def _page(self, first, last):
        self._head(L('هذه الصفحة', 'This page'))
        if not first:
            self.body_lay.addWidget(muted(L('لا محتوى قابلاً للتغيير في هذه الصفحة.', 'Nothing on this page can be changed here.')))
            return
        fs, fi = (int(x) for x in first.split(':'))
        ls_li = tuple(int(x) for x in last.split(':')) if last else None
        o = QComboBox()
        for k in ('landscape', 'portrait', 'section'):
            o.addItem(L(*ORIENTS[k]), k)
        fit(o, 160)
        only = button(L('هذه الصفحة فقط', 'This page only'), 'check', 'primary')
        only.clicked.connect(lambda: self.turn_from(fs, fi, o.currentData(), ls_li))
        on = button(L('من هذه الصفحة إلى نهاية القسم', 'From this page to the end of the section'), 'down')
        on.clicked.connect(lambda: self.turn_from(fs, fi, o.currentData(), None))
        self._form([(L('اتجاه الصفحة', 'Page direction'), o), (None, flow_row([only, on]))])
        self.body_lay.addWidget(muted(L('تُعاد صفحات هذا الجزء بالاتجاه المختار، وقد تتغير كمية النص في كل صفحة تبعاً لذلك.',
                                        'The pages of this part are laid out again in the chosen direction, so the amount of text on each may change.')))

    def _section(self, sid):
        s = self.db.section(sid)
        if not s:
            return
        self._head(L('القسم: ', 'Section: ') + (s.get('title_ar') or s.get('title_en') or ''))
        st = s.get('style') or {}
        t_ar, t_en = QLineEdit(s.get('title_ar') or ''), ltr(QLineEdit(s.get('title_en') or ''))

        def save_title():
            if (t_ar.text().strip(), t_en.text().strip()) != (s.get('title_ar') or '', s.get('title_en') or ''):
                self._snapshot(sid)
                self.db.save_section({'title_ar': t_ar.text().strip(), 'title_en': t_en.text().strip()}, sid)
                self.changed.emit(sid)
        t_ar.editingFinished.connect(save_title)
        t_en.editingFinished.connect(save_title)
        o = QComboBox()
        o.addItem(L('كإعداد الدليل', 'As the manual'), '')
        o.addItem(L('عمودي', 'Portrait'), 'portrait')
        o.addItem(L('أفقي', 'Landscape'), 'landscape')
        o.setCurrentIndex(max(0, o.findData(st.get('orientation', ''))))
        fit(o, 160)

        def set_orient():
            self._snapshot(sid)
            stl = dict(self.db.section(sid).get('style') or {})
            if o.currentData():
                stl['orientation'] = o.currentData()
            else:
                stl.pop('orientation', None)
            self.db.save_section({'style': stl}, sid)
            self.changed.emit(sid)
        o.currentIndexChanged.connect(set_orient)
        self._form([(L('العنوان بالعربية', 'Arabic title'), t_ar), (L('العنوان بالإنجليزية', 'English title'), t_en),
                    (L('اتجاه كل صفحات القسم', 'Direction of all the section pages'), o)])

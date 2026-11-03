"""The current manual's identity and page design: titles, organisation, edition, logo, document-control data and the
confidentiality notice; page size, orientation and margins; language mode, fonts and colours; header and footer
(styles and texts with fields such as the page number); cover and page backgrounds; table of contents and numbering."""
import json

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractSpinBox, QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMenu, QPlainTextEdit, QPushButton, QSpinBox, QSplitter,
                               QTabWidget, QToolButton, QVBoxLayout, QWidget)

from ..core import backgrounds as BG
from ..core.html import DEFAULT_DISCLAIMER
from ..core.templates import (ALIGNMENTS, DEFAULT_LAYOUT, FRONT_NUMBERING, HEADER_STYLES, LANG_MODES, PAGE_DIGITS,
                              PAGE_NUMBER_FORMATS, PAGE_SIZES, TOKENS,
                              layout_with_defaults)
from .background import edit_background
from .inspector import TokenEdit
from .common import L
from .library import asset_pixmap, pick_asset
from .theme import a11y, button, card, field, fit, flow_row, form_grid, hint, icon_button, ltr, muted, scroll_page

COLOR_NAMES = {'primary': ('اللون الأساسي', 'Primary colour'), 'secondary': ('اللون الثانوي', 'Secondary colour'),
               'accent': ('لون التمييز', 'Accent colour'), 'text': ('لون النص', 'Text colour'),
               'heading': ('لون العناوين', 'Heading colour'), 'table_head': ('رأس الجداول', 'Table header'),
               'table_head_text': ('نص رأس الجداول', 'Table header text'), 'box_border': ('إطار الأقسام', 'Section frame'),
               'callout': ('خلفية مربع التنبيه', 'Callout background'), 'table_stripe': ('أسطر الجداول المتناوبة', 'Alternate table rows'),
               'table_border': ('حدود الجداول', 'Table borders'), 'table_text': ('نص خلايا الجداول', 'Table cell text')}


class DesignTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.db = ctx, ctx.db
        self.mid = None
        self.assets = {}
        self.bgs = {'page': None, 'cover': None}
        self.history = []              # the manual as it was before each automatic save, for «undo»
        self._loading = False
        # identity
        self.title_ar, self.title_en = QLineEdit(), ltr(QLineEdit())
        self.sub_ar, self.sub_en = QLineEdit(), ltr(QLineEdit())
        self.org_ar, self.org_en = QLineEdit(), ltr(QLineEdit())
        self.ed_ar, self.ed_en = QLineEdit(), ltr(QLineEdit())
        self.issue_no = ltr(QLineEdit(), 140)
        self.issue_date = ltr(QLineEdit(), 140)
        self.issue_date.setPlaceholderText('2026-12-31')
        self.prepared, self.reviewed, self.approved = QLineEdit(), QLineEdit(), QLineEdit()
        self.first_draft = ltr(QLineEdit(), 140)
        self.logo = QLabel()
        self.logo.setFixedSize(90, 70)
        self.logo.setAlignment(Qt.AlignCenter)
        self.logo.setStyleSheet('background:#f1f5f9;border-radius:8px')
        a11y(self.logo, L('الشعار', 'Logo'))
        logo_pick = button(L('اختيار الشعار…', 'Choose the logo…'), 'image')
        logo_pick.clicked.connect(lambda: self._pick('logo'))
        logo_clear = icon_button('close', L('إزالة الشعار', 'Remove the logo'))
        logo_clear.clicked.connect(lambda: self._set_asset('logo', None))
        self.disc_ar = QPlainTextEdit()
        self.disc_en = QPlainTextEdit()
        self.disc_en.setLayoutDirection(Qt.LeftToRight)
        for w in (self.disc_ar, self.disc_en):
            w.setFixedHeight(80)
        self.disc_ar.setPlaceholderText(DEFAULT_DISCLAIMER[0][:90] + '…')
        self.disc_en.setPlaceholderText(DEFAULT_DISCLAIMER[1][:90] + '…')

        g = form_grid()
        rows = [((L('العنوان بالعربية', 'Arabic title'), self.title_ar), (L('العنوان بالإنجليزية', 'English title'), self.title_en)),
                ((L('العنوان الفرعي بالعربية', 'Arabic subtitle'), self.sub_ar), (L('العنوان الفرعي بالإنجليزية', 'English subtitle'), self.sub_en)),
                ((L('المؤسسة بالعربية', 'Organisation (Arabic)'), self.org_ar), (L('المؤسسة بالإنجليزية', 'Organisation (English)'), self.org_en)),
                ((L('النسخة بالعربية', 'Edition (Arabic)'), self.ed_ar), (L('النسخة بالإنجليزية', 'Edition (English)'), self.ed_en)),
                ((L('رقم الإصدار', 'Issue number'), self.issue_no), (L('تاريخ الإصدار', 'Issue date'), self.issue_date)),
                ((L('إعداد', 'Prepared by'), self.prepared), (L('مراجعة', 'Reviewed by'), self.reviewed)),
                ((L('اعتماد', 'Approved by'), self.approved), (L('تاريخ المسودة الأولى', 'First draft date'), self.first_draft))]
        for i, (a, b) in enumerate(rows):
            field(g, i, 0, a[0], a[1])
            field(g, i, 2, b[0], b[1])
        lr = QHBoxLayout()
        lr.addWidget(self.logo)
        lr.addWidget(logo_pick)
        lr.addWidget(logo_clear)
        lr.addStretch(1)
        field(g, len(rows), 0, L('الشعار', 'Logo'), lr, 3)
        field(g, len(rows) + 1, 0, L('تنويه السرية (عربي)', 'Confidentiality notice (Arabic)'), self.disc_ar, 3)
        field(g, len(rows) + 2, 0, L('تنويه السرية (إنجليزي)', 'Confidentiality notice (English)'), self.disc_en, 3)
        g.setColumnStretch(1, 1)
        g.setColumnStretch(3, 1)
        ident = card(L('بيانات الدليل', 'Manual details'))
        ident.setLayout(g)

        # page
        self.size = QComboBox()
        for k in PAGE_SIZES:
            self.size.addItem(k, k)
        self.orient = QComboBox()
        self.orient.addItem(L('أفقي', 'Landscape'), 'landscape')
        self.orient.addItem(L('عمودي', 'Portrait'), 'portrait')
        self.margins = {}
        for k in ('top', 'bottom', 'right', 'left'):
            sp = QSpinBox()
            sp.setRange(5, 60)
            sp.setSuffix(L(' مم', ' mm'))
            fit(sp, 100)
            self.margins[k] = sp
        self.lang = QComboBox()
        for k, (ar, en) in LANG_MODES.items():
            self.lang.addItem(L(ar, en), k)
        from .fonts import FontPicker
        self.font_ar = FontPicker(arabic=True)
        self.font_en = FontPicker()
        self.font_note = hint('')
        for w in (self.font_ar, self.font_en):
            w.currentIndexChanged.connect(self._font_note)
        self.font_size = QDoubleSpinBox()
        self.font_size.setRange(7, 16)
        self.font_size.setSingleStep(0.5)
        self.font_size.setSuffix(' pt')
        self.line = QDoubleSpinBox()
        self.line.setRange(1, 2.4)
        self.line.setSingleStep(0.05)
        self.align = QComboBox()
        for k, (ar, en) in ALIGNMENTS.items():
            self.align.addItem(L(ar, en), k)
        for w, n in ((self.size, 120), (self.orient, 140), (self.lang, 320), (self.align, 330), (self.font_ar, 260), (self.font_en, 260),
                     (self.font_size, 110), (self.line, 100)):
            fit(w, n)
        pg = form_grid()
        field(pg, 0, 0, L('حجم الورق', 'Paper size'), self.size)
        field(pg, 0, 2, L('الاتجاه', 'Orientation'), self.orient)
        mr = QHBoxLayout()
        for k, lab in (('top', L('أعلى', 'Top')), ('bottom', L('أسفل', 'Bottom')), ('right', L('يمين', 'Right')), ('left', L('يسار', 'Left'))):
            mr.addWidget(QLabel(lab))
            mr.addWidget(self.margins[k])
            a11y(self.margins[k], L('الهامش: ', 'Margin: ') + lab)
        mr.addStretch(1)
        field(pg, 1, 0, L('الهوامش', 'Margins'), mr, 3)
        field(pg, 2, 0, L('لغة الدليل', 'Manual language'), self.lang, 3)
        field(pg, 3, 0, L('الخط العربي', 'Arabic font'), self.font_ar)
        field(pg, 3, 2, L('الخط الإنجليزي', 'English font'), self.font_en)
        pg.addWidget(self.font_note, 4, 1, 1, 3)
        field(pg, 5, 0, L('حجم الخط', 'Font size'), self.font_size)
        field(pg, 5, 2, L('تباعد الأسطر', 'Line spacing'), self.line)
        field(pg, 10, 0, L('محاذاة النصوص', 'Text alignment'), self.align, 3,
              desc=L('محاذاة كل الفقرات؛ ويمكن تغيير محاذاة فقرة بعينها من المحرر', 'Alignment of every paragraph; one paragraph can be changed in the editor'))
        self.boxes = QCheckBox(L('إطار حول كل قسم', 'A frame around every section'))
        self.numbering = QCheckBox(L('ترقيم العناوين (1، 1.1، 1.1.1)', 'Number the headings (1, 1.1, 1.1.1)'))
        self.policy_footer = QCheckBox(L('«المسؤول عن التحديث» و«سجل التغييرات» في نهاية كل سياسة', '«Responsible» and «Change history» at the end of every policy'))
        self.draft_mark = QCheckBox(L('علامة «مسودة» على الأقسام غير المعتمدة (عند تفعيل سير العمل)', '«Draft» mark on sections not approved (when the workflow is on)'))
        self.toc_depth = QSpinBox()
        self.toc_depth.setRange(1, 4)
        fit(self.toc_depth, 90)
        self.watermark = QLineEdit()
        self.watermark.setPlaceholderText(L('مثلاً: سري', 'e.g. Confidential'))
        pg.addWidget(self.boxes, 6, 1)
        pg.addWidget(self.numbering, 6, 3)
        pg.addWidget(self.policy_footer, 7, 1, 1, 3)
        pg.addWidget(self.draft_mark, 8, 1, 1, 3)
        field(pg, 9, 0, L('مستويات الفهرس', 'Contents levels'), self.toc_depth)
        field(pg, 9, 2, L('علامة مائية', 'Watermark'), self.watermark)
        pg.setColumnStretch(1, 1)
        pg.setColumnStretch(3, 1)
        page = card(L('الصفحة والخطوط', 'Page & fonts'))
        page.setLayout(pg)

        # header / footer / backgrounds
        self.h_style = QComboBox()
        for k, (ar, en) in HEADER_STYLES.items():
            self.h_style.addItem(L(ar, en), k)
        self.h_height = QSpinBox()
        self.h_height.setRange(8, 60)
        self.h_height.setSuffix(L(' مم', ' mm'))
        self.h_logo = QCheckBox(L('الشعار في الترويسة', 'Logo in the header'))
        self.h_image = QPushButton(L('صورة الترويسة…', 'Header image…'))
        self.h_image.clicked.connect(lambda: self._pick('header'))
        h_clear = icon_button('close', L('إزالة صورة الترويسة', 'Remove the header image'))
        h_clear.clicked.connect(lambda: self._set_asset('header', None))
        self.h_start, self.h_center, self.h_end = TokenEdit(), TokenEdit(), TokenEdit()
        self.f_style = QComboBox()
        for k, (ar, en) in HEADER_STYLES.items():
            self.f_style.addItem(L(ar, en), k)
        self.f_start, self.f_center, self.f_end = TokenEdit(), TokenEdit(), TokenEdit()
        self.cover_style = QComboBox()
        for k in ('wave', 'band', 'none'):
            self.cover_style.addItem(L(*HEADER_STYLES[k]), k)
        self.bg_labels = {}
        self.bg_rows = {}
        for key, ttl in (('page', L('خلفية كل الصفحات', 'Background of every page')), ('cover', L('خلفية الغلاف', 'Cover background'))):
            pick = button(L('تعديل الخلفية…', 'Edit the background…'), 'image')
            pick.clicked.connect(lambda _=False, k=key, t=ttl: self._edit_bg(k, t))
            clear = icon_button('close', L('إزالة الخلفية', 'Remove the background'))
            clear.clicked.connect(lambda _=False, k=key: self._set_bg(k, None))
            lab = muted('')
            lab.setWordWrap(True)
            row = QHBoxLayout()
            row.addWidget(pick)
            row.addWidget(clear)
            row.addWidget(lab, 1)
            self.bg_labels[key], self.bg_rows[key] = lab, row
        for w, n in ((self.h_style, 160), (self.h_height, 100), (self.f_style, 160), (self.cover_style, 160)):
            fit(w, n)
        hg = form_grid()
        hr = QHBoxLayout()
        for w in (self.h_style, self.h_height, self.h_logo, self.h_image, h_clear):
            hr.addWidget(w)
        hr.addStretch(1)
        field(hg, 0, 0, L('شكل الترويسة', 'Header style'), hr, 3)
        a11y(self.h_height, L('ارتفاع الترويسة', 'Header height'))
        field(hg, 1, 0, L('بداية الترويسة', 'Header start'), self.h_start)
        field(hg, 1, 2, L('وسط الترويسة', 'Header centre'), self.h_center)
        field(hg, 2, 0, L('نهاية الترويسة', 'Header end'), self.h_end)
        field(hg, 3, 0, L('شكل التذييل', 'Footer style'), self.f_style)
        field(hg, 4, 0, L('بداية التذييل', 'Footer start'), self.f_start)
        field(hg, 4, 2, L('وسط التذييل', 'Footer centre'), self.f_center)
        field(hg, 5, 0, L('نهاية التذييل', 'Footer end'), self.f_end)
        field(hg, 6, 0, L('شكل الغلاف', 'Cover style'), self.cover_style)
        hg.addWidget(hint(L('زر «حقل» بجانب كل خانة يُدرج ما يتغير عند الطباعة، مثل [رقم الصفحة] و[عدد الصفحات] و[الباب الحالي] و[تاريخ الإصدار].',
                            'The «Field» button beside each box inserts what changes when printing, such as [Page number], [Page count], [Current chapter] and [Issue date].')), 7, 1, 1, 3)
        hg.setColumnStretch(1, 1)
        hg.setColumnStretch(3, 1)
        hf = card(L('الترويسة والتذييل والغلاف', 'Header, footer & cover'))
        hf.setLayout(hg)
        bgg = form_grid()
        field(bgg, 0, 0, L('كل الصفحات', 'Every page'), self.bg_rows['page'])
        field(bgg, 1, 0, L('الغلاف', 'Cover'), self.bg_rows['cover'])
        bgg.addWidget(hint(L('لكل خلفية: صورة أو لون، خلف النص أو أمامه، وموضعها وحجمها وتدويرها ودرجة ظهورها. '
                             'خلفية قسم بعينه، واتجاه صفحاته (عمودي أو أفقي)، يُختاران من المحرر عند فتح القسم.',
                             'Each background: an image or a colour, behind or in front of the text, its position, size, turning and strength. '
                             'The background of one section, and the direction of its pages, are chosen in the editor.')), 2, 1)
        bgg.setColumnStretch(1, 1)
        bgbox = card(L('الخلفيات', 'Backgrounds'))
        bgbox.setLayout(bgg)

        # page numbers
        self.pn_digits = QComboBox()
        for k, (ar, en) in PAGE_DIGITS.items():
            self.pn_digits.addItem(L(ar, en), k)
        self.pn_front = QComboBox()
        for k, (ar, en) in FRONT_NUMBERING.items():
            self.pn_front.addItem(L(ar, en), k)
        self.pn_start = QSpinBox()
        self.pn_start.setRange(1, 999)
        self.pn_cover = QCheckBox(L('يُحسب الغلاف صفحةً أولى', 'The cover counts as page one'))
        self.pn_format = QComboBox()
        self.pn_format.addItem(L('اختيار صيغة جاهزة…', 'Choose a ready format…'), '')
        for k, (ar, en, _tpl) in PAGE_NUMBER_FORMATS.items():
            self.pn_format.addItem(L(ar, en), k)
        self.pn_format.activated.connect(self._number_format)
        for w, n in ((self.pn_digits, 260), (self.pn_front, 280), (self.pn_start, 90), (self.pn_format, 220)):
            fit(w, n)
        ng = form_grid()
        field(ng, 0, 0, L('شكل الأرقام', 'Digits'), self.pn_digits)
        field(ng, 0, 2, L('الصفحات التمهيدية', 'Front matter pages'), self.pn_front,
              desc=L('التنويه وضبط الوثيقة والفهرس قبل أول قسم من المحتوى', 'The notice, document control and contents before the first content section'))
        field(ng, 1, 0, L('يبدأ ترقيم المحتوى من', 'Content numbering starts at'), self.pn_start)
        ng.addWidget(self.pn_cover, 1, 3)
        field(ng, 2, 0, L('صيغة رقم الصفحة في التذييل', 'Page number format in the footer'), self.pn_format, 3)
        ng.addWidget(hint(L('عبارة «من 20» تعدّ صفحات المحتوى المرقّمة فقط، وأرقام الفهرس تتبع شكل الأرقام نفسه.',
                            '«of 20» counts the numbered content pages only, and the contents page numbers use the same digits.')), 3, 1, 1, 3)
        ng.setColumnStretch(1, 1)
        ng.setColumnStretch(3, 1)
        nbox = card(L('ترقيم الصفحات', 'Page numbering'))
        nbox.setLayout(ng)

        # colours
        self.colors = {}
        cg = QGridLayout()
        cg.setHorizontalSpacing(12)
        for i, (k, (ar, en)) in enumerate(COLOR_NAMES.items()):
            b = ltr(QPushButton())
            b.setFixedWidth(110)
            b.clicked.connect(lambda _=False, kk=k: self._color(kk))
            a11y(b, L(ar, en))
            self.colors[k] = b
            cg.addWidget(QLabel(L(ar, en)), i // 3, (i % 3) * 2)
            cg.addWidget(b, i // 3, (i % 3) * 2 + 1)
        reset = button(L('الألوان الافتراضية', 'Default colours'), 'reset', 'ghost')
        reset.clicked.connect(self._reset_colors)
        cg.addWidget(reset, (len(COLOR_NAMES) + 2) // 3, 0, 1, 2)
        cbox = card(L('الألوان', 'Colours'))
        cbox.setLayout(cg)

        # every change is saved by itself after a moment, and the pages beside redrawn
        self.undo_btn = button(L('تراجع عن آخر تغيير', 'Undo the last change'), 'reset')
        self.undo_btn.clicked.connect(self.undo)
        self.state = muted('')
        self.preview_scope = QComboBox()
        self.preview_scope.addItem(L('أول صفحات الدليل', 'The first pages'), 'first')
        self.preview_scope.addItem(L('الدليل كاملاً', 'The whole manual'), 'all')
        fit(self.preview_scope, 190)
        a11y(self.preview_scope, L('ما تعرضه المعاينة', 'What the preview shows'))
        self.preview_scope.currentIndexChanged.connect(self.refresh_preview)
        self.tabs = QTabWidget()
        for box, (ar, en) in ((ident, ('بيانات الدليل', 'Details')), (page, ('الصفحة والخطوط', 'Page & fonts')),
                              (hf, ('الترويسة والتذييل', 'Header & footer')), (bgbox, ('الخلفيات', 'Backgrounds')),
                              (nbox, ('ترقيم الصفحات', 'Page numbers')), (cbox, ('الألوان', 'Colours'))):
            holder = QWidget()
            hl = QVBoxLayout(holder)
            hl.setContentsMargins(0, 6, 0, 0)
            hl.addWidget(box)
            hl.addStretch(1)
            self.tabs.addTab(scroll_page(holder, horizontal=False), L(ar, en))
        from .editor import Preview
        self.preview = Preview(ctx)
        self.preview.scope.hide()
        self.preview.auto.hide()
        self.preview.refresh_btn.clicked.connect(self.refresh_preview)
        self.preview.picked.connect(self._picked)
        self.preview.inspector.changed.connect(self._inspected)
        self.preview.inspector.before_change = lambda: self._timer.isActive() and (self._timer.stop(), self.save(quiet=True))
        self.preview.inspector.open_block.connect(lambda sid, i: self.ctx.window and (self.ctx.window.show_page(self.ctx.window.editor),
                                                                              self.ctx.window.editor.goto(sid, i)))
        self.preview.lay.itemAt(0).layout().insertWidget(0, self.preview_scope)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.tabs)
        split.addWidget(self.preview)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([760, 520])
        split.setCollapsible(0, False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 14)
        lay.addWidget(flow_row([self.undo_btn, self.state]))
        lay.addWidget(split, 1)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(900)
        self._timer.timeout.connect(lambda: self.save(quiet=True))
        for w in self.findChildren(QLineEdit):
            if not isinstance(w.parent(), QAbstractSpinBox):
                w.textChanged.connect(self._changed)
        for w in self.findChildren(QPlainTextEdit):
            w.textChanged.connect(self._changed)
        for w in self.findChildren(QComboBox):
            if w is not self.preview_scope and w is not self.pn_format and w.parent() is not self.preview:
                w.currentIndexChanged.connect(self._changed)
        for w in self.findChildren(QSpinBox) + self.findChildren(QDoubleSpinBox):
            w.valueChanged.connect(self._changed)
        for w in self.findChildren(QCheckBox):
            if w is not self.preview.auto:
                w.toggled.connect(self._changed)
        self.undo_btn.setEnabled(False)

    TABS = {'details': 0, 'page': 1, 'header': 2, 'background': 3, 'numbers': 4, 'colours': 5}

    def open_tab(self, name):
        self.tabs.setCurrentIndex(self.TABS.get(name, 1))

    def _picked(self, what):
        self.preview.inspector.show_for(what)

    def _inspected(self, sid):
        if self._timer.isActive():
            self._timer.stop()
        self.load_manual(self.mid, keep_history=True)       # the fields here follow what the panel changed
        self._others_stale = True
        self.refresh_preview()

    def _changed(self, *_):
        if self._loading or not self.mid:
            return
        self.state.setText(L('سيُحفظ التغيير…', 'The change will be saved…'))
        self._timer.start()

    def hideEvent(self, e):
        super().hideEvent(e)
        if self._timer.isActive():
            self._timer.stop()
            self.save(quiet=True)
        if getattr(self, '_others_stale', False) and self.ctx.window:
            self._others_stale = False
            QTimer.singleShot(0, self.ctx.window.manual_changed)

    def showEvent(self, e):
        super().showEvent(e)
        if self.mid:
            QTimer.singleShot(100, self.refresh_preview)

    def refresh_preview(self):
        if not self.mid or not self.isVisible():
            return
        from ..core.html import build_html
        from ..core.pdf import page_size_mm
        only = None
        if self.preview_scope.currentData() == 'first':
            secs = self.db.sections(self.mid)
            only = [x['id'] for x in secs[:6]]
            first_content = next((x for x in secs[6:] if x['kind'] in ('text', 'policy', 'table')), None)
            if first_content:
                only.append(first_content['id'])
        try:
            html = build_html(self.db, self.mid, 'print', only=only, workflow=self.ctx.workflow, draft=True)
        except Exception as e:  # noqa: BLE001 — a preview must never take the page down
            self.preview.state.setText(str(e)[:120])
            return
        self.preview.show_html(html, page_size_mm(self.db.manual(self.mid))[0])

    def load_manual(self, mid, keep_history=False):
        if self._timer.isActive() and self.mid:
            self._timer.stop()
            self.save(quiet=True)
        if not keep_history and mid != self.mid:
            self.history = []
            self.undo_btn.setEnabled(False)
        self.mid = mid
        self.setEnabled(bool(mid) and self.ctx.can('edit'))
        if not mid:
            return
        self._loading = True
        try:
            self._load(mid)
        finally:
            self._loading = False
        self.state.setText(L('تُحفظ التغييرات تلقائياً.', 'Changes are saved automatically.'))
        self.refresh_preview()

    def _load(self, mid):
        m = self.db.manual(mid)
        lay = layout_with_defaults(m['layout'])
        meta = m.get('meta') or {}
        for w, v in ((self.title_ar, m['title_ar']), (self.title_en, m['title_en']), (self.sub_ar, m.get('subtitle_ar')),
                     (self.sub_en, m.get('subtitle_en')), (self.org_ar, m.get('org_ar')), (self.org_en, m.get('org_en')),
                     (self.ed_ar, m.get('edition_ar')), (self.ed_en, m.get('edition_en')), (self.issue_no, m.get('issue_no')),
                     (self.issue_date, m.get('issue_date')), (self.prepared, meta.get('prepared_by')),
                     (self.reviewed, meta.get('reviewed_by')), (self.approved, meta.get('approved_by')),
                     (self.first_draft, meta.get('first_draft')), (self.watermark, lay.get('watermark'))):
            w.setText(v or '')
        self.disc_ar.setPlainText(meta.get('disclaimer_ar') or '')
        self.disc_en.setPlainText(meta.get('disclaimer_en') or '')
        self.assets = {'logo': m.get('logo_id'), 'header': lay['header'].get('image_id'),
                       }
        self.bgs = {'page': BG.of_page(lay), 'cover': BG.of_cover(lay)}
        self._asset_labels()
        self.align.setCurrentIndex(max(0, self.align.findData(lay.get('align', 'justify'))))
        self.size.setCurrentIndex(max(0, self.size.findData(lay['page_size'])))
        self.orient.setCurrentIndex(max(0, self.orient.findData(lay['orientation'])))
        for k, sp in self.margins.items():
            sp.setValue(int(lay['margins'].get(k, 15)))
        self.lang.setCurrentIndex(max(0, self.lang.findData(lay['lang_mode'])))
        self.font_ar.set_value(lay['fonts']['ar'])
        self.font_en.set_value(lay['fonts']['en'])
        self.font_size.setValue(float(lay['fonts']['size']))
        self.line.setValue(float(lay['fonts']['line']))
        self.boxes.setChecked(bool(lay.get('boxes')))
        self.numbering.setChecked(bool(lay.get('numbering')))
        self.policy_footer.setChecked(bool(lay.get('policy_footer')))
        self.draft_mark.setChecked(bool(lay.get('draft_mark')))
        self.toc_depth.setValue(int(lay.get('toc_depth') or 2))
        h, f = lay['header'], lay['footer']
        self.h_style.setCurrentIndex(max(0, self.h_style.findData(h.get('style'))))
        self.h_height.setValue(int(h.get('height') or 22))
        self.h_logo.setChecked(bool(h.get('logo')))
        self.h_start.set_text(h.get('start') or '')
        self.h_center.set_text(h.get('center') or '')
        self.h_end.set_text(h.get('end') or '')
        self.f_style.setCurrentIndex(max(0, self.f_style.findData(f.get('style'))))
        self.f_start.set_text(f.get('start') or '')
        self.f_center.set_text(f.get('center') or '')
        self.f_end.set_text(f.get('end') or '')
        self.cover_style.setCurrentIndex(max(0, self.cover_style.findData((lay.get('cover') or {}).get('style', 'wave'))))
        pn = lay['page_numbers']
        self.pn_digits.setCurrentIndex(max(0, self.pn_digits.findData(pn.get('digits', 'latin'))))
        self.pn_front.setCurrentIndex(max(0, self.pn_front.findData(pn.get('front', 'same'))))
        self.pn_start.setValue(int(pn.get('start') or 1))
        self.pn_cover.setChecked(bool(pn.get('count_cover', True)))
        self.pn_format.setCurrentIndex(0)
        self.color_values = dict(lay['colors'])
        self._paint_colors()

    def _font_note(self, *_):
        """Says where a font installed in Windows shows exactly as chosen, and where another font stands in for it."""
        if not hasattr(self, 'font_en'):
            return
        sysf = [w.value() for w in (self.font_ar, self.font_en) if w.is_system()]
        if not sysf:
            self.font_note.setText(L('خطوط البرنامج تظهر كما هي في PDF وفي النسخة التفاعلية على أي جهاز.',
                                     "The program's fonts show as they are in the PDF and in the interactive copy on any computer."))
            return
        names = '، '.join(dict.fromkeys(sysf)) if L('ar', 'en') == 'ar' else ', '.join(dict.fromkeys(sysf))
        self.font_note.setText(L(f'الخط المثبت ({names}) يُضمَّن في ملف PDF فيظهر كما هو عند الجميع. أما ملف Word والنسخة '
                                 'التفاعلية فيظهر فيهما على الأجهزة المثبَّت عليها هذا الخط فقط، وفي غيرها يحل محله خط '
                                 'Tajawal.',
                                 f'The installed font ({names}) is placed inside the PDF, so it shows the same for everyone. The '
                                 'Word file and the interactive copy show it only on computers where this font is installed; '
                                 'elsewhere Tajawal stands in for it.'))

    def _number_format(self, i):
        key = self.pn_format.itemData(i)
        if not key:
            return
        tpl = PAGE_NUMBER_FORMATS[key][2]
        for box in (self.f_start, self.f_center, self.f_end):          # the page number moves, the rest stays
            if '{page}' in box.text():
                box.set_text(tpl)
                return
        (self.f_end if not self.f_end.text() else self.f_center).set_text(tpl)

    def _asset_labels(self):
        pm = asset_pixmap(self.db, self.assets.get('logo'), 64)
        if pm.isNull():
            self.logo.setText(L('بلا شعار', 'No logo'))
            self.logo.setPixmap(pm)
        else:
            self.logo.setPixmap(pm)
        a = self.db.asset(self.assets.get('header')) if self.assets.get('header') else None
        self.h_image.setText(a['name'] if a else L('صورة الترويسة…', 'Header image…'))
        for key, lab in self.bg_labels.items():
            bg = self.bgs.get(key)
            a = self.db.asset(bg['asset_id']) if bg and bg.get('asset_id') else None
            lab.setText(BG.summary(bg, L, a['name'] if a else None))

    def _edit_bg(self, key, title):
        landscape = self.orient.currentData() == 'landscape'
        ok, bg = edit_background(self, self.db, self.bgs.get(key), title, False, landscape)
        if ok:
            self._set_bg(key, bg)

    def _set_bg(self, key, bg):
        self.bgs[key] = BG.normalize(bg) if BG.active(bg) else None
        self._asset_labels()
        self._changed()

    def _pick(self, key):
        kind = {'logo': 'logo', 'header': 'background'}[key]
        aid = pick_asset(self, self.db, kind)
        if aid:
            self._set_asset(key, aid)

    def _set_asset(self, key, aid):
        self.assets[key] = aid
        self._asset_labels()
        self._changed()

    def _paint_colors(self):
        for k, b in self.colors.items():
            c = self.color_values.get(k, '#000000')
            light = QColor(c).lightness() > 150
            b.setText('')                        # the colour itself, its code only on hover
            b.setToolTip(c.upper())
            b.setStyleSheet(f'background:{c};color:{"#1e293b" if light else "#ffffff"};border:1px solid #c9d4e3;border-radius:6px')

    def _color(self, k):
        c = QColorDialog.getColor(QColor(self.color_values.get(k, '#000000')), self, L(*COLOR_NAMES[k]))
        if c.isValid():
            self.color_values[k] = c.name().upper()
            self._paint_colors()
            self._changed()

    def _reset_colors(self):
        self.color_values = dict(DEFAULT_LAYOUT['colors'])
        self._paint_colors()
        self._changed()

    SAVED = ('title_ar', 'title_en', 'subtitle_ar', 'subtitle_en', 'org_ar', 'org_en', 'edition_ar', 'edition_en',
             'issue_no', 'issue_date', 'logo_id', 'layout', 'meta')

    def save(self, quiet=False):
        if not self.mid or self._loading:
            return
        m = self.db.manual(self.mid)
        before = {k: m.get(k) for k in self.SAVED}
        lay = layout_with_defaults(m['layout'])
        lay.update({
            'page_size': self.size.currentData(), 'orientation': self.orient.currentData(),
            'margins': {k: sp.value() for k, sp in self.margins.items()}, 'lang_mode': self.lang.currentData(),
            'fonts': {'ar': self.font_ar.value(), 'en': self.font_en.value(), 'size': self.font_size.value(),
                      'line': round(self.line.value(), 2)},
            'colors': self.color_values, 'boxes': self.boxes.isChecked(), 'numbering': self.numbering.isChecked(),
            'policy_footer': self.policy_footer.isChecked(), 'draft_mark': self.draft_mark.isChecked(),
            'toc_depth': self.toc_depth.value(), 'watermark': self.watermark.text().strip(),
            # what this page does not show (colours, a placed picture…) is kept as it is
            'header': dict(lay['header'], style=self.h_style.currentData(), height=self.h_height.value(),
                           logo=self.h_logo.isChecked(), start=self.h_start.text(), center=self.h_center.text(),
                           end=self.h_end.text(), image_id=self.assets.get('header'),
                           image_bg=lay['header'].get('image_bg') if self.assets.get('header') == lay['header'].get('image_id') else None),
            'footer': dict(lay['footer'], style=self.f_style.currentData(), start=self.f_start.text(),
                           center=self.f_center.text(), end=self.f_end.text()),
            'cover': dict({k: v for k, v in (lay.get('cover') or {}).items() if k not in ('bg_id', 'bg_opacity')},
                          style=self.cover_style.currentData(), bg=self.bgs.get('cover')),
            'page_bg': self.bgs.get('page'), 'page_bg_id': None, 'align': self.align.currentData(),
            'page_numbers': {'digits': self.pn_digits.currentData(), 'front': self.pn_front.currentData(),
                             'start': self.pn_start.value(), 'count_cover': self.pn_cover.isChecked()},
        })
        meta = dict(m.get('meta') or {}, prepared_by=self.prepared.text().strip(), reviewed_by=self.reviewed.text().strip(),
                    approved_by=self.approved.text().strip(), first_draft=self.first_draft.text().strip(),
                    disclaimer_ar=self.disc_ar.toPlainText().strip(), disclaimer_en=self.disc_en.toPlainText().strip())
        self.db.save_manual({'title_ar': self.title_ar.text().strip(), 'title_en': self.title_en.text().strip(),
                             'subtitle_ar': self.sub_ar.text().strip(), 'subtitle_en': self.sub_en.text().strip(),
                             'org_ar': self.org_ar.text().strip(), 'org_en': self.org_en.text().strip(),
                             'edition_ar': self.ed_ar.text().strip(), 'edition_en': self.ed_en.text().strip(),
                             'issue_no': self.issue_no.text().strip(), 'issue_date': self.issue_date.text().strip(),
                             'logo_id': self.assets.get('logo'), 'layout': lay, 'meta': meta}, self.mid)
        after = self.db.manual(self.mid)
        if json.dumps({k: after.get(k) for k in self.SAVED}, sort_keys=True, default=str) != \
                json.dumps(before, sort_keys=True, default=str):
            self.history.append(before)
            del self.history[:-30]
            self.undo_btn.setEnabled(True)
            self._others_stale = True
        self.state.setText(L('حُفظ التغيير.', 'The change is saved.'))
        self.refresh_preview()
        if not quiet and self.ctx.window:
            self._others_stale = False
            self.ctx.window.manual_changed()

    def undo(self):
        if not self.history or not self.mid:
            return
        self._timer.stop()
        self.db.save_manual(self.history.pop(), self.mid)
        self.undo_btn.setEnabled(bool(self.history))
        self._others_stale = True
        self.load_manual(self.mid, keep_history=True)
        self.state.setText(L('أُعيد التصميم كما كان قبل آخر تغيير.', 'The design is back as it was before the last change.'))

"""The current manual's identity and page design: titles, organisation, edition, logo, document-control data and the
confidentiality notice; page size, orientation and margins; language mode, fonts and colours; header and footer
(styles and texts with fields such as the page number); cover and page backgrounds; table of contents and numbering."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout, QLabel,
                               QLineEdit, QMenu, QPlainTextEdit, QPushButton, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from ..core.html import DEFAULT_DISCLAIMER
from ..core.templates import (DEFAULT_LAYOUT, FONTS, HEADER_STYLES, LANG_MODES, PAGE_SIZES, TOKENS,
                              layout_with_defaults)
from .common import L, info
from .library import asset_pixmap, pick_asset
from .theme import a11y, button, card, field, fit, form_grid, hint, icon_button, ltr

COLOR_NAMES = {'primary': ('اللون الأساسي', 'Primary colour'), 'secondary': ('اللون الثانوي', 'Secondary colour'),
               'accent': ('لون التمييز', 'Accent colour'), 'text': ('لون النص', 'Text colour'),
               'heading': ('لون العناوين', 'Heading colour'), 'table_head': ('رأس الجداول', 'Table header'),
               'table_head_text': ('نص رأس الجداول', 'Table header text'), 'box_border': ('إطار الأقسام', 'Section frame'),
               'callout': ('خلفية مربع التنبيه', 'Callout background')}


class TokenEdit(QWidget):
    """A header/footer text with a button that inserts a field (page number, issue date…)."""

    def __init__(self, text=''):
        super().__init__()
        self.edit = QLineEdit(text)
        self.edit.setMinimumWidth(220)
        btn = QToolButton()
        btn.setText('{…}')
        btn.setToolTip(L('إدراج حقل', 'Insert a field'))
        a11y(btn, L('إدراج حقل', 'Insert a field'))
        m = QMenu(btn)
        for tok, (ar, en) in TOKENS.items():
            m.addAction(f'{L(ar, en)}  {tok}', lambda t=tok: self.edit.insert(t))
        btn.setMenu(m)
        btn.setPopupMode(QToolButton.InstantPopup)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(self.edit, 1)
        lay.addWidget(btn)

    def text(self):
        return self.edit.text()


class DesignTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.db = ctx, ctx.db
        self.mid = None
        self.assets = {}
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
        self.font_ar = QComboBox()
        self.font_en = QComboBox()
        for f in FONTS:
            self.font_ar.addItem(f, f)
            self.font_en.addItem(f, f)
        self.font_size = QDoubleSpinBox()
        self.font_size.setRange(7, 16)
        self.font_size.setSingleStep(0.5)
        self.font_size.setSuffix(' pt')
        self.line = QDoubleSpinBox()
        self.line.setRange(1, 2.4)
        self.line.setSingleStep(0.05)
        for w, n in ((self.size, 120), (self.orient, 140), (self.lang, 320), (self.font_ar, 200), (self.font_en, 200),
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
        field(pg, 4, 0, L('حجم الخط', 'Font size'), self.font_size)
        field(pg, 4, 2, L('تباعد الأسطر', 'Line spacing'), self.line)
        self.boxes = QCheckBox(L('إطار حول كل قسم', 'A frame around every section'))
        self.numbering = QCheckBox(L('ترقيم العناوين (1، 1.1، 1.1.1)', 'Number the headings (1, 1.1, 1.1.1)'))
        self.policy_footer = QCheckBox(L('«المسؤول عن التحديث» و«سجل التغييرات» في نهاية كل سياسة', '«Responsible» and «Change history» at the end of every policy'))
        self.draft_mark = QCheckBox(L('علامة «مسودة» على الأقسام غير المعتمدة (عند تفعيل سير العمل)', '«Draft» mark on sections not approved (when the workflow is on)'))
        self.toc_depth = QSpinBox()
        self.toc_depth.setRange(1, 4)
        fit(self.toc_depth, 90)
        self.watermark = QLineEdit()
        self.watermark.setPlaceholderText(L('مثلاً: سري', 'e.g. Confidential'))
        pg.addWidget(self.boxes, 5, 1)
        pg.addWidget(self.numbering, 5, 3)
        pg.addWidget(self.policy_footer, 6, 1, 1, 3)
        pg.addWidget(self.draft_mark, 7, 1, 1, 3)
        field(pg, 8, 0, L('مستويات الفهرس', 'Contents levels'), self.toc_depth)
        field(pg, 8, 2, L('علامة مائية', 'Watermark'), self.watermark)
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
        self.h_start, self.h_center, self.h_end = TokenEdit(), TokenEdit(), TokenEdit()
        self.f_style = QComboBox()
        self.f_style.addItem(L('خط فاصل', 'Separator line'), 'line')
        self.f_style.addItem(L('بدون', 'None'), 'none')
        self.f_start, self.f_center, self.f_end = TokenEdit(), TokenEdit(), TokenEdit()
        self.cover_style = QComboBox()
        for k in ('wave', 'band', 'none'):
            self.cover_style.addItem(L(*HEADER_STYLES[k]), k)
        self.cover_bg = QPushButton()
        self.cover_bg.clicked.connect(lambda: self._pick('cover'))
        cover_clear = icon_button('close', L('إزالة خلفية الغلاف', 'Remove the cover background'))
        cover_clear.clicked.connect(lambda: self._set_asset('cover', None))
        self.page_bg = QPushButton()
        self.page_bg.clicked.connect(lambda: self._pick('page'))
        page_clear = icon_button('close', L('إزالة خلفية الصفحات', 'Remove the page background'))
        page_clear.clicked.connect(lambda: self._set_asset('page', None))
        self.page_bg_op = QSpinBox()
        self.page_bg_op.setRange(2, 100)
        self.page_bg_op.setSuffix(' %')
        for w, n in ((self.h_style, 160), (self.h_height, 100), (self.f_style, 160), (self.cover_style, 160), (self.page_bg_op, 100)):
            fit(w, n)
        hg = form_grid()
        hr = QHBoxLayout()
        for w in (self.h_style, self.h_height, self.h_logo, self.h_image):
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
        cr = QHBoxLayout()
        cr.addWidget(self.cover_style)
        cr.addWidget(self.cover_bg)
        cr.addWidget(cover_clear)
        cr.addStretch(1)
        field(hg, 6, 0, L('الغلاف', 'Cover'), cr, 3)
        a11y(self.cover_style, L('شكل الغلاف', 'Cover style'))
        pr = QHBoxLayout()
        pr.addWidget(self.page_bg)
        pr.addWidget(page_clear)
        pr.addWidget(QLabel(L('الشفافية', 'Opacity')))
        pr.addWidget(self.page_bg_op)
        pr.addStretch(1)
        field(hg, 7, 0, L('خلفية كل الصفحات', 'Background of every page'), pr, 3)
        a11y(self.page_bg_op, L('شفافية خلفية الصفحات', 'Page background opacity'))
        hg.addWidget(hint(L('الحقول بين القوسين { } تُستبدل عند الطباعة: {page} رقم الصفحة، {pages} عدد الصفحات، {chapter} الباب الحالي، {issue_date} تاريخ الإصدار… '
                            'خلفية قسم بعينه تُختار من المحرر.',
                            'Fields in braces { } are replaced when printing: {page} page number, {pages} page count, {chapter} current chapter, {issue_date} issue date… '
                            'The background of a single section is chosen in the editor.')), 8, 1, 1, 3)
        hg.setColumnStretch(1, 1)
        hg.setColumnStretch(3, 1)
        hf = card(L('الترويسة والتذييل والخلفيات', 'Header, footer & backgrounds'))
        hf.setLayout(hg)

        # colours
        self.colors = {}
        cg = QGridLayout()
        cg.setHorizontalSpacing(12)
        for i, (k, (ar, en)) in enumerate(COLOR_NAMES.items()):
            b = QPushButton()
            b.setFixedWidth(110)
            b.clicked.connect(lambda _=False, kk=k: self._color(kk))
            a11y(b, L(ar, en))
            self.colors[k] = b
            cg.addWidget(QLabel(L(ar, en)), i // 3, (i % 3) * 2)
            cg.addWidget(b, i // 3, (i % 3) * 2 + 1)
        reset = button(L('الألوان الافتراضية', 'Default colours'), 'reset', 'ghost')
        reset.clicked.connect(self._reset_colors)
        cg.addWidget(reset, 3, 0, 1, 2)
        cbox = card(L('الألوان', 'Colours'))
        cbox.setLayout(cg)

        save = button(L('حفظ التصميم', 'Save the design'), 'save', 'primary')
        save.clicked.connect(self.save)
        row = QHBoxLayout()
        row.addWidget(save)
        row.addStretch(1)
        inner = QWidget()
        inner.setMaximumWidth(1100)
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.addLayout(row)
        for b in (ident, page, hf, cbox):
            il.addWidget(b)
        il.addStretch(1)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 14)
        lay.addWidget(inner, 1)

    def load_manual(self, mid):
        self.mid = mid
        self.setEnabled(bool(mid) and self.ctx.can('edit'))
        if not mid:
            return
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
                       'cover': (lay.get('cover') or {}).get('bg_id'), 'page': lay.get('page_bg_id')}
        self._asset_labels()
        self.size.setCurrentIndex(max(0, self.size.findData(lay['page_size'])))
        self.orient.setCurrentIndex(max(0, self.orient.findData(lay['orientation'])))
        for k, sp in self.margins.items():
            sp.setValue(int(lay['margins'].get(k, 15)))
        self.lang.setCurrentIndex(max(0, self.lang.findData(lay['lang_mode'])))
        self.font_ar.setCurrentIndex(max(0, self.font_ar.findData(lay['fonts']['ar'])))
        self.font_en.setCurrentIndex(max(0, self.font_en.findData(lay['fonts']['en'])))
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
        self.h_start.edit.setText(h.get('start') or '')
        self.h_center.edit.setText(h.get('center') or '')
        self.h_end.edit.setText(h.get('end') or '')
        self.f_style.setCurrentIndex(max(0, self.f_style.findData(f.get('style'))))
        self.f_start.edit.setText(f.get('start') or '')
        self.f_center.edit.setText(f.get('center') or '')
        self.f_end.edit.setText(f.get('end') or '')
        self.cover_style.setCurrentIndex(max(0, self.cover_style.findData((lay.get('cover') or {}).get('style', 'wave'))))
        self.page_bg_op.setValue(int(float(lay.get('page_bg_opacity') or 0.06) * 100))
        self.color_values = dict(lay['colors'])
        self._paint_colors()

    def _asset_labels(self):
        pm = asset_pixmap(self.db, self.assets.get('logo'), 64)
        if pm.isNull():
            self.logo.setText(L('بلا شعار', 'No logo'))
            self.logo.setPixmap(pm)
        else:
            self.logo.setPixmap(pm)
        for key, btn, empty in (('cover', self.cover_bg, L('صورة خلفية للغلاف…', 'Cover background image…')),
                                ('page', self.page_bg, L('صورة خلفية للصفحات…', 'Page background image…')),
                                ('header', self.h_image, L('صورة الترويسة…', 'Header image…'))):
            a = self.db.asset(self.assets.get(key)) if self.assets.get(key) else None
            btn.setText(a['name'] if a else empty)

    def _pick(self, key):
        kind = {'logo': 'logo', 'header': 'background', 'cover': 'background', 'page': 'background'}[key]
        aid = pick_asset(self, self.db, kind)
        if aid:
            self._set_asset(key, aid)

    def _set_asset(self, key, aid):
        self.assets[key] = aid
        self._asset_labels()

    def _paint_colors(self):
        for k, b in self.colors.items():
            c = self.color_values.get(k, '#000000')
            light = QColor(c).lightness() > 150
            b.setText(c.upper())
            b.setStyleSheet(f'background:{c};color:{"#1e293b" if light else "#ffffff"};border:1px solid #c9d4e3;border-radius:6px')

    def _color(self, k):
        c = QColorDialog.getColor(QColor(self.color_values.get(k, '#000000')), self, L(*COLOR_NAMES[k]))
        if c.isValid():
            self.color_values[k] = c.name().upper()
            self._paint_colors()

    def _reset_colors(self):
        self.color_values = dict(DEFAULT_LAYOUT['colors'])
        self._paint_colors()

    def save(self):
        if not self.mid:
            return
        m = self.db.manual(self.mid)
        lay = layout_with_defaults(m['layout'])
        lay.update({
            'page_size': self.size.currentData(), 'orientation': self.orient.currentData(),
            'margins': {k: sp.value() for k, sp in self.margins.items()}, 'lang_mode': self.lang.currentData(),
            'fonts': {'ar': self.font_ar.currentData(), 'en': self.font_en.currentData(), 'size': self.font_size.value(),
                      'line': round(self.line.value(), 2)},
            'colors': self.color_values, 'boxes': self.boxes.isChecked(), 'numbering': self.numbering.isChecked(),
            'policy_footer': self.policy_footer.isChecked(), 'draft_mark': self.draft_mark.isChecked(),
            'toc_depth': self.toc_depth.value(), 'watermark': self.watermark.text().strip(),
            'header': {'style': self.h_style.currentData(), 'height': self.h_height.value(), 'logo': self.h_logo.isChecked(),
                       'start': self.h_start.text(), 'center': self.h_center.text(), 'end': self.h_end.text(),
                       'image_id': self.assets.get('header')},
            'footer': {'style': self.f_style.currentData(), 'start': self.f_start.text(), 'center': self.f_center.text(),
                       'end': self.f_end.text()},
            'cover': dict(lay.get('cover') or {}, style=self.cover_style.currentData(), bg_id=self.assets.get('cover')),
            'page_bg_id': self.assets.get('page'), 'page_bg_opacity': self.page_bg_op.value() / 100,
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
        info(self, L('حُفظ التصميم. تظهر التغييرات في المعاينة والتصدير.', 'The design is saved. The changes show in the preview and the exports.'))
        if self.ctx.window:
            self.ctx.window.manual_changed()

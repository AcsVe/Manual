"""The background dialog, the same for the pages of the manual, the cover and a section: the image or colour, behind
or in front of the text, the area (sections), how it fits, where it sits, its size, turning, mirroring and
see-through level, with a drawing of a page that follows every change."""
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (QToolButton, QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialogButtonBox, QGridLayout,
                               QHBoxLayout, QLabel, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget)

from ..core import backgrounds as BG
from .common import L
from .library import pick_asset
from .theme import SizedDialog, a11y, button, field, fit, form_grid, hint, icon_button, muted, name_buttons


def asset_image(db, asset_id):
    a = db.asset(asset_id) if asset_id else None
    if not a:
        return QPixmap()
    if a['mime'] == 'image/svg+xml':
        from PySide6.QtCore import QByteArray
        from PySide6.QtSvg import QSvgRenderer
        r = QSvgRenderer(QByteArray(a['data']))
        size = r.defaultSize()
        pm = QPixmap(max(1, size.width()), max(1, size.height()))
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        r.render(p)
        p.end()
        return pm
    pm = QPixmap()
    pm.loadFromData(a['data'])
    if not pm.isNull() and max(pm.width(), pm.height()) > 1200:
        pm = pm.scaled(1200, 1200, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return pm


class PageSketch(QWidget):
    """A page drawn small: the background as set, grey lines for the text, a box for a section."""

    def __init__(self):
        super().__init__()
        self.bg, self.pm, self.landscape, self.section = BG.normalize({}), QPixmap(), False, False
        self.setMinimumSize(230, 230)
        a11y(self, L('رسم الصفحة بالخلفية', 'Drawing of the page with the background'))

    def show_bg(self, bg, pm, landscape, section):
        self.bg, self.pm, self.landscape, self.section = bg, pm, landscape, section
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.Antialiasing)
        W, H = self.width() - 16, self.height() - 16
        ratio = 297 / 210
        pw, ph = (min(W, H * ratio), min(W, H * ratio) / ratio) if self.landscape else (min(H / ratio, W), min(H / ratio, W) * ratio)
        page = QRectF((self.width() - pw) / 2, (self.height() - ph) / 2, pw, ph)
        p.fillRect(page.adjusted(3, 3, 3, 3), QColor('#cbd5e1'))
        p.fillRect(page, Qt.white)
        area = page
        if self.section and self.bg['area'] == 'section':
            area = QRectF(page.left() + pw * 0.08, page.top() + ph * 0.18, pw * 0.84, ph * 0.42)
        text = QRectF(page.left() + pw * 0.08, page.top() + ph * 0.1, pw * 0.84, ph * 0.8)

        def draw_bg():
            b = self.bg
            if b.get('color'):
                c = QColor(b['color'])
                c.setAlphaF(b['opacity'] if self.pm.isNull() else 1)
                p.fillRect(area, c)
            if self.pm.isNull():
                return
            pm = self.pm
            t = QTransform()
            if b['rotate']:
                t.rotate(b['rotate'])
            if b['flip']:
                t.scale(-1, 1)
            if b['rotate'] or b['flip']:
                pm = pm.transformed(t, Qt.SmoothTransformation)
            iw, ih = pm.width(), pm.height()
            if b['fit'] == 'cover':
                s = max(area.width() / iw, area.height() / ih)
                w, h = iw * s, ih * s
            elif b['fit'] == 'contain':
                s = min(area.width() / iw, area.height() / ih)
                w, h = iw * s, ih * s
            elif b['fit'] == 'stretch':
                w, h = area.width(), area.height()
            else:
                w = area.width() * b['scale'] / 100
                h = ih * w / iw
            pos = b['pos']
            x = area.left() + (area.width() - w) * (1 if 'right' in pos else 0 if 'left' in pos else 0.5)
            y = area.top() + (area.height() - h) * (0 if 'top' in pos else 1 if 'bottom' in pos else 0.5)
            p.save()
            p.setClipRect(area)
            p.setOpacity(b['opacity'])
            p.drawPixmap(QRectF(x, y, w, h), pm, QRectF(0, 0, iw, ih))
            p.restore()

        def draw_text():
            p.setPen(QPen(QColor('#94a3b8'), 1))
            if self.section:
                p.drawRect(QRectF(page.left() + pw * 0.08, page.top() + ph * 0.18, pw * 0.84, ph * 0.42))
            y = text.top()
            while y < text.bottom():
                p.fillRect(QRectF(text.left(), y, text.width() * (0.6 if (int(y) // 9) % 5 == 4 else 1), 2.2), QColor('#64748b'))
                y += 9

        if self.bg['layer'] == 'front':
            draw_text()
            draw_bg()
        else:
            draw_bg()
            draw_text()
        p.setPen(QPen(QColor('#94a3b8'), 1))
        p.drawRect(page)
        p.end()


class PositionGrid(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.group = QButtonGroup(self)
        g = QGridLayout(self)
        g.setSpacing(3)
        g.setContentsMargins(0, 0, 0, 0)
        keys = [['top-left', 'top', 'top-right'], ['left', 'center', 'right'], ['bottom-left', 'bottom', 'bottom-right']]
        self.buttons = {}
        for r, row in enumerate(keys):
            for c, k in enumerate(row):
                b = QToolButton()
                b.setText('●' if k == 'center' else '')
                b.setCheckable(True)
                b.setFixedSize(30, 24)
                b.setToolTip(L(*BG.POSITIONS[k]))
                a11y(b, L(*BG.POSITIONS[k]))
                b.setStyleSheet('QToolButton{border:1px solid #c9d4e3;border-radius:5px;background:#fff}'
                                'QToolButton:checked{background:#0C67EC;border-color:#0C67EC;color:#fff}')
                self.group.addButton(b)
                g.addWidget(b, r, c)        # physical places: the grid is not mirrored
                self.buttons[k] = b
                b.clicked.connect(self.changed.emit)
        self.setLayoutDirection(Qt.LeftToRight)
        self.setFixedSize(3 * 30 + 2 * 3, 3 * 24 + 2 * 3)

    def value(self):
        for k, b in self.buttons.items():
            if b.isChecked():
                return k
        return 'center'

    def set_value(self, k):
        self.buttons.get(k, self.buttons['center']).setChecked(True)


class BackgroundDialog(SizedDialog):
    """``value`` after OK: the background description, or None when it was removed."""

    def __init__(self, parent, db, bg, title, section=False, landscape=False):
        super().__init__(parent)
        self.db, self.section, self.landscape = db, section, landscape
        self.setWindowTitle(title)
        b = BG.normalize(bg) if bg else BG.normalize({'opacity': 0.15 if section else 0.1})
        self.asset_id, self.color = b['asset_id'], b['color']
        self.pm = asset_image(db, self.asset_id)
        self.value = bg
        self.sketch = PageSketch()
        self.img_label = muted('')
        pick = button(L('اختيار صورة…', 'Choose an image…'), 'image')
        pick.clicked.connect(self._pick)
        no_img = icon_button('close', L('إزالة الصورة', 'Remove the image'))
        no_img.clicked.connect(lambda: self._set_image(None))
        self.color_btn = QPushButton()
        self.color_btn.clicked.connect(self._color)
        a11y(self.color_btn, L('لون الخلفية', 'Background colour'))
        no_color = icon_button('close', L('إزالة اللون', 'Remove the colour'))
        no_color.clicked.connect(lambda: self._set_color(''))
        self.layer = QComboBox()
        for k, (ar, en) in BG.LAYERS.items():
            self.layer.addItem(L(ar, en), k)
        self.area = QComboBox()
        for k, (ar, en) in BG.AREAS.items():
            self.area.addItem(L(ar, en), k)
        self.fitc = QComboBox()
        for k, (ar, en) in BG.FITS.items():
            self.fitc.addItem(L(ar, en), k)
        self.scale = QSpinBox()
        self.scale.setRange(5, 400)
        self.scale.setSuffix(' %')
        self.pos = PositionGrid()
        self.rotate = QComboBox()
        for k, (ar, en) in BG.ROTATIONS.items():
            self.rotate.addItem(L(ar, en), k)
        self.flip = QCheckBox(L('عكس الصورة أفقياً (كالمرآة)', 'Mirror the image'))
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(2, 100)
        a11y(self.opacity, L('درجة الظهور', 'How strongly it shows'))
        self.op_label = QLabel()
        for w, n in ((self.layer, 260), (self.area, 300), (self.fitc, 280), (self.scale, 100), (self.rotate, 220)):
            fit(w, n)
        g = form_grid()
        r = 0
        img_row = QHBoxLayout()
        for w in (pick, no_img, self.img_label):
            img_row.addWidget(w)
        img_row.addStretch(1)
        field(g, r, 0, L('الصورة', 'Image'), img_row)
        r += 1
        col_row = QHBoxLayout()
        col_row.addWidget(self.color_btn)
        col_row.addWidget(no_color)
        col_row.addStretch(1)
        field(g, r, 0, L('لون', 'Colour'), col_row)
        r += 1
        if section:
            field(g, r, 0, L('المساحة', 'Area'), self.area)
            r += 1
        field(g, r, 0, L('الطبقة', 'Layer'), self.layer)
        r += 1
        field(g, r, 0, L('الملاءمة', 'Fit'), self.fitc)
        r += 1
        field(g, r, 0, L('العرض', 'Width'), self.scale)
        r += 1
        field(g, r, 0, L('الموضع', 'Position'), self.pos)
        r += 1
        field(g, r, 0, L('التدوير', 'Turning'), self.rotate)
        r += 1
        g.addWidget(self.flip, r, 1)
        r += 1
        op_row = QHBoxLayout()
        op_row.addWidget(self.opacity, 1)
        op_row.addWidget(self.op_label)
        field(g, r, 0, L('درجة الظهور', 'Strength'), op_row)
        r += 1
        g.addWidget(hint(L('خلف النص: ١٠–٢٠٪ تكفي ليبقى النص مقروءاً. أمام النص: ٥–١٢٪ كعلامة مائية.',
                           'Behind the text: 10–20% keeps it readable. In front of it: 5–12% as a watermark.')), r, 1)
        g.setColumnStretch(1, 1)
        left = QWidget()
        left.setLayout(g)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(L('تطبيق', 'Apply'))
        bb.button(QDialogButtonBox.Cancel).setText(L('إلغاء', 'Cancel'))
        remove = bb.addButton(L('بلا خلفية', 'No background'), QDialogButtonBox.DestructiveRole)
        name_buttons(bb)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        remove.clicked.connect(self._remove)
        row = QHBoxLayout()
        row.addWidget(left, 3)
        row.addWidget(self.sketch, 2)
        lay = QVBoxLayout(self)
        lay.addLayout(row, 1)
        lay.addWidget(bb)
        # values
        self.layer.setCurrentIndex(max(0, self.layer.findData(b['layer'])))
        self.area.setCurrentIndex(max(0, self.area.findData(b['area'])))
        self.fitc.setCurrentIndex(max(0, self.fitc.findData(b['fit'])))
        self.scale.setValue(b['scale'])
        self.pos.set_value(b['pos'])
        self.rotate.setCurrentIndex(max(0, self.rotate.findData(b['rotate'])))
        self.flip.setChecked(bool(b['flip']))
        self.opacity.setValue(round(b['opacity'] * 100))
        for w in (self.layer, self.area, self.fitc, self.rotate):
            w.currentIndexChanged.connect(self._update)
        self.scale.valueChanged.connect(self._update)
        self.flip.toggled.connect(self._update)
        self.opacity.valueChanged.connect(self._update)
        self.pos.changed.connect(self._update)
        self._set_color(self.color)
        self._set_image(self.asset_id)
        self.resize(840, 640)

    def current(self):
        return BG.normalize({'asset_id': self.asset_id, 'color': self.color, 'layer': self.layer.currentData(),
                             'area': self.area.currentData() if self.section else 'page', 'fit': self.fitc.currentData(),
                             'pos': self.pos.value(), 'scale': self.scale.value(), 'rotate': self.rotate.currentData(),
                             'flip': self.flip.isChecked(), 'opacity': self.opacity.value() / 100})

    def _update(self):
        self.scale.setEnabled(self.fitc.currentData() == 'width')
        self.op_label.setText(f'{self.opacity.value()}%')
        self.sketch.show_bg(self.current(), self.pm, self.landscape, self.section)

    def _pick(self):
        aid = pick_asset(self, self.db, 'background', L('صورة الخلفية', 'Background image'))
        if aid:
            self._set_image(aid)

    def _set_image(self, aid):
        self.asset_id = aid
        self.pm = asset_image(self.db, aid)
        a = self.db.asset(aid) if aid else None
        self.img_label.setText(a['name'] if a else L('بلا صورة', 'No image'))
        self._update()

    def _color(self):
        c = QColorDialog.getColor(QColor(self.color or '#ffffff'), self, L('لون الخلفية', 'Background colour'))
        if c.isValid():
            self._set_color(c.name().upper())

    def _set_color(self, c):
        self.color = c
        self.color_btn.setText(c or L('بلا لون', 'No colour'))
        self.color_btn.setStyleSheet(f'background:{c};border:1px solid #c9d4e3;border-radius:6px;padding:4px 10px' if c else '')
        if hasattr(self, 'sketch'):
            self._update()

    def _ok(self):
        v = self.current()
        self.value = v if BG.active(v) else None
        self.accept()

    def _remove(self):
        self.value = None
        self.accept()


def edit_background(parent, db, bg, title, section=False, landscape=False):
    """Opens the dialog: (changed, new value)."""
    d = BackgroundDialog(parent, db, bg, title, section, landscape)
    if d.exec():
        return True, d.value
    return False, bg

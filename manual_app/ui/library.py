"""The image library: logos, backgrounds and pictures kept inside the database. A picker dialog lets every other page
choose an image (or add one from a file)."""
import os

from PySide6.QtCore import QByteArray, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel, QListView, QListWidget,
                               QListWidgetItem, QVBoxLayout, QWidget)

from ..core import backgrounds as BG
from .common import L, confirm, error, info
from .theme import SizedDialog, a11y, button, card, hint, name_buttons

KINDS = {'image': ('صورة', 'Picture'), 'logo': ('شعار', 'Logo'), 'background': ('خلفية', 'Background')}
MIMES = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp',
         '.svg': 'image/svg+xml', '.bmp': 'image/bmp'}
FILTER = 'Images (*.png *.jpg *.jpeg *.gif *.webp *.svg *.bmp)'


def add_image_file(db, path, kind='image'):
    ext = os.path.splitext(path)[1].lower()
    mime = MIMES.get(ext)
    if not mime:
        raise ValueError(L('نوع الملف غير مدعوم.', 'Unsupported file type.'))
    data = open(path, 'rb').read()
    w = h = None
    if mime != 'image/svg+xml':
        img = QImage()
        if not img.loadFromData(data):
            raise ValueError(L('تعذّرت قراءة الصورة.', 'The image cannot be read.'))
        w, h = img.width(), img.height()
        if max(w, h) > 3000 and mime in ('image/png', 'image/bmp'):          # very large pictures are reduced
            img = img.scaled(3000, 3000, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            from PySide6.QtCore import QBuffer, QIODevice
            buf = QBuffer()
            buf.open(QIODevice.WriteOnly)
            img.save(buf, 'PNG')
            data, w, h = bytes(buf.data()), img.width(), img.height()
    return db.add_asset(os.path.basename(path), data, mime, kind, w, h)


def asset_pixmap(db, asset_id, size=96):
    a = db.asset(asset_id) if asset_id else None
    if not a:
        return QPixmap()
    if a['mime'] == 'image/svg+xml':
        from PySide6.QtGui import QPainter
        from PySide6.QtSvg import QSvgRenderer
        r = QSvgRenderer(QByteArray(a['data']))
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        r.render(p)
        p.end()
        return pm
    pm = QPixmap()
    pm.loadFromData(a['data'])
    return pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation) if not pm.isNull() else pm


class AssetGrid(QListWidget):
    picked = Signal(int)

    def __init__(self, db, kind=None):
        super().__init__()
        self.db, self.kind = db, kind
        self.setViewMode(QListView.IconMode)
        self.setIconSize(QSize(120, 90))
        self.setGridSize(QSize(150, 130))
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setWordWrap(True)
        self.itemDoubleClicked.connect(lambda it: self.picked.emit(it.data(Qt.UserRole)))
        a11y(self, L('الصور', 'Images'), L('انقر نقراً مزدوجاً لاختيار صورة', 'Double-click to choose an image'))
        self.reload()

    def reload(self):
        self.clear()
        for a in self.db.assets(self.kind):
            it = QListWidgetItem(QIcon(asset_pixmap(self.db, a['id'], 120)),
                                 f"{a['name']}\n{L(*KINDS.get(a['kind'], KINDS['image']))}"
                                 + (f" · {a['width']}×{a['height']}" if a['width'] else ''))
            it.setData(Qt.UserRole, a['id'])
            it.setToolTip(a['name'])
            self.addItem(it)

    def selected_ids(self):
        return [i.data(Qt.UserRole) for i in self.selectedItems()]


class AssetPicker(SizedDialog):
    """Choose an image from the library or add one; ``chosen`` is its id."""

    def __init__(self, parent, db, kind=None, title=None):
        super().__init__(parent)
        self.db, self.kind, self.chosen = db, kind, None
        self.setWindowTitle(title or L('اختيار صورة', 'Choose an image'))
        self.grid = AssetGrid(db, None)
        self.grid.picked.connect(self._pick)
        add = button(L('إضافة من ملف…', 'Add from a file…'), 'plus')
        add.clicked.connect(self._add)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(L('اختيار', 'Choose'))
        bb.button(QDialogButtonBox.Cancel).setText(L('إلغاء', 'Cancel'))
        name_buttons(bb)
        bb.accepted.connect(lambda: self._pick(self.grid.selected_ids()[0]) if self.grid.selected_ids() else None)
        bb.rejected.connect(self.reject)
        top = QHBoxLayout()
        top.addWidget(add)
        top.addStretch(1)
        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.grid, 1)
        lay.addWidget(bb)
        self.resize(820, 560)

    def _add(self):
        path, _ = QFileDialog.getOpenFileName(self, L('اختيار صورة', 'Choose an image'), '', FILTER)
        if not path:
            return
        try:
            aid = add_image_file(self.db, path, self.kind or 'image')
        except (OSError, ValueError) as e:
            error(self, str(e))
            return
        self._pick(aid)

    def _pick(self, aid):
        self.chosen = aid
        self.accept()


def pick_asset(parent, db, kind=None, title=None):
    d = AssetPicker(parent, db, kind, title)
    return d.chosen if d.exec() else None


class LibraryTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.db = ctx, ctx.db
        self.grid = AssetGrid(self.db)
        self.grid.itemSelectionChanged.connect(self._sel)
        self.count = QLabel()
        self.count.setProperty('chip', True)
        add = button(L('إضافة صور…', 'Add images…'), 'plus', 'primary')
        add.clicked.connect(self.add)
        self.as_logo = button(L('شعاراً للدليل الحالي', 'Logo of the current manual'), 'star')
        self.as_logo.clicked.connect(lambda: self._use('logo'))
        self.as_bg = button(L('خلفيةً لصفحات الدليل', 'Background of the manual pages'), 'layers')
        self.as_bg.clicked.connect(lambda: self._use('page_bg'))
        self.as_cover = button(L('خلفيةً للغلاف', 'Cover background'), 'image')
        self.as_cover.clicked.connect(lambda: self._use('cover_bg'))
        self.delete = button(L('حذف المحدد', 'Delete selected'), 'trash', 'danger')
        self.delete.clicked.connect(self.remove)
        self.sel_label = QLabel()
        self.sel_label.setProperty('muted', True)
        top = QHBoxLayout()
        top.addWidget(add)
        top.addWidget(self.count)
        top.addStretch(1)
        bar = QHBoxLayout()
        bar.addWidget(self.sel_label)
        bar.addStretch(1)
        for b in (self.as_logo, self.as_bg, self.as_cover, self.delete):
            bar.addWidget(b)
        box = card(L('مكتبة الصور', 'Image library'))
        bl = QVBoxLayout(box)
        bl.addWidget(hint(L('الشعارات والخلفيات والصور محفوظة داخل قاعدة البيانات، فتنتقل مع النسخة الاحتياطية. لا تُحذف صورة مستخدمة في دليل.',
                            'Logos, backgrounds and pictures are kept inside the database, so they travel with the backup. An image used in a manual cannot be deleted.')))
        bl.addLayout(top)
        bl.addWidget(self.grid, 1)
        bl.addLayout(bar)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 14)
        lay.addWidget(box, 1)
        self.reload()

    def reload(self):
        self.grid.reload()
        self.count.setText(L(f'الإجمالي: {self.grid.count()}', f'Total: {self.grid.count()}'))
        self._sel()

    def _sel(self):
        n = len(self.grid.selected_ids())
        self.sel_label.setText(L(f'المحدد: {n} من {self.grid.count()}', f'Selected: {n} of {self.grid.count()}'))
        for b in (self.as_logo, self.as_bg, self.as_cover):
            b.setEnabled(n == 1 and self.ctx.manual_id is not None)
        self.delete.setEnabled(n > 0)

    def add(self):
        paths, _ = QFileDialog.getOpenFileNames(self, L('اختيار صور', 'Choose images'), '', FILTER)
        bad = []
        for p in paths:
            try:
                add_image_file(self.db, p)
            except (OSError, ValueError):
                bad.append(os.path.basename(p))
        self.reload()
        if bad:
            error(self, L('تعذّرت إضافة: ', 'Could not add: ') + '، '.join(bad))

    def _use(self, what):
        ids = self.grid.selected_ids()
        mid = self.ctx.manual_id
        if len(ids) != 1 or not mid:
            return
        m = self.db.manual(mid)
        if what == 'logo':
            self.db.save_manual({'logo_id': ids[0]}, mid)
        else:
            lay = dict(m['layout'])
            if what == 'page_bg':
                lay['page_bg'] = dict(BG.of_page(lay) or BG.normalize({'opacity': 0.08}), asset_id=ids[0])
                lay['page_bg_id'] = None
            else:
                cv = {k: v for k, v in (lay.get('cover') or {}).items() if k not in ('bg_id', 'bg_opacity')}
                lay['cover'] = dict(cv, bg=dict(BG.of_cover(lay) or BG.normalize({}), asset_id=ids[0]))
            self.db.save_manual({'layout': lay}, mid)
        info(self, L('تم. تظهر الصورة في المعاينة والتصدير.', 'Done. The image shows in the preview and the exports.'))
        if self.ctx.window:
            self.ctx.window.manual_changed()

    def remove(self):
        ids = self.grid.selected_ids()
        if not ids or not confirm(self, L(f'حذف {len(ids)} صورة؟', f'Delete {len(ids)} image(s)?')):
            return
        kept = self.db.delete_assets(ids)
        self.reload()
        if kept:
            info(self, L(f'لم تُحذف {len(kept)} صورة لأنها مستخدمة في دليل.', f'{len(kept)} image(s) were kept because a manual uses them.'))

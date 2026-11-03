"""Choosing the manual's fonts: the program's own fonts (inside every file it makes) and every font installed in
Windows. The Arabic list holds only fonts that have Arabic letters. Typing in the box finds a font by any part of its
name, and each installed font is shown in its own shape."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QComboBox, QCompleter

from ..core.templates import FONTS
from .common import L

SYSTEM_ROLE = Qt.UserRole + 2           # True for a font installed in Windows (not one of the program's own)


def installed_families(arabic=False):
    """The font families installed on this computer, without the vertical copies («@…») Windows lists, and — for
    the Arabic list — only those with Arabic letters."""
    out = []
    for fam in QFontDatabase.families():
        if fam.startswith('@') or fam in FONTS or QFontDatabase.isPrivateFamily(fam):
            continue
        if arabic and QFontDatabase.WritingSystem.Arabic not in QFontDatabase.writingSystems(fam):
            continue
        out.append(fam)
    return sorted(set(out), key=str.casefold)


def is_installed(fam):
    return fam in FONTS or fam in QFontDatabase.families()


class FontPicker(QComboBox):
    """A font list: the program's fonts first, then the installed ones; a search by typing."""

    def __init__(self, arabic=False, parent=None, inherit=None):
        """``inherit``: the text of a first choice «as the manual» (its value is ''), for a font of one block."""
        super().__init__(parent)
        self.arabic = arabic
        self.inherit = inherit
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.setMaxVisibleItems(18)
        self.lineEdit().setPlaceholderText(L('اكتب جزءاً من اسم الخط للبحث', 'Type part of a font name to find it'))
        self.fill()
        comp = QCompleter(self.model(), self)
        comp.setFilterMode(Qt.MatchContains)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setCompletionMode(QCompleter.PopupCompletion)
        self.setCompleter(comp)
        comp.activated[str].connect(self._chosen_text)
        self.lineEdit().editingFinished.connect(self._typed)

    def fill(self):
        model = QStandardItemModel(self)

        def head(text):
            it = QStandardItem(text)
            it.setFlags(Qt.NoItemFlags)                     # a heading, not a choice
            f = QFont()
            f.setBold(True)
            it.setFont(f)
            model.appendRow(it)

        if self.inherit:
            it = QStandardItem(self.inherit)
            it.setData('', Qt.UserRole)
            it.setData(False, SYSTEM_ROLE)
            model.appendRow(it)
        head(L('خطوط البرنامج (تُضمَّن في كل ملف يُصدَّر)', "The program's fonts (inside every exported file)"))
        for fam in FONTS:
            it = QStandardItem(fam)
            it.setData(fam, Qt.UserRole)
            it.setData(False, SYSTEM_ROLE)
            model.appendRow(it)
        fams = installed_families(self.arabic)
        head(L(f'الخطوط المثبتة في ويندوز ({len(fams)})', f'Fonts installed in Windows ({len(fams)})'))
        for fam in fams:
            it = QStandardItem(fam)
            it.setData(fam, Qt.UserRole)
            it.setData(True, SYSTEM_ROLE)
            it.setFont(QFont(fam))                          # each name in its own shape
            model.appendRow(it)
        self.setModel(model)

    def _row_of(self, fam):
        for r in range(self.count()):
            if self.itemData(r) == fam:
                return r
        return -1

    def set_value(self, fam):
        r = self._row_of(fam if fam or not self.inherit else '')
        if r < 0 and fam:
            # a manual made on another computer: its font stays chosen and is marked, with nothing changed
            self.addItem(fam + L(' — غير مثبت على هذا الجهاز', ' — not installed on this computer'), fam)
            r = self.count() - 1
        self.setCurrentIndex(max(self._row_of('Tajawal'), 0) if r < 0 else r)

    def value(self):
        if self.inherit:
            return self.currentData() or ''
        return self.currentData() or 'Tajawal'

    def is_system(self):
        return bool(self.itemData(self.currentIndex(), SYSTEM_ROLE))

    def _chosen_text(self, text):
        r = self.findText(text, Qt.MatchExactly)
        if r >= 0:
            self.setCurrentIndex(r)

    def _typed(self):
        """A name typed in full (in any letter case) chooses that font; anything else returns to the chosen one."""
        text = self.lineEdit().text().strip()
        for r in range(self.count()):
            if self.itemData(r) and self.itemText(r).casefold() == text.casefold():
                self.setCurrentIndex(r)
                return
        self.lineEdit().setText(self.itemText(self.currentIndex()))

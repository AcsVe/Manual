"""Main window: the pages of the program, the overview of the open manual, the workflow users, the settings, the
licence dialog and the sign-in dialog."""
import os
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont, QGuiApplication
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QMainWindow, QPushButton, QTabWidget, QVBoxLayout, QWidget)

from .. import __version__
from ..core import license as lic
from ..core.db import ROLES, STATUSES
from .common import DataTable, L, confirm, error, info
from .compliance import ComplianceTab
from .design import DesignTab
from .editor import EditorTab
from .export import ExportTab
from .doctor import DoctorTab
from .library import LibraryTab
from .manuals import ManualsTab
from .org import OrgTab
from .theme import (SizedDialog, a11y, button, card, field, fit, fit_to_screen, form_grid, hint, icon, icon_button, ltr, muted,
                    name_buttons, scroll_page)


class LicenseDialog(SizedDialog):
    def __init__(self, parent, ctx):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(L('ترخيص الاستخدام', 'Licence'))
        st = ctx.license(refresh=True)
        self.state = QLabel(st.describe(L))
        self.state.setObjectName('status')
        self.state.setProperty('warn', st.mode not in ('licensed',))
        a11y(self.state, L('حالة الترخيص', 'Licence status'))
        mono = QFont('Consolas')
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSizeF(11)
        fp = ltr(QLineEdit(st.fingerprint), 240)
        fp.setReadOnly(True)
        fp.setFont(mono)
        fp.setAlignment(Qt.AlignCenter)
        copy_btn = icon_button('copy', L('نسخ البصمة', 'Copy the fingerprint'))
        copy_btn.clicked.connect(lambda: (QGuiApplication.clipboard().setText(st.fingerprint),
                                          copy_btn.setIcon(icon('check', '#166534'))))
        self.key = ltr(QLineEdit())
        self.key.setFont(mono)
        self.key.setPlaceholderText('YYYYMMDD:…')
        self.key.setMinimumWidth(300)
        act = button(L('تفعيل', 'Activate'), 'key', 'primary')
        act.clicked.connect(self.activate)
        g = form_grid()
        field(g, 0, 0, L('الحالة', 'Status'), self.state, 2)
        fp_row = QHBoxLayout()
        fp_row.addWidget(fp)
        fp_row.addWidget(copy_btn)
        fp_row.addStretch(1)
        a11y(fp, L('بصمة هذا الجهاز', 'This computer\'s fingerprint'))
        field(g, 1, 0, L('بصمة هذا الجهاز', 'This computer\'s fingerprint'), fp_row, 2)
        note = muted(L('أرسل البصمة إلى مزوّد البرنامج ليرسل لك مفتاح الترخيص لهذا الجهاز.',
                       'Send the fingerprint to the supplier to receive the licence key for this computer.'))
        note.setWordWrap(True)
        g.addWidget(note, 2, 1, 1, 2)
        field(g, 3, 0, L('مفتاح الترخيص', 'Licence key'), self.key, 2)
        g.setColumnStretch(1, 1)
        box = card()
        box.setLayout(g)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText(L('إغلاق', 'Close'))
        name_buttons(bb)
        bb.rejected.connect(self.reject)
        row2 = QHBoxLayout()
        row2.addWidget(act)
        row2.addStretch(1)
        row2.addWidget(bb)
        lay = QVBoxLayout(self)
        lay.addWidget(box)
        lay.addLayout(row2)
        fit_to_screen(self, max(640, self.sizeHint().width()), self.sizeHint().height())

    def activate(self):
        key = ''.join(self.key.text().split())
        ok, expired, exp = lic.check_license(key, self.ctx.license().fingerprint, date.today())
        if not ok:
            error(self, L('المفتاح غير صحيح لهذا الجهاز. تأكد من نسخه كاملاً، وأنه صادر لبصمة هذا الجهاز.',
                          'The key is not valid for this computer. Make sure it is copied in full and issued for this fingerprint.'))
            return
        if expired:
            error(self, L(f'هذا المفتاح انتهى في {exp}.', f'This key expired on {exp}.'))
            return
        lic.save_key(self.ctx.data_dir, key)
        st = self.ctx.license(refresh=True)
        self.state.setText(st.describe(L))
        self.state.setProperty('warn', False)
        self.state.style().polish(self.state)
        info(self, L('تم تفعيل الترخيص.', 'The licence is active.'))
        if self.ctx.window:
            self.ctx.window.update_title()


class LoginDialog(SizedDialog):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle(L('تسجيل الدخول', 'Sign in'))
        self.user = QLineEdit()
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        g = form_grid()
        field(g, 0, 0, L('اسم المستخدم', 'Username'), self.user)
        field(g, 1, 0, L('كلمة المرور', 'Password'), self.pw)
        g.setColumnStretch(1, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(L('دخول', 'Sign in'))
        bb.button(QDialogButtonBox.Cancel).setText(L('إغلاق', 'Close'))
        name_buttons(bb)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(hint(L('سير العمل مفعّل: لكل مستخدم دوره (معِدّ، مراجِع، معتمِد، مدير).',
                             'The workflow is on: every user has a role (author, reviewer, approver, administrator).')))
        lay.addLayout(g)
        lay.addWidget(bb)
        self.resize(420, 200)

    def _ok(self):
        u = self.ctx.db.check_user(self.user.text(), self.pw.text())
        if not u:
            error(self, L('اسم المستخدم أو كلمة المرور غير صحيحة.', 'Wrong username or password.'))
            return
        self.ctx.user = u
        self.ctx.db.audit('login', user=u['username'])
        self.accept()


class UserDialog(SizedDialog):
    def __init__(self, parent, db, user=None):
        super().__init__(parent)
        self.db, self.u = db, user or {}
        self.setWindowTitle(L('مستخدم', 'User'))
        self.name = QLineEdit(self.u.get('name') or '')
        self.username = ltr(QLineEdit(self.u.get('username') or ''), 220)
        self.pw = ltr(QLineEdit(), 220)
        self.pw.setEchoMode(QLineEdit.Password)
        self.pw.setPlaceholderText(L('اتركها فارغة لإبقائها', 'Leave empty to keep it') if user else '')
        self.role = QComboBox()
        for k, (ar, en) in ROLES.items():
            self.role.addItem(L(ar, en), k)
        self.role.setCurrentIndex(max(0, self.role.findData(self.u.get('role') or 'author')))
        fit(self.role, 200)
        g = form_grid()
        field(g, 0, 0, L('الاسم *', 'Name *'), self.name)
        field(g, 1, 0, L('اسم المستخدم *', 'Username *'), self.username)
        field(g, 2, 0, L('كلمة المرور', 'Password') + ('' if user else ' *'), self.pw)
        field(g, 3, 0, L('الدور', 'Role'), self.role)
        g.setColumnStretch(1, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText(L('حفظ', 'Save'))
        bb.button(QDialogButtonBox.Cancel).setText(L('إلغاء', 'Cancel'))
        name_buttons(bb)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(g)
        lay.addWidget(bb)
        self.resize(460, 260)

    def _save(self):
        if not self.name.text().strip() or not self.username.text().strip():
            error(self, L('الاسم واسم المستخدم مطلوبان.', 'Name and username are required.'))
            return
        if not self.u and len(self.pw.text()) < 6:
            error(self, L('كلمة المرور 6 أحرف على الأقل.', 'The password needs at least 6 characters.'))
            return
        if self.pw.text() and len(self.pw.text()) < 6:
            error(self, L('كلمة المرور 6 أحرف على الأقل.', 'The password needs at least 6 characters.'))
            return
        other = next((u for u in self.db.users() if u['username'] == self.username.text().strip() and u['id'] != self.u.get('id')), None)
        if other:
            error(self, L('اسم المستخدم مستخدم لحساب آخر.', 'The username belongs to another account.'))
            return
        self.db.save_user({'name': self.name.text().strip(), 'username': self.username.text().strip(),
                           'password': self.pw.text(), 'role': self.role.currentData()}, self.u.get('id'))
        self.accept()


class UsersTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.db = ctx, ctx.db
        self.enable = QCheckBox(L('تفعيل سير العمل (إعداد ← مراجعة ← اعتماد) وتسجيل الدخول', 'Turn on the workflow (prepare → review → approve) and sign-in'))
        self.enable.setChecked(ctx.workflow)
        self.enable.toggled.connect(self._toggle)
        new = button(L('مستخدم جديد…', 'New user…'), 'plus', 'primary')
        new.clicked.connect(lambda: self.edit(None))
        self.table = DataTable(
            [(L('الاسم', 'Name'), 'text'), (L('اسم المستخدم', 'Username'), 'text'), (L('الدور', 'Role'), 'select'),
             (L('الحالة', 'Status'), 'select')],
            [(L('تفعيل', 'Activate'), lambda ids: self._active(ids, True), False, 'on'),
             (L('تعطيل', 'Deactivate'), lambda ids: self._active(ids, False), False, 'off'),
             (L('حذف', 'Delete'), self.delete, True, 'trash')], export_name='users', title=L('المستخدمون', 'Users'))
        self.table.activated.connect(self.edit)
        box = card(L('المستخدمون وسير العمل', 'Users & workflow'))
        bl = QVBoxLayout(box)
        bl.addWidget(hint(L('عند التفعيل: يُطلب تسجيل الدخول، ويعمل كل مستخدم حسب دوره — المعِدّ يكتب ويرسل للمراجعة، والمراجِع يعيد للمسودة أو يمرّر، '
                            'والمعتمِد يعتمد. تحمل الأقسام غير المعتمدة علامة «مسودة»، ويمكن تصدير المعتمد فقط. عند التعطيل: مستخدم واحد بلا أدوار.',
                            'When on: sign-in is required and every user works by role — the author writes and sends for review, the reviewer returns to draft or passes it on, '
                            'the approver approves. Sections not approved carry a «draft» mark, and the approved ones alone can be exported. When off: one user, no roles.')))
        bl.addWidget(self.enable)
        top = QHBoxLayout()
        top.addWidget(new)
        top.addStretch(1)
        bl.addLayout(top)
        bl.addWidget(self.table, 1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 14)
        lay.addWidget(box, 1)
        self.reload()

    def reload(self):
        self.table.set_rows([(u['id'], [u['name'], u['username'], L(*ROLES.get(u['role'], ('', ''))),
                                        L('مفعّل', 'Active') if u['is_active'] else L('معطّل', 'Inactive')]) for u in self.db.users()])
        self.setEnabled(self.ctx.can('manage'))

    def _toggle(self, on):
        if on and not any(u['role'] == 'admin' and u['is_active'] for u in self.db.users()):
            info(self, L('أضف أولاً مستخدماً بدور «مدير» حتى لا تُقفل البرنامج على نفسك.',
                         'First add a user with the «Administrator» role so that you do not lock yourself out.'))
            self.enable.blockSignals(True)
            self.enable.setChecked(False)
            self.enable.blockSignals(False)
            self.edit(None, role='admin')
            return
        self.db.set('workflow', '1' if on else '0')
        if on and not self.ctx.user:
            admins = [u for u in self.db.users() if u['role'] == 'admin' and u['is_active']]
            self.ctx.user = admins[0] if admins else None
        if not on:
            self.ctx.user = None
        self.ctx.window.manual_changed()
        info(self, L('تم. يُطلب تسجيل الدخول عند فتح البرنامج.', 'Done. Sign-in is required when the program opens.') if on
             else L('أُوقف سير العمل.', 'The workflow is off.'))

    def edit(self, uid, role=None):
        u = next((x for x in self.db.users() if x['id'] == uid), None)
        d = UserDialog(self, self.db, u)
        if role:
            d.role.setCurrentIndex(d.role.findData(role))
        if d.exec():
            self.reload()

    def _active(self, ids, on):
        cur = (self.ctx.user or {}).get('id')
        ids = [i for i in ids if on or i != cur]
        self.db.set_active('users', ids, on)
        self.reload()

    def delete(self, ids):
        if not ids or not confirm(self, L(f'حذف {len(ids)} مستخدم؟', f'Delete {len(ids)} user(s)?')):
            return
        kept = self.db.delete_users(ids, (self.ctx.user or {}).get('id'))
        self.reload()
        if kept:
            info(self, L('لا يُحذف حسابك الحالي ولا آخر مدير. التعطيل بديل.', 'Your own account and the last administrator are not deleted. Deactivating is an alternative.'))


class SettingsTab(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.db = ctx, ctx.db
        self.lang = QComboBox()
        self.lang.addItem('العربية', 'ar')
        self.lang.addItem('English', 'en')
        self.lang.setCurrentIndex(max(0, self.lang.findData(self.db.get('lang', 'ar'))))
        fit(self.lang, 200)
        self.author = QLineEdit(self.db.get('author_name') or '')
        self.author.setPlaceholderText(L('يظهر في سجل التغييرات عند عدم تفعيل سير العمل', 'Shown in the change history when the workflow is off'))
        g0 = form_grid()
        field(g0, 0, 0, L('لغة البرنامج', 'Language'), self.lang)
        field(g0, 1, 0, L('اسمك', 'Your name'), self.author)
        g0.setColumnStretch(1, 1)
        g_gen = card(L('عام', 'General'))
        g_gen.setLayout(g0)
        self.backup_dir = ltr(QLineEdit(self.db.get('backup_dir') or os.path.join(ctx.data_dir, 'backups')))
        pick = icon_button('folder', L('اختيار مجلد النسخ الاحتياطية', 'Choose the backup folder'))
        pick.clicked.connect(self._pick)
        bnow = button(L('نسخة احتياطية الآن', 'Back up now'), 'save')
        bnow.clicked.connect(self.backup_now)
        rest = button(L('استرجاع نسخة…', 'Restore a backup…'), 'reset')
        rest.clicked.connect(self.restore)
        bl = QHBoxLayout()
        bl.addWidget(self.backup_dir, 1)
        bl.addWidget(pick)
        a11y(self.backup_dir, L('مجلد النسخ الاحتياطية', 'Backup folder'))
        bl2 = QHBoxLayout()
        bl2.addWidget(bnow)
        bl2.addWidget(rest)
        bl2.addStretch(1)
        gb = form_grid()
        field(gb, 0, 0, L('المجلد', 'Folder'), bl)
        gb.addLayout(bl2, 1, 1)
        data = muted(L(f'مجلد البيانات: {ctx.data_dir}', f'Data folder: {ctx.data_dir}'))
        data.setTextInteractionFlags(Qt.TextSelectableByMouse)
        gb.addWidget(data, 2, 1)
        gb.setColumnStretch(1, 1)
        g_bk = card(L('النسخ الاحتياطي (يومياً عند فتح البرنامج، وتُحفظ آخر 30 نسخة)', 'Backups (daily when the program opens; the last 30 are kept)'))
        g_bk.setLayout(gb)
        init_btn = button(L('تهيئة النظام…', 'Initialise the system…'), 'reset')
        init_btn.clicked.connect(self.initialise)
        gi = QVBoxLayout()
        gi.addWidget(hint(L('تحذف الملفات المؤقتة التي يصنعها البرنامج أثناء العمل (صفحات المعاينة والتصدير، وسجلات '
                            'الأخطاء، وذاكرة المعاينة)، وتغلق النوافذ المعلّقة، وتفحص ملف البيانات وترتّبه. لا تمسّ '
                            'الأدلة ولا الصور ولا النسخ الاحتياطية ولا الترخيص ولا الإعدادات. يُنصح بها عند بطء '
                            'البرنامج أو ظهور معاينة قديمة.',
                            'Deletes the temporary files the program makes while it works (the preview and export pages, '
                            'the error logs, the preview store), closes windows left open, and checks and tidies the data '
                            'file. The manuals, pictures, backups, licence and settings are not touched. Useful when the '
                            'program is slow or the preview shows an old copy.')))
        ir = QHBoxLayout()
        ir.addWidget(init_btn)
        ir.addStretch(1)
        gi.addLayout(ir)
        g_init = card(L('تهيئة النظام', 'System initialisation'))
        g_init.setLayout(gi)
        lic_btn = button(L('ترخيص الاستخدام…', 'Licence…'), 'key')
        lic_btn.clicked.connect(lambda: LicenseDialog(self, ctx).exec())
        save = button(L('حفظ الإعدادات', 'Save settings'), 'save', 'primary')
        save.clicked.connect(self.save)
        inner = QWidget()
        inner.setMaximumWidth(900)
        il = QVBoxLayout(inner)
        il.setContentsMargins(0, 0, 0, 0)
        il.addWidget(g_gen)
        il.addWidget(g_bk)
        il.addWidget(g_init)
        row = QHBoxLayout()
        row.addWidget(save)
        row.addWidget(lic_btn)
        row.addStretch(1)
        row.addWidget(muted(L(f'الإصدار {__version__}', f'Version {__version__}')))
        il.addLayout(row)
        il.addStretch(1)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 14)
        lay.addWidget(inner, 1)

    def _pick(self):
        d = QFileDialog.getExistingDirectory(self, L('مجلد النسخ الاحتياطية', 'Backup folder'), self.backup_dir.text())
        if d:
            self.backup_dir.setText(d)

    def save(self):
        old = self.db.get('lang', 'ar')
        self.db.set('lang', self.lang.currentData())
        self.db.set('author_name', self.author.text().strip())
        self.db.set('backup_dir', self.backup_dir.text().strip())
        info(self, L('تُطبَّق اللغة الجديدة عند إعادة فتح البرنامج.', 'The new language applies when the program is reopened.')
             if old != self.lang.currentData() else L('حُفظت الإعدادات.', 'Settings saved.'))

    def backup_now(self):
        try:
            path = self.db.backup(self.backup_dir.text().strip() or os.path.join(self.ctx.data_dir, 'backups'))
        except OSError as e:
            error(self, str(e))
            return
        self.db.set('last_backup', date.today().isoformat())
        info(self, L(f'حُفظت النسخة:\n{path}', f'Backup saved:\n{path}'))

    def restore(self):
        path, _ = QFileDialog.getOpenFileName(self, L('اختر نسخة احتياطية', 'Choose a backup'), self.backup_dir.text(), 'Backup (*.db)')
        if not path or not confirm(self, L('ستُستبدل البيانات الحالية بهذه النسخة (تُحفظ نسخة من الحالية أولاً). متابعة؟',
                                            'The current data will be replaced by this backup (a copy of it is saved first). Continue?')):
            return
        try:
            safety = self.db.restore(path)
        except Exception as e:  # noqa: BLE001
            error(self, L('ليست نسخة احتياطية صالحة لهذا البرنامج.', 'Not a valid backup of this program.') + f'\n{e}')
            return
        info(self, L(f'تم الاسترجاع. نسخة البيانات السابقة:\n{safety}', f'Restored. The previous data was saved to:\n{safety}'))
        self.ctx.window.manual_changed()

    def initialise(self):
        if not confirm(self, L('ستُحذف الملفات المؤقتة وسجلات الأخطاء، وتُغلق النوافذ المفتوحة، ويُفحص ملف البيانات. '
                               'يُحفظ ما تكتبه في المحرر أولاً، ولا تُمسّ الأدلة ولا النسخ الاحتياطية. متابعة؟',
                               'The temporary files and error logs will be deleted, open windows closed and the data file '
                               'checked. What is being written in the editor is saved first; the manuals and backups are not '
                               'touched. Continue?')):
            return
        from PySide6.QtWidgets import QApplication, QDialog
        from ..core import cleanup
        win = self.ctx.window
        if win is not None:
            if win.editor.dirty:
                win.editor.save(quiet=True)
            win.editor.preview.inspector.hide()
        for w in QApplication.topLevelWidgets():          # windows left open behind (a form never closed)
            if isinstance(w, QDialog) and w.isVisible():
                w.reject()
        try:
            from PySide6.QtWebEngineCore import QWebEngineProfile
            QWebEngineProfile.defaultProfile().clearHttpCache()
        except ImportError:
            pass
        try:
            done = cleanup.initialise(self.db, self.ctx.data_dir)
        except Exception as e:  # noqa: BLE001 — reported, never hidden
            error(self, L('تعذّرت التهيئة:', 'The initialisation failed:') + f'\n{e}')
            return
        self.db.audit('system_initialised', files=done['files'], bytes=done['bytes'])
        if win is not None:
            win.editor.preview._digest = None              # the preview is laid out again from a fresh page
            win.manual_changed()
        text = L(f'تمت التهيئة: حُذف {done["files"]} من الملفات والمجلدات المؤقتة، ورُتِّب ملف البيانات.',
                 f'Done: {done["files"]} temporary file(s) and folder(s) deleted, and the data file tidied.')
        if done['kept']:
            text += '\n' + L(f'بقي {done["kept"]} ملفاً قيد الاستعمال، ويُحذف في التهيئة القادمة.',
                             f'{done["kept"]} file(s) in use were left; they go at the next initialisation.')
        if not done['db_ok']:
            error(self, text + '\n\n' + L('وُجد خلل في ملف البيانات، فلم يُرتَّب. استرجع آخر نسخة احتياطية من الأعلى.',
                                          'The data file has a fault, so it was not tidied. Restore the latest backup above.'))
            return
        info(self, text)


class HomeTab(QWidget):
    """The open manual at a glance (every number opens the list behind it) and the list of manuals."""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.overview = QHBoxLayout()
        self.ov_box = card(L('الدليل المفتوح', 'Open manual'))
        ol = QVBoxLayout(self.ov_box)
        self.ov_title = QLabel()
        self.ov_title.setStyleSheet('font-size:15px;font-weight:700;color:#0847B0')
        ol.addWidget(self.ov_title)
        ol.addLayout(self.overview)
        self.manuals = ManualsTab(ctx)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        wrap = QVBoxLayout()
        wrap.setContentsMargins(14, 0, 14, 0)
        wrap.addWidget(self.ov_box)
        lay.addLayout(wrap)
        lay.addWidget(self.manuals, 1)

    def reload(self):
        self.manuals.reload()
        while self.overview.count():
            it = self.overview.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        mid = self.ctx.manual_id
        self.ov_box.setVisible(bool(mid))
        if not mid:
            return
        db = self.ctx.db
        m = db.manual(mid)
        st = db.stats(mid)
        self.ov_title.setText(m['title_ar'] or m['title_en'] or '')
        w = self.ctx.window
        chips = [(L(f'الأقسام ({st["sections"]})', f'Sections ({st["sections"]})'), lambda: w.open_editor()),
                 (L(f'السياسات ({st["policies"]})', f'Policies ({st["policies"]})'), lambda: w.open_editor())]
        if self.ctx.workflow:
            for k, (ar, en) in STATUSES.items():
                if k != 'archived':
                    chips.append((f'{L(ar, en)} ({st["status"].get(k, 0)})', lambda: w.open_editor()))
        chips += [(L(f'مراجعات مستحقة ({st["due_sections"] + st["due_controls"]})', f'Reviews due ({st["due_sections"] + st["due_controls"]})'),
                   lambda: w.show_page(w.compliance)),
                  (L(f'الوظائف في الهيكل ({st["units"]})', f'Positions in the chart ({st["units"]})'), lambda: w.show_page(w.org)),
                  (L(f'بنود الالتزام ({st["controls"]})', f'Compliance items ({st["controls"]})'), lambda: w.show_page(w.compliance))]
        for text, fn in chips:
            b = QPushButton(text)
            b.setProperty('ghost', True)
            b.setCursor(Qt.PointingHandCursor)
            a11y(b, text)
            b.clicked.connect(fn)
            self.overview.addWidget(b)
        self.overview.addStretch(1)


class MainWindow(QMainWindow):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        ctx.window = self
        self.setAcceptDrops(True)              # a file dropped on the window opens as a new manual
        self.tabs = QTabWidget()
        a11y(self.tabs, L('أقسام البرنامج', 'Program sections'))
        self.home = HomeTab(ctx)
        self.editor = EditorTab(ctx)
        self.org = OrgTab(ctx)
        self.compliance = ComplianceTab(ctx)
        self.design = DesignTab(ctx)
        self.library = LibraryTab(ctx)
        self.export = ExportTab(ctx)
        self.doctor = DoctorTab(ctx)
        self.users = UsersTab(ctx)
        self.settings = SettingsTab(ctx)
        self._areas = {}
        for wdg, ic, ar, en, scroll in ((self.home, 'book', 'الأدلة', 'Manuals', False),
                                        (self.editor, 'edit', 'المحرر', 'Editor', False),
                                        (self.org, 'org', 'الهيكل التنظيمي', 'Organisational chart', False),
                                        (self.compliance, 'shield', 'سجل الالتزام', 'Compliance register', False),
                                        (self.design, 'palette', 'التصميم', 'Design', True),
                                        (self.library, 'image', 'الصور', 'Images', False),
                                        (self.doctor, 'shield', 'المدقق', 'Checker', False),
                                        (self.export, 'export', 'التصدير', 'Export', True),
                                        (self.users, 'users', 'المستخدمون وسير العمل', 'Users & workflow', False),
                                        (self.settings, 'calibrate', 'الإعدادات', 'Settings', True)):
            a11y(wdg, L(ar, en))
            self._areas[wdg] = scroll_page(wdg) if scroll else wdg
            self.tabs.addTab(self._areas[wdg], icon(ic, '#64748b'), L(ar, en))
        self.tabs.setUsesScrollButtons(True)
        self.setCentralWidget(self.tabs)
        self.tabs.currentChanged.connect(self._tab_changed)
        lic_act = QAction(L('الترخيص', 'Licence'), self)
        lic_act.triggered.connect(lambda: LicenseDialog(self, ctx).exec())
        self.menuBar().addAction(lic_act)
        self.update_title()
        self.manual_changed()
        fit_to_screen(self, 1440, 900)

    def update_title(self):
        st = self.ctx.license(refresh=True)
        who = f' — {self.ctx.user["name"]} ({self.ctx.role_label(L)})' if self.ctx.user else ''
        self.setWindowTitle(L('منشئ الأدلة المؤسسية', 'Manual Builder') + f' {__version__}{who} — ' + st.describe(L))

    def show_page(self, page):
        self.tabs.setCurrentWidget(self._areas[page])

    def open_doctor(self, run=False):
        self.doctor.load_manual(self.ctx.manual_id)
        self.show_page(self.doctor)
        if run:
            self.doctor.run()

    @staticmethod
    def _dropped_files(e):
        from ..core.importer import OPENABLE
        if not e.mimeData().hasUrls():
            return []
        return [u.toLocalFile() for u in e.mimeData().urls()
                if u.isLocalFile() and os.path.splitext(u.toLocalFile())[1].lower() in OPENABLE]

    def dragEnterEvent(self, e):           # noqa: N802 (Qt name)
        if self._dropped_files(e):
            e.acceptProposedAction()

    def dropEvent(self, e):                # noqa: N802 (Qt name)
        files = self._dropped_files(e)
        if files:
            e.acceptProposedAction()
            self.open_files(files)

    def open_files(self, files):
        """Files from the desktop, «Open with» or a drop: each becomes a new manual (the last one stays open)."""
        from .manuals import open_file
        self.raise_()
        self.activateWindow()
        for f in files:
            if os.path.isfile(f):
                open_file(self, self.ctx, f)
        self.home.reload()

    def open_design(self, tab='page'):
        self.show_page(self.design)
        self.design.open_tab(tab)

    def open_in_editor(self, what):
        """A click on the design preview: the block or section opens in the editor."""
        self.show_page(self.editor)
        self.editor.picked(what)

    def open_editor(self):
        self.manual_changed()
        self.show_page(self.editor)

    def manual_changed(self):
        mid = self.ctx.manual_id
        self.home.reload()
        self.editor.load_manual(mid)
        self.org.load_manual(mid)
        self.compliance.load_manual(mid)
        self.design.load_manual(mid)
        self.export.load_manual(mid)
        self.doctor.load_manual(mid)
        self.library.reload()
        self.users.reload()
        self.update_title()

    def _tab_changed(self, i):
        w = self.tabs.widget(i)
        if w is self._areas[self.home]:
            self.home.reload()
        elif w is self._areas[self.export]:
            self.export.load_manual(self.ctx.manual_id)
        elif w is self._areas[self.editor] and self.editor.mid:
            self.editor.refresh_preview(force=True)

    def closeEvent(self, e):
        if self.editor.dirty:
            self.editor.save(quiet=True)
        super().closeEvent(e)

    def showEvent(self, e):
        from .theme import size_tree
        size_tree(self)
        super().showEvent(e)
        if not self.ctx.db.manuals():
            info(self, L('مرحباً! ابدأ بإنشاء دليلك الأول: اختر هيكلاً مبدئياً (دليل مؤسسي كامل، أو سياسات، أو دليل تعريفي) أو استورد ملف Word أو PDF موجوداً.',
                         'Welcome! Start by creating your first manual: choose a starting structure (complete institutional manual, policies or handbook) or import an existing Word or PDF file.'))
            self.home.manuals.new()
        st = self.ctx.license()
        if st.mode in ('expired', 'trial_over'):
            self.ctx.license_blocked(self)

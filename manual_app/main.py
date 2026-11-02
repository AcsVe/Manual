"""ManualBuilder — entry point. Data folder: %ProgramData%\\ManualBuilder on Windows (shared by the PC's users;
the installer gives users write access), ~/.manual_builder elsewhere; MANUAL_DATA overrides it."""
import os
import sys
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__
from .core import license as lic
from .core.db import ROLES, Database


def data_dir():
    if os.environ.get('MANUAL_DATA'):
        return os.environ['MANUAL_DATA']
    if sys.platform.startswith('win'):
        base = os.environ.get('PROGRAMDATA') or os.environ.get('APPDATA') or os.path.expanduser('~')
        return os.path.join(base, 'ManualBuilder')
    return os.path.join(os.path.expanduser('~'), '.manual_builder')


def resource(name):
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, 'assets', name)


# what each role may do when the workflow is on
CAN = {
    'admin': {'edit', 'review', 'approve', 'manage', 'export'},
    'author': {'edit', 'export'},
    'reviewer': {'edit', 'review', 'export'},
    'approver': {'review', 'approve', 'export'},
    'viewer': {'export'},
}


class AppContext:
    def __init__(self, folder):
        self.data_dir = folder
        os.makedirs(folder, exist_ok=True)
        self.db = Database(os.path.join(folder, 'manuals.db'))
        self.window = None
        self.user = None                 # the signed-in user when the workflow is on
        self._license = None

    # ── current manual ───────────────────────────────────────────────
    @property
    def manual_id(self):
        v = self.db.get('current_manual')
        if v and self.db.manual(int(v)):
            return int(v)
        ms = self.db.manuals(active_only=True)
        return ms[0]['id'] if ms else None

    @manual_id.setter
    def manual_id(self, v):
        self.db.set('current_manual', v)

    # ── workflow ─────────────────────────────────────────────────────
    @property
    def workflow(self):
        return self.db.get('workflow', '0') == '1'

    def can(self, what):
        if not self.workflow or not self.user:
            return True
        return what in CAN.get(self.user['role'], set())

    def user_name(self):
        return (self.user or {}).get('name') or self.db.get('author_name') or ''

    def role_label(self, L):
        if not self.user:
            return ''
        ar, en = ROLES.get(self.user['role'], ('', ''))
        return L(ar, en)

    # ── licence ──────────────────────────────────────────────────────
    def license(self, refresh=False):
        if refresh or self._license is None:
            self._license = lic.current_state(self.data_dir)
        return self._license

    def license_blocked(self, parent):
        from .ui.common import L
        from .ui.main_window import LicenseDialog
        st = self.license(refresh=True)
        QMessageBox.warning(parent, L('الترخيص', 'Licence'),
                            st.describe(L) + '\n\n' + L('أدخل مفتاح الترخيص لهذا الجهاز لمتابعة التصدير. البيانات محفوظة ويمكن تعديلها وعرضها.',
                                                        'Enter the licence key for this computer to continue exporting. Your data is kept and can be edited and viewed.'))
        LicenseDialog(parent, self).exec()

    def daily_backup(self):
        today = date.today().isoformat()
        if self.db.get('last_backup') == today:
            return
        try:
            self.db.backup(self.db.get('backup_dir') or os.path.join(self.data_dir, 'backups'))
            self.db.set('last_backup', today)
        except OSError:
            pass


def _web_engine_flags():
    """The browser engine draws the preview and the PDF; on machines without working graphics drivers it falls back
    to software drawing instead of showing a blank page."""
    os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu-compositing')
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts, True)


def selftest(out):
    """Used by the build: a sample manual exported to PDF, Word and the interactive copy with a throw-away database."""
    import tempfile
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    _web_engine_flags()
    QApplication.instance() or QApplication([])
    from .core import templates
    from .core.docx_export import export_docx
    from .core.html import build_html
    from .core.pdf import count_pages, make_pdf_blocking, page_size_mm
    folder = tempfile.mkdtemp(prefix='manual-selftest-')
    ctx = AppContext(folder)
    mid = templates.create_from_starter(ctx.db, 'institutional', {'title_ar': 'دليل تجريبي', 'title_en': 'Test manual',
                                                                  'issue_date': '2026-01-01'})
    pdf = os.path.join(folder, 'test.pdf')
    ok, msg = make_pdf_blocking(build_html(ctx.db, mid, 'print'), pdf, page_size_mm(ctx.db.manual(mid)), 300)
    pages = count_pages(pdf) if ok else 0
    docx = export_docx(ctx.db, mid, os.path.join(folder, 'test.docx'))
    web = build_html(ctx.db, mid, 'web')
    ok = ok and pages >= 5 and os.path.getsize(docx) > 5000 and 'دليل تجريبي' in web
    with open(out, 'w', encoding='utf-8') as f:
        f.write(('ok ' if ok else 'FAILED ') + f'pages={pages} {msg} ' + lic.machine_fingerprint(folder) + '\n')
    ctx.db.close()
    return 0 if ok else 1


INSTANCE = 'ManualBuilder-' + (os.environ.get('USERNAME') or os.environ.get('USER') or 'user')


def _send_to_running(files):
    """When the program is already open, hands it the files to open and returns True."""
    from PySide6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(INSTANCE)
    if not sock.waitForConnected(400):
        return False
    sock.write(('\n'.join(files)).encode('utf-8'))
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def _listen(window):
    """Receives the files a second start of the program was asked to open."""
    from PySide6.QtNetwork import QLocalServer
    QLocalServer.removeServer(INSTANCE)
    server = QLocalServer(window)
    if not server.listen(INSTANCE):
        return None

    def take():
        conn = server.nextPendingConnection()
        if conn is None:
            return

        def read():
            data = bytes(conn.readAll()).decode('utf-8', 'ignore')
            files = [f for f in data.splitlines() if f.strip()]
            if files:
                window.showNormal()
                window.open_files(files)
        conn.readyRead.connect(read)
        conn.disconnected.connect(conn.deleteLater)
    server.newConnection.connect(take)
    return server


def main(argv=None):
    argv = argv if argv is not None else sys.argv
    if '--fingerprint' in argv:
        print(lic.machine_fingerprint(data_dir()))
        return 0
    if '--selftest' in argv:
        return selftest(argv[argv.index('--selftest') + 1] if len(argv) > argv.index('--selftest') + 1 else 'selftest.txt')
    files = [os.path.abspath(a) for a in argv[1:] if not a.startswith('-') and os.path.isfile(a)]
    _web_engine_flags()
    app = QApplication(argv)
    if files and _send_to_running(files):
        return 0                           # the program already open takes the file(s)
    app.setApplicationName('ManualBuilder')
    app.setApplicationVersion(__version__)
    if os.path.isfile(resource('icon.ico')):
        app.setWindowIcon(QIcon(resource('icon.ico')))
    try:
        ctx = AppContext(data_dir())
    except Exception as e:  # noqa: BLE001 — folder not writable, damaged database…
        QMessageBox.critical(None, 'ManualBuilder', f'تعذّر فتح مجلد البيانات / Cannot open the data folder:\n{data_dir()}\n\n{e}')
        return 1
    from .ui.common import set_lang
    set_lang(ctx.db.get('lang', 'ar'))
    if ctx.db.get('lang', 'ar') != 'en':
        app.setLayoutDirection(Qt.RightToLeft)
    from .ui.theme import apply_theme
    apply_theme(app)
    ctx.daily_backup()
    if ctx.workflow and ctx.db.users():
        from .ui.main_window import LoginDialog
        dlg = LoginDialog(ctx)
        if not dlg.exec():
            return 0
    from .ui.main_window import MainWindow
    w = MainWindow(ctx)
    w.show()
    server = _listen(w)                    # noqa: F841 — kept alive while the window is open
    if files:
        from PySide6.QtCore import QTimer
        QTimer.singleShot(400, lambda: w.open_files(files))
    code = app.exec()
    ctx.db.close()
    return code


if __name__ == '__main__':
    sys.exit(main())

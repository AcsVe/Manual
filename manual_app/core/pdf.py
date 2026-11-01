"""PDF from the print HTML: the built-in browser engine (Qt WebEngine) lays the pages out with Paged.js and prints
them at the manual's exact page size. Also used to write the HTML of the live preview."""
import os
import tempfile

from PySide6.QtCore import QEventLoop, QMarginsF, QObject, QSizeF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QPageLayout, QPageSize

from .templates import PAGE_SIZES, layout_with_defaults


def page_size_mm(manual):
    lay = layout_with_defaults(manual['layout'])
    w, h = PAGE_SIZES.get(lay['page_size'], PAGE_SIZES['A4'])
    return (h, w) if lay['orientation'] == 'landscape' else (w, h)


def write_html(html, folder=None, name='manual.html'):
    folder = folder or os.path.join(tempfile.gettempdir(), 'ManualBuilder')
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    return path


def settings_for(page):
    from PySide6.QtWebEngineCore import QWebEngineSettings
    s = page.settings()
    s.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
    s.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, False)
    s.setAttribute(QWebEngineSettings.PrintElementBackgrounds, True)


class PdfJob(QObject):
    """Loads an HTML file, waits until Paged.js has laid out every page, prints it to ``pdf_path``.
    Signals: progress(pages so far), finished(ok, message)."""
    progress = Signal(int)
    finished = Signal(bool, str)

    def __init__(self, html_path, pdf_path, size_mm, timeout_s=900):
        super().__init__()
        from PySide6.QtWebEngineWidgets import QWebEngineView
        self.html_path, self.pdf_path, self.size_mm = html_path, pdf_path, size_mm
        self.view = QWebEngineView()
        self.view.setAttribute(Qt.WA_DontShowOnScreen, True)     # laid out and painted, never on screen
        self.view.resize(1400, 1000)
        settings_for(self.view.page())
        self.view.page().pdfPrintingFinished.connect(self._printed)
        self.view.loadFinished.connect(self._loaded)
        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._poll)
        self._deadline = QTimer(self)
        self._deadline.setSingleShot(True)
        self._deadline.setInterval(timeout_s * 1000)
        self._deadline.timeout.connect(lambda: self._done(False, 'timeout'))
        self._finished = False

    def start(self):
        self.view.show()
        self._deadline.start()
        self.view.load(QUrl.fromLocalFile(self.html_path))

    def _loaded(self, ok):
        if not ok:
            self._done(False, 'load failed')
            return
        self._timer.start()

    def _poll(self):
        self.view.page().runJavaScript(
            "[window.__pages||0, document.querySelectorAll('.pagedjs_page').length].join(',')", 0, self._state)

    def _state(self, v):
        try:
            done, so_far = (int(x) for x in str(v).split(','))
        except (TypeError, ValueError):
            return
        self.progress.emit(so_far)
        if done and not self._finished:
            self._timer.stop()
            w, h = self.size_mm
            layout = QPageLayout(QPageSize(QSizeF(w, h), QPageSize.Millimeter, 'manual', QPageSize.ExactMatch),
                                 QPageLayout.Portrait, QMarginsF(0, 0, 0, 0))
            self.view.page().printToPdf(self.pdf_path, layout)

    def _printed(self, path, ok):
        self._done(ok and os.path.isfile(path) and os.path.getsize(path) > 0, path)

    def _done(self, ok, msg):
        if self._finished:
            return
        self._finished = True
        self._timer.stop()
        self._deadline.stop()
        self.finished.emit(ok, msg)
        self.view.deleteLater()


def make_pdf_blocking(html, pdf_path, size_mm, timeout_s=900, progress=None):
    """Runs a PdfJob and waits (an event loop inside) — for the self-test, tests and simple callers."""
    path = write_html(html, name=f'pdf-{os.getpid()}.html')
    job = PdfJob(path, pdf_path, size_mm, timeout_s)
    result = {}
    loop = QEventLoop()
    job.finished.connect(lambda ok, msg: (result.update(ok=ok, msg=msg), loop.quit()))
    if progress:
        job.progress.connect(progress)
    job.start()
    loop.exec()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)    # the hidden browser view closes before returning
    job.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    return result.get('ok', False), result.get('msg', '')


def count_pages(pdf_path):
    """Pages in a PDF we wrote (counts page objects; no extra library)."""
    import re
    data = open(pdf_path, 'rb').read()
    return len(re.findall(rb'/Type\s*/Page[^s]', data))

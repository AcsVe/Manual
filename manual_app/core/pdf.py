"""PDF from the print HTML: the built-in browser engine (Qt WebEngine) lays the pages out with Paged.js and prints
them at the manual's exact page size. Also used to write the HTML of the live preview."""
import json
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


AUDIT_JS = r"""
(function(){
 function ref(el, o){var b=el.closest('[data-b]'), s=el.closest('[data-sid]');
   o.b=b?b.getAttribute('data-b'):null; o.sid=s?parseInt(s.getAttribute('data-sid')):null; return o;}
 var out={pages:0, items:[]}, pages=document.querySelectorAll('.pagedjs_page'), mm=96/25.4;
 var seen={}, hidden={}, got={}, need={}, first={};
 function inside(el, A){            // characters of el that lie inside the page box
   var n=0, w=document.createTreeWalker(el, NodeFilter.SHOW_TEXT), t;
   while((t=w.nextNode())){
     var len=t.data.replace(/\s+/g,'').length; if(!len) continue;
     var rg=document.createRange(); rg.selectNodeContents(t);
     var rs=rg.getClientRects(), tot=0, ins=0;
     for(var i=0;i<rs.length;i++){var q=rs[i], a=Math.max(q.width,0.1)*Math.max(q.height,0.1); tot+=a;
       if(q.left<A.right-1 && q.top<A.bottom-1 && q.right>A.left-1 && q.bottom>A.top-1) ins+=a;}
     n+= tot ? len*ins/tot : 0;
   }
   return n;
 }
 out.pages=pages.length;
 var sel='.tbar,.h-sub,.blk,table.t,.figure,.org,.callout,.quote,.toc .row,.links,.chapter-page,.history,ul,ol,img';
 pages.forEach(function(pg, pi){
   var area=pg.querySelector('.pagedjs_page_content'); if(!area) return;
   var A=area.getBoundingClientRect(), n=pi+1, W=A.right-A.left;
   // what lies outside the page (Paged.js keeps it beyond the right edge): printed elsewhere, or lost
   area.querySelectorAll('[data-ref]').forEach(function(el){
     if(!el.textContent.trim() && !el.querySelector('img')) return;
     var r=el.getBoundingClientRect(); if(r.width<1&&r.height<1) return;
     var k=el.getAttribute('data-ref');
     if(r.left>=A.right-2 || r.top>=A.bottom-2){ if(!hidden[k]) hidden[k]=ref(el,{t:'lost',page:n}); }
     else seen[k]=1;
   });
   area.querySelectorAll('[data-k]').forEach(function(el){
     var k=el.getAttribute('data-k'); need[k]=parseInt(el.getAttribute('data-n'))||0;
     got[k]=(got[k]||0)+inside(el, A);
     if(!first[k]) first[k]=ref(el,{t:'lost',page:n});
   });
   if(pg.classList.contains('pagedjs_cover_page')) return;
   var chapter=!!area.querySelector('.chapter-page'), last=null, lastBottom=-1e9, visible=0;
   area.querySelectorAll(sel).forEach(function(el){
     var r=el.getBoundingClientRect(); if(r.width<1||r.height<1) return;
     if(r.left>=A.right-2 || r.top>=A.bottom-2) return;           // a part kept outside the page
     visible++;
     var bottom=Math.min(r.bottom, A.bottom);
     if(bottom>lastBottom){lastBottom=bottom; last=el;}
     var right=r.right, left=r.left;
     if(el.matches('table.t')){        // rows with text only (a split table carries empty filler rows)
       right=-1e9; left=1e9;
       el.querySelectorAll('tr').forEach(function(tr){if(!tr.textContent.trim())return;var q=tr.getBoundingClientRect();
         if(q.left>=A.right-2||q.top>=A.bottom-2)return; left=Math.min(left,q.left); right=Math.max(right,Math.min(q.right,A.right+W*0.75));});
       if(right<left) return;
     }
     var over=Math.max(right-A.right, A.left-left);
     if(el.matches('table.t,.figure,img,.org') && over>3 && over<W*0.75)
       out.items.push(ref(el,{t:'x',page:n,mm:Math.round(over/mm)}));
     if(el.matches('.figure,.org') && r.height>A.bottom-A.top+3)
       out.items.push(ref(el,{t:'y',page:n,mm:Math.round((r.height-(A.bottom-A.top))/mm)}));
   });
   area.querySelectorAll('td,th').forEach(function(td){
     var q=td.getBoundingClientRect(); if(q.left>=A.right-2||q.top>=A.bottom-2) return;
     if(td.scrollWidth>td.clientWidth+2) out.items.push(ref(td,{t:'cell',page:n}));});
   area.querySelectorAll('table.t').forEach(function(tb){        // column titles alone at the foot of a page
     var rows=[].filter.call(tb.querySelectorAll('tbody tr'),function(tr){var q=tr.getBoundingClientRect();
       return q.height>0 && q.left<A.right-2 && q.top<A.bottom-2 && tr.textContent.trim();});
     if(!rows.length && tb.hasAttribute('data-split-to') && pi<pages.length-1) out.items.push(ref(tb,{t:'orphan',page:n}));});
   if(!visible){                     // what stands before and after a blank page tells what made it
     var o={t:'blank',page:n}, prev=pi>0?pages[pi-1].querySelectorAll('.pagedjs_page_content [data-b]'):[],
         next=pi+1<pages.length?pages[pi+1].querySelector('.pagedjs_page_content [data-b], .pagedjs_page_content [data-sid]'):null;
     if(prev.length) o.prev=prev[prev.length-1].getAttribute('data-b');
     if(next){ var nb=next.closest('[data-b]')||next.querySelector('[data-b]'); o.next=nb?nb.getAttribute('data-b'):null;
       var ns=next.closest('[data-sid]')||next; o.nextsid=parseInt(ns.getAttribute('data-sid'))||null; }
     out.items.push(o); return;
   }
   var secEl=last?last.closest('[data-sid]'):null;
   if(!chapter && last && last.closest('.tbar,.h-sub') && secEl && secEl.hasAttribute('data-split-to') && pi<pages.length-1)
     out.items.push(ref(last,{t:'orphan',page:n}));
   else if(!chapter && pi<pages.length-1 && (lastBottom-A.top)/A.height<0.15)
     out.items.push(ref(last,{t:'sparse',page:n,fill:Math.round(100*(lastBottom-A.top)/A.height)}));
 });
 for(var k in hidden){ if(!seen[k]) out.items.push(hidden[k]); }
 var km=window.__kmap||{}, gone={};          // text that never reached any page (the layout stopped early)
 for(var k in km){ if(need[k]===undefined){ var r=km[k][0].split(':'), sid=parseInt(r[0]);
   if(!gone[sid]) gone[sid]={t:'lost',page:out.pages,sid:sid,b:r[1]!==''?r[0]+':'+r[1]:null,chars:0,never:1};
   gone[sid].chars+=km[k][1]; } }
 for(var g in gone) out.items.push(gone[g]);
 for(var k in need){
   var g=got[k]||0, o=first[k];
   if(g < need[k]-2 && g < need[k]*0.995){ o.chars=Math.round(need[k]-g); out.items.push(o); }
   else if(g > need[k]*1.01+4){ o.t='dup'; o.chars=Math.round(g-need[k]); out.items.push(o); }
 }
 return JSON.stringify(out);
})()
"""


MISSING_JS = r"""
(function(){var km=window.__kmap||{}, seen={}, n=0;
 document.querySelectorAll('.pagedjs_page [data-k]').forEach(function(e){seen[e.getAttribute('data-k')]=1;});
 for(var k in km) if(!seen[k]) n++;
 return n;})()
"""


ORIENT_JS = r"""
(function(){var o='';document.querySelectorAll('.pagedjs_page').forEach(function(p){
  var r=p.getBoundingClientRect(),k=(r.width>r.height+1)?'L':'P';p.setAttribute('data-mbo',k);o+=k;});return o;})()
"""


def merge_orientations(parts, orients):
    """Each pass printed only the pages of its own direction (the others hidden, or the browser would shrink every
    page to fit the widest); they are put back in the laid-out order."""
    import io
    from pypdf import PdfReader, PdfWriter
    portrait, landscape = (PdfReader(io.BytesIO(p)) for p in parts)
    out = PdfWriter()
    next_page = {'P': 0, 'L': 0}
    for o in orients:
        src = landscape if o == 'L' else portrait
        i = next_page[o]
        next_page[o] += 1
        if i < len(src.pages):
            out.add_page(src.pages[i])
    buf = io.BytesIO()
    out.write(buf)
    return buf.getvalue()


class PdfJob(QObject):
    """Loads an HTML file, waits until Paged.js has laid out every page, prints it to ``pdf_path``.
    Signals: progress(pages so far), finished(ok, message)."""
    progress = Signal(int)
    finished = Signal(bool, str)

    def __init__(self, html_path, pdf_path, size_mm, timeout_s=900, audit=False):
        super().__init__()
        self.missing = 0              # texts that did not reach any page (0 when the file is whole)
        self.audit = audit            # True: no PDF — the laid-out pages are measured instead (finished(ok, json))
        from PySide6.QtWebEngineWidgets import QWebEngineView
        self.html_path, self.pdf_path, self.size_mm = html_path, pdf_path, size_mm
        self.view = QWebEngineView()
        self.view.setAttribute(Qt.WA_DontShowOnScreen, True)     # laid out and painted, never on screen
        self.view.resize(1400, 1000)
        settings_for(self.view.page())
        self.view.loadFinished.connect(self._loaded)
        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._poll)
        self._deadline = QTimer(self)
        self._deadline.setSingleShot(True)
        self._deadline.setInterval(timeout_s * 1000)
        self._deadline.timeout.connect(lambda: self._done(False, 'timeout'))
        self._finished = False
        self._busy = False
        self._parts = []               # the PDF of each orientation when the manual mixes them

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
        if done and not self._finished and not self._busy:
            self._busy = True
            self._timer.stop()
            if self.audit:
                self.view.page().runJavaScript(AUDIT_JS, 0, lambda v: self._done(bool(v), str(v or '')))
                return
            w, h = self.size_mm
            layout = QPageLayout(QPageSize(QSizeF(w, h), QPageSize.Millimeter, 'manual', QPageSize.ExactMatch),
                                 QPageLayout.Portrait, QMarginsF(0, 0, 0, 0))
            # how much marked text never reached a page (the layout can stop early on a pathological piece)
            self.view.page().runJavaScript(MISSING_JS, 0, lambda v: self._print(v, layout))

    def _print(self, missing, layout):
        try:
            self.missing = int(missing or 0)
        except (TypeError, ValueError):
            self.missing = 0
        self.view.page().runJavaScript(ORIENT_JS, 0, self._orients)

    def _orients(self, v):
        """Pages of another orientation (a landscape table in a portrait manual) are printed in a second pass on
        paper of that orientation, and the two files are put together page by page."""
        self.orients = str(v or '')
        w, h = self.size_mm
        portrait, landscape = (min(w, h), max(w, h)), (max(w, h), min(w, h))
        kinds = set(self.orients)
        if len(kinds) <= 1:
            self._passes = [landscape if self.orients[:1] == 'L' else portrait]
        else:
            self._passes = [portrait, landscape]
        self._next_pass()

    def _next_pass(self):
        w, h = self._passes[len(self._parts)]
        css = '@page{size:%smm %smm !important;margin:0 !important}' % (w, h)
        if len(self._passes) > 1:
            other = 'P' if w > h else 'L'
            css += '.pagedjs_page[data-mbo="%s"]{display:none !important}' % other
        layout = QPageLayout(QPageSize(QSizeF(w, h), QPageSize.Millimeter, 'manual', QPageSize.ExactMatch),
                             QPageLayout.Portrait, QMarginsF(0, 0, 0, 0))
        js = ("(function(){var s=document.getElementById('mb-print-size')||document.createElement('style');"
              "s.id='mb-print-size';s.textContent=%s;document.head.appendChild(s);return 1;})()" % json.dumps(css))
        # the PDF comes back in memory and is written here: Qt's own «print to file» fails on long manuals
        self.view.page().runJavaScript(js, 0, lambda _v: self.view.page().printToPdf(self._printed, layout))

    def _printed(self, data):
        data = bytes(data or b'')
        if not data:
            self._done(False, 'empty')
            return
        self._parts.append(data)
        if len(self._parts) < len(self._passes):
            self._next_pass()
            return
        try:
            if len(self._parts) > 1:
                data = merge_orientations(self._parts, self.orients)
            with open(self.pdf_path, 'wb') as f:
                f.write(data)
        except Exception as e:  # noqa: BLE001 — a damaged pass or a file that cannot be written
            self._done(False, str(e))
            return
        self._done(True, self.pdf_path)

    def _done(self, ok, msg):
        if self._finished:
            return
        self._finished = True
        self._timer.stop()
        self._deadline.stop()
        self.finished.emit(ok, msg)
        self.view.deleteLater()


def make_pdf_blocking(html, pdf_path, size_mm, timeout_s=900, progress=None, audit=False):
    """Runs a PdfJob and waits (an event loop inside) — for the self-test, tests and simple callers."""
    path = write_html(html, name=f'pdf-{os.getpid()}.html')
    job = PdfJob(path, pdf_path, size_mm, timeout_s, audit)
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


def audit_blocking(html, size_mm, timeout_s=900, progress=None):
    """The laid-out pages measured: {'pages': n, 'items': [{'t': kind, 'page': n, 'sid', 'b', …}]}."""
    import json
    ok, msg = make_pdf_blocking(html, '', size_mm, timeout_s, progress, audit=True)
    return json.loads(msg) if ok else {'pages': 0, 'items': [], 'error': msg}

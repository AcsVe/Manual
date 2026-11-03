"""شكل ملف PDF الأصلي: يُقرأ تصميم كل صفحة (الأشرطة والإطارات والشعار والخلفية والعلامة المائية) دون نصها، وتُجمع
الصفحات المتشابهة التصميم في مجموعات، ثم يُطبَّق الشكل على الدليل:

* التصميم الأكثر تكراراً في صفحات المتن خلفيةً لكل الصفحات، وهوامش الدليل ومقاس صفحته كما في الملف، فيقع النص حيث
  كان في الأصل لا فوق الأشرطة.
* القسم الذي جاء من صفحات بتصميم آخر (فصل بلون آخر، صفحات أفقية) يأخذ تصميم صفحاته واتجاهها.
* الغلاف، والصفحات الفاصلة، والغلاف الخلفي، والصفحات الممسوحة ضوئياً، والصفحات التي لا يُقرأ نصها: تدخل صفحاتٍ كاملة
  كما هي.
* نص الترويسة والتذييل المتكرر والعلامة المائية المائلة يبقى في التصميم ولا يدخل في المتن؛ وأرقام الصفحات الأصلية
  تُزال ويُرقِّم البرنامج الصفحات في الموضع نفسه.

ويُفتح الملف المحمي بكلمة مرور (بعد إدخالها)، ويُصلَح الملف التالف إن أمكن، وإلا فُتحت صفحاته صوراً.
"""
import os
import re
import tempfile
from collections import Counter

from .importer import AR, PAGE_NO_RE, line_from_chars, slanted

DPI = 110                        # دقة صورة التصميم المحفوظة
SIG = (96, 136)                  # مقاس صورة المقارنة الصغيرة (عرض × ارتفاع للصفحة العمودية)
SAME = 0.012                     # أقصى نسبة من مساحة الصفحة تختلف بين صفحتين من التصميم نفسه
MAX_SCAN = 80                    # أقصى عدد من الصفحات تُفحص تصاميمها في الملف الطويل
COVER_CHARS = 600                # الصفحة الأولى التي نصها أقل من هذا غلاف
SPECIAL_CHARS = 400              # صفحة بتصميم مختلف ونص أقل من هذا: صفحة فاصلة أو غلاف خلفي
MM = 25.4 / 72


class PdfPasswordError(ValueError):
    """الملف محمي بكلمة مرور لم تُدخل بعد أو أُدخلت خاطئة."""


# ── تهيئة الملف: كلمة المرور والإصلاح ──────────────────────────────────────────────────────────────────
def prepare(path, password=None):
    """يرجع (مسار يقرؤه البرنامج، مسار مؤقت يُحذف بعد الانتهاء أو None، وصف ما جرى أو '').
    يرفع PdfPasswordError إذا احتاج الملف كلمة مرور، وValueError برسالة مقروءة إذا تعذّرت قراءته كلياً."""
    from pypdf import PdfReader, PdfWriter
    note = ''
    reader = None
    try:
        reader = PdfReader(path, strict=False)
        if reader.is_encrypted:
            ok = False
            for pw in ([password] if password else []) + ['']:
                try:
                    if reader.decrypt(pw):
                        ok = True
                        break
                except Exception:  # noqa: BLE001 — كلمة مرور خاطئة أو تشفير غير مدعوم
                    continue
            if not ok:
                raise PdfPasswordError(path)
            note = 'decrypted'
        elif _miner_reads(path):
            return path, None, ''
        else:
            note = 'repaired'
        writer = PdfWriter()
        for pg in reader.pages:
            writer.add_page(pg)
        fd, tmp = tempfile.mkstemp(suffix='.pdf', prefix='mb-')
        with os.fdopen(fd, 'wb') as f:
            writer.write(f)
        if _miner_reads(tmp):
            return tmp, tmp, note
        os.remove(tmp)
    except PdfPasswordError:
        raise
    except Exception:  # noqa: BLE001 — يُجرَّب ما بعده
        pass
    if _qt_pages(path):
        return path, None, 'pictures'           # يُعرض الملف ويتعذّر قراءة نصه: تدخل صفحاته صوراً
    raise ValueError('الملف تالف ولا يمكن قراءته.\nThe file is damaged and cannot be read.')


def _miner_reads(path):
    try:
        from pdfminer.pdfpage import PDFPage
        with open(path, 'rb') as f:
            return sum(1 for _ in PDFPage.get_pages(f)) > 0
    except Exception:  # noqa: BLE001
        return False


def _qt_doc(path):
    from PySide6.QtPdf import QPdfDocument
    doc = QPdfDocument()
    if doc.load(path) != QPdfDocument.Error.None_ or doc.pageCount() < 1:
        return None
    return doc


def _qt_pages(path):
    try:
        doc = _qt_doc(path)
        return doc.pageCount() if doc else 0
    except Exception:  # noqa: BLE001
        return 0


# ── قراءة الصفحات ─────────────────────────────────────────────────────────────────────────────────────
def _pages(path, tick=None):
    """كل صفحة: مقاسها كما تُعرض (بعد القص والتدوير) وأسطر نصها بنسب من الصفحة المعروضة."""
    from pdfminer.converter import PDFPageAggregator
    from pdfminer.layout import LAParams, LTChar, LTTextContainer, LTTextLine
    from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
    from pdfminer.pdfpage import PDFPage
    out = []
    rm = PDFResourceManager()
    dev = PDFPageAggregator(rm, laparams=LAParams(line_margin=0.4))
    interp = PDFPageInterpreter(rm, dev)
    with open(path, 'rb') as f:
        pages_iter = PDFPage.get_pages(f)
        no = 0
        while True:
            try:
                page = next(pages_iter)
            except StopIteration:
                break
            except Exception:  # noqa: BLE001 — the rest of the file cannot be walked: those pages come in as they are
                out.extend(_qt_rest(path, no))
                break
            no += 1
            if tick:
                tick()
            rec = {'no': no, 'lines': [], 'chars': 0, 'bad': 0}
            mb = [float(v) for v in page.mediabox]
            cb = [float(v) for v in (page.cropbox or page.mediabox)]
            rot = int(page.rotate or 0) % 360
            # إحداثيات pdfminer تبدأ من ركن صندوق الوسائط؛ والصفحة المعروضة هي صندوق القص (مع التدوير)
            if rot % 180 == 0 and (cb[0] > mb[0] or cb[1] > mb[1] or cb[2] < mb[2] or cb[3] < mb[3]):
                ox, oy, W, H = cb[0] - mb[0], cb[1] - mb[1], cb[2] - cb[0], cb[3] - cb[1]
            else:
                ox = oy = 0
                W, H = abs(mb[2] - mb[0]), abs(mb[3] - mb[1])
                if rot % 180:
                    W, H = H, W
            rec['w_mm'], rec['h_mm'] = W * MM, H * MM
            rec['landscape'] = W > H
            try:
                interp.process_page(page)
                layout = dev.get_result()
            except Exception:  # noqa: BLE001 — صفحة لا يُقرأ نصها: تدخل صورة
                rec['bad'] = 1
                out.append(rec)
                continue
            for el in layout:
                if not isinstance(el, LTTextContainer):
                    continue
                for ln in el:
                    if not isinstance(ln, LTTextLine):
                        continue
                    chars = [c for c in ln if isinstance(c, LTChar)]
                    raw = ln.get_text().strip()
                    if not chars or not raw:
                        continue
                    if AR.search(raw):                 # النص العربي بترتيب قراءته (كما يُستورد)
                        raw = line_from_chars([(c.x0, c.x1, c.size, c.get_text()) for c in chars]) or raw
                    bad = sum(1 for c in chars if c.get_text().startswith('(cid:') or _private(c.get_text()))
                    upright = not slanted(chars)
                    rec['chars'] += len(chars) - bad
                    rec['bad'] += bad
                    rec['lines'].append({
                        'color': _color(chars),
                        'x0': (ln.x0 - ox) / W, 'x1': (ln.x1 - ox) / W,
                        'y0': 1 - (ln.y1 - oy) / H, 'y1': 1 - (ln.y0 - oy) / H,
                        'text': raw, 'upright': upright, 'size': max(c.size for c in chars)})
            out.append(rec)
    return out


def _color(chars):
    """لون نص السطر (#RRGGBB) من لون تعبئة حروفه، أو None."""
    c = chars[len(chars) // 2]
    v = getattr(getattr(c, 'graphicstate', None), 'ncolor', None)
    try:
        if isinstance(v, (int, float)):
            r = g = b = float(v)
        elif v is not None and len(v) == 3:
            r, g, b = (float(x) for x in v)
        elif v is not None and len(v) == 4:
            C, M, Y, K = (float(x) for x in v)
            r, g, b = (1 - C) * (1 - K), (1 - M) * (1 - K), (1 - Y) * (1 - K)
        else:
            return None
    except (TypeError, ValueError):
        return None
    return '#%02X%02X%02X' % tuple(int(round(min(1, max(0, x)) * 255)) for x in (r, g, b))


def _qt_rest(path, after):
    """Pages after ``after`` that pdfminer cannot reach: their size from Qt, marked unreadable (whole pages)."""
    doc = _qt_doc(path)
    out = []
    if doc is None:
        return out
    for i in range(after, doc.pageCount()):
        sz = doc.pagePointSize(i)
        out.append({'no': i + 1, 'lines': [], 'chars': 0, 'bad': 1, 'w_mm': sz.width() * MM, 'h_mm': sz.height() * MM,
                    'landscape': sz.width() > sz.height()})
    return out


def _private(t):
    return any(0xE000 <= ord(ch) <= 0xF8FF for ch in t)


def unreadable(rec):
    """صفحة لا يُقرأ نصها (خطوط دون جدول ترميز) أو لا نص فيها تقريباً."""
    total = rec['chars'] + rec['bad']
    return rec['chars'] < 60 or (total and rec['bad'] / total > 0.3)


def _classify(pages):
    """نوع كل سطر: text (يدخل المتن ويُمحى من التصميم)، keep (يبقى في التصميم: ترويسة أو تذييل متكرر أو علامة
    مائية مائلة)، number (رقم صفحة: يُمحى ويُرقِّم البرنامج في موضعه)."""
    rep = Counter()
    for p in pages:
        for ln in p['lines']:
            if ln['y0'] < 0.12 or ln['y1'] > 0.9:
                rep[re.sub(r'\d+', '#', ln['text'])] += 1
    many = max(2, len(pages) // 3)
    for p in pages:
        for ln in p['lines']:
            key = re.sub(r'\d+', '#', ln['text'])
            edge = ln['y0'] < 0.12 or ln['y1'] > 0.9
            if not ln['upright']:
                ln['kind'] = 'keep'
            elif PAGE_NO_RE.fullmatch(ln['text']) or (edge and rep[key] >= many and '#' in key):
                ln['kind'] = 'number'
            elif edge and rep[key] >= many:
                ln['kind'] = 'keep'
            else:
                ln['kind'] = 'text'


# ── صورة التصميم ──────────────────────────────────────────────────────────────────────────────────────
def _render(doc, rec, size):
    from PySide6.QtCore import QSize
    from .importer import _on_white
    return _on_white(doc.render(rec['no'] - 1, QSize(*size)))


class Pix:
    """صورة صفحة بنقاطها في ذاكرة قابلة للتعديل (Qt وحده، دون مكتبات حساب خارجية: البرنامج المبني لا يحملها)."""

    def __init__(self, img):
        from PySide6.QtGui import QImage
        img = img.convertToFormat(QImage.Format_RGB32)
        self.w, self.h, self.stride = img.width(), img.height(), img.bytesPerLine()
        self.buf = bytearray(bytes(img.constBits())[:self.stride * self.h])

    def get(self, x, y):
        o = y * self.stride + x * 4                  # الترتيب في الذاكرة: أزرق، أخضر، أحمر، ثم الشفافية
        b = self.buf
        return b[o + 2], b[o + 1], b[o]

    def put(self, x, y, c):
        o = y * self.stride + x * 4
        self.buf[o + 2], self.buf[o + 1], self.buf[o] = c

    def image(self):
        from PySide6.QtGui import QImage
        return QImage(bytes(self.buf), self.w, self.h, self.stride, QImage.Format_RGB32).copy()

    def small(self, step=4):
        """متوسط كل مربع step×step: صورة صغيرة للمقارنة."""
        out = []
        for gy in range(self.h // step):
            row = []
            for gx in range(self.w // step):
                r = g = bl = 0
                for y in range(gy * step, gy * step + step):
                    for x in range(gx * step, gx * step + step):
                        c = self.get(x, y)
                        r, g, bl = r + c[0], g + c[1], bl + c[2]
                n = step * step
                row.append((r / n, g / n, bl / n))
            out.append(row)
        return out


def _median(colors):
    if not colors:
        return None
    k = len(colors) // 2
    return tuple(sorted(c[i] for c in colors)[k] for i in range(3))


def _gap(c1, c2):
    return (abs(c1[0] - c2[0]) + abs(c1[1] - c2[1]) + abs(c1[2] - c2[2])) / 3


def _mix(c1, c2, t):
    return (int(c1[0] + (c2[0] - c1[0]) * t + 0.5), int(c1[1] + (c2[1] - c1[1]) * t + 0.5),
            int(c1[2] + (c2[2] - c1[2]) * t + 0.5))


def _erase(px, rec):
    """يمحو أسطر النص وأرقام الصفحات من صورة الصفحة. يُملأ موضع كل سطر بتدرّج بين لوني جانبيه (يمينه ويساره، أو
    أعلاه وأسفله، أيهما أكثر اتساقاً)، فيبقى الشريط الملوّن والشريط الجانبي والتدرّج كما هي ولا تظهر رقعة."""
    w, h = px.w, px.h
    mm = w / max(1.0, rec['w_mm'])                    # نقاط في المليمتر في هذه الصورة
    pad = max(1, int(round(0.6 * mm)))
    band = max(2, pad)
    for ln in rec['lines']:
        if ln.get('kind') == 'keep':
            continue
        lh = (ln['y1'] - ln['y0']) * h
        x0 = int(max(0, ln['x0'] * w - pad - lh * 0.1))
        x1 = int(min(w, ln['x1'] * w + pad + lh * 0.1))
        y0 = int(max(0, ln['y0'] * h - pad - lh * 0.2))
        y1 = int(min(h, ln['y1'] * h + pad + lh * 0.2))
        if x1 <= x0 or y1 <= y0:
            continue
        rows = range(y0, y1)
        cols = range(x0, x1)
        L = [_median([px.get(x, y) for x in range(max(0, x0 - band), x0)]) for y in rows] if x0 > 0 else None
        R = [_median([px.get(x, y) for x in range(x1, min(w, x1 + band))]) for y in rows] if x1 < w else None
        T = [_median([px.get(x, y) for y in range(max(0, y0 - band), y0)]) for x in cols] if y0 > 0 else None
        B = [_median([px.get(x, y) for y in range(y1, min(h, y1 + band))]) for x in cols] if y1 < h else None
        L, R = (R if L is None else L), (L if R is None else R)
        T, B = (B if T is None else T), (T if B is None else B)
        cost_h = sum(_gap(a_, b_) for a_, b_ in zip(L, R)) / len(L) if L else 1e9
        cost_v = sum(_gap(a_, b_) for a_, b_ in zip(T, B)) / len(T) if T else 1e9
        if cost_h == cost_v == 1e9:
            continue
        if cost_h <= cost_v:
            span = max(1, x1 - x0 - 1)
            for i, y in enumerate(rows):
                for x in cols:
                    px.put(x, y, _mix(L[i], R[i], (x - x0) / span))
        else:
            span = max(1, y1 - y0 - 1)
            for j, x in enumerate(cols):
                for y in rows:
                    px.put(x, y, _mix(T[j], B[j], (y - y0) / span))
    return px


def _band_text(px, rec):
    """نص في أعلى الصفحة أو أسفلها فوق شريط ملوّن (اسم المؤسسة على شريط الترويسة) جزء من التصميم، ولو لم يتكرر
    (ملف بصفحة واحدة)."""
    w, h = px.w, px.h
    for ln in rec['lines']:
        if ln.get('kind') != 'text' or not (ln['y0'] < 0.12 or ln['y1'] > 0.9):
            continue
        x0, x1 = int(ln['x0'] * w), int(min(w, ln['x1'] * w + 1))
        y0, y1 = int(ln['y0'] * h), int(min(h, ln['y1'] * h + 1))
        ring = [px.get(x, y) for x in range(x0, x1) for y in (*range(max(0, y0 - 2), y0), *range(y1, min(h, y1 + 2)))]
        ring += [px.get(x, y) for y in range(y0, y1) for x in (*range(max(0, x0 - 2), x0), *range(x1, min(w, x1 + 2)))]
        c = _median(ring)
        if c and (sum(c) / 3 < 200 or max(c) - min(c) > 60):
            ln['kind'] = 'keep'


def _differs(a, b):
    """نسبة مساحة الصفحة التي يختلف لونها بوضوح بين صورتين صغيرتين: شريط ملوّن رفيع بلون آخر يكفي للتفريق، وبقايا
    محو النص لا تكفي."""
    cells = diff = 0
    for ra, rb in zip(a, b):
        for ca, cb in zip(ra, rb):
            cells += 1
            diff += _gap(ca, cb) > 25
    return diff / max(1, cells)


def _plain(px):
    """صفحة بيضاء تماماً تقريباً (الخلفية الفاتحة والشعار الصغير والخط الرفيع تصميم يُحفظ)."""
    b = px.buf
    white = total = 0
    for y in range(px.h):
        o = y * px.stride
        for x in range(px.w):
            i = o + x * 4
            total += 1
            white += b[i] >= 253 and b[i + 1] >= 253 and b[i + 2] >= 253
    return white / max(1, total) > 0.997


def _sig_size(rec):
    return (SIG[1], SIG[0]) if rec['landscape'] else SIG


def design_image(doc, rec, dpi=DPI):
    """صورة تصميم الصفحة دون نصها (QImage)."""
    k = dpi / 25.4
    w, h = int(rec['w_mm'] * k), int(rec['h_mm'] * k)
    scale = min(1.0, 2200 / max(w, h))          # الصفحات الكبيرة جداً لا تتجاوز 2200 نقطة
    px = Pix(_render(doc, rec, (max(1, int(w * scale)), max(1, int(h * scale)))))
    return _erase(px, rec).image()


def _png(img):
    from PySide6.QtCore import QBuffer, QIODevice
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, 'PNG')
    return bytes(buf.data())


# ── التحليل ───────────────────────────────────────────────────────────────────────────────────────────
def analyse(path, progress=None):
    """يحلّل الملف ويرجع وصف شكله (انظر أعلى الملف). progress(تم، الكل) اختياري."""
    from .importer import pdf_page_count
    total = pdf_page_count(path)
    steps = {'done': 0, 'total': total + min(total, MAX_SCAN)}

    def tick():
        steps['done'] += 1
        if progress:
            progress(min(steps['done'], steps['total']), steps['total'])
    pages = _pages(path, tick)
    n = len(pages)
    look = {'path': path, 'pages': pages, 'n': n, 'groups': {}, 'body': {}, 'cover': False, 'image_pages': set(),
            'orientation': 'portrait', 'margins': None, 'page_size': None, 'number_pos': None, 'head_text': False}
    if not n:
        return look
    _classify(pages)
    doc = _qt_doc(path)
    # الصفحات التي تُفحص تصاميمها: كلها في الملف القصير، وفي الطويل أوله ثم عيّنة منتظمة من باقيه
    if n <= MAX_SCAN:
        scan = list(range(n))
    else:
        head = MAX_SCAN // 2
        step = (n - head) / (MAX_SCAN - head)
        scan = sorted(set(list(range(head)) + [head + int(i * step) for i in range(MAX_SCAN - head)]))
    sigs = {}
    errors = look['errors'] = []                 # why a page could not be drawn (kept for the log)
    for i, idx in enumerate(scan):
        rec = pages[idx]
        try:
            px = Pix(_render(doc, rec, _sig_size(rec)))
            _band_text(px, rec)
            _erase(px, rec)
            rec['plain'] = _plain(px)
            sigs[idx] = px.small(4)
        except Exception:  # noqa: BLE001 — no picture of this page (or no Qt reader): it counts as a plain page
            rec['plain'] = True
            sigs[idx] = None
            if len(errors) < 3:
                import traceback
                errors.append(traceback.format_exc()[-700:])
        tick()
    # المجموعات: صفحات بالاتجاه نفسه وتصميم متقارب
    groups = []
    for idx in scan:
        rec = pages[idx]
        for g in groups:
            if g['landscape'] == rec['landscape'] and g['plain'] == rec['plain'] and \
                    (rec['plain'] or (sigs[idx] is not None and sigs[g['rep']] is not None
                                      and _differs(sigs[g['rep']], sigs[idx]) < SAME)):
                g['pages'].append(rec['no'])
                rec['group'] = g['id']
                break
        else:
            gid = len(groups) + 1
            groups.append({'id': gid, 'rep': idx, 'landscape': rec['landscape'], 'plain': rec['plain'], 'pages': [rec['no']]})
            rec['group'] = gid
    last = None
    for rec in pages:                            # الصفحات غير المفحوصة تتبع أقرب صفحة مفحوصة قبلها
        if 'group' in rec:
            last = rec
        elif last is not None:
            rec['group'], rec['plain'] = last['group'], last['plain']
            groups[last['group'] - 1]['pages'].append(rec['no'])
    look['groups'] = {g['id']: g for g in groups}

    # الغلاف، والصفحات التي تدخل صوراً، وتصميم المتن لكل اتجاه
    first = pages[0]
    look['cover'] = n >= 2 and first['chars'] < COVER_CHARS
    images = {p['no'] for p in pages if unreadable(p)}
    if look['cover']:
        images.add(1)
    count = {}
    for p in pages:
        if p['no'] not in images:
            count.setdefault(p['landscape'], Counter())[p['group']] += max(1, p['chars'])
    look['body'] = {land: c.most_common(1)[0][0] for land, c in count.items()}
    for p in pages:
        if p['no'] in images or p['chars'] >= SPECIAL_CHARS:
            continue
        if look['body'].get(p['landscape']) != p['group']:
            images.add(p['no'])                  # صفحة فاصلة أو غلاف خلفي أو ملصق بتصميمه الخاص
    look['image_pages'] = images
    tall = sum(1 for p in pages if not p['landscape'])
    look['orientation'] = 'portrait' if tall >= n - tall else 'landscape'

    # الهوامش ومقاس الصفحة من صفحات المتن بالاتجاه الغالب
    land = look['orientation'] == 'landscape'
    main = look['body'].get(land)
    body_pages = [p for p in pages if p['no'] not in images and p['landscape'] == land and p.get('group') == main]
    lines = [ln for p in body_pages for ln in p['lines'] if ln['kind'] == 'text']
    if lines:
        ref = body_pages[0]
        W, H = ref['w_mm'], ref['h_mm']
        pick = lambda vals, q: sorted(vals)[min(len(vals) - 1, max(0, int(len(vals) * q)))]  # noqa: E731
        left = pick([ln['x0'] for ln in lines], 0.03) * W
        right = (1 - pick([ln['x1'] for ln in lines], 0.97)) * W
        top = pick([ln['y0'] for ln in lines], 0.02) * H
        bottom = (1 - pick([ln['y1'] for ln in lines], 0.98)) * H
        # الصفحة التي لم يمتلئ نصها لا تدل على الهامش السفلي: لا يزيد على العلوي، ولا يقل عن موضع رقم الصفحة
        nums = [ln for p in body_pages for ln in p['lines'] if ln['kind'] in ('number', 'keep') and ln['y0'] > 0.75]
        foot = (1 - min(ln['y0'] for ln in nums)) * H + 3 if nums else 12
        bottom = max(min(bottom, max(top, 20)), foot)
        clamp = lambda v: int(round(min(70, max(6, v - 2))))  # noqa: E731
        look['margins'] = {'top': clamp(top), 'bottom': clamp(bottom), 'left': clamp(left), 'right': clamp(right)}
    ref = body_pages[0] if body_pages else first
    look['page_size'] = _page_size(ref['w_mm'], ref['h_mm'])
    nums = [ln for p in pages for ln in p['lines'] if ln['kind'] == 'number']
    if nums:
        mid = sorted((ln['x0'] + ln['x1']) / 2 for ln in nums)[len(nums) // 2]
        look['number_pos'] = 'left' if mid < 0.36 else 'right' if mid > 0.64 else 'center'
        look['number_top'] = sorted(ln['y0'] for ln in nums)[len(nums) // 2] < 0.5
    sizes = sorted(ln['size'] for p in body_pages for ln in p['lines'] if ln['kind'] == 'text')
    look['font_size'] = round(min(16, max(8, sizes[len(sizes) // 2])) * 2) / 2 if sizes else None
    # لون النص ولون العناوين كما في الملف
    body_size = sizes[len(sizes) // 2] if sizes else 0
    txt = Counter(ln.get('color') for p in body_pages for ln in p['lines'] if ln['kind'] == 'text' and ln.get('color')
                  and abs(ln['size'] - body_size) < 0.6)
    heads = Counter(ln.get('color') for p in body_pages for ln in p['lines'] if ln['kind'] == 'text' and ln.get('color')
                    and ln['size'] >= body_size * 1.18)
    look['text_color'] = txt.most_common(1)[0][0] if txt else None
    look['heading_color'] = heads.most_common(1)[0][0] if heads else look['text_color']
    # تباعد الأسطر: المسافة بين سطرين متتاليين من الفقرة نفسها، نسبةً إلى حجم الخط
    ratios = []
    for p in body_pages:
        ls = sorted((ln for ln in p['lines'] if ln['kind'] == 'text'), key=lambda ln: ln['y0'])
        for a_, b_ in zip(ls, ls[1:]):
            if abs(a_['size'] - b_['size']) < 0.3 and abs(a_['x1'] - b_['x1']) < 0.02:
                gap = (b_['y0'] - a_['y0']) * p['h_mm'] / MM / a_['size']
                if 0.9 < gap < 2.6:
                    ratios.append(gap)
    look['line'] = round(sorted(ratios)[len(ratios) // 2], 2) if len(ratios) >= 3 else None
    look['head_text'] = any(ln['kind'] == 'keep' and ln['y0'] < 0.12 for p in pages for ln in p['lines'])
    look['doc'] = doc
    return look


def _page_size(w, h):
    from .templates import PAGE_SIZES
    a, b = sorted((w, h))
    best, diff = 'A4', 1e9
    for name, (pw, ph) in PAGE_SIZES.items():
        d = abs(pw - a) + abs(ph - b)
        if d < diff:
            best, diff = name, d
    return best


def group_design(look, gid):
    """صورة تصميم مجموعة (PNG، عرض، ارتفاع) أو None إذا كانت صفحاتها بيضاء أو تعذّر الرسم."""
    g = look['groups'].get(gid)
    doc = look.get('doc')
    if not g or g['plain'] or doc is None:
        return None
    recs = [p for p in look['pages'] if p['no'] in g['pages'] and p['no'] not in look['image_pages']] or \
        [p for p in look['pages'] if p['no'] in g['pages']]
    rec = max(recs[:6], key=lambda p: p['chars'])      # صفحة مليئة بالنص تمثّل المجموعة
    img = design_image(doc, rec)
    return _png(img), img.width(), img.height()


# ── التطبيق على الدليل ────────────────────────────────────────────────────────────────────────────────
def page_keys(look):
    """{رقم الصفحة: مفتاح تصميمها} لصفحات المتن (يُمرَّر إلى الاستيراد ليضع فاصل صفحات حيث يتغيّر التصميم)."""
    return {p['no']: f"{p.get('group')}{'L' if p['landscape'] else 'P'}" for p in look['pages']
            if p['no'] not in look['image_pages'] and p.get('group')}


def drop_lines(look):
    """{رقم الصفحة: [(نص السطر دون المسافات، موضع أعلاه)]} للأسطر التي تبقى في تصميم الصفحة ولا تدخل المتن."""
    out = {}
    for p in look['pages']:
        for ln in p['lines']:
            if ln.get('kind') in ('keep', 'number'):
                out.setdefault(p['no'], []).append((re.sub(r'\s+', '', ln['text']), ln['y0']))
    return out


def _key(k):
    if not k:
        return None
    return int(k[:-1]), k[-1] == 'L'


def apply(db, mid, look, created, mode='manual', name='تصميم صفحات الملف الأصلي'):
    """يطبّق الشكل. created: [(معرّف القسم، مستواه، القسم كما قرأه الاستيراد)] بترتيب الدليل.
    mode: manual (دليل جديد من الملف: الخلفية والهوامش والمقاس على الدليل كله) أو sections (استيراد إلى دليل
    قائم: يأخذ كل قسم مستورد تصميم صفحاته دون تغيير شكل الدليل)."""
    from .templates import layout_with_defaults
    lay = layout_with_defaults(db.manual(mid)['layout'])
    assets = {}

    def asset_of(gid):
        if gid not in assets:
            d = group_design(look, gid)
            assets[gid] = db.add_asset(f'{name} {len(assets) + 1}.png', d[0], 'image/png', 'background', d[1], d[2]) if d else None
        return assets[gid]

    main_land = look['orientation'] == 'landscape'
    if mode == 'manual':
        lay['orientation'] = look['orientation']
        if look['page_size']:
            lay['page_size'] = look['page_size']
        main = look['body'].get(main_land)
        aid = asset_of(main) if main else None
        lay['page_bg'] = {'asset_id': aid, 'fit': 'stretch', 'layer': 'behind', 'opacity': 1.0} if aid else None
        if look['margins']:
            lay['margins'] = dict(lay['margins'], **look['margins'])
        if look.get('font_size'):
            lay['fonts'] = dict(lay['fonts'], size=look['font_size'])
        if look.get('text_color'):
            hc = look.get('heading_color') or look['text_color']
            lay['colors'] = dict(lay['colors'], text=look['text_color'], table_text=look['text_color'],
                                 heading=hc, accent=hc, secondary=hc)
        if look.get('line'):
            lay['fonts'] = dict(lay['fonts'], line=min(2.2, max(1.15, look['line'])))
        lay['header'] = dict(lay['header'], style='none', logo=False, start='', center='', end='')
        foot = {'start': '', 'center': '', 'end': ''}
        if look['number_pos']:
            rtl = lay.get('lang_mode', 'bi_side') != 'en'
            side = {'center': 'center', 'right': 'start' if rtl else 'end', 'left': 'end' if rtl else 'start'}[look['number_pos']]
            if look.get('number_top'):
                lay['header'] = dict(lay['header'], **{side: '{page}'})
            else:
                foot[side] = '{page}'
        lay['footer'] = dict(lay['footer'], style='none', **foot)
        lay['boxes'] = False
        db.save_manual({'layout': lay}, mid)
        default = (main, main_land) if main else None
    else:
        default = None                           # لا تصميم مشترك: كل قسم مستورد يأخذ تصميمه
    manual_orient = lay['orientation']
    bare = mode == 'sections'

    def design_of(want):
        gid, land = want
        aid = asset_of(gid)
        return aid, ('landscape' if land else 'portrait')

    parents = []                                 # (المستوى، الشكل الفعلي)
    for sid, level, sec_in in created:
        while parents and parents[-1][0] >= level:
            parents.pop()
        inherited = parents[-1][1] if parents else default
        want = _key(sec_in.get('_look')) or inherited
        parents.append((level, want))
        if want is not None and want != inherited:
            st = dict(db.section(sid).get('style') or {})
            aid, orient = design_of(want)
            if orient != manual_orient:
                st['orientation'] = orient
            st['bg'] = ({'asset_id': aid, 'fit': 'stretch', 'layer': 'behind', 'area': 'page', 'opacity': 1.0} if aid else
                        {'asset_id': None, 'color': '#FFFFFF', 'layer': 'behind', 'area': 'page', 'opacity': 1.0})
            if bare:
                st['pdf_look'] = True            # صفحات القسم بتصميمها وحده، دون شكل ترويسة الدليل ونصها
            db.save_section({'style': st}, sid)
        # فواصل الصفحات التي وضعها الاستيراد حيث يتغيّر التصميم داخل القسم
        blocks = db.blocks(sid)
        changed = False
        for blk in blocks:
            st = blk.get('style') or {}
            if blk['kind'] != 'pagebreak' or 'page_look' not in st:
                continue
            k = _key(st.pop('page_look'))
            if k is None or k == want:
                st.update({'orient': 'section', 'page_bg': 0})
            else:
                aid, orient = design_of(k)
                st.update({'orient': orient, 'page_bg': aid or 'white', 'bare': bare})
            blk['style'] = st
            changed = True
        if changed:
            db.replace_blocks(sid, blocks)
    return assets


def close(look):
    doc = look.pop('doc', None) if look else None
    if doc is not None:
        doc.close()

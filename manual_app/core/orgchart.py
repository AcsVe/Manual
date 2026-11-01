"""The organisational chart as an SVG drawing, laid out automatically from the tree of units and positions.

Upper levels spread side by side; a unit whose members have nobody under them lists them in a column below it
(as most school and company charts do), which keeps wide structures readable on one page. In Arabic the chart is
mirrored so it reads from the right."""
from html import escape

BW, BH = 170, 46           # box width / minimum height
HGAP, VGAP, INDENT = 18, 34, 18
PALETTE = ['#0B3D91', '#1F6FD1', '#F28C28', '#3A8DDE', '#5B9BD5', '#7FB2E5']


def _wrap(text, size, width):
    """Splits text into lines that fit ``width`` px at font ``size`` (an estimate good for Arabic and Latin)."""
    if not text:
        return []
    per = max(6, int(width / (size * 0.55)))
    words, lines, cur = text.split(), [], ''
    for w in words:
        if cur and len(cur) + 1 + len(w) > per:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + ' ' + w).strip()
    if cur:
        lines.append(cur)
    return lines[:4]


class _Node:
    def __init__(self, unit, mode, depth):
        self.u, self.depth = unit, depth
        name_ar, name_en = unit.get('name_ar') or '', unit.get('name_en') or ''
        self.lines = []                                  # (text, size, bold, direction)
        if mode in ('ar', 'bi_side', 'bi_stack'):
            self.lines += [(t, 12, True, 'rtl') for t in _wrap(name_ar, 12, BW - 14)]
        if mode in ('en', 'bi_side', 'bi_stack') and name_en:
            self.lines += [(t, 10, mode == 'en', 'ltr') for t in _wrap(name_en, 10, BW - 14)]
        if unit.get('holder'):
            self.lines += [(t, 9.5, False, 'auto') for t in _wrap(unit['holder'], 9.5, BW - 14)]
        self.h = max(BH, 12 + sum(int(s * 1.35) for _, s, _, _ in self.lines))
        self.children = []
        self.vertical = False
        self.w = self.th = 0
        self.x = self.y = 0


def _build(unit, mode, depth, max_depth):
    n = _Node(unit, mode, depth)
    if not max_depth or depth < max_depth:
        n.children = [_build(c, mode, depth + 1, max_depth) for c in unit.get('children', []) if c.get('is_active', 1)]
    n.vertical = bool(n.children) and depth >= 1 and all(not c.children for c in n.children) and len(n.children) > 1
    return n


def _measure(n):
    for c in n.children:
        _measure(c)
    if not n.children:
        n.w, n.th = BW, n.h
    elif n.vertical:
        n.w = BW + INDENT
        n.th = n.h + sum(c.h + 10 for c in n.children) + 10
    else:
        total = sum(c.w for c in n.children) + HGAP * (len(n.children) - 1)
        n.w = max(BW, total)
        n.th = n.h + VGAP + max(c.th for c in n.children)


def _place(n, x, y, boxes, lines):
    n.x, n.y = x + (n.w - BW) / 2 if not n.vertical else x, y
    boxes.append(n)
    if not n.children:
        return
    if n.vertical:
        cy = y + n.h + 10
        trunk_x = n.x + 10
        for c in n.children:
            c.x, c.y = n.x + INDENT, cy
            boxes.append(c)
            lines.append(('h', trunk_x, cy + c.h / 2, c.x, cy + c.h / 2, c.u.get('link')))
            last = cy + c.h / 2
            cy += c.h + 10
        lines.append(('v', trunk_x, y + n.h, trunk_x, last, 'solid'))
        return
    total = sum(c.w for c in n.children) + HGAP * (len(n.children) - 1)
    cx = x + (n.w - total) / 2
    mid_y = y + n.h + VGAP / 2
    centers = []
    for c in n.children:
        _place(c, cx, y + n.h + VGAP, boxes, lines)
        centers.append((c.x + BW / 2, c.u.get('link')))
        cx += c.w + HGAP
    px = n.x + BW / 2
    lines.append(('v', px, y + n.h, px, mid_y, 'solid'))
    if len(centers) > 1:
        lines.append(('h', centers[0][0], mid_y, centers[-1][0], mid_y, 'solid'))
    for cxx, style in centers:
        lines.append(('v', cxx, mid_y, cxx, y + n.h + VGAP, style))


def render_svg(roots, mode='bi_side', colors=None, font='Tajawal', max_depth=0, title=None):
    """roots: units with 'children' (db.org_tree). Returns an SVG string (empty string when there is nothing)."""
    colors = colors or {}
    palette = [colors.get('primary', PALETTE[0]), colors.get('secondary', PALETTE[1]), colors.get('accent', PALETTE[2])] + PALETTE[3:]
    nodes = [_build(r, mode, 0, max_depth) for r in roots]
    if not nodes:
        return ''
    for n in nodes:
        _measure(n)
    boxes, lines = [], []
    x = 10
    for n in nodes:
        _place(n, x, 10, boxes, lines)
        x += n.w + HGAP * 2
    W = x - HGAP * 2 + 10
    H = max(n.th for n in nodes) + 20
    rtl = mode in ('ar', 'bi_side', 'bi_stack')

    def mx(v, w=0):
        return (W - v - w) if rtl else v
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" height="{H:.0f}" '
           f'font-family="{escape(font)}, Tajawal, Arial, sans-serif" role="img"'
           + (f' aria-label="{escape(title)}"' if title else '') + '>']
    for kind, x1, y1, x2, y2, style in lines:
        dash = ' stroke-dasharray="5 4"' if style == 'dashed' else ''
        out.append(f'<line x1="{mx(x1):.1f}" y1="{y1:.1f}" x2="{mx(x2):.1f}" y2="{y2:.1f}" stroke="#7a8aa6" stroke-width="1.4"{dash}/>')
    for b in boxes:
        col = b.u.get('color') or palette[min(b.depth, len(palette) - 1)]
        light = b.depth >= 2 and not b.u.get('color')
        fill = '#EAF1FC' if light else col
        txt = '#0B2A5B' if light else '#FFFFFF'
        bx = mx(b.x, BW)
        stroke = col if light else 'none'
        out.append(f'<rect x="{bx:.1f}" y="{b.y:.1f}" width="{BW}" height="{b.h}" rx="7" fill="{fill}" stroke="{stroke}"/>')
        total = sum(int(s * 1.35) for _, s, _, _ in b.lines)
        ty = b.y + (b.h - total) / 2
        for text, size, bold, direction in b.lines:
            ty += size * 1.35
            out.append(f'<text x="{bx + BW / 2:.1f}" y="{ty - size * 0.3:.1f}" font-size="{size}" text-anchor="middle" '
                       f'fill="{txt}"{" font-weight=" + chr(34) + "700" + chr(34) if bold else ""}'
                       f'{" direction=" + chr(34) + direction + chr(34) if direction != "auto" else ""}>{escape(text)}</text>')
    out.append('</svg>')
    return '\n'.join(out)

"""Backgrounds of the pages, the cover and the sections, all described the same way:

    {'asset_id': image or None, 'color': '#RRGGBB' or '',
     'layer': 'behind' | 'front'          behind the text, or over it (see-through, like a watermark)
     'area': 'page' | 'section'           sections only: every page of the section, or behind its text only
     'fit': 'cover' | 'contain' | 'stretch' | 'width'
     'pos': one of POSITIONS, 'scale': percent (fit «width»), 'rotate': 0/90/180/270, 'flip': mirrored,
     'opacity': 0..1}

Older manuals kept only an image, an opacity and a fit (page_bg_id, cover.bg_id, section style bg_id): they are read
here as the same description, so nothing has to be converted.
"""
import base64
import re

POSITIONS = {
    'top-right': ('أعلى اليمين', 'Top right'), 'top': ('أعلى الوسط', 'Top centre'), 'top-left': ('أعلى اليسار', 'Top left'),
    'right': ('وسط اليمين', 'Middle right'), 'center': ('الوسط', 'Centre'), 'left': ('وسط اليسار', 'Middle left'),
    'bottom-right': ('أسفل اليمين', 'Bottom right'), 'bottom': ('أسفل الوسط', 'Bottom centre'),
    'bottom-left': ('أسفل اليسار', 'Bottom left'),
}
CSS_POS = {'top-right': 'right top', 'top': 'center top', 'top-left': 'left top', 'right': 'right center',
           'center': 'center center', 'left': 'left center', 'bottom-right': 'right bottom', 'bottom': 'center bottom',
           'bottom-left': 'left bottom'}
FITS = {'cover': ('تملأ المساحة (قد يُقصّ طرف منها)', 'Fill the area (an edge may be cut)'),
        'contain': ('الصورة كاملة داخل المساحة', 'The whole image inside the area'),
        'stretch': ('تمديد على المساحة كلها', 'Stretched over the whole area'),
        'width': ('بنسبة من عرض المساحة', 'A share of the area width')}
LAYERS = {'behind': ('خلف النص', 'Behind the text'), 'front': ('أمام النص (شفافة فوقه)', 'In front of the text (see-through)')}
AREAS = {'page': ('كل صفحات القسم (الصفحة كاملة)', 'Every page of the section (the whole page)'),
         'section': ('خلف نص القسم فقط', 'Behind the section text only')}
ROTATIONS = {0: ('دون تدوير', 'Not turned'), 90: ('90° مع عقارب الساعة', '90° clockwise'), 180: ('180°', '180°'),
             270: ('90° عكس عقارب الساعة', '90° anticlockwise')}
DEFAULT = {'asset_id': None, 'color': '', 'layer': 'behind', 'area': 'page', 'fit': 'cover', 'pos': 'center',
           'scale': 100, 'rotate': 0, 'flip': False, 'opacity': 1.0}


def normalize(bg):
    out = dict(DEFAULT)
    out.update({k: v for k, v in (bg or {}).items() if k in DEFAULT})
    try:
        out['opacity'] = min(1.0, max(0.02, float(out['opacity'])))
    except (TypeError, ValueError):
        out['opacity'] = 1.0
    try:
        out['scale'] = min(400, max(5, int(out['scale'])))
    except (TypeError, ValueError):
        out['scale'] = 100
    out['rotate'] = int(out.get('rotate') or 0) % 360 if int(out.get('rotate') or 0) % 90 == 0 else 0
    if out['fit'] not in FITS:
        out['fit'] = 'cover'
    if out['pos'] not in POSITIONS:
        out['pos'] = 'center'
    if out['layer'] not in LAYERS:
        out['layer'] = 'behind'
    if out['area'] not in AREAS:
        out['area'] = 'page'
    if out['color'] and not re.fullmatch(r'#[0-9a-fA-F]{6}', out['color']):
        out['color'] = ''
    return out


def active(bg):
    return bool(bg and (bg.get('asset_id') or bg.get('color')))


def of_page(lay):
    """The background of every page of the manual."""
    if lay.get('page_bg'):
        return normalize(lay['page_bg'])
    if lay.get('page_bg_id'):
        return normalize({'asset_id': lay['page_bg_id'], 'opacity': lay.get('page_bg_opacity', 0.06)})
    return None


def of_cover(lay):
    cv = lay.get('cover') or {}
    if cv.get('bg'):
        return normalize(cv['bg'])
    if cv.get('bg_id'):
        return normalize({'asset_id': cv['bg_id'], 'opacity': cv.get('bg_opacity', 1.0)})
    return None


def of_section(style):
    st = style or {}
    if st.get('bg'):
        return normalize(st['bg'])
    if st.get('bg_id'):
        return normalize({'asset_id': st['bg_id'], 'area': 'page' if st.get('bg_mode') == 'page' else 'section',
                          'opacity': st.get('bg_opacity', 0.15), 'fit': st.get('bg_fit', 'cover')})
    return None


def size_css(bg):
    return {'cover': 'cover', 'contain': 'contain', 'stretch': '100% 100%'}.get(bg['fit'], f'{bg["scale"]}% auto')


def image_uri(uri, w, h, bg):
    """The image turned, mirrored and faded as asked, wrapped in an SVG of the turned size (CSS can do none of
    these to a background)."""
    if not uri:
        return ''
    w, h = int(w or 1000), int(h or 750)
    rot, flip, op = bg['rotate'], bg['flip'], bg['opacity']
    if not rot and not flip and op >= 0.999:
        return uri
    W, H = (h, w) if rot in (90, 270) else (w, h)
    t = []
    t.append(f'translate({W / 2:.1f},{H / 2:.1f})')
    if rot:
        t.append(f'rotate({rot})')
    if flip:
        t.append('scale(-1,1)')
    t.append(f'translate({-w / 2:.1f},{-h / 2:.1f})')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{W}" height="{H}" '
           f'viewBox="0 0 {W} {H}" preserveAspectRatio="none"><image width="{w}" height="{h}" transform="{" ".join(t)}" '
           f'opacity="{op:.2f}" href="{uri}" xlink:href="{uri}"/></svg>')
    return 'data:image/svg+xml;base64,' + base64.b64encode(svg.encode()).decode()


def css(bg, uri):
    """«background» for a box: the image layer (if any) over the colour (if any)."""
    parts = []
    if uri:
        parts.append(f'url("{uri}") {CSS_POS[bg["pos"]]} / {size_css(bg)} no-repeat')
    if bg.get('color'):
        parts.append(_faded_color(bg['color'], bg['opacity']) if not uri else bg['color'])
    return ', '.join(parts)


def _faded_color(c, op):
    r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
    return f'rgba({r},{g},{b},{op:.2f})'


def summary(bg, L, asset_name=None):
    """One line for the form: what the background is."""
    if not active(bg):
        return L('بلا خلفية', 'No background')
    bg = normalize(bg)
    bits = []
    if bg.get('asset_id'):
        bits.append(asset_name or L('صورة', 'Image'))
    if bg.get('color'):
        bits.append(L('لون ', 'colour ') + bg['color'])
    bits.append(L(*LAYERS[bg['layer']]))
    bits.append(L(*FITS[bg['fit']]).split(' (')[0])
    bits.append(L(*POSITIONS[bg['pos']]))
    if bg['rotate']:
        bits.append(f'{bg["rotate"]}°')
    if bg['flip']:
        bits.append(L('معكوسة', 'mirrored'))
    bits.append(f'{round(bg["opacity"] * 100)}%')
    return ' · '.join(bits)

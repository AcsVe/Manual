"""Text inside a block: plain text or a small, safe subset of HTML (bold, italic, underline, colour, links, line
breaks). Anything else that comes in (from the editor, Word or a web page) is reduced to that subset."""
import re
from html import escape
from html.parser import HTMLParser

ALLOWED = {'b': 'b', 'strong': 'b', 'i': 'i', 'em': 'i', 'u': 'u', 'a': 'a', 'br': 'br', 'span': 'span',
           'sub': 'sub', 'sup': 'sup', 'mark': 'mark', 's': 's', 'p': None, 'div': None}
_COLOR = re.compile(r'(?:^|;)\s*(color|background-color)\s*:\s*(#[0-9a-fA-F]{3,8}|rgb\([0-9,\s]+\))', re.I)
_WEIGHT = re.compile(r'font-weight\s*:\s*(bold|[6-9]00)', re.I)
_ITALIC = re.compile(r'font-style\s*:\s*italic', re.I)
_UNDER = re.compile(r'text-decoration[^;]*underline', re.I)


class _Clean(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.stack, self.blocks = [], [], 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        a = dict(attrs)
        if tag in ('p', 'div', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
            if self.out and self.out[-1] != '<br>':
                self.out.append('<br>')
            self.stack.append(None)
            return
        if tag == 'br':
            self.out.append('<br>')
            return
        if tag not in ALLOWED:
            self.stack.append(None)
            return
        name = ALLOWED[tag]
        if name == 'a':
            href = (a.get('href') or '').strip()
            if not re.match(r'^(https?://|mailto:|#)', href, re.I):
                self.stack.append(None)
                return
            self.out.append(f'<a href="{escape(href, quote=True)}">')
            self.stack.append('a')
            return
        if name == 'span':
            style = a.get('style') or ''
            opens = []
            if _WEIGHT.search(style):
                opens.append('b')
            if _ITALIC.search(style):
                opens.append('i')
            if _UNDER.search(style):
                opens.append('u')
            css = ';'.join(f'{m.group(1).lower()}:{m.group(2)}' for m in _COLOR.finditer(style))
            for t in opens:
                self.out.append(f'<{t}>')
            if css:
                self.out.append(f'<span style="{escape(css, quote=True)}">')
                opens.append('span')
            self.stack.append(opens or None)
            return
        self.out.append(f'<{name}>')
        self.stack.append(name)

    def handle_endtag(self, tag):
        if not self.stack:
            return
        top = self.stack.pop()
        if top is None:
            return
        for t in reversed(top if isinstance(top, list) else [top]):
            self.out.append(f'</{t}>')

    def handle_data(self, data):
        self.out.append(escape(data, quote=False))


def clean(text):
    """Safe inline HTML for a block side. Plain text keeps its line breaks."""
    if not text:
        return ''
    if '<' not in text:
        return escape(text, quote=False).replace('\n', '<br>')
    if 'qrichtext' in text or '<body' in text.lower():           # Qt's full document → its body only
        m = re.search(r'<body[^>]*>(.*)</body>', text, re.S | re.I)
        text = m.group(1) if m else text
        text = re.sub(r'>\s*\n\s*<', '><', text)                 # Qt's layout line breaks are not content
    p = _Clean()
    p.feed(text)
    p.close()
    html = ''.join(p.out)
    html = re.sub(r'^(\s|<br>)+|(\s|<br>)+$', '', html)
    return re.sub(r'(<br>){3,}', '<br><br>', html)


def plain(text):
    """The words only (for Word export, search and lists)."""
    if not text:
        return ''
    if '<' not in text:
        return text
    s = re.sub(r'<br\s*/?>', '\n', clean(text))
    s = re.sub(r'<[^>]+>', '', s)
    from html import unescape
    return unescape(s).strip()


def lines(text):
    """List items: one per line."""
    return [ln.strip(' •-\t') for ln in plain(text).split('\n') if ln.strip(' •-\t')]


def runs(text):
    """Inline formatting as runs [(text, {'b','i','u','color','href'})] — used by the Word export."""
    html = clean(text)
    out = []
    state = {'b': 0, 'i': 0, 'u': 0, 'color': [], 'href': []}

    class P(HTMLParser):
        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag in ('b', 'i', 'u'):
                state[tag] += 1
            elif tag == 'span':
                m = re.search(r'color:(#[0-9a-fA-F]{6})', a.get('style') or '')
                state['color'].append(m.group(1) if m else None)
            elif tag == 'a':
                state['href'].append(a.get('href'))
            elif tag == 'br':
                out.append(('\n', {}))

        def handle_endtag(self, tag):
            if tag in ('b', 'i', 'u') and state[tag]:
                state[tag] -= 1
            elif tag == 'span' and state['color']:
                state['color'].pop()
            elif tag == 'a' and state['href']:
                state['href'].pop()

        def handle_data(self, data):
            col = next((c for c in reversed(state['color']) if c), None)
            out.append((data, {'b': state['b'] > 0, 'i': state['i'] > 0, 'u': state['u'] > 0, 'color': col,
                               'href': state['href'][-1] if state['href'] else None}))
    P(convert_charrefs=True).feed(html)
    return out

"""初期HTML用の安全なMarkdown表示。ブラウザでは従来のmarkedが表示を更新する。"""
import html
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit
from rakuten_links import prepare, MARKER


def safe_url(value, image=False):
    value = html.unescape(value).strip()
    if any(ord(c) < 32 for c in value) or '\\' in value:
        return ''
    try:
        parsed = urlsplit(value)
        if parsed.username or parsed.password:
            return ''
        if parsed.scheme and parsed.scheme.lower() not in ({'http', 'https'} if image else {'http', 'https', 'mailto', 'tel'}):
            return ''
        return value
    except ValueError:
        return ''


class Sanitizer(HTMLParser):
    tags = set('p br hr h2 h3 h4 h5 h6 ul ol li strong em b i del blockquote pre code a img figure figcaption table thead tbody tfoot tr th td div span video source iframe'.split())
    void = {'img', 'br', 'hr', 'source'}
    attrs = {'class', 'id', 'title', 'alt', 'width', 'height', 'colspan', 'rowspan', 'scope', 'controls', 'muted', 'playsinline', 'preload', 'allowfullscreen', 'data-embed-type', 'data-embed-id', 'data-style', 'data-from-embed', 'data-token', 'aria-label'}

    def __init__(self, verified=None):
        super().__init__(convert_charrefs=True)
        self.out, self.stack, self.blocked = [], [], 0
        self.verified = verified or {}

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'object'}:
            self.blocked += 1
            return
        if self.blocked or tag not in self.tags:
            return
        values = dict(attrs)
        if tag == 'iframe':
            try:
                u = urlsplit(values.get('src', ''))
                valid = u.scheme == 'https' and u.hostname in {'youtube.com', 'www.youtube.com', 'youtube-nocookie.com', 'www.youtube-nocookie.com'} and not u.port and not u.username and not u.password and re.fullmatch(r'/embed/[A-Za-z0-9_-]{11}', u.path)
            except ValueError:
                valid = False
            if not valid:
                return
        verified = self.verified.get(values.get(MARKER)) if tag == 'a' and set(values) == {MARKER} else None
        out = [(k, v or '') for k, v in verified] if verified else []
        for key, value in ([] if verified else attrs):
            if key in {'href', 'src', 'poster'}:
                value = safe_url(value or '', key != 'href')
                if value:
                    out.append((key, value))
            elif key in self.attrs:
                out.append((key, value or ''))
        if tag == 'img':
            out.append(('loading', 'lazy'))
        if tag == 'iframe':
            if not values.get('title', '').strip():
                out = [(k, v) for k, v in out if k != 'title']
                out.append(('title', 'YouTube動画'))
            out.extend([('loading', 'lazy'), ('referrerpolicy', 'strict-origin-when-cross-origin')])
        if tag == 'a' and not verified:
            rel = [x for x in values.get('rel', '').lower().split() if x in {'nofollow', 'sponsored', 'ugc', 'noopener', 'noreferrer'}]
            if values.get('target') == '_blank':
                out.append(('target', '_blank'))
                if 'noopener' not in rel:
                    rel.append('noopener')
            out.append(('rel', ' '.join(rel) or 'noopener noreferrer'))
        self.out.append('<' + tag + ''.join(' ' + k + '="' + html.escape(v, quote=True) + '"' for k, v in out) + '>')
        if tag not in self.void:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.void:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'object'}:
            self.blocked = max(0, self.blocked - 1)
            return
        if not self.blocked and tag in self.stack:
            while self.stack:
                item = self.stack.pop()
                self.out.append('</' + item + '>')
                if item == tag:
                    break

    def handle_data(self, value):
        if not self.blocked:
            self.out.append(html.escape(value))

    def result(self):
        return ''.join(self.out) + ''.join('</' + x + '>' for x in reversed(self.stack))


def sanitize(value):
    value, verified = prepare(value)
    parser = Sanitizer(verified)
    parser.feed(value)
    parser.close()
    return parser.result()


def inline(value):
    tokens = []

    def save(markup):
        tokens.append(markup)
        return '\x00' + str(len(tokens) - 1) + '\x00'

    value = value.replace('\x00', '')
    value = re.sub(r'`([^`]+)`', lambda m: save('<code>' + html.escape(m[1]) + '</code>'), value)
    # タグは最終段階で許可リストによりサニタイズする。
    value = re.sub(r'<[^>]+>', lambda m: save(m[0]), value)

    def link(m):
        image, label, url = m[1], m[2], m[3].strip('<>')
        url = safe_url(url, bool(image))
        if not url:
            return html.escape(label)
        if image:
            return save('<img src="' + html.escape(url, quote=True) + '" alt="' + html.escape(html.unescape(label), quote=True) + '">')
        return save('<a href="' + html.escape(url, quote=True) + '">' + html.escape(html.unescape(label)) + '</a>')

    value = re.sub(r'(!?)\[([^\]]*)\]\(([^\s)]+)(?:\s+"[^"]*")?\)', link, value)
    # CommonMarkの行末バックスラッシュ改行。コード・HTML・画像URLは上のトークンで保護済み。
    value = re.sub(r'(\\+)\n', lambda m: '\\' * (len(m[1]) // 2) +
                   (save('<br>\n') if len(m[1]) % 2 else '\n'), value)
    value = html.escape(html.unescape(value))
    value = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', value)
    value = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', value)
    value = re.sub(r'~~(.+?)~~', r'<del>\1</del>', value)
    return re.sub(r'\x00(\d+)\x00', lambda m: tokens[int(m[1])], value)


def render(source):
    """現在の記事で使用する見出し・段落・画像・リンク・表・リスト・HTMLに対応。"""
    lines = str(source or '').replace('\r\n', '\n').splitlines()
    out, paragraph, items = [], [], []
    list_tag = None

    def flush():
        nonlocal list_tag
        if paragraph:
            out.append('<p>' + inline('\n'.join(paragraph)).replace('  \n', '<br>\n') + '</p>')
            paragraph.clear()
        if items:
            out.append('<' + list_tag + '>' + ''.join('<li>' + inline(x) + '</li>' for x in items) + '</' + list_tag + '>')
            items.clear()
            list_tag = None

    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            flush()
            i += 1
            continue
        if line.startswith(('```', '~~~')):
            flush()
            fence, code = line[:3], []
            i += 1
            while i < len(lines) and not lines[i].startswith(fence):
                code.append(lines[i])
                i += 1
            out.append('<pre><code>' + html.escape('\n'.join(code)) + '</code></pre>')
        elif re.match(r'^\s*<(?:div|figure|table|video|iframe|blockquote)\b', line):
            flush()
            raw = [line]
            tag = re.match(r'^\s*<(\w+)', line)[1]
            while not re.search('</' + tag + r'\s*>', '\n'.join(raw), re.I) and i + 1 < len(lines):
                i += 1
                raw.append(lines[i])
            out.append('\n'.join(raw))
        elif re.match(r'^#{1,6}\s', line):
            flush()
            m = re.match(r'^(#{1,6})\s+(.*)', line)
            level = max(2, len(m[1]))
            out.append(f'<h{level}>' + inline(m[2]) + f'</h{level}>')
        elif re.fullmatch(r'\s*(?:-\s*){3,}|\s*(?:\*\s*){3,}|\s*_{3,}\s*', line):
            flush()
            out.append('<hr>')
        elif i + 1 < len(lines) and '|' in line and re.fullmatch(r'\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*', lines[i + 1]):
            flush()
            def cells(s, tag):
                return '<tr>' + ''.join('<' + tag + '>' + inline(x.strip()) + '</' + tag + '>' for x in s.strip().strip('|').split('|')) + '</tr>'
            table = '<div class="table-scroll"><table><thead>' + cells(line, 'th') + '</thead><tbody>'
            i += 2
            while i < len(lines) and '|' in lines[i] and lines[i].strip():
                table += cells(lines[i], 'td')
                i += 1
            out.append(table + '</tbody></table></div>')
            i -= 1
        elif re.match(r'^\s*(?:[-*+] |\d+\. )', line):
            m = re.match(r'^\s*([-*+]|\d+\.)\s+(.*)', line)
            tag = 'ol' if m[1][0].isdigit() else 'ul'
            if paragraph or (list_tag and list_tag != tag):
                flush()
            list_tag = tag
            items.append(m[2])
        elif line.startswith('> '):
            flush()
            out.append('<blockquote><p>' + inline(line[2:]) + '</p></blockquote>')
        else:
            if items:
                flush()
            paragraph.append(line)
        i += 1
    flush()
    return sanitize('\n'.join(out))

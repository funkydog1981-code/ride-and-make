"""ブラウザ版rakuten-links.jsと同じ限定ポリシー。属性値を正規化しない。"""
import html
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit, parse_qs

MARKER = 'data-rakuten-verified'


def valid_attributes(attrs):
    values = dict(attrs)
    if len(values) != len(attrs) or any(k not in {'href', 'rel', 'target', 'style', 'title'} for k in values):
        return False
    href = values.get('href') or ''
    try:
        u = urlsplit(href)
        if (not re.match(r'^https://hb\.afl\.rakuten\.co\.jp/', href, re.I) or u.hostname != 'hb.afl.rakuten.co.jp'
                or u.scheme.lower() != 'https' or u.username or u.password or u.port or u.fragment
                or not re.fullmatch(r'/ichiba/[A-Za-z0-9._/-]+', u.path)
                or re.search(r'[\s\\\x00-\x1f\x7f]', href) or any(x in {'.', '..'} for x in u.path.split('/'))):
            return False
        query = parse_qs(u.query, keep_blank_values=True)
        if query.get('link_type') != ['text'] or len(query.get('pc', [])) != 1:
            return False
        pc = query['pc'][0]
        product = urlsplit(pc)
        if (not re.match(r'^https?://item\.rakuten\.co\.jp/', pc, re.I) or product.hostname != 'item.rakuten.co.jp'
                or product.username or product.password or product.port or product.fragment
                or re.search(r'[\s\\\x00-\x1f\x7f]', pc) or len([x for x in product.path.split('/') if x]) < 2
                or re.search(r'(?:^|/)(?:\.|%2e){1,2}(?:/|$)', pc.split('?')[0], re.I)):
            return False
    except ValueError:
        return False
    rel = (values.get('rel') or '').lower().split()
    if (not {'nofollow', 'sponsored'}.issubset(rel)
            or any(x not in {'nofollow', 'sponsored', 'noopener', 'noreferrer', 'ugc'} for x in rel)
            or values.get('target') not in {None, '', '_blank'}
            or (values.get('target') == '_blank' and 'noopener' not in rel)):
        return False
    return 'style' not in values or bool(re.fullmatch(r'\s*word-wrap\s*:\s*break-word\s*;?\s*', values['style'] or '', re.I))


class PlainText(HTMLParser):
    def __init__(self, source):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.feed(source)

    def handle_data(self, value):
        self.text.append(value)


class LinkFilter(HTMLParser):
    """aタグを閉じるまで検証。無効な楽天リンクは安全な文字だけにする。"""
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.out, self.records, self.parents, self.anchor = [], {}, [], None

    def emit(self, value):
        (self.anchor['parts'] if self.anchor else self.out).append(value)

    def handle_starttag(self, tag, attrs):
        raw = self.get_starttag_text()
        if self.anchor:
            self.anchor['children'] = True
            if tag == 'a':
                self.anchor['depth'] += 1
            self.emit(raw)
        elif tag == 'a':
            values = dict(attrs)
            try:
                candidate = urlsplit(values.get('href') or '').hostname == 'hb.afl.rakuten.co.jp'
            except ValueError:
                candidate = False
            self.anchor = {'attrs': attrs, 'parts': [raw], 'depth': 1, 'children': False,
                           'candidate': candidate or any(card for _, card in self.parents)}
        else:
            self.emit(raw)
            if tag not in {'img', 'br', 'hr', 'source', 'input', 'meta', 'link', 'wbr', 'area', 'base', 'embed', 'param', 'col', 'track'}:
                self.parents.append((tag, 'product-card' in (dict(attrs).get('class') or '').split()))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.anchor:
            self.emit('</' + tag + '>')
            if tag == 'a':
                self.anchor['depth'] -= 1
                if self.anchor['depth'] == 0:
                    self.flush_anchor()
        else:
            self.emit('</' + tag + '>')
            for i in range(len(self.parents) - 1, -1, -1):
                if self.parents[i][0] == tag:
                    del self.parents[i:]
                    break

    def flush_anchor(self):
        a, self.anchor = self.anchor, None
        raw = ''.join(a['parts'])
        text = ''.join(PlainText(raw).text)
        if valid_attributes(a['attrs']) and not a['children'] and text.strip() and raw.lower().endswith('</a>'):
            key = str(len(self.records))
            self.records[key] = a['attrs']
            # 元属性は後段で検証済みレコードから復元する。
            opening = re.match(r'<a\b(?:[^"\'<>]|"[^"]*"|\'[^\']*\')*>', raw, re.I)
            self.out.append('<a ' + MARKER + '="' + key + '">' + raw[opening.end():])
        elif a['candidate']:
            self.out.append(html.escape(text))
        else:
            # 投稿者が承認マーカーを偽装しても後段のレコード照合に渡さない。
            clean_attrs = [(k, v) for k, v in a['attrs'] if k != MARKER]
            start = '<a' + ''.join(' ' + k + '="' + html.escape(v or '', quote=True) + '"' for k, v in clean_attrs) + '>'
            opening = re.match(r'<a\b(?:[^"\'<>]|"[^"]*"|\'[^\']*\')*>', raw, re.I)
            self.out.append(start + raw[opening.end():])

    def handle_data(self, value):
        self.emit(value)

    def handle_entityref(self, name):
        self.emit('&' + name + ';')

    def handle_charref(self, name):
        self.emit('&#' + name + ';')

    def handle_comment(self, value):
        if self.anchor:
            self.anchor['children'] = True
        self.emit('<!--' + value + '-->')


def prepare(source):
    parser = LinkFilter()
    parser.feed(source)
    parser.close()
    if parser.anchor:
        parser.anchor['candidate'] = True
        parser.flush_anchor()
    return ''.join(parser.out), parser.records

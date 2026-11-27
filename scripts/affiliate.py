"""広告の目印を本文から検出する。ブラウザ版との一致は共通ケースで検証する。"""
import html
import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

NOTICE = 'この記事にはアフィリエイト広告が含まれています。'
MARKUP = '<aside class="affiliate-disclosure" aria-label="広告について"><p>' + NOTICE + '</p><a href="/privacy/#advertising">広告・アフィリエイトについて</a></aside>'
MANUAL = r'(?:この記事|本記事|本ページ|当記事)(?:には|は)(?:アフィリエイト広告|広告|PR|プロモーション)(?:が|を)?(?:含まれ(?:てい)?ます|含みます|利用しています)'


def clean_source(source):
    lines, fence = [], None
    for line in str(source or '').splitlines():
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if fence:
            if marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and re.fullmatch(r' {0,3}(?:`+|~+)\s*', line):
                fence = None
            continue
        if marker:
            fence = marker[1]
        elif not re.match(r'^(?: {4}|\t)', line):
            lines.append(line)
    return re.sub(r'(`+)[^`]*?\1', '', '\n'.join(lines))


def rakuten_url(value):
    try:
        url = urlsplit(html.unescape(value).strip())
        return (url.scheme.lower() in {'https', 'http'} and not url.username and not url.password
                and url.hostname in {'hb.afl.rakuten.co.jp', 'hbb.afl.rakuten.co.jp', 'a.r10.to'}
                and url.port in {None, 443 if url.scheme.lower() == 'https' else 80})
    except ValueError:
        return False


class Signals(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ad, self.text, self.skip = False, [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {'script', 'style', 'pre', 'code'}:
            self.skip += 1
        if self.skip:
            return
        attrs = dict(attrs)
        if 'product-card' in attrs.get('class', '').split():
            self.ad = True
        if tag == 'a' and ('sponsored' in attrs.get('rel', '').lower().split() or rakuten_url(attrs.get('href', ''))):
            self.ad = True

    def handle_endtag(self, tag):
        if tag in {'script', 'style', 'pre', 'code'}:
            self.skip = max(0, self.skip - 1)

    def handle_data(self, value):
        if not self.skip:
            self.text.append(value)


def detect(source):
    source = clean_source(source)
    parser = Signals()
    parser.feed(source)
    # Markdownのインラインリンク・参照リンク・自動リンクも調べる。
    markdown = re.sub(r'<!--[\s\S]*?-->|<(script|style|pre|code)\b[^>]*>[\s\S]*?</\1\s*>', '', source, flags=re.I)
    urls = re.findall(r'\]\(\s*<?([^\s)>]+)|^ {0,3}\[[^\]]+\]:\s*<?([^\s>]+)|<(https?://[^\s<>]+)>', markdown, re.M | re.I)
    ad = parser.ad or any(rakuten_url(next(x for x in match if x)) for match in urls)
    manual = bool(re.search(MANUAL, re.sub(r'\s+', '', ''.join(parser.text)), re.I))
    return {'advertising': ad, 'manual': manual}


def disclosure(source):
    state = detect(source)
    return MARKUP if state['advertising'] and not state['manual'] else ''

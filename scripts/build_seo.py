"""CMSのJSONから公開用HTMLを生成。画像変換はPillow。外部通信・publicへの書き込みなし。"""
from pathlib import Path
from urllib.parse import urlsplit, quote, unquote, parse_qs
from datetime import date
import html
import json
import os
import re
import shutil
import sys
from seo_markdown import render, safe_url
from affiliate import disclosure
from optimize_images import optimize_site
from navigation import add_navigation
from analytics import apply_to_site as apply_analytics
from check_image_privacy import assert_clean as assert_private_images

ROOT = Path(__file__).resolve().parent.parent
PUBLIC, OUT = ROOT / 'public', ROOT / '_site'
SLUG = re.compile(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?')


def publish_source(path):
    """作業用ファイルやローカル認証設定を公開先へコピーしない。"""
    relative = path.relative_to(PUBLIC)
    if any(part in {'.git', '.venv', '.netlify', '.image-cache', '__pycache__'} for part in relative.parts):
        return False
    name = path.name.lower()
    return not (name in {'.ds_store', 'thumbs.db', '.env'} or name.startswith('.env.') or
                name.endswith(('.pyc', '.pyo', '.log', '.tmp', '.bak', '.orig', 'backup.zip')))


def ignore_public_files(directory, names):
    return [name for name in names if not publish_source(Path(directory) / name)]


def esc(value):
    return html.escape('' if value is None else str(value), quote=True)


def validate_images(data):
    """公開元に存在するファイルと、大文字小文字まで一致することを要求する。"""
    images = {'/' + p.relative_to(PUBLIC).as_posix() for p in PUBLIC.rglob('*') if p.is_file()}

    def check(value):
        if not isinstance(value, str) or not value.strip():
            return
        if not safe_url(value, True):
            raise ValueError('不正な画像URLです: ' + value)
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc:
            return  # 外部画像は通信せず、構造のみ確認する。
        if not parsed.path.startswith('/') or unquote(parsed.path) not in images:
            raise ValueError('画像が存在しないか、大文字小文字が一致しません: ' + value)

    def visit(value, key=''):
        if isinstance(value, dict):
            for k, v in value.items():
                visit(v, k)
        elif isinstance(value, list):
            for v in value:
                visit(v, key)
        elif isinstance(value, str):
            if key in {'image', 'hero_image', 'poster'}:
                check(value)
            for url in re.findall(r'(?<![\w:/.-])/assets/[^\s"\'<>\\()]+?\.(?:jpe?g|png|webp|gif|svg|avif|heic|ico)(?:[?#][^\s"\'<>\\()]*)?', value, re.I):
                check(url)
    visit(data)


def article_path(kind, slug):
    return ('/journeys/' if kind == 'journeys' else '/making/') + slug + '/'


def set_id(source, key, content):
    opening = re.search(r'<(?P<tag>\w+)\b[^>]*\bid="' + re.escape(key) + r'"[^>]*>', source)
    if not opening:
        raise ValueError('テンプレートに必要な要素がありません: ' + key)
    depth = 1
    for tag in re.finditer(r'</?' + opening['tag'] + r'\b[^>]*>', source[opening.end():]):
        depth += -1 if tag[0].startswith('</') else 1
        if depth == 0:
            end = opening.end() + tag.start()
            return source[:opening.end()] + content + source[end:]
    raise ValueError('テンプレートの閉じタグがありません: ' + key)


def visible(source, key):
    return re.sub(r'(<\w+\b[^>]*\bid="' + re.escape(key) + r'"[^>]*?)\s+hidden(?=[\s>])', r'\1', source, count=1)


def metadata(source, title, summary, route, base, image='', noindex=False, article=None, image_alt=''):
    source = re.sub(r'<title>.*?</title>', lambda m: '<title>' + esc(title) + '</title>', source, count=1, flags=re.S)
    # 属性順が異なる旧テンプレートにも対応する。
    source = re.sub(r'<meta\b(?=[^>]*\bname=["\']description["\'])[^>]*>', lambda m: '<meta name="description" content="' + esc(summary) + '">', source, count=1)
    url = base + route
    image = safe_url(image, True) or '/assets/hero.webp'
    image = image if urlsplit(image).scheme else base + '/' + image.lstrip('/')
    image = quote(image, safe=':/%?=&-._~')
    tags = [f'<link rel="canonical" href="{esc(url)}">',
            f'<meta property="og:type" content="{"article" if article else "website"}">',
            f'<meta property="og:site_name" content="走って、つくって。">',
            f'<meta property="og:locale" content="ja_JP">',
            f'<meta property="og:title" content="{esc(title)}">',
            f'<meta property="og:description" content="{esc(summary)}">',
            f'<meta property="og:url" content="{esc(url)}">',
            f'<meta property="og:image" content="{esc(image)}">',
            f'<meta property="og:image:alt" content="{esc((article.get("hero_image_alt") or article.get("image_alt")) if article else image_alt)}">',
            '<meta name="twitter:card" content="summary_large_image">',
            f'<meta name="twitter:title" content="{esc(title)}">',
            f'<meta name="twitter:description" content="{esc(summary)}">',
            f'<meta name="twitter:image" content="{esc(image)}">']
    if noindex:
        tags.append('<meta name="robots" content="noindex,follow">')
    if article:
        structured = {'@context': 'https://schema.org', '@type': 'Article', 'headline': article['title'],
                      'description': summary, 'image': [image], 'mainEntityOfPage': url,
                      'author': {'@type': 'Person', 'name': 'Funky Maguro'}}
        if article.get('date'):
            structured['datePublished'] = str(article['date'])
        tags.append('<script type="application/ld+json">' + json.dumps(structured, ensure_ascii=False).replace('<', '\\u003c') + '</script>')
    return source.replace('</head>', '\n' + '\n'.join(tags) + '\n</head>', 1)


def card(item, kind, top):
    making = kind == 'making_articles'
    prefix = 'journey' if top or not making else 'making'
    url = article_path(kind, item['slug'])
    category = (item.get('making_info') or {}).get('category') if making else ' / '.join(filter(None, [item.get('region'), item.get('ride_category')]))
    heading = 'h3' if prefix == 'journey' else 'h2'
    image = safe_url(item.get('image', ''), True)
    photo = f'<a class="{prefix}-card-photo" href="{url}" tabindex="-1" aria-hidden="true"><img src="{esc(image)}" alt="{esc(item.get("image_alt") or item["title"])}" loading="lazy"></a>' if image else ''
    more = '' if making else '<span>距離 ' + esc(item.get('distance') or '—') + '</span><span>獲得標高 ' + esc(item.get('ascent') or '—') + '</span>'
    return f'<article class="{prefix}-card">{photo}<div class="{prefix}-card-copy"><span class="pill">{esc(category)}</span><{heading}><a href="{url}">{esc(item["title"])}</a></{heading}><p>{esc(item.get("summary"))}</p><div class="card-meta"><span>{esc(str(item.get("date", ""))[:7].replace("-", "."))}</span>{more}</div><a class="card-link" href="{url}">記事を読む　↗</a></div></article>'


def build():
    # 元画像もGitHubへ送られるため、最適化前に検査する。ビルド中には書き換えない。
    assert_private_images(PUBLIC)
    configured = re.search(r'^site_url:\s*(\S+)', (PUBLIC / 'admin/config.yml').read_text(encoding='utf-8'), re.M)
    base = os.environ.get('SITE_URL', configured[1] if configured else '').rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise ValueError('SITE_URLには正式なHTTPSのサイトURLを指定してください（末尾の/は不要）。')
    data_bytes = (PUBLIC / 'content/site.json').read_bytes()
    data = json.loads(data_bytes.decode('utf-8-sig'))
    groups = {}
    for kind in ['journeys', 'making_articles']:
        seen = set()
        groups[kind] = data.get(kind, [])
        if not isinstance(groups[kind], list):
            raise ValueError(kind + 'は配列で指定してください。')
        for item in groups[kind]:
            slug = item.get('slug', '')
            if not isinstance(slug, str) or not SLUG.fullmatch(slug) or slug in seen or not str(item.get('title', '')).strip():
                raise ValueError(kind + 'のslug・重複・タイトルを確認してください: ' + str(slug))
            seen.add(slug)
            if not isinstance(item.get('summary'), str) or not item['summary'].strip():
                raise ValueError(kind + 'の記事概要が空です: ' + slug)
            date.fromisoformat(str(item['date'])[:10])
        groups[kind] = sorted(groups[kind], key=lambda x: x.get('date', ''), reverse=True)
    manifest_file = OUT / '.seo-build.json'
    if OUT.exists() and any(OUT.iterdir()) and not manifest_file.is_file():
        raise ValueError('_siteが既に存在します。既存データ保護のため自動上書きしません。')
    previous_state = json.loads(manifest_file.read_text(encoding='utf-8')) if manifest_file.exists() else {}
    previous = previous_state if isinstance(previous_state, list) else previous_state.get('articles', [])
    previous_sources = [] if isinstance(previous_state, list) else previous_state.get('source_files', [])
    previous_navigation = [] if isinstance(previous_state, list) else previous_state.get('navigation_files', [])
    validate_images(data)
    source_files = sorted(p.relative_to(PUBLIC).as_posix() for p in PUBLIC.rglob('*') if p.is_file() and publish_source(p))
    shutil.copytree(PUBLIC, OUT, dirs_exist_ok=True, ignore=ignore_public_files)
    for old in previous_sources:
        relative = Path(old)
        if old not in source_files and not relative.is_absolute() and '..' not in relative.parts:
            target = OUT / relative
            if target.is_file():
                target.unlink()
    generated = []
    sitemap = ['/', '/journeys/', '/making/', '/contact/', '/privacy/']
    for kind, articles in groups.items():
        for item in articles:
            making = kind == 'making_articles'
            route = article_path(kind, item['slug'])
            template = 'making-article/index.html' if making else 'journey/index.html'
            page = (PUBLIC / template).read_text(encoding='utf-8')
            body = disclosure(item.get('body', '')) + render(item.get('body', ''))
            page = set_id(page, 'article-body', body)
            page = set_id(page, 'article-date', esc(str(item.get('date', ''))[:7].replace('-', '.')))
            image = safe_url(item.get('hero_image') or item.get('image') or '', True)
            alt = item.get('hero_image_alt') or item.get('image_alt') or item['title']
            if making:
                page = visible(page, 'making-article')
                page = set_id(page, 'article-status', '')
                page = page.replace('id="article-status"', 'id="article-status" hidden')
                page = page.replace('aria-busy="true"', 'aria-busy="false"')
                page = set_id(page, 'article-title', esc(item['title']))
                page = set_id(page, 'article-summary', esc(item.get('summary')))
                if item.get('summary'):
                    page = visible(page, 'article-summary')
                category = (item.get('making_info') or {}).get('category', '')
                page = set_id(page, 'article-category', esc(category))
                if category:
                    page = visible(page, 'article-category')
                if image:
                    page = visible(page, 'article-hero')
                    page = re.sub(r'<img id="hero-image"[^>]*>', lambda m: '<img id="hero-image" src="' + esc(image) + '" alt="' + esc(alt) + '" fetchpriority="high">', page)
                caption = item.get('hero_image_caption')
                if caption:
                    page = visible(set_id(page, 'hero-caption', esc(caption)), 'hero-caption')
                values = [x for x in (item.get('making_info') or {}).get('production_data', []) if str(x.get('value', '')).strip()]
                page = set_id(page, 'production-data', ''.join('<dt>' + esc(x.get('label')) + '</dt><dd>' + esc(x.get('value')) + '</dd>' for x in values))
                if values:
                    page = visible(page, 'production-info')
                page = re.sub(r'<noscript>.*?</noscript>', '', page, flags=re.S)
            else:
                page = re.sub(r'(<div class="hero-copy">\s*)<h1>.*?</h1>\s*<p>.*?</p>', lambda m: m[1] + '<h1>' + esc(item['title']) + '</h1><p>' + esc(item.get('summary')) + '</p>', page, count=1, flags=re.S)
                page = re.sub(r'(<section class="hero">\s*)<img[^>]*>', lambda m: m[1] + '<img src="' + esc(image) + '" alt="' + esc(alt) + '" fetchpriority="high">', page, count=1)
                page = set_id(page, 'article-breadcrumb', esc(item['title']))
                page = set_id(page, 'article-category-label', esc(' / '.join(filter(None, [item.get('region'), item.get('ride_category')]))))
                page = re.sub(r'(<section class="intro" id="story">[\s\S]*?)<h2>.*?</h2>\s*<p>.*?</p>', lambda m: m[1] + '<h2>' + esc(item.get('intro_title') or item['title']) + '</h2><p>' + esc(item.get('intro') or item.get('summary')) + '</p>', page, count=1, flags=re.S)
            page = metadata(page, item['title'] + '｜走って、つくって。', item.get('summary', ''), route, base, image, article=item)
            dest = OUT / route.strip('/') / 'index.html'
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(page, encoding='utf-8')
            generated.append(dest.relative_to(OUT).as_posix())
            sitemap.append(route)
    # 削除された記事の生成物だけを除去。素材やpublic内のファイルは削除しない。
    for old in previous:
        if old not in generated and re.fullmatch(r'(journeys|making)/[a-z0-9-]+/index\.html', old):
            (OUT / old).unlink(missing_ok=True)
    active_journeys = {x['slug'] for x in groups['journeys']}
    # publicに残る旧記事HTMLも、CMSから削除された記事として扱う。
    for legacy in (OUT / 'journeys').glob('*/index.html'):
        if legacy.parent.name not in active_journeys and 'id="article-body"' in legacy.read_text(encoding='utf-8'):
            legacy.unlink()
    for route, kind, grid, top in [('/', 'journeys', 'latest-journeys', True), ('/', 'making_articles', 'latest-making', True), ('/journeys/', 'journeys', 'all-journeys', False), ('/making/', 'making_articles', 'all-making-articles', False)]:
        dest = OUT / route.strip('/') / 'index.html'
        page = dest.read_text(encoding='utf-8')
        articles = groups[kind][:3] if top else groups[kind]
        page = set_id(page, grid, ''.join(card(x, kind, top) for x in articles) or '<p>記事はまだありません。</p>')
        page = page.replace('aria-busy="true"', 'aria-busy="false"')
        dest.write_text(page, encoding='utf-8')
    for route in sitemap[:5]:
        dest = OUT / route.strip('/') / 'index.html'
        page = dest.read_text(encoding='utf-8')
        title = html.unescape(re.search(r'<title>(.*?)</title>', page, re.S)[1])
        desc_tag = re.search(r'<meta\b(?=[^>]*name=["\']description["\'])[^>]*>', page)[0]
        summary = html.unescape(re.search(r'content=["\']([^"\']*)', desc_tag)[1])
        dest.write_text(metadata(page, title, summary, route, base, image_alt=data.get('hero', {}).get('image_alt', '')), encoding='utf-8')
    for relative in ['admin/index.html', 'journey/index.html', 'making-article/index.html']:
        dest = OUT / relative
        page = dest.read_text(encoding='utf-8').replace('</head>', '<meta name="robots" content="noindex,follow">\n</head>', 1)
        dest.write_text(page, encoding='utf-8')
    navigation_files, category_routes = add_navigation(PUBLIC, OUT, groups, base, card, set_id, metadata, article_path,
                                                       previous_navigation, data.get('hero', {}).get('image_alt', ''))
    sitemap.extend(category_routes)
    # 公開用コピーのJSだけを新URLへ対応させる。CMSや通常のpublicプレビューは維持する。
    for filename in ['journey-list.js', 'cms-content.js', 'making-list.js']:
        dest = OUT / 'assets/js' / filename
        js = dest.read_text(encoding='utf-8').replace('/journey/?slug=${encodeURIComponent(slug)}', '/journeys/${encodeURIComponent(slug)}/').replace('/making-article/?slug=${encodeURIComponent(item.slug)}', '/making/${encodeURIComponent(item.slug)}/')
        dest.write_text(js, encoding='utf-8')
    dest = OUT / 'assets/js/making-article.js'
    js = dest.read_text(encoding='utf-8').replace("new URLSearchParams(window.location.search).get('slug')", "new URLSearchParams(window.location.search).get('slug') || decodeURIComponent(window.location.pathname.split('/').filter(Boolean)[1] || '')")
    js = js.replace('entries.forEach((entry) => {', "get('production-data').replaceChildren();\n    entries.forEach((entry) => {")
    dest.write_text(js, encoding='utf-8')
    # Netlifyは末尾スラッシュを正規化するため、重複するルールは出力しない。
    redirects = ['/journey/ slug=:slug /journeys/:slug/? 301!', '/making-article/ slug=:slug /making/:slug/? 301!']
    (OUT / '_redirects').write_text('\n'.join(redirects) + '\n', encoding='utf-8')
    (OUT / '_headers').write_text('/admin/*\n  X-Robots-Tag: noindex, nofollow\n/journey/*\n  X-Robots-Tag: noindex, follow\n/making-article/*\n  X-Robots-Tag: noindex, follow\n', encoding='utf-8')
    (OUT / 'robots.txt').write_text('User-agent: *\nAllow: /\n\nSitemap: ' + base + '/sitemap.xml\n', encoding='utf-8')
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    xml += ''.join('  <url><loc>' + esc(base + route) + '</loc></url>\n' for route in sitemap)
    (OUT / 'sitemap.xml').write_text(xml + '</urlset>\n', encoding='utf-8')
    error_page = (PUBLIC / 'privacy/index.html').read_text(encoding='utf-8')
    error_page = re.sub(r'<main>.*?</main>', '<main><h1>ページが見つかりません</h1><p>URLが変更されたか、ページが存在しません。</p><p><a href="/">トップページへ</a> / <a href="/journeys/">旅の記事一覧</a> / <a href="/making/">制作記事一覧</a></p></main>', error_page, flags=re.S)
    error_page = re.sub(r'<title>.*?</title>', '<title>ページが見つかりません｜走って、つくって。</title>', error_page)
    error_page = error_page.replace('</head>', '<meta name="robots" content="noindex,follow"></head>')
    (OUT / '404.html').write_text(error_page, encoding='utf-8')
    for dest in OUT.rglob('*.html'):
        page = dest.read_text(encoding='utf-8')
        for kind, articles in groups.items():
            old = '/journey/?slug=' if kind == 'journeys' else '/making-article/?slug='
            for item in articles:
                page = page.replace('href="' + old + item['slug'] + '"', 'href="' + article_path(kind, item['slug']) + '"')
        # 固定フッターに残った削除記事リンクは、文字を残してリンクだけ無効にする。
        active_paths = {article_path(k, x['slug']) for k, items in groups.items() for x in items}
        def footer_links(match):
            def anchor(a):
                url = urlsplit(html.unescape(a[2]))
                if url.scheme or url.netloc:
                    return a[0]
                target = url.path
                if target.rstrip('/') in {'/journey', '/making-article'}:
                    slug = parse_qs(url.query).get('slug', [''])[0]
                    target = ('/journeys/' if target.rstrip('/') == '/journey' else '/making/') + slug + '/'
                if re.fullmatch(r'/(?:journeys|making)/[a-z0-9-]+/', target) and target not in active_paths:
                    return a[1] + 'aria-disabled="true"' + a[3]
                return a[0]
            return re.sub(r'(<a\b[^>]*?)href="([^"]+)"([^>]*>)', anchor, match[0])
        page = re.sub(r'<footer\b[^>]*>.*?</footer>', footer_links, page, flags=re.S)
        dest.write_text(page, encoding='utf-8')
    optimize_site(ROOT, PUBLIC, OUT)
    assert_private_images(OUT)
    apply_analytics(OUT, base, sitemap)
    manifest_file.write_text(json.dumps({'articles': generated, 'source_files': source_files, 'navigation_files': navigation_files}, ensure_ascii=False, indent=2), encoding='utf-8')
    if (PUBLIC / 'content/site.json').read_bytes() != data_bytes:
        raise RuntimeError('ビルド中にsite.jsonが更新されました。再実行してください。')
    print(f'公開用HTML生成完了: {OUT} / 記事{len(generated)}件 / サイトマップ{len(sitemap)}件 / {base}')


if __name__ == '__main__':
    sys.dont_write_bytecode = True
    build()

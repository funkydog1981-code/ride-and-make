"""既存カード・CMS分類を利用した、JavaScript不要の回遊リンク生成。"""
import hashlib
import html
import json
import re

LABELS = {'journeys': '旅の記録', 'making_articles': '道具とものづくり'}
CATEGORY_IDS = {
    '日帰りグループライド': 'day-group', '日帰りソロライド': 'day-solo',
    '宿泊グループライド': 'overnight-group', '宿泊ソロライド': 'overnight-solo', 'イベントライド': 'event',
    '3Dプリンター・自作パーツ': '3d-printing', '自転車用品・カスタマイズ': 'bike-custom',
    'メンテナンス': 'maintenance', 'DIY': 'diy', 'その他モノづくり': 'other',
}


def esc(value):
    return html.escape(str(value or ''), quote=True)


def listing(kind):
    return '/journeys/' if kind == 'journeys' else '/making/'


def category(item, kind):
    return item.get('ride_category', '') if kind == 'journeys' else (item.get('making_info') or {}).get('category', '')


def categories(items, kind):
    return list(dict.fromkeys(category(item, kind) for item in items if category(item, kind)))


def category_path(kind, label):
    identifier = CATEGORY_IDS.get(label) or 'category-' + hashlib.sha256(label.encode()).hexdigest()[:12]
    return listing(kind) + 'category/' + identifier + '/'


def recent(groups):
    # 同じ公開日の記事は、CMSデータの登録順を維持する。
    return sorted([(kind, item) for kind, items in groups.items() for item in items],
                  key=lambda pair: pair[1].get('date', ''), reverse=True)[:3]


def related(current, items, kind):
    def rank(item):
        points = 0
        label = category(current, kind)
        if label and category(item, kind) == label:
            points += 1
        if kind == 'journeys' and current.get('region') and current.get('region') == item.get('region'):
            points += 2
        return points, item.get('date', '')
    return sorted([item for item in items if item['slug'] != current['slug']], key=rank, reverse=True)[:3]


def compact_card(item, kind, route_for):
    url = route_for(kind, item['slug'])
    image = item.get('image') or ''
    # 元データはビルドの画像URL検証を通過済み。表示する文字列は常にエスケープする。
    thumb = '<a class="discovery-thumb" href="' + url + '" tabindex="-1" aria-hidden="true"><img src="' + esc(image) + '" alt="' + esc(item.get('image_alt') or item['title']) + '" loading="lazy"></a>' if image else ''
    return '<article class="discovery-card">' + thumb + '<div class="discovery-copy"><span class="discovery-category">' + esc(LABELS[kind] + ' / ' + category(item, kind)) + '</span><h3><a href="' + url + '">' + esc(item['title']) + '</a></h3><time datetime="' + esc(str(item.get('date', ''))[:10]) + '">' + esc(str(item.get('date', ''))[:7].replace('-', '.')) + '</time></div></article>'


def filters(items, kind, selected=''):
    links = '<a href="' + listing(kind) + '"' + (' aria-current="page"' if not selected else '') + '>すべて（' + str(len(items)) + '）</a>'
    for label in categories(items, kind):
        count = sum(category(item, kind) == label for item in items)
        links += '<a href="' + category_path(kind, label) + '"' + (' aria-current="page"' if selected == label else '') + '>' + esc(label) + '（' + str(count) + '）</a>'
    return '<nav class="discovery-filters" aria-label="カテゴリーで記事を探す">' + links + '</nav>' if items else ''


def breadcrumb(kind, title, category_label=''):
    label = category_label or title
    return '<nav class="discovery-breadcrumb" aria-label="パンくずリスト"><a href="/">トップ</a><span aria-hidden="true">›</span><a href="' + listing(kind) + '">' + LABELS[kind] + '</a><span aria-hidden="true">›</span><span id="article-breadcrumb" aria-current="page">' + esc(label) + '</span></nav>'


def decorate_head(page, base, kind=None, title='', route=''):
    extras = '<link rel="stylesheet" href="/assets/css/navigation.css">'
    if kind:
        data = {'@context': 'https://schema.org', '@type': 'BreadcrumbList', 'itemListElement': [
            {'@type': 'ListItem', 'position': 1, 'name': 'トップ', 'item': base + '/'},
            {'@type': 'ListItem', 'position': 2, 'name': LABELS[kind], 'item': base + listing(kind)},
            {'@type': 'ListItem', 'position': 3, 'name': title, 'item': base + route}]}
        extras += '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False).replace('<', '\\u003c') + '</script>'
    return page.replace('</head>', extras + '\n</head>', 1)


def add_navigation(public, output, groups, base, render_card, set_id, metadata, route_for, previous_files, site_image_alt=''):
    files, routes = [], []
    home = output / 'index.html'
    page = home.read_text(encoding='utf-8')
    latest = recent(groups)
    if latest:
        section = '<section class="wrap discovery-latest" id="latest-articles" aria-labelledby="latest-articles-title"><span class="eyebrow">LATEST STORIES</span><h2 id="latest-articles-title">新しい記事から。</h2><div class="discovery-grid">' + ''.join(compact_card(item, kind, route_for) for kind, item in latest) + '</div></section>'
        marker = '<section class="wrap" id="journeys">'
        if marker not in page:
            raise ValueError('トップページの記事欄が見つかりません。')
        page = page.replace(marker, section + '\n' + marker, 1)
    home.write_text(decorate_head(page, base), encoding='utf-8')

    for kind, items in groups.items():
        root_page = output / listing(kind).strip('/') / 'index.html'
        grid = 'all-journeys' if kind == 'journeys' else 'all-making-articles'
        page = root_page.read_text(encoding='utf-8')
        opening = re.search(r'<div\b[^>]*id="' + grid + '"[^>]*>', page)
        page = page[:opening.start()] + filters(items, kind) + page[opening.start():]
        # 静的カードがあるため、従来の「JSを有効に」の案内は表示しない。
        page = re.sub(r'<noscript>.*?</noscript>', '', page, flags=re.S)
        root_page.write_text(decorate_head(page, base), encoding='utf-8')
        for label in categories(items, kind):
            route = category_path(kind, label)
            template = (public / listing(kind).strip('/') / 'index.html').read_text(encoding='utf-8')
            template = re.sub(r'<h1>.*?</h1>', lambda m: '<h1>' + esc(label) + '</h1>', template, count=1, flags=re.S)
            template = re.sub(r'<div class="breadcrumb">.*?</div>', lambda m: breadcrumb(kind, label, label), template, count=1, flags=re.S)
            filtered = [item for item in items if category(item, kind) == label]
            template = set_id(template, grid, ''.join(render_card(item, kind, False) for item in filtered))
            opening = re.search(r'<div\b[^>]*id="' + grid + '"[^>]*>', template)
            template = template[:opening.start()] + filters(items, kind, label) + template[opening.start():]
            # 選択済み一覧を、既存の全件表示JSで上書きさせない。
            template = re.sub(r'<script\b[^>]*src="/assets/js/(?:journey-list|making-list)\.js"[^>]*>\s*</script>', '', template)
            template = re.sub(r'<noscript>.*?</noscript>', '', template, flags=re.S).replace('aria-busy="true"', 'aria-busy="false"')
            template = metadata(template, label + 'の記事一覧｜走って、つくって。', LABELS[kind] + 'から「' + label + '」の記事を紹介します。', route, base, image_alt=site_image_alt)
            template = decorate_head(template, base, kind, label, route)
            destination = output / route.strip('/') / 'index.html'
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(template, encoding='utf-8')
            files.append(destination.relative_to(output).as_posix())
            routes.append(route)

        for index, item in enumerate(items):
            route = route_for(kind, item['slug'])
            destination = output / route.strip('/') / 'index.html'
            page = destination.read_text(encoding='utf-8')
            crumb = breadcrumb(kind, item['title'])
            if kind == 'journeys':
                page, replaced = re.subn(r'<div style="padding:14px 7%;font-size:12px">.*?</div>', lambda m: crumb, page, count=1, flags=re.S)
                if replaced != 1:
                    raise ValueError('旅記事のパンくずが見つかりません。')
            else:
                page = page.replace('<p id="article-status"', crumb + '\n<p id="article-status"', 1)
            older = items[index + 1] if index + 1 < len(items) else None
            newer = items[index - 1] if index else None
            def neighbor(article, label):
                return '<div><a href="' + route_for(kind, article['slug']) + '"><small>' + label + '</small><span>' + esc(article['title']) + '</span></a></div>' if article else '<div></div>'
            pager = '<nav class="discovery-pagination" aria-label="記事間の移動">' + neighbor(older, '← 前の記事（古い記事）') + '<div><a href="' + listing(kind) + '">記事一覧へ戻る</a></div>' + neighbor(newer, '次の記事（新しい記事）→') + '</nav>'
            suggestions = related(item, items, kind)
            related_section = '<section class="discovery-related" aria-labelledby="related-title"><h2 id="related-title">あわせて読みたい記事</h2><div class="discovery-grid">' + ''.join(compact_card(other, kind, route_for) for other in suggestions) + '</div></section>' if suggestions else ''
            assembly = '<div class="discovery-area">' + pager + related_section + '</div>'
            if kind == 'journeys':
                marker = '</article>\n</main>'
                if marker not in page:
                    raise ValueError('旅記事の末尾が見つかりません。')
                page = page.replace(marker, '</article>\n' + assembly + '\n</main>', 1)
            else:
                page, replaced = re.subn(r'<p class="back"><a href="/making/">.*?</a></p>', lambda m: assembly, page, count=1, flags=re.S)
                if replaced != 1:
                    raise ValueError('制作記事の一覧リンクが見つかりません。')
            page = decorate_head(page, base, kind, item['title'], route)
            destination.write_text(page, encoding='utf-8')
    for old in previous_files:
        if old not in files and re.fullmatch(r'(?:journeys|making)/category/[a-z0-9-]+/index\.html', old):
            (output / old).unlink(missing_ok=True)
    return files, routes

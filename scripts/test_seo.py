"""外部通信・元データ更新なし。生成物・ローカルHTTP・隔離CMSデータを検証。"""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit, unquote
import html
import json
import re
import copy
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import analytics
import affiliate
from rakuten_links import valid_attributes
from test_image_privacy import ImagePrivacyTests
import xml.etree.ElementTree as ET
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from urllib.request import urlopen
from urllib.error import HTTPError
from email.utils import parsedate_to_datetime
from seo_markdown import render
from build_seo import ROOT, OUT, article_path, rss_feed
from preview_seo import Handler
from navigation import category, categories, category_path, recent, related


def original_url(url, output=OUT):
    manifest = json.loads((output / 'assets/image-manifest.json').read_text(encoding='utf-8'))
    lookup = {v['src']: source for source, item in manifest['images'].items() for v in item['variants'] + ([item['og']] if 'og' in item else [])}
    return lookup.get(unquote(urlsplit(url).path), url)


def restore_image_urls(value, output):
    manifest = json.loads((output / 'assets/image-manifest.json').read_text(encoding='utf-8'))
    lookup = {v['src']: source for source, item in manifest['images'].items() for v in item['variants']}
    def restore(item):
        if isinstance(item, dict):
            return {k: restore(v) for k, v in item.items()}
        if isinstance(item, list):
            return [restore(v) for v in item]
        if isinstance(item, str):
            return re.sub(r'/assets/optimized/[a-z0-9.-]+', lambda m: lookup.get(m[0], m[0]), item)
        return item
    return restore(value)


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.meta, self.canonicals, self.images, self.links = {}, [], [], []
        self.h1 = 0
        self.stack = []
        self.areas = {key: [] for key in ['recent', 'related', 'pagination', 'filters', 'breadcrumb', 'listing']}
        self.filter_current = []
        self.resources = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta':
            self.meta[attrs.get('name') or attrs.get('property')] = attrs.get('content')
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonicals.append(attrs['href'])
        if tag == 'img' and attrs.get('src'):
            self.images.append(attrs['src'])
            self.images.extend(x.strip().split()[0] for x in attrs.get('srcset', '').split(',') if x.strip())
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])
            ids = {a.get('id') for t, a in self.stack}
            classes = {c for t, a in self.stack for c in a.get('class', '').split()}
            active = {'recent': 'latest-articles' in ids, 'related': 'discovery-related' in classes,
                      'pagination': 'discovery-pagination' in classes, 'filters': 'discovery-filters' in classes,
                      'breadcrumb': 'discovery-breadcrumb' in classes,
                      'listing': bool(ids & {'all-journeys', 'all-making-articles'})}
            for key, yes in active.items():
                if yes:
                    self.areas[key].append(attrs['href'])
            if active['filters'] and attrs.get('aria-current') == 'page':
                self.filter_current.append(attrs['href'])
        if tag == 'script' and attrs.get('src'):
            self.resources.append(attrs['src'])
        if tag == 'link' and attrs.get('rel') == 'stylesheet':
            self.resources.append(attrs['href'])
        self.h1 += tag == 'h1'
        if tag not in {'meta', 'link', 'img', 'br', 'hr', 'source', 'input', 'area', 'base', 'embed', 'wbr'}:
            self.stack.append((tag, attrs))

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


class SEOTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / 'public/content/site.json').read_text(encoding='utf-8'))
        cls.pages = []
        for kind in ['journeys', 'making_articles']:
            for item in cls.data[kind]:
                route = article_path(kind, item['slug'])
                source = (OUT / route.strip('/') / 'index.html').read_text(encoding='utf-8')
                cls.pages.append((kind, item, route, source, Page(source)))

    def test_article_metadata_in_initial_html(self):
        for kind, item, route, source, page in self.pages:
            with self.subTest(route=route):
                self.assertIn(html.escape(item['title']), source)
                self.assertEqual(page.meta['description'], item['summary'])
                self.assertEqual(page.meta['og:description'], item['summary'])
                self.assertEqual(page.meta['og:title'], item['title'] + '｜走って、つくって。')
                self.assertEqual(page.meta['twitter:card'], 'summary_large_image')
                for name in ['description', 'og:title', 'og:description', 'og:image', 'og:url', 'twitter:title', 'twitter:description', 'twitter:image']:
                    self.assertTrue(page.meta.get(name, '').strip(), route + ': ' + name)
                self.assertEqual(len(page.canonicals), 1)
                self.assertTrue(page.canonicals[0].endswith(route))
                self.assertEqual(page.meta['og:url'], page.canonicals[0])
                self.assertTrue(page.meta['og:image'].startswith('https://'))
                self.assertEqual(page.h1, 1)
                self.assertNotIn('robots', page.meta)

    def test_body_headings_images_and_schema_in_initial_html(self):
        for kind, item, route, source, page in self.pages:
            with self.subTest(route=route):
                for heading in re.findall(r'^##\s+(.+)', item['body'], re.M):
                    self.assertIn('<h2>' + html.escape(heading) + '</h2>', source)
                # Markdown画像の任意タイトルはURLの一部ではない。
                for image in re.findall(r'!\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)', item['body']):
                    self.assertIn(image.strip('<>'), [original_url(url) for url in page.images])
                schema = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', source, re.S)[1])
                self.assertEqual(schema['headline'], item['title'])
                self.assertEqual(schema['@type'], 'Article')

    def test_all_static_links_and_images(self):
        for file in OUT.rglob('*.html'):
            if 'admin' in file.parts:
                continue
            page = Page(file.read_text(encoding='utf-8'))
            for url in page.images + page.links + page.resources:
                parsed = urlsplit(url)
                if parsed.scheme or parsed.netloc or not parsed.path or not parsed.path.startswith('/'):
                    continue
                target = OUT / unquote(parsed.path).lstrip('/')
                self.assertTrue(target.is_file() or (target / 'index.html').is_file(), str(file) + ': ' + url)
                # Windowsでも大文字小文字の差を検出する。
                current = OUT
                for part in target.relative_to(OUT).parts:
                    self.assertIn(part, [p.name for p in current.iterdir()])
                    current = current / part
            for name in ['og:image', 'twitter:image']:
                url = page.meta.get(name)
                if url and urlsplit(url).netloc == urlsplit(page.meta.get('og:url', '')).netloc:
                    target = OUT / unquote(urlsplit(url).path).lstrip('/')
                    self.assertTrue(target.is_file(), str(file) + ': ' + name)

    def test_ga4_is_disabled_without_production_settings(self):
        base = 'https://resonant-fairy-4cc735.netlify.app'
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(analytics.load_settings(base))
        for context in ['', 'dev', 'deploy-preview', 'branch-deploy']:
            with patch.dict(os.environ, {'CONTEXT': context, 'GA4_ENABLED': 'true',
                                       'GA4_MEASUREMENT_ID': 'TEST_ONLY_NOT_A_MEASUREMENT_ID'}, clear=True):
                self.assertIsNone(analytics.load_settings(base))
        with patch.dict(os.environ, {'CONTEXT': 'production', 'GA4_ENABLED': 'true'}, clear=True):
            self.assertIsNone(analytics.load_settings(base))
        with patch.dict(os.environ, {'CONTEXT': 'production', 'GA4_ENABLED': 'true',
                                   'GA4_MEASUREMENT_ID': 'TEST_ONLY_NOT_A_MEASUREMENT_ID'}, clear=True):
            with self.assertRaises(ValueError):
                analytics.load_settings(base)

    def test_ga4_insertion_is_single_and_reversible(self):
        # 測定IDは作らない。設定取得だけをモックし、IDでない試験用文字列を使用。
        config = {'measurement_id': 'TEST_ONLY_NOT_A_MEASUREMENT_ID',
                  'origin': 'https://resonant-fairy-4cc735.netlify.app'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'index.html').write_text('<html><head><title>試験</title></head><body></body></html>', encoding='utf-8')
            (root / 'admin').mkdir()
            (root / 'admin/index.html').write_text('<html><head></head><body></body></html>', encoding='utf-8')
            with patch('analytics.load_settings', return_value=config):
                analytics.apply_to_site(root, config['origin'], ['/'])
                analytics.apply_to_site(root, config['origin'], ['/'])
            self.assertEqual((root / 'index.html').read_text(encoding='utf-8').count('id="site-ga4"'), 1)
            self.assertNotIn('site-ga4', (root / 'admin/index.html').read_text(encoding='utf-8'))
            with patch('analytics.load_settings', return_value=None):
                analytics.apply_to_site(root, config['origin'], ['/'])
            self.assertNotIn('site-ga4', (root / 'index.html').read_text(encoding='utf-8'))

    def test_ga4_runtime_never_loads_offsite_or_before_consent(self):
        config = {'measurement_id': 'TEST_ONLY_NOT_A_MEASUREMENT_ID',
                  'origin': 'https://resonant-fairy-4cc735.netlify.app'}
        code = re.search(r'<script[^>]*>(.*?)</script>', analytics.markup(config), re.S)[1]
        runner = r"""
const vm = require('vm'); const code = JSON.parse(process.argv[1]);
function run(origin, granted=true, storageError=false) {
  const loaded=[]; const ctx={URL, addEventListener(){}, SiteAnalyticsConsent:{hasConsent(){if(storageError)throw Error('blocked');return granted}}, location:{origin,protocol:new URL(origin).protocol,pathname:'/making/article/'},
    localStorage:{getItem(){if(storageError)throw Error('blocked');return granted?'granted':null}},
    document:{referrer:'https://example.org/from?email=private#secret',createElement(){return {}},head:{appendChild(s){loaded.push(s.src)}}}};
  ctx.window=ctx;vm.createContext(ctx);vm.runInContext(code,ctx);vm.runInContext(code,ctx);
  return {loaded,events:(ctx.dataLayer||[]).map(x=>Array.from(x))};
}
console.log(JSON.stringify([
 run('http://localhost:8000'),run('http://127.0.0.1:4174'),
 run('https://deploy-preview-1--resonant-fairy-4cc735.netlify.app'),
 run('https://resonant-fairy-4cc735.netlify.app',false),
 run('https://resonant-fairy-4cc735.netlify.app',true,true),
 run('https://resonant-fairy-4cc735.netlify.app')
]));
"""
        result = subprocess.run(['node', '-e', runner, json.dumps(code)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        cases = json.loads(result.stdout)
        for case in cases[:-1]:
            self.assertEqual(case, {'loaded': [], 'events': []})
        self.assertEqual(len(cases[-1]['loaded']), 1)
        configs = [event for event in cases[-1]['events'] if event[0] == 'config']
        self.assertEqual(len(configs), 1)
        self.assertFalse(configs[0][2]['allow_google_signals'])
        self.assertFalse(configs[0][2]['allow_ad_personalization_signals'])
        self.assertEqual(configs[0][2]['page_location'], config['origin'] + '/making/article/')
        self.assertEqual(configs[0][2]['page_referrer'], 'https://example.org/from')

    def test_ga4_consent_changes_stop_measurement(self):
        config = {'measurement_id': 'TEST_ONLY_NOT_A_MEASUREMENT_ID',
                  'origin': 'https://resonant-fairy-4cc735.netlify.app'}
        code = re.search(r'<script[^>]*>(.*?)</script>', analytics.markup(config), re.S)[1]
        runner = r"""
const vm=require('vm');let granted=false;const loaded=[],events={};
const ctx={URL,location:{origin:'https://resonant-fairy-4cc735.netlify.app',protocol:'https:',pathname:'/'},
 SiteAnalyticsConsent:{hasConsent:()=>granted},addEventListener(n,f){events[n]=f},
 document:{referrer:'',createElement(){return {}},head:{appendChild(s){loaded.push(s)}}}};
ctx.window=ctx;vm.createContext(ctx);vm.runInContext(JSON.parse(process.argv[1]),ctx);
const before=loaded.length;granted=true;events['ride-and-make:analytics-consent']();
const afterGrant=loaded.length;events['ride-and-make:analytics-consent']();
granted=false;events['ride-and-make:analytics-consent']();
console.log(JSON.stringify({before,afterGrant,afterRepeatedEvent:loaded.length,
 disabled:ctx['ga-disable-TEST_ONLY_NOT_A_MEASUREMENT_ID']}));
"""
        result = subprocess.run(['node', '-e', runner, json.dumps(code)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'before': 0, 'afterGrant': 1,
                         'afterRepeatedEvent': 1, 'disabled': True})

    def test_consent_controls_and_policy(self):
        base = Page((OUT / 'index.html').read_text(encoding='utf-8')).canonicals[0].rstrip('/')
        settings = analytics.load_settings(base)
        routes = {urlsplit(node.text).path for node in
                  ET.fromstring((OUT / 'sitemap.xml').read_text()).findall('{*}url/{*}loc')}
        targets = {OUT / route.lstrip('/') / 'index.html' for route in routes}
        for file in OUT.rglob('*.html'):
            text = file.read_text(encoding='utf-8')
            if not settings or file not in targets:
                self.assertNotIn('id="site-consent-script"', text)
                self.assertNotIn('class="analytics-consent-open"', text)
            elif '<footer' in text:
                self.assertEqual(text.count('id="site-consent-script"'), 1, str(file))
                self.assertEqual(text.count('class="analytics-consent-open"'), 1, str(file))
                self.assertIn('aria-controls="analytics-consent-panel"', text)
        policy = (OUT / 'privacy/index.html').read_text(encoding='utf-8')
        self.assertIn('id="analytics"', policy)
        self.assertIn('policies.google.com/technologies/partner-sites', policy)
        self.assertIn('同意撤回', policy)
        self.assertIn('<noscript>', policy)

    def test_disabled_consent_assets_are_removed_on_rebuild(self):
        config = {'measurement_id': 'TEST_ONLY_NOT_A_MEASUREMENT_ID',
                  'origin': 'https://resonant-fairy-4cc735.netlify.app'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / 'index.html'
            file.write_text('<html><head></head><body><footer><div></div></footer></body></html>', encoding='utf-8')
            with patch('analytics.load_settings', return_value=config):
                analytics.apply_to_site(root, config['origin'], ['/'])
                analytics.apply_to_site(root, config['origin'], ['/'])
            text = file.read_text(encoding='utf-8')
            self.assertEqual(text.count('id="site-consent-script"'), 1)
            self.assertEqual(text.count('class="analytics-consent-open"'), 1)
            with patch('analytics.load_settings', return_value=None):
                analytics.apply_to_site(root, config['origin'], ['/'])
            text = file.read_text(encoding='utf-8')
            self.assertNotIn('id="site-consent-script"', text)
            self.assertNotIn('class="analytics-consent-open"', text)
            self.assertNotIn('id="site-ga4"', text)

    def test_ga4_output_matches_environment(self):
        base = Page((OUT / 'index.html').read_text(encoding='utf-8')).canonicals[0].rstrip('/')
        settings = analytics.load_settings(base)
        routes = [urlsplit(node.text).path for node in
                  ET.fromstring((OUT / 'sitemap.xml').read_text()).findall('{*}url/{*}loc')]
        targets = {OUT / route.lstrip('/') / 'index.html' for route in routes}
        for file in OUT.rglob('*.html'):
            expected = 1 if settings and file in targets else 0
            self.assertEqual(file.read_text(encoding='utf-8').count('id="site-ga4"'), expected, str(file))

    def test_homepage_verification_tags_are_preserved(self):
        class VerificationTags(HTMLParser):
            def __init__(self, source):
                super().__init__()
                self.in_head = False
                self.tags = []
                self.feed(source)

            def handle_starttag(self, tag, attrs):
                if tag == 'head':
                    self.in_head = True
                values = dict(attrs)
                if self.in_head and tag == 'meta' and values.get('name') == 'google-site-verification':
                    self.tags.append(values.get('content'))

            def handle_endtag(self, tag):
                if tag == 'head':
                    self.in_head = False

        original = VerificationTags((ROOT / 'public/index.html').read_text(encoding='utf-8')).tags
        generated = VerificationTags((OUT / 'index.html').read_text(encoding='utf-8')).tags
        self.assertEqual(original, generated)

    def test_sitemap_and_noindex(self):
        sitemap = ET.fromstring((OUT / 'sitemap.xml').read_text(encoding='utf-8'))
        locations = [n.text for n in sitemap.findall('{*}url/{*}loc')]
        category_count = sum(len(categories(self.data[kind], kind)) for kind in ['journeys', 'making_articles'])
        self.assertEqual(len(locations), 5 + len(self.pages) + category_count)
        self.assertEqual(len(locations), len(set(locations)))
        for kind, item, route, source, page in self.pages:
            self.assertIn(page.canonicals[0], locations)
        self.assertNotIn('/admin/', '\n'.join(locations))
        for f in ['admin/index.html', 'journey/index.html', 'making-article/index.html', '404.html']:
            self.assertIn('noindex', Page((OUT / f).read_text(encoding='utf-8')).meta['robots'])
        self.assertIn('sitemap.xml', (OUT / 'robots.txt').read_text(encoding='utf-8'))

    def test_static_cards_and_urls(self):
        for route, kind in [('/journeys/', 'journeys'), ('/making/', 'making_articles')]:
            page = Page((OUT / route.strip('/') / 'index.html').read_text(encoding='utf-8'))
            for item in self.data[kind]:
                self.assertIn(article_path(kind, item['slug']), page.links)
        home = Page((OUT / 'index.html').read_text(encoding='utf-8'))
        for kind in ['journeys', 'making_articles']:
            for item in sorted(self.data[kind], key=lambda x: x['date'], reverse=True)[:3]:
                self.assertIn(article_path(kind, item['slug']), home.links)
        redirects = (OUT / '_redirects').read_text(encoding='utf-8')
        self.assertIn('/journey/ slug=:slug /journeys/:slug/? 301!', redirects)
        self.assertNotIn(' 200', redirects)

    def test_navigation_links_and_combined_recent(self):
        home = Page((OUT / 'index.html').read_text(encoding='utf-8'))
        expected = [article_path(kind, item['slug']) for kind, item in recent(self.data_groups())]
        self.assertEqual(list(dict.fromkeys(home.areas['recent'])), expected)
        for kind, item, route, source, page in self.pages:
            candidates = list(dict.fromkeys(page.areas['related']))
            self.assertNotIn(route, candidates)
            self.assertLessEqual(len(candidates), 3)
            self.assertEqual(candidates, [article_path(kind, x['slug']) for x in related(item, self.data[kind], kind)])
            self.assertTrue(all(x.startswith('/journeys/' if kind == 'journeys' else '/making/') for x in candidates))
            ordered = sorted(self.data[kind], key=lambda x: x['date'], reverse=True)
            index = next(i for i, x in enumerate(ordered) if x['slug'] == item['slug'])
            expected_pager = {('/journeys/' if kind == 'journeys' else '/making/')}
            expected_pager.update(article_path(kind, ordered[i]['slug']) for i in [index - 1, index + 1] if 0 <= i < len(ordered))
            self.assertEqual(set(page.areas['pagination']), expected_pager)
            self.assertIn('/', page.areas['breadcrumb'])
            self.assertIn('/journeys/' if kind == 'journeys' else '/making/', page.areas['breadcrumb'])
            schemas = [json.loads(x) for x in re.findall(r'<script type="application/ld\+json">(.*?)</script>', source, re.S)]
            self.assertIn('Article', [x['@type'] for x in schemas])
            self.assertIn('BreadcrumbList', [x['@type'] for x in schemas])

    def test_footers_do_not_show_fixed_article_dates(self):
        for root in [ROOT / 'public', OUT]:
            for file in root.rglob('*.html'):
                for footer in re.findall(r'<footer\b[^>]*>.*?</footer>', file.read_text(encoding='utf-8'), re.S):
                    self.assertNotIn('旅の記録：2026年8月 / 更新：2026年10月25日', footer, str(file))
        for kind, item, route, source, page in self.pages:
            if kind == 'journeys':
                footer = re.search(r'<footer\b[^>]*>.*?</footer>', source, re.S)[0]
                self.assertIn('/contact/', footer)
                self.assertIn('/privacy/', footer)

    def data_groups(self):
        return {kind: sorted(self.data[kind], key=lambda x: x['date'], reverse=True) for kind in ['journeys', 'making_articles']}

    def test_static_category_pages(self):
        sitemap = (OUT / 'sitemap.xml').read_text(encoding='utf-8')
        for kind, items in self.data_groups().items():
            for label in categories(items, kind):
                route = category_path(kind, label)
                source = (OUT / route.strip('/') / 'index.html').read_text(encoding='utf-8')
                page = Page(source)
                expected = [article_path(kind, x['slug']) for x in items if category(x, kind) == label]
                self.assertEqual(list(dict.fromkeys(page.areas['listing'])), expected)
                self.assertEqual(page.filter_current, [route])
                self.assertTrue(page.canonicals[0].endswith(route))
                self.assertIn(route, sitemap)
                self.assertNotRegex(source, r'<script[^>]+src="/assets/js/(?:journey-list|making-list)\.js"')

    def test_affiliate_disclosure_cases_and_static_output(self):
        cases = json.loads((ROOT / 'scripts/fixtures/affiliate_cases.json').read_text(encoding='utf-8'))
        for case in cases:
            with self.subTest(case=case['name']):
                self.assertEqual(affiliate.detect(case['body']), {k: case[k] for k in ['advertising', 'manual']})
                self.assertEqual(bool(affiliate.disclosure(case['body'])), case['advertising'] and not case['manual'])
        for _, item, _, source, _ in self.pages:
            expected = bool(affiliate.disclosure(item.get('body', '')))
            self.assertEqual(source.count('class="affiliate-disclosure"'), int(expected))
        policy = (OUT / 'privacy/index.html').read_text(encoding='utf-8')
        for text in ['楽天アフィリエイト', '紹介料', '販売事業者', 'analytics-policy-status', 'Tally']:
            self.assertIn(text, policy)

    def test_sanitizer(self):
        for source in ['<script>alert(1)</script>', '![](javascript:alert)', '<img src="/safe.jpg" onerror="alert(1)">', '<iframe src="https://evil.invalid/embed/abcdefghijk"></iframe>']:
            output = render(source)
            self.assertNotIn('<script', output)
            self.assertNotIn('javascript:', output)
            self.assertNotIn('onerror=', output)
            self.assertNotIn('evil.invalid', output)
        self.assertIn('youtube-nocookie.com/embed/abcdefghijk', render('<iframe src="https://www.youtube-nocookie.com/embed/abcdefghijk"></iframe>'))

    def test_product_card_and_affiliate_link_safety(self):
        url = 'https://hb.afl.rakuten.co.jp/ichiba/example/?pc=https%3A%2F%2Fitem.rakuten.co.jp%2Ftest%2Fitem%2F&link_type=text&ut=' + 'a' * 1200
        card = '<div class="product-card"><img src="/assets/hero.webp" alt="商品写真"><div class="product-card__body"><h3>商品名</h3><p>説明</p><p><a href="' + html.escape(url, quote=True) + '" target="_blank" rel="nofollow sponsored noopener">商品名を楽天市場で見る</a></p></div></div>'
        output = render('※この記事にはアフィリエイト広告が含まれます。\n\n' + card + '\n\n' + card)
        page = Page(output)
        self.assertEqual(output.count('class="product-card"'), 2)
        self.assertEqual(page.links.count(url), 2)
        self.assertEqual(output.count('target="_blank"'), 2)
        self.assertEqual(output.count('rel="nofollow sponsored noopener"'), 2)
        self.assertNotIn('onclick', output)
        self.assertIn('rel="sponsored noopener"', render('<a href="https://example.com" target="_blank" rel="sponsored evil">商品</a>'))
        self.assertNotIn('target=', render('<a href="https://example.com" target="evil">商品</a>'))

    def test_rakuten_attributes_and_rejected_inputs(self):
        cases = json.loads((ROOT / 'scripts/fixtures/rakuten_links.json').read_text(encoding='utf-8'))
        # DOMから取り出す属性値を入力し、実際のJS検証関数との一致もCIで確認する。
        runner = r"""
const fs = require('fs'), vm = require('vm');
const payload = JSON.parse(fs.readFileSync(0, 'utf8'));
const context = {window: {}, URL};
vm.runInNewContext(fs.readFileSync(payload.script, 'utf8'), context);
const results = payload.cases.map(c => context.window.RakutenLinks.check({
  attributes: Object.entries(c.attrs).map(([name, value]) => ({name, value})),
  children: [], childNodes: [{nodeType: 3}], textContent: c.label
}));
process.stdout.write(JSON.stringify(results));
"""
        result = subprocess.run(['node', '-e', runner],
                                input=json.dumps({'script': str(ROOT / 'public/assets/js/rakuten-links.js'), 'cases': cases}),
                                capture_output=True, text=True, check=True)
        for case, checked in zip(cases, json.loads(result.stdout)):
            self.assertEqual(checked['valid'], case['valid'], case['name'])
            if case['valid']:
                self.assertEqual(checked['attrs'], case['attrs'])
        for case in cases:
            with self.subTest(case=case['name']):
                attrs = case['attrs']
                self.assertEqual(valid_attributes(list(attrs.items())), case['valid'] or case['name'] == 'blank-label')
                anchor = '<a' + ''.join(' ' + k + '="' + html.escape(v, quote=True) + '"' for k, v in attrs.items()) + '>' + html.escape(case['label']) + '</a>'
                for source in [anchor, '<div class="product-card">' + anchor + '</div>']:
                    output = render(source)
                    parser = Page(output)
                    if case['valid']:
                        self.assertIn(attrs['href'], parser.links)
                        # HTMLParserで属性値を比較（エンティティの表記差は別物として扱わない）。
                        class Anchors(HTMLParser):
                            def handle_starttag(self, tag, values):
                                if tag == 'a': self.attrs = dict(values)
                        a = Anchors(); a.feed(output)
                        self.assertEqual(a.attrs, attrs)
                        self.assertIn(html.escape(case['label']), output)
                    elif 'href="https://hb.afl.rakuten.co.jp/' in anchor or source.startswith('<div'):
                        self.assertFalse(parser.links)
                    self.assertNotIn('data-rakuten-verified', output)
                    self.assertNotIn('onclick=', output)
        sample = cases[0]['attrs']
        for child in ['<img src="/assets/hero.webp">', '<b>商品</b>', '<script>alert(1)</script>']:
            tag = '<a' + ''.join(' ' + k + '="' + html.escape(v, quote=True) + '"' for k, v in sample.items()) + '>' + child + '</a>'
            self.assertNotIn('href=', render(tag))

    def test_link_entities_are_escaped_once(self):
        output = render('<a href="https://example.com/?x=1&amp;y=2">A &amp; B &lt;C&gt; &quot;D&quot; &#39;E&#39;</a>')
        class Text(HTMLParser):
            def __init__(self): super().__init__(); self.text = []
            def handle_data(self, value): self.text.append(value)
        parser = Text(); parser.feed(output)
        self.assertEqual(''.join(parser.text), 'A & B <C> "D" \'E\'')
        self.assertNotIn('&amp;amp;', output)
        escaped = render('&lt;img src=x onerror=alert(1)&gt;')
        self.assertNotIn('<img', escaped)
        self.assertIn('&lt;img', escaped)
        self.assertIn('&amp;amp;', render('`&amp;`'))

    def test_markdown_backslash_break_does_not_touch_code_or_images(self):
        source = '![写真](/assets/hero.webp)\\\n写真の説明\n\n次の段落'
        result = render(source)
        self.assertIn('<br>\n写真の説明', result)
        self.assertNotIn('\\\n写真の説明', result)
        self.assertIn('src="/assets/hero.webp"', result)
        self.assertIn('<p>次の段落</p>', result)
        self.assertNotIn('<br>', render('普通の改行\n続き'))
        self.assertIn('<br>', render('空白の改行  \n続き'))
        self.assertIn('\\', render('二重' + '\\' * 2 + '\n続き'))
        self.assertNotIn('<br>', render('二重' + '\\' * 2 + '\n続き'))
        self.assertIn('<br>', render('三重' + '\\' * 3 + '\n続き'))
        self.assertIn('<code>\\</code>', render('`\\`'))
        code = render('```\n\\\n```')
        self.assertIn('<pre><code>\\</code></pre>', code)

    def test_markdown_table_and_text(self):
        output = render('## 見出し\n\n本文の**強調**と[リンク](/privacy/)。\n\n| 項目 | 値 |\n| --- | --- |\n| 費用 | 5円 |')
        for token in ['<h2>見出し</h2>', '<strong>強調</strong>', '<table>', '<td>5円</td>', 'href="/privacy/"']:
            self.assertIn(token, output)

    def test_youtube_channel_and_video_markup(self):
        channel = 'https://www.youtube.com/channel/UCoxnBBcvXtO9DqRjDJId24w'
        for file in OUT.rglob('*.html'):
            if file.relative_to(OUT).parts[0] == 'admin':
                continue
            page = file.read_text(encoding='utf-8')
            for section in ['header', 'footer']:
                block = re.search('<' + section + r'\b[^>]*>.*?</' + section + '>', page, re.S)
                self.assertIsNotNone(block, str(file))
                self.assertIn(channel, block[0], str(file))
                links = re.findall(r'<a\b[^>]*>', block[0])
                link = next(tag for tag in links if channel in tag)
                self.assertIn('target="_blank"', link)
                self.assertIn('rel="noopener noreferrer"', link)
        self.assertIn('class="youtube-channel"', (OUT / 'index.html').read_text(encoding='utf-8'))
        for kind in ['journeys', 'making_articles']:
            result = render('## 動画\n\n<iframe src="https://www.youtube.com/embed/nXEZ7wvYxMs"></iframe>')
            self.assertIn('title="YouTube動画"', result)
            self.assertIn('loading="lazy"', result)
        self.assertNotIn('<iframe', render('## 動画なし\n\n本文のみ'))
        self.assertNotIn('<iframe', render('<iframe src="https://example.com/embed/nXEZ7wvYxMs"></iframe>'))

    def test_only_referenced_social_images_are_published(self):
        manifest = json.loads((OUT / 'assets/image-manifest.json').read_text(encoding='utf-8'))
        html_pages = '\n'.join(p.read_text(encoding='utf-8') for p in OUT.rglob('*.html'))
        expected = set()
        for record in manifest['images'].values():
            for image in record['variants'] + ([record['og']] if 'og' in record else []):
                expected.add(Path(image['src']).name)
            if 'og' in record:
                self.assertIn(record['og']['src'], html_pages)
        self.assertEqual(expected, {p.name for p in (OUT / 'assets/optimized').iterdir() if p.is_file()})
        # JSフォールバックとSVGは残し、本文用に置換済みの大きな元画像は公開しない。
        self.assertTrue((OUT / 'assets/hero.webp').is_file())
        self.assertTrue((OUT / 'assets/elevation.svg').is_file())
        self.assertFalse((OUT / 'assets/uploads/いきいきパーク・ロードバイク写真・紅葉とともに.jpg').exists())

    def test_responsive_images_and_social_formats(self):
        from PIL import Image
        manifest = json.loads((OUT / 'assets/image-manifest.json').read_text(encoding='utf-8'))
        self.assertTrue(manifest['images'])
        for source, record in manifest['images'].items():
            with self.subTest(source=source):
                self.assertEqual(record['variants'], sorted(record['variants'], key=lambda v: v['width']))
                for variant in record['variants']:
                    self.assertLessEqual(variant['width'], record['width'])
                    self.assertGreaterEqual(variant['psnr'], 38)
                    with Image.open(OUT / variant['src'].lstrip('/')) as image:
                        self.assertEqual(image.size, (variant['width'], variant['height']))
                        self.assertLess(abs(image.width / image.height - record['width'] / record['height']), .01)
                if 'og' in record:
                    with Image.open(OUT / record['og']['src'].lstrip('/')) as image:
                        self.assertIn(image.format, {'JPEG', 'PNG'})
        for kind, item, route, source, page in self.pages:
            for tag in re.findall(r'<img\b[^>]*>', source):
                if '/assets/optimized/' in tag:
                    self.assertIn('srcset=', tag)
                    self.assertIn('sizes=', tag)
                    self.assertIn('width=', tag)
                    self.assertIn('height=', tag)
                    self.assertIn('loading=', tag)

    def test_transparent_png_and_external_urls(self):
        from PIL import Image
        from optimize_images import create_record, ASSET
        with tempfile.TemporaryDirectory(prefix='image-alpha-') as directory:
            public = Path(directory) / 'public'
            public.mkdir()
            image = Image.new('P', (64, 64), 0)
            image.putpalette([0, 0, 0, 255, 0, 0] + [0] * 762)
            image.paste(1, (16, 16, 48, 48))
            source = public / 'transparent.png'
            image.save(source, transparency=0)
            before = source.read_bytes()
            record, cache = create_record(public, '/transparent.png', Path(directory) / 'cache')
            for variant in record['variants'] + [record['og']]:
                with Image.open(cache / Path(variant['src']).name) as result:
                    self.assertEqual(result.convert('RGBA').getextrema()[-1], (0, 255))
            self.assertEqual(source.read_bytes(), before)
        self.assertFalse(ASSET.search('https://example.invalid/assets/photo.jpg'))

    def test_http_redirects_and_missing_articles(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(OUT)))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = 'http://127.0.0.1:' + str(server.server_port)
        try:
            for kind, item, route, source, page in self.pages:
                old = '/journey/' if kind == 'journeys' else '/making-article/'
                with urlopen(origin + old + '?slug=' + item['slug']) as response:
                    self.assertEqual(response.status, 200)
                    self.assertTrue(response.url.endswith(route))
            for route in ['/journeys/no-such-article/', '/making/no-such-article/', '/no-such-page/']:
                with self.assertRaises(HTTPError) as error:
                    urlopen(origin + route)
                self.assertEqual(error.exception.code, 404)
                self.assertIn('ページが見つかりません', error.exception.read().decode('utf-8'))
                error.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


    def test_rss_public_articles_and_discovery(self):
        data = json.loads((ROOT / 'public/content/site.json').read_text(encoding='utf-8'))
        feed = ET.parse(OUT / 'feed.xml').getroot()
        self.assertEqual(feed.attrib, {'version': '2.0'})
        channel = feed.find('channel')
        base = channel.findtext('link').rstrip('/')
        expected = {base + article_path(kind, a['slug']): (kind, a)
                    for kind in ['journeys', 'making_articles'] for a in data[kind]}
        items = channel.findall('item')
        self.assertEqual({i.findtext('link') for i in items}, set(expected))
        self.assertEqual(len(items), len(expected))
        dates = []
        for item in items:
            url = item.findtext('link')
            kind, article = expected[url]
            self.assertEqual(item.findtext('title'), article['title'])
            self.assertEqual(item.findtext('description'), article['summary'])
            self.assertEqual(item.findtext('guid'), url)
            self.assertEqual(item.find('guid').get('isPermaLink'), 'true')
            published = parsedate_to_datetime(item.findtext('pubDate'))
            self.assertEqual(published.date().isoformat(), str(article['date'])[:10])
            self.assertEqual(published.utcoffset().total_seconds(), 9 * 3600)
            dates.append(published)
            self.assertEqual(item.findall('category')[0].text, '旅の記録' if kind == 'journeys' else '道具とものづくり')
            page = (OUT / article_path(kind, article['slug']).strip('/') / 'index.html').read_text(encoding='utf-8')
            self.assertEqual(Page(page).canonicals, [url])
        self.assertEqual(dates, sorted(dates, reverse=True))
        sitemap = ET.parse(OUT / 'sitemap.xml').getroot()
        for loc in sitemap.findall('{*}url/{*}loc'):
            path = OUT / loc.text.removeprefix(base).strip('/') / 'index.html'
            page = path.read_text(encoding='utf-8')
            self.assertEqual(page.count('type="application/rss+xml"'), 1)
            self.assertIn('href="' + base + '/feed.xml"', page)

    def test_rss_escape_and_private_fields(self):
        article = {'slug': 'sample', 'title': '日本語 & <商品>', 'summary': '概要 "引用" & <script>alert(1)</script>',
                   'date': '2026-11-23', 'ride_category': '日帰り & ソロ',
                   'body': 'PRIVATE_BODY /private/local/path GPS', 'private_note': 'SECRET'}
        groups = {'journeys': [article], 'making_articles': []}
        raw = rss_feed(groups, 'https://example.com')
        item = ET.fromstring(raw).find('channel/item')
        self.assertEqual(item.findtext('title'), article['title'])
        self.assertEqual(item.findtext('description'), article['summary'])
        self.assertIsNone(item.find('description/script'))
        self.assertNotIn(b'PRIVATE_BODY', raw)
        self.assertNotIn(b'SECRET', raw)
        guid = item.findtext('guid')
        article.update(title='変更', summary='変更後')
        self.assertEqual(ET.fromstring(rss_feed(groups, 'https://example.com')).findtext('channel/item/guid'), guid)
        self.assertEqual(rss_feed(groups, 'https://example.com'), rss_feed(groups, 'https://example.com'))
        self.assertEqual(ET.fromstring(rss_feed({'journeys': [], 'making_articles': []}, 'https://example.com')).findall('channel/item'), [])


class CMSBuildTests(unittest.TestCase):
    """CMSが保存するJSONと同じ構造を隔離コピーへ保存し、ビルド連携を検証する。"""
    @classmethod
    def setUpClass(cls):
        parent = os.environ.get('SEO_TEST_WORK')
        if parent:
            Path(parent).mkdir(parents=True, exist_ok=True)
        cls.fixture = Path(tempfile.mkdtemp(prefix='cms-build-', dir=parent))
        shutil.copytree(ROOT / 'public', cls.fixture / 'public')
        shutil.copytree(ROOT / 'scripts', cls.fixture / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
        cls.original = json.loads((ROOT / 'public/content/site.json').read_text(encoding='utf-8'))
        cls.source_hash = hashlib.sha256((ROOT / 'public/content/site.json').read_bytes()).hexdigest()
        print('\n隔離CMSデータ試験: ' + str(cls.fixture), flush=True)

    @classmethod
    def tearDownClass(cls):
        assert hashlib.sha256((ROOT / 'public/content/site.json').read_bytes()).hexdigest() == cls.source_hash

    def save(self, data):
        (self.fixture / 'public/content/site.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

    def build(self, success=True):
        result = subprocess.run([sys.executable, '-B', str(self.fixture / 'scripts/build_seo.py')], cwd=self.fixture,
                                capture_output=True, encoding='utf-8', env={**os.environ, 'PYTHONUTF8': '1', 'IMAGE_CACHE_DIR': str(ROOT / '.image-cache')}, timeout=240)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, '不正なデータでビルドが成功しました')
        return result

    def output(self, relative):
        return (self.fixture / '_site' / relative).read_text(encoding='utf-8')

    def snapshot(self):
        return {p.relative_to(self.fixture / '_site').as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (self.fixture / '_site').rglob('*') if p.is_file()}

    def test_cms_add_edit_delete_and_repeated_builds(self):
        data = copy.deepcopy(self.original)
        additions = []
        for kind in ['journeys', 'making_articles']:
            article = copy.deepcopy(data[kind][0])
            article.update(slug='qa-' + kind.replace('_', '-'), title='検証用 <新規> ' + kind, date='2099-01-01',
                           summary='隔離コピー内だけのテスト概要', body='## 新規見出し\n\n新規本文。\n\n![写真](/assets/hero.webp)')
            if kind == 'journeys':
                article['ride_category'] = 'イベントライド'
            else:
                article['making_info']['category'] = 'DIY'
            data[kind].append(article)
            additions.append((kind, article))
        self.save(data)
        self.build()
        for kind, article in additions:
            route = article_path(kind, article['slug'])
            page = self.output(route.strip('/') + '/index.html')
            self.assertIn('新規本文', page)
            self.assertEqual(Page(page).meta['og:title'], article['title'] + '｜走って、つくって。')
            self.assertIn(route, Page(self.output('index.html')).links)
            self.assertIn(route, Page(self.output(('journeys' if kind == 'journeys' else 'making') + '/index.html')).links)
            self.assertIn(route, self.output('sitemap.xml'))
            feed_item = next(x for x in ET.fromstring(self.output('feed.xml')).findall('channel/item') if x.findtext('link').endswith(route))
            self.assertEqual(feed_item.findtext('title'), article['title'])
            self.assertTrue((self.fixture / '_site' / category_path(kind, category(article, kind)).strip('/') / 'index.html').exists())
            article.update(title='更新したタイトル ' + kind, summary='更新した概要', image='/assets/view.webp',
                           hero_image='/assets/arrival.jpg', body='## 更新後の見出し\n\n更新後の本文。\n\n![更新写真](/assets/view.webp)')
        self.save(data)
        self.build()
        for kind, article in additions:
            page = self.output(article_path(kind, article['slug']).strip('/') + '/index.html')
            self.assertIn('更新後の本文', page)
            self.assertNotIn('新規本文', page)
            self.assertEqual(Page(page).meta['description'], '更新した概要')
            feed_item = next(x for x in ET.fromstring(self.output('feed.xml')).findall('channel/item') if x.findtext('guid').endswith(article_path(kind, article['slug'])))
            self.assertEqual(feed_item.findtext('title'), article['title'])
            self.assertEqual(feed_item.findtext('description'), '更新した概要')
            self.assertEqual(original_url(Page(page).meta['og:image'], self.fixture / '_site'), '/assets/arrival.jpg')
            self.assertIn('/assets/view.webp', [original_url(url, self.fixture / '_site') for url in Page(page).images])
        # 旧HTMLもpublicに存在する別府記事を削除。再生成で復活しないことも確認する。
        for kind, article in additions:
            data[kind] = [x for x in data[kind] if x['slug'] != article['slug']]
        data['journeys'] = [x for x in data['journeys'] if x['slug'] != 'beppu']
        self.save(data)
        self.build()
        removed = ['/journeys/beppu/'] + [article_path(k, a['slug']) for k, a in additions]
        for route in removed:
            self.assertFalse((self.fixture / '_site' / route.strip('/') / 'index.html').exists(), route)
            self.assertNotIn(route, self.output('sitemap.xml'))
            for relative in ['index.html', 'journeys/index.html', 'making/index.html']:
                self.assertNotIn(route, Page(self.output(relative)).links)
            for file in (self.fixture / '_site').rglob('*.html'):
                self.assertNotIn(route, Page(file.read_text(encoding='utf-8')).links)
        for kind, article in additions:
            self.assertFalse((self.fixture / '_site' / category_path(kind, category(article, kind)).strip('/') / 'index.html').exists())
        links = Page(self.output('contact/index.html')).links
        self.assertFalse(any('slug=beppu' in link or link == '/journeys/beppu/' for link in links))
        before = self.snapshot()
        self.build()
        self.assertEqual(self.snapshot(), before, '再生成結果が安定していません')

    def test_empty_articles_remove_legacy_pages(self):
        data = copy.deepcopy(self.original)
        data['journeys'], data['making_articles'] = [], []
        self.save(data)
        self.build()
        self.assertIn('記事はまだありません', self.output('journeys/index.html'))
        self.assertIn('記事はまだありません', self.output('making/index.html'))
        self.assertFalse((self.fixture / '_site/journeys/beppu/index.html').exists())
        self.assertFalse((self.fixture / '_site/journeys/tanba-kuromame-ride/index.html').exists())
        self.assertEqual(len(ET.fromstring(self.output('sitemap.xml')).findall('{*}url')), 5)
        self.assertEqual(ET.fromstring(self.output('feed.xml')).findall('channel/item'), [])

    def test_reject_duplicate_urls_broken_images_and_missing_metadata(self):
        cases = []
        for kind in ['journeys', 'making_articles']:
            data = copy.deepcopy(self.original)
            data[kind].append(copy.deepcopy(data[kind][0]))
            cases.append(('duplicate-' + kind, data))
        for field, value in [('image', '/assets/qa-missing.jpg'), ('hero_image', '/assets/HERO.webp'), ('summary', '')]:
            data = copy.deepcopy(self.original)
            data['making_articles'][0][field] = value
            cases.append((field, data))
        for name, data in cases:
            with self.subTest(case=name):
                self.save(data)
                self.build(success=False)

    def test_removed_source_image_does_not_survive_in_output(self):
        data = copy.deepcopy(self.original)
        image = self.fixture / 'public/assets/qa-transient.svg'
        image.write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>', encoding='utf-8')
        self.save(data)
        self.build()
        self.assertTrue((self.fixture / '_site/assets/qa-transient.svg').is_file())
        image.unlink()
        self.build()
        self.assertFalse((self.fixture / '_site/assets/qa-transient.svg').exists())

    def test_private_and_backup_files_are_not_published(self):
        candidates = ['.env', 'assets/debug.log', 'assets/photo.tmp', 'assets/js/oldbackup.zip', '__pycache__/test.pyc']
        for name in candidates:
            path = self.fixture / 'public' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('local-only-audit-fixture', encoding='utf-8')
        self.build()
        for name in candidates:
            self.assertTrue((self.fixture / 'public' / name).exists())
            self.assertFalse((self.fixture / '_site' / name).exists())

    def test_cms_configuration_is_copied_unchanged(self):
        self.save(copy.deepcopy(self.original))
        self.build()
        for relative in ['admin/config.yml', 'assets/js/making-info-widget.js']:
            self.assertEqual((self.fixture / 'public' / relative).read_bytes(), (self.fixture / '_site' / relative).read_bytes())
        self.assertEqual(json.loads((self.fixture / 'public/content/site.json').read_text(encoding='utf-8')),
                         restore_image_urls(json.loads(self.output('content/site.json')), self.fixture / '_site'))
        self.assertIn('CMS.init()', self.output('admin/index.html'))
        self.assertIn('name: \'preSave\'', self.output('admin/index.html'))

    def test_ga4_configured_output_in_isolated_copy(self):
        self.save(copy.deepcopy(self.original))
        # ID発行・Googleへの通信は行わず、設定読み取りを隔離プロセス内でモックする。
        runner = "import sys; sys.path.insert(0, sys.argv[1]); import analytics, build_seo; analytics.load_settings=lambda base: {'measurement_id':'TEST_ONLY_NOT_A_MEASUREMENT_ID','origin':base}; build_seo.build()"
        try:
            result = subprocess.run([sys.executable, '-B', '-c', runner, str(self.fixture / 'scripts')],
                                    cwd=self.fixture, capture_output=True, encoding='utf-8',
                                    env={**os.environ, 'IMAGE_CACHE_DIR': str(ROOT / '.image-cache')}, timeout=240)
            self.assertEqual(result.returncode, 0, result.stderr)
            routes = [urlsplit(node.text).path for node in ET.fromstring(self.output('sitemap.xml')).findall('{*}url/{*}loc')]
            for route in routes:
                source = self.output(route.lstrip('/') + 'index.html')
                head = re.search(r'<head\b[^>]*>(.*?)</head>', source, re.S)[1]
                self.assertEqual(head.count('id="site-ga4"'), 1)
            for route in ['admin/index.html', 'journey/index.html', 'making-article/index.html', '404.html']:
                self.assertNotIn('id="site-ga4"', self.output(route))
        finally:
            self.build()
        self.assertNotIn('TEST_ONLY_NOT_A_MEASUREMENT_ID', self.output('index.html'))

    def test_google_verification_head_tag_survives_build(self):
        # Googleの確認コードは生成しない。隔離コピーに空の構造テストタグだけを置く。
        # 実プロジェクトのpublicと_siteには、このタグを書き込まない。
        home = self.fixture / 'public/index.html'
        original = home.read_bytes()
        tag = '<meta name="google-site-verification" content="">'
        try:
            home.write_text(original.decode('utf-8').replace('</head>', tag + '\n</head>', 1), encoding='utf-8')
            self.build()
            head = re.search(r'<head\b[^>]*>(.*?)</head>', self.output('index.html'), re.S)[1]
            self.assertEqual(head.count(tag), 1)
            self.assertEqual(home.read_text(encoding='utf-8').count(tag), 1)
            # 繰り返し生成しても重複・消失しない。
            self.build()
            head = re.search(r'<head\b[^>]*>(.*?)</head>', self.output('index.html'), re.S)[1]
            self.assertEqual(head.count(tag), 1)
        finally:
            home.write_bytes(original)
            self.build()

    def test_new_cms_photo_and_alt(self):
        from PIL import Image
        data = copy.deepcopy(self.original)
        photo = self.fixture / 'public/assets/qa-new-photo.png'
        Image.new('RGB', (1800, 1200), (40, 110, 70)).save(photo)
        original_bytes = photo.read_bytes()
        article = copy.deepcopy(data['making_articles'][0])
        article.update(slug='qa-new-photo', image='/assets/qa-new-photo.png', image_alt='検証用の緑色画像',
                       hero_image='/assets/qa-new-photo.png', hero_image_alt='検証用の緑色画像',
                       body='## 写真テスト\n\n![検証用の緑色画像](/assets/qa-new-photo.png)')
        data['making_articles'].append(article)
        self.save(data)
        self.build()
        page = self.output('making/qa-new-photo/index.html')
        self.assertIn('alt="検証用の緑色画像"', page)
        self.assertIn('srcset=', page)
        manifest = json.loads(self.output('assets/image-manifest.json'))
        self.assertIn('/assets/qa-new-photo.png', manifest['images'])
        self.assertEqual(photo.read_bytes(), original_bytes)
        self.assertFalse((self.fixture / '_site/assets/qa-new-photo.png').exists())
        for image in manifest['images']['/assets/qa-new-photo.png']['variants']:
            self.assertTrue((self.fixture / '_site' / image['src'].lstrip('/')).is_file())
        self.save(copy.deepcopy(self.original))
        self.build()
        self.assertEqual(photo.read_bytes(), original_bytes)
        self.assertFalse((self.fixture / '_site/assets/qa-new-photo.png').exists())
        cleaned = json.loads(self.output('assets/image-manifest.json'))
        self.assertNotIn('/assets/qa-new-photo.png', cleaned['images'])


class NavigationLogicTests(unittest.TestCase):
    def test_recent_order_and_limit(self):
        groups = {'journeys': [{'slug': 'old', 'date': '2025-01-01'}, {'slug': 'ride', 'date': '2026-11-20'}],
                  'making_articles': [{'slug': 'make', 'date': '2026-11-21'}, {'slug': 'middle', 'date': '2026-11-19'}]}
        self.assertEqual([x['slug'] for _, x in recent(groups)], ['make', 'ride', 'middle'])
        self.assertEqual(recent({'journeys': [], 'making_articles': []}), [])
        self.assertEqual(len(recent({'journeys': groups['journeys'][:1]})), 1)

    def test_related_ranking_and_self_exclusion(self):
        current = {'slug': 'self', 'region': '大阪', 'ride_category': '日帰りソロライド', 'date': '2026-01-01'}
        items = [current, {'slug': 'recent', 'region': '京都', 'ride_category': 'イベントライド', 'date': '2099-01-01'},
                 {'slug': 'region', 'region': '大阪', 'ride_category': 'イベントライド', 'date': '2020-01-01'},
                 {'slug': 'category', 'region': '京都', 'ride_category': '日帰りソロライド', 'date': '2025-01-01'}]
        self.assertEqual([x['slug'] for x in related(current, items, 'journeys')], ['region', 'category', 'recent'])
        self.assertEqual(related(current, [current], 'journeys'), [])
        maker = {'slug': 'self', 'making_info': {'category': 'DIY'}}
        others = [maker, {'slug': 'new', 'making_info': {'category': 'メンテナンス'}, 'date': '2099-01-01'},
                  {'slug': 'same', 'making_info': {'category': 'DIY'}, 'date': '2020-01-01'}]
        self.assertEqual([x['slug'] for x in related(maker, others, 'making_articles')], ['same', 'new'])

    def test_category_urls_are_stable_and_distinct(self):
        self.assertEqual(category_path('journeys', '日帰りソロライド'), '/journeys/category/day-solo/')
        self.assertNotEqual(category_path('journeys', 'その他'), category_path('making_articles', 'その他'))
        self.assertNotEqual(category_path('making_articles', '新分類A'), category_path('making_articles', '新分類B'))


if __name__ == '__main__':
    unittest.main(verbosity=2)

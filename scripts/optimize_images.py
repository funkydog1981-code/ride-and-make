"""元画像を保持し、内容ハッシュで再利用できる高画質の表示用画像を生成。"""
from pathlib import Path
from urllib.parse import urlsplit, unquote
from html.parser import HTMLParser
from io import BytesIO
import hashlib
import html
import json
import math
import os
import re
import shutil
import xml.etree.ElementTree as ET
from PIL import Image, ImageOps, ImageChops, ImageStat, ImageCms, __version__

VERSION = 'responsive-v1-q94-psnr38-' + __version__
WIDTHS = (640, 960, 1600, 2000)
RASTER = re.compile(r'\.(?:jpe?g|png|webp)$', re.I)
ASSET = re.compile(r'(?<![\w:/.-])/assets/[^\s"\'<>\\()]+?\.(?:jpe?g|png|webp)(?:[?#][^\s"\'<>\\()]*)?', re.I)


def local_path(url):
    try:
        parsed = urlsplit(html.unescape(url))
        return unquote(parsed.path) if not parsed.scheme and not parsed.netloc else None
    except ValueError:
        return None


def psnr(reference, encoded):
    with Image.open(BytesIO(encoded)) as decoded:
        diff = ImageChops.difference(reference.convert('RGB'), decoded.convert('RGB'))
        mse = sum(x * x for x in ImageStat.Stat(diff).rms) / 3
    return round(20 * math.log10(255 / math.sqrt(mse)), 2) if mse else 100.0


def candidate(image, format):
    alpha = image.mode == 'RGBA' and image.getextrema()[-1][0] < 255
    if alpha:
        output = BytesIO()
        if format == 'WEBP':
            image.save(output, format, lossless=True, method=4)
        else:
            image.save(output, 'PNG', optimize=True)
        return output.getvalue(), 100.0
    rgb = image.convert('RGB')
    for quality in (94, 97, 100):
        output = BytesIO()
        if format == 'WEBP':
            rgb.save(output, format, quality=quality, method=4)
        else:
            rgb.save(output, 'JPEG', quality=quality, subsampling=0, optimize=True, progressive=True)
        encoded = output.getvalue()
        score = psnr(rgb, encoded)
        if score >= 38:
            return encoded, score
    # 上限品質でも基準を満たさない場合は、可逆圧縮を使う。
    output = BytesIO()
    rgb.save(output, 'WEBP', lossless=True, method=4)
    return output.getvalue(), 100.0


def retain_smaller_original(record, folder, raw):
    """既に十分小さい元画像を、同じ解像度で再圧縮して大きくしない。"""
    largest = record['variants'][-1]
    if largest['width'] != record['width'] or largest['bytes'] <= len(raw):
        return record
    with Image.open(BytesIO(raw)) as source:
        if source.getexif().get(274, 1) != 1 or source.info.get('icc_profile'):
            return record
        extension = {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp'}.get(source.format)
        if not extension:
            return record
    previous = largest['src']
    name = Path(previous).stem + '.' + extension
    (folder / name).write_bytes(raw)
    largest.update(src='/assets/optimized/' + name, bytes=len(raw), psnr=100.0)
    for key in ['defaultSrc', 'heroSrc']:
        if record[key] == previous:
            record[key] = largest['src']
    record['retainedOriginalEncoding'] = True
    return record


def create_record(public, source, cache, need_og=True):
    raw = (public / source.lstrip('/')).read_bytes()
    token = hashlib.sha256(raw + VERSION.encode() + source.encode()).hexdigest()[:24]
    folder = cache / token
    manifest = folder / 'record.json'
    if manifest.exists():
        record = json.loads(manifest.read_text(encoding='utf-8'))
        if (not need_og or 'og' in record) and all((folder / Path(v['src']).name).exists() for v in record['variants'] + ([record['og']] if need_og else [])):
            record = retain_smaller_original(record, folder, raw)
            manifest.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
            return record, folder
    folder.mkdir(parents=True, exist_ok=True)
    with Image.open(BytesIO(raw)) as original:
        image = ImageOps.exif_transpose(original)
        if image.mode == 'P' and 'transparency' in image.info:
            image = image.convert('RGBA')
        if image.info.get('icc_profile'):
            try:
                alpha = image.getchannel('A') if 'A' in image.getbands() else None
                image = ImageCms.profileToProfile(image.convert('RGB'), ImageCms.ImageCmsProfile(BytesIO(image.info['icc_profile'])), ImageCms.createProfile('sRGB'), outputMode='RGB')
                if alpha is not None:
                    image.putalpha(alpha)
            except (ImageCms.PyCMSError, OSError):
                pass
        image = image.convert('RGBA' if 'A' in image.getbands() else 'RGB')
        width, height = image.size
        variants = []
        comparisons = []
        for size in sorted({min(w, width) for w in WIDTHS}):
            resized = image.resize((size, max(1, round(height * size / width))), Image.Resampling.LANCZOS) if size != width else image.copy()
            alpha = resized.mode == 'RGBA' and resized.getextrema()[-1][0] < 255
            webp, webp_score = candidate(resized, 'WEBP')
            alternate, alternate_score = candidate(resized, 'PNG' if alpha else 'JPEG')
            chosen, extension, score = (webp, 'webp', webp_score) if len(webp) <= len(alternate) else (alternate, 'png' if alpha else 'jpg', alternate_score)
            if chosen.startswith(b'RIFF'):
                extension = 'webp'
            name = f'{token}-{size}.{extension}'
            (folder / name).write_bytes(chosen)
            variants.append({'src': '/assets/optimized/' + name, 'width': size, 'height': resized.height, 'bytes': len(chosen), 'psnr': score})
            comparisons.append({'width': size, 'webp': len(webp), 'png' if alpha else 'jpeg': len(alternate)})
    body = max((v for v in variants if v['width'] <= 1600), key=lambda v: v['width'])
    record = {'source': source, 'width': width, 'height': height, 'originalBytes': len(raw), 'variants': variants,
              'defaultSrc': body['src'], 'heroSrc': variants[-1]['src'], 'comparisons': comparisons}
    if need_og:
        # OGPはJPEG/PNG。WebP対応に依存せず、写真の縦横比も維持する。
        og_width = min(width, 1200)
        og = image.resize((og_width, max(1, round(height * og_width / width))), Image.Resampling.LANCZOS)
        alpha = og.mode == 'RGBA' and og.getextrema()[-1][0] < 255
        og_bytes, _ = candidate(og, 'PNG' if alpha else 'JPEG')
        og_ext = 'png' if alpha else 'jpg'
        # candidateの品質保護用WebPフォールバックをJPEGへ明示的に変換。
        if not alpha and not og_bytes.startswith(b'\xff\xd8'):
            output = BytesIO()
            og.convert('RGB').save(output, 'JPEG', quality=100, subsampling=0, optimize=True)
            og_bytes = output.getvalue()
        og_name = f'{token}-og.{og_ext}'
        (folder / og_name).write_bytes(og_bytes)
        record['og'] = {'src': '/assets/optimized/' + og_name, 'width': og.width, 'height': og.height, 'bytes': len(og_bytes)}
    record = retain_smaller_original(record, folder, raw)
    manifest.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    return record, folder


def optimize_site(root, public, output):
    cache = Path(os.environ.get('IMAGE_CACHE_DIR', root / '.image-cache'))
    cache.mkdir(parents=True, exist_ok=True)
    sources = set()
    class References(HTMLParser):
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            for key in (['src'] if tag == 'img' else ['poster'] if tag == 'video' else []):
                source = local_path(attrs.get(key, ''))
                if source and RASTER.search(source):
                    sources.add(source)
    for file in output.rglob('*.html'):
        page = file.read_text(encoding='utf-8')
        sources.update(unquote(x.split('?')[0].split('#')[0]) for x in ASSET.findall(page))
        References().feed(page)
    sources.update(unquote(x.split('?')[0].split('#')[0]) for x in ASSET.findall((output / 'content/site.json').read_text(encoding='utf-8')))
    # メタ情報・構造化データで実際に使うローカル画像だけOGPを用意する。
    social_sources = set()
    for file in output.rglob('*.html'):
        page = file.read_text(encoding='utf-8')
        for tag in re.findall(r'<meta\b[^>]*>', page):
            if re.search(r'(?:property="og:image"|name="twitter:image")', tag):
                match = re.search(r'content="([^"]+)"', tag)
                if match:
                    social_sources.add(unquote(urlsplit(html.unescape(match[1])).path))
        for payload in re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S):
            data = json.loads(payload)
            images = data.get('image', [])
            for url in ([images] if isinstance(images, str) else images):
                if isinstance(url, str):
                    social_sources.add(unquote(urlsplit(url).path))
    records = {}
    vectors = {}
    for vector in public.rglob('*.svg'):
        svg = ET.fromstring(vector.read_text(encoding='utf-8'))
        viewbox = svg.attrib.get('viewBox', '').split()
        if len(viewbox) == 4:
            width, height = int(float(viewbox[2])), int(float(viewbox[3]))
            source = '/' + vector.relative_to(public).as_posix()
            vectors[source] = {'width': width, 'height': height, 'defaultSrc': source, 'heroSrc': source,
                               'variants': [{'src': source, 'width': width, 'height': height}]}
    target = output / 'assets/optimized'
    target.mkdir(parents=True, exist_ok=True)
    desired = set()
    for source in sorted(sources):
        record, folder = create_record(public, source, cache, source in social_sources)
        record = dict(record)
        if source not in social_sources:
            record.pop('og', None)
        records[source] = record
        for variant in record['variants'] + ([record['og']] if 'og' in record else []):
            name = Path(variant['src']).name
            desired.add(name)
            shutil.copyfile(folder / name, target / name)
    for stale in target.iterdir():
        if stale.is_file() and stale.name not in desired:
            stale.unlink()  # 自分で生成した公開用の派生ファイルだけを整理。
    def image_tag(match, page):
        class Attributes(HTMLParser):
            def handle_starttag(self, tag, attrs):
                self.attrs = dict(attrs)
        parsed = Attributes()
        parsed.feed(match[0])
        attrs = parsed.attrs
        source = local_path(attrs.get('src', ''))
        record = records.get(source) or vectors.get(source)
        if not record:
            return match[0]
        hero = attrs.get('fetchpriority') == 'high' or attrs.get('id') == 'hero-image'
        context = page[max(0, match.start() - 250):match.start()]
        card = bool(re.search(r'class="(?:journey|making)-card-photo"[^>]*>\s*$', context))
        compact = bool(re.search(r'class="discovery-thumb"[^>]*>\s*$', context))
        gear = bool(re.search(r'class="gear-photo"[^>]*>\s*$', context))
        split_hero = bool(re.search(r'class="hero-image"[^>]*>\s*$', context))
        body_sizes = f'(max-width:650px) min({record["width"]}px, calc(100vw - 44px)), (max-width:1000px) min({record["width"]}px, calc(100vw - 56px)), {min(record["width"],900)}px'
        sizes = '88px' if compact else '(max-width:650px) 100vw, 57.5vw' if split_hero else '100vw' if hero else '(max-width:650px) calc(100vw - 44px), 370px' if card else '(max-width:650px) calc(100vw - 44px), (max-width:1100px) calc(50vw - 60px), 520px' if gear else body_sizes
        attrs.update(src=record['heroSrc'] if hero else record['defaultSrc'], width=str(record['width']), height=str(record['height']),
                     srcset=', '.join(v['src'] + ' ' + str(v['width']) + 'w' for v in record['variants']),
                     sizes=sizes,
                     loading='eager' if hero else 'lazy', decoding='async')
        if hero:
            attrs['fetchpriority'] = 'high'
        return '<img' + ''.join(' ' + key + ('="' + html.escape(value, quote=True) + '"' if value is not None else '') for key, value in attrs.items()) + '>'

    for file in output.rglob('*.html'):
        page = file.read_text(encoding='utf-8')
        page = re.sub(r'<img\b[^>]*>', lambda m: image_tag(m, page), page)
        page = re.sub(r'poster="([^"]+)"', lambda m: 'poster="' + records[local_path(m[1])]['defaultSrc'] + '"' if local_path(m[1]) in records else m[0], page)
        canonical = re.search(r'<link rel="canonical" href="([^"]+)"', page)
        site_host = urlsplit(html.unescape(canonical[1])).netloc if canonical else ''
        def social(match):
            tag, url = match[0], html.unescape(match[2])
            parsed = urlsplit(url)
            if parsed.netloc and parsed.netloc != site_host:
                return tag
            record = records.get(unquote(parsed.path))
            if not record:
                return tag
            tag = tag.replace(match[2], html.escape(parsed.scheme + '://' + parsed.netloc + record['og']['src'], quote=True))
            if 'property="og:image"' in tag:
                tag += f'\n<meta property="og:image:width" content="{record["og"]["width"]}">\n<meta property="og:image:height" content="{record["og"]["height"]}">'
            return tag
        page = re.sub(r'(<meta\b[^>]*(?:property="og:image"|name="twitter:image")[^>]*content=")([^"]+)"[^>]*>', social, page)
        def schema(match):
            data = json.loads(match[1])
            for i, url in enumerate(data.get('image', [])):
                parsed = urlsplit(url)
                if parsed.netloc and parsed.netloc != urlsplit(data.get('mainEntityOfPage', '')).netloc:
                    continue
                record = records.get(unquote(parsed.path))
                if record:
                    data['image'][i] = parsed.scheme + '://' + parsed.netloc + record['og']['src']
            return '<script type="application/ld+json">' + json.dumps(data, ensure_ascii=False).replace('<', '\\u003c') + '</script>'
        page = re.sub(r'<script type="application/ld\+json">(.*?)</script>', schema, page, flags=re.S)
        if '<img' in page:
            page = page.replace('</head>', '<script src="/assets/js/responsive-images.js" defer></script>\n</head>')
        file.write_text(page, encoding='utf-8')

    def rewrite_data(value, key='', parent=''):
        if isinstance(value, dict):
            return {k: rewrite_data(v, k, key) for k, v in value.items()}
        if isinstance(value, list):
            return [rewrite_data(v, key, parent) for v in value]
        if isinstance(value, str):
            record = records.get(local_path(value))
            if record:
                return record['heroSrc'] if key == 'hero_image' or parent == 'hero' else record['defaultSrc']
            return ASSET.sub(lambda m: records.get(local_path(m[0]), {}).get('defaultSrc', m[0]), value)
        return value
    data_file = output / 'content/site.json'
    data_file.write_text(json.dumps(rewrite_data(json.loads(data_file.read_text(encoding='utf-8'))), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    # 元画像の保管先はpublic。出力から消すのは、実行用ファイル内に
    # 参照が残っていない最適化済み元画像だけ（マニフェストの対応表は除く）。
    referenced = set()
    reference_text = []
    for file in output.rglob('*'):
        if file.is_file() and file.suffix.lower() in {'.html', '.css', '.js', '.json', '.md', '.xml'} and file.name not in {'image-manifest.json', 'image-report.json', '.seo-build.json'}:
            text = unquote(html.unescape(file.read_text(encoding='utf-8'))).replace('\\/', '/')
            reference_text.append(text)
            referenced.update(unquote(html.unescape(x).split('?')[0].split('#')[0]) for x in ASSET.findall(text))
    reference_text = '\n'.join(reference_text)
    for source_file in public.rglob('*'):
        if not source_file.is_file() or not RASTER.search(source_file.name):
            continue
        source = '/' + source_file.relative_to(public).as_posix()
        if source not in referenced and Path(source).name not in reference_text:
            original = output / source.lstrip('/')
            if original.is_file():
                original.unlink()
    manifest = {'version': VERSION, 'images': records, 'vectors': vectors}
    (output / 'assets/image-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    totals = {'images': len(records), 'originalBytes': sum(r['originalBytes'] for r in records.values()),
              'desktopBytes': sum(r['variants'][-1]['bytes'] for r in records.values()),
              'mobileBytes': sum(r['variants'][0]['bytes'] for r in records.values()),
              'allVariantsBytes': sum(v['bytes'] for r in records.values() for v in r['variants'] + ([r['og']] if 'og' in r else [])),
              'variants': sum(len(r['variants']) for r in records.values()),
              'minPsnr': min(v['psnr'] for r in records.values() for v in r['variants'])}
    (output / 'assets/image-report.json').write_text(json.dumps(totals, indent=2), encoding='utf-8')
    print('画像最適化: ' + json.dumps(totals, ensure_ascii=False), flush=True)

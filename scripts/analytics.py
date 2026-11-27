"""GA4の準備。未設定・本番以外は出力せず、同意前は外部通信しない。"""
import json
import html
import os
import re
from urllib.parse import urlsplit


MARKER = 'site-ga4'
CONSENT_KEY = 'ride-and-make.analytics-consent'


def load_settings(base):
    measurement_id = os.environ.get('GA4_MEASUREMENT_ID', '').strip()
    if (not measurement_id or os.environ.get('GA4_ENABLED') != 'true' or
            os.environ.get('CONTEXT') != 'production'):
        return None
    if not re.fullmatch(r'G-[A-Z0-9]+', measurement_id):
        raise ValueError('GA4_MEASUREMENT_IDにはGoogle発行のGA4測定IDを指定してください。')
    url = urlsplit(base)
    if url.scheme != 'https' or not url.hostname or url.hostname in {'localhost', '127.0.0.1', '::1'}:
        raise ValueError('GA4は正式なHTTPSの本番URLだけで有効にできます。')
    return {'measurement_id': measurement_id, 'origin': url.scheme + '://' + url.netloc}


def markup(settings):
    config = json.dumps(settings, ensure_ascii=True).replace('<', '\\u003c')
    return '<script id="' + MARKER + '">\n' + """(() => {
  'use strict';
  const config = CONFIG;
  if (location.protocol !== 'https:' || location.origin !== config.origin) return;
  if (window.__rideAndMakeGA4Attached) return;
  window.__rideAndMakeGA4Attached = true;
  const id = config.measurement_id;
  function syncConsent() {
    let allowed = false;
    try { allowed = window.SiteAnalyticsConsent?.hasConsent() === true; } catch {}
    window['ga-disable-' + id] = !allowed;
    if (!allowed || window.__rideAndMakeGA4Started) return;
    window.__rideAndMakeGA4Started = true;
    window.dataLayer = window.dataLayer || [];
    window.gtag = window.gtag || function () { window.dataLayer.push(arguments); };
    let referrer = '';
    try {
      const url = new URL(document.referrer);
      if (['https:', 'http:'].includes(url.protocol)) referrer = url.origin + url.pathname;
    } catch {}
    window.gtag('js', new Date());
    window.gtag('config', id, {
      send_page_view: true,
      page_location: location.origin + location.pathname,
      page_referrer: referrer,
      allow_google_signals: false,
      allow_ad_personalization_signals: false
    });
    const script = document.createElement('script');
    script.async = true;
    script.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(id);
    document.head.appendChild(script);
  }
  window.addEventListener('ride-and-make:analytics-consent', syncConsent);
  syncConsent();
})();
""".replace('CONFIG', config) + '</script>'


def apply_to_site(output, base, routes):
    settings = load_settings(base)
    targets = {output / route.lstrip('/') / 'index.html' for route in routes}
    for file in output.rglob('*.html'):
        original = file.read_text(encoding='utf-8')
        page = re.sub(r'<script id="site-ga4">.*?</script>\s*', '', original, flags=re.S)
        page = re.sub(r'<link id="site-consent-style"[^>]*>\s*', '', page)
        page = re.sub(r'<script id="site-consent-script"[^>]*>.*?</script>\s*', '', page, flags=re.S)
        page = re.sub(r'<button type="button" class="analytics-consent-open"[^>]*>.*?</button>\s*', '', page, flags=re.S)
        if settings and file in targets and '</footer>' in page:
            active = 'true' if settings and file in targets else 'false'
            assets = '<link id="site-consent-style" rel="stylesheet" href="/assets/css/analytics-consent.css">\n'
            assets += '<script id="site-consent-script" src="/assets/js/analytics-consent.js" defer data-analytics-enabled="' + active + '" data-analytics-origin="' + html.escape(base, quote=True) + '"></script>\n'
            page = page.replace('</head>', assets + '</head>', 1)
            button = '<button type="button" class="analytics-consent-open" aria-controls="analytics-consent-panel" aria-expanded="false" hidden>アクセス解析の設定</button>'
            footer_start = page.index('<footer')
            footer_end = page.index('</footer>', footer_start)
            links_end = page.rfind('</div>', footer_start, footer_end)
            position = links_end if links_end >= 0 else footer_end
            page = page[:position] + button + page[position:]

        policy_status = 'この公開版では、同意した場合に限りGA4によるアクセス解析を開始します。' if settings and file in targets else '現在、アクセス解析の計測は無効です。有効化後も、同意した場合に限り計測を開始します。'
        page = re.sub(r'<p id="analytics-policy-status">.*?</p>', lambda match: '<p id="analytics-policy-status">' + policy_status + '</p>', page, flags=re.S)
        if settings and file in targets:
            if 'googletagmanager.com/gtag/js' in page or 'google-analytics.com/' in page:
                raise ValueError('既存の解析コードとの二重挿入を防止しました: ' + str(file))
            if '</head>' not in page:
                raise ValueError('GA4の挿入先headがありません: ' + str(file))
            page = page.replace('</head>', markup(settings) + '\n</head>', 1)
        if page != original:
            file.write_text(page, encoding='utf-8')

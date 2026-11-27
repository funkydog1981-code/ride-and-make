(() => {
  'use strict';
  if (window.SiteAnalyticsConsent) return;
  const KEY = 'ride-and-make.analytics-consent';
  const VERSION = 1;
  const EVENT = 'ride-and-make:analytics-consent';
  const source = document.currentScript;
  const active = source?.dataset.analyticsEnabled === 'true' &&
    location.protocol === 'https:' && location.origin === source.dataset.analyticsOrigin;
  // 本番用出力をローカル等で開いた場合も、無効な計測の同意UIは表示しない。
  if (!active) return;
  let failedStorage = false;
  let panel, status, returnFocus;

  function readChoice() {
    if (failedStorage) return null;
    try {
      const state = JSON.parse(window.localStorage.getItem(KEY));
      if (state?.version === VERSION && ['granted', 'denied'].includes(state.choice) &&
          Number.isFinite(state.time) && state.time > 0) return state.choice;
    } catch {}
    return null;
  }

  function deleteCookies() {
    let cookies;
    try { cookies = document.cookie; } catch { return; }
    const names = cookies.split(';').map(x => x.trim().split('=')[0])
      .filter(x => /^_ga(?:_|$)|^_gid$|^_gat(?:_|$)/.test(x));
    const domains = ['', location.hostname];
    const labels = location.hostname.split('.');
    for (let i = 1; i < labels.length - 1; i++) domains.push(labels.slice(i).join('.'));
    const paths = new Set(['/']);
    const segments = location.pathname.split('/').filter(Boolean);
    for (let i = 1; i <= segments.length; i++) {
      paths.add('/' + segments.slice(0, i).join('/'));
      paths.add('/' + segments.slice(0, i).join('/') + '/');
    }
    for (const name of names) for (const domain of domains) for (const path of paths) {
      const scope = domain ? '; Domain=' + domain : '';
      try { document.cookie = name + '=; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=' + path + scope; } catch {}
    }
  }

  function notify() {
    window.dispatchEvent(new CustomEvent(EVENT, { detail: { choice: readChoice() } }));
  }

  function closePanel() {
    if (!panel) return;
    const focusedInside = panel.contains(document.activeElement);
    panel.hidden = true;
    document.querySelectorAll('.analytics-consent-open').forEach(x => x.setAttribute('aria-expanded', 'false'));
    if (returnFocus?.isConnected) returnFocus.focus();
    else if (focusedInside) document.querySelector('.analytics-consent-open')?.focus();
    returnFocus = null;
  }

  function updateStatus() {
    const choice = readChoice();
    const label = choice === 'granted' ? '同意する' : choice === 'denied' ? '同意しない' : '未選択';
    panel.querySelector('.analytics-consent-current').textContent = '現在の設定：' + label;
  }

  function openPanel(event) {
    if (!panel) return;
    returnFocus = event?.currentTarget || document.activeElement;
    updateStatus();
    panel.hidden = false;
    document.querySelectorAll('.analytics-consent-open').forEach(x => x.setAttribute('aria-expanded', 'true'));
    panel.querySelector('h2').focus();
  }

  function choose(choice) {
    const wasRunning = Boolean(window.__rideAndMakeGA4Started);
    try {
      window.localStorage.setItem(KEY, JSON.stringify({ version: VERSION, choice, time: Date.now() }));
      if (readChoice() !== choice) throw Error('not saved');
    } catch {
      failedStorage = true;
      status.textContent = '設定を保存できないため、このページではアクセス解析を行いません。サイトは通常どおり閲覧できます。';
    }
    notify(); // GA停止フラグを先に設定し、Cookie削除・再読み込みを行う。
    if (readChoice() !== 'granted') deleteCookies();
    closePanel();
    if (wasRunning && readChoice() !== 'granted') location.reload();
  }

  window.SiteAnalyticsConsent = { hasConsent: () => readChoice() === 'granted', open: openPanel };
  window.addEventListener('storage', event => {
    if (event.key !== KEY && event.key !== null) return;
    const wasRunning = Boolean(window.__rideAndMakeGA4Started);
    notify();
    if (panel) {
      updateStatus();
      if (readChoice()) closePanel();
      else panel.hidden = false;
      document.querySelectorAll('.analytics-consent-open').forEach(button => button.setAttribute('aria-expanded', String(!panel.hidden)));
    }
    if (readChoice() !== 'granted') {
      deleteCookies();
      if (wasRunning) location.reload();
    }
  });

  function init() {
    if (document.getElementById('analytics-consent-panel')) return;
    panel = document.createElement('section');
    panel.id = 'analytics-consent-panel';
    panel.className = 'analytics-consent-panel';
    panel.setAttribute('role', 'region');
    panel.setAttribute('aria-labelledby', 'analytics-consent-title');
    panel.hidden = true;
    panel.innerHTML = '<button type="button" class="analytics-consent-close" aria-label="設定を変更せず閉じる">×</button>' +
      '<h2 id="analytics-consent-title" tabindex="-1">アクセス解析の設定</h2>' +
      '<p>記事やサイトの改善のため、同意いただいた場合に限りGoogle Analytics 4を利用します。Cookie等を通じて閲覧ページや端末情報などがGoogleへ送信されます。拒否しても通常どおり閲覧できます。</p>' +
      '<p class="analytics-consent-environment"></p><p class="analytics-consent-current"></p>' +
      '<div class="analytics-consent-actions"><button type="button" data-consent-choice="granted">同意する</button>' +
      '<button type="button" data-consent-choice="denied">同意しない</button></div>' +
      '<p><a href="/privacy/#analytics">プライバシーポリシー・撤回方法</a></p>';
    panel.querySelector('.analytics-consent-environment').textContent = active ?
      '選択はこのブラウザに保存され、フッターからいつでも変更できます。' :
      '現在この環境ではアクセス解析は無効です。選択は保存され、今後有効になった場合に適用されます。';
    panel.querySelectorAll('[data-consent-choice]').forEach(button =>
      button.addEventListener('click', () => choose(button.dataset.consentChoice)));
    panel.querySelector('.analytics-consent-close').addEventListener('click', closePanel);
    panel.addEventListener('keydown', event => {
      if (event.key === 'Escape') { event.preventDefault(); closePanel(); }
    });
    document.body.appendChild(panel);
    status = document.createElement('p');
    status.className = 'analytics-consent-status';
    status.setAttribute('role', 'status');
    document.querySelector('footer')?.appendChild(status);
    document.querySelectorAll('.analytics-consent-open').forEach(button => {
      button.hidden = false;
      button.addEventListener('click', openPanel);
    });
    updateStatus();
    panel.hidden = Boolean(readChoice());
    document.querySelectorAll('.analytics-consent-open').forEach(button => button.setAttribute('aria-expanded', String(!panel.hidden)));
    if (readChoice() !== 'granted') deleteCookies();
    notify();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
  else init();
})();

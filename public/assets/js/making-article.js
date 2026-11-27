(() => {
  'use strict';

  const text = (value) => value == null ? '' : String(value);
  const hasValue = (value) => text(value).trim() !== '';
  const get = (id) => document.getElementById(id);

  function safeUrl(value, link = false) {
    if (typeof value !== 'string' || !value.trim()) return null;
    try {
      const url = new URL(value.trim(), window.location.origin + '/');
      if (url.username || url.password) return null;
      const protocols = link ? ['https:', 'http:', 'mailto:', 'tel:'] : ['https:', 'http:'];
      return protocols.includes(url.protocol) ? url.href : null;
    } catch { return null; }
  }

  function youtubeUrl(value) {
    try {
      // HTTPSの正規埋め込みだけを許可し、任意のパラメーターは引き継がない。
      const url = new URL(value);
      if (url.protocol !== 'https:' || url.port || url.username || url.password ||
          !['www.youtube.com', 'youtube.com', 'www.youtube-nocookie.com', 'youtube-nocookie.com'].includes(url.hostname) ||
          !/^\/embed\/[A-Za-z0-9_-]{11}$/.test(url.pathname)) return null;
      const clean = new URL(url.pathname, `https://${url.hostname}`);
      const start = url.searchParams.get('start');
      if (start && /^\d{1,8}$/.test(start)) clean.searchParams.set('start', start);
      return clean.href;
    } catch { return null; }
  }

  function formatDate(value) {
    if (typeof value !== 'string') return null;
    const match = value.match(/^(\d{4})-(\d{2})-(\d{2})(?:T|$)/);
    if (!match || !Number.isFinite(Date.parse(value))) return null;
    const day = `${match[1]}-${match[2]}-${match[3]}`;
    if (new Date(`${day}T00:00:00Z`).toISOString().slice(0, 10) !== day) return null;
    return { label: `${match[1]}.${match[2]}`, datetime: day };
  }

  function renderBody(container, value) {
    const source = text(value);
    // ライブラリー未読込時はHTMLを解釈しない。sanitizeの未対応環境も同様。
    if (!window.RakutenLinks || !window.marked || typeof window.marked.parse !== 'function' ||
        !window.DOMPurify || !window.DOMPurify.isSupported ||
        typeof window.DOMPurify.sanitize !== 'function') {
      container.classList.add('plain-text');
      container.textContent = source;
      return;
    }
    try {
      const fragment = window.RakutenLinks.sanitize(window.marked.parse(source), {
        RETURN_DOM_FRAGMENT: true,
        ALLOWED_TAGS: ['p', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
          'strong', 'em', 'b', 'i', 's', 'del', 'a', 'ul', 'ol', 'li', 'blockquote',
          'pre', 'code', 'img', 'figure', 'figcaption', 'table', 'thead', 'tbody',
          'tfoot', 'tr', 'th', 'td', 'div', 'span', 'video', 'source', 'iframe'],
        ALLOWED_ATTR: ['class', 'rel', 'target', 'href', 'src', 'alt', 'title', 'colspan', 'rowspan',
          'controls', 'preload', 'poster', 'type', 'start', 'reversed'],
        ALLOW_DATA_ATTR: false,
        ALLOW_ARIA_ATTR: false
      });

      fragment.querySelectorAll('iframe').forEach((frame) => {
        const src = youtubeUrl(frame.getAttribute('src'));
        if (!src) { frame.remove(); return; }
        // 許可した動画も固定属性の新しいiframeに置き換える。
        const clean = document.createElement('iframe');
        clean.src = src;
        clean.title = frame.getAttribute('title') || 'YouTube動画';
        clean.loading = 'lazy';
        clean.setAttribute('allowfullscreen', '');
        clean.setAttribute('allow', 'encrypted-media; fullscreen; picture-in-picture');
        clean.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-presentation');
        clean.setAttribute('referrerpolicy', 'strict-origin-when-cross-origin');
        frame.replaceWith(clean);
      });
      fragment.querySelectorAll('img, video, source').forEach((media) => {
        const src = safeUrl(media.getAttribute('src'));
        if (src) media.setAttribute('src', src);
        else media.removeAttribute('src');
        if (media.hasAttribute('poster')) {
          const poster = safeUrl(media.getAttribute('poster'));
          if (poster) media.setAttribute('poster', poster);
          else media.removeAttribute('poster');
        }
        if (media.tagName === 'IMG') {
          media.loading = 'lazy';
          media.addEventListener('error', () => { media.hidden = true; }, { once: true });
        }
        if (media.tagName === 'VIDEO') {
          media.controls = true;
          media.preload = 'metadata';
        }
      });
      fragment.querySelectorAll('a').forEach((anchor) => {
        if (window.RakutenLinks.check(anchor).valid) return;
        const href = safeUrl(anchor.getAttribute('href'), true);
        if (href) anchor.setAttribute('href', href);
        else anchor.removeAttribute('href');
        const rel = (anchor.getAttribute('rel') || '').toLowerCase().split(/\s+/).filter(v => ['nofollow', 'sponsored', 'ugc', 'noopener', 'noreferrer'].includes(v));
        if (anchor.getAttribute('target') === '_blank') {
          if (!rel.includes('noopener')) rel.push('noopener');
        } else anchor.removeAttribute('target');
        anchor.setAttribute('rel', [...new Set(rel)].join(' ') || 'noopener noreferrer');
      });
      fragment.querySelectorAll('table').forEach((table) => {
        const wrapper = document.createElement('div');
        wrapper.className = 'table-scroll';
        wrapper.tabIndex = 0;
        wrapper.setAttribute('role', 'region');
        wrapper.setAttribute('aria-label', '記事内の表（横にスクロールできます）');
        table.replaceWith(wrapper);
        wrapper.appendChild(table);
      });
      container.replaceChildren(fragment);
    } catch (error) {
      console.error('記事本文を安全なテキストとして表示します:', error);
      container.classList.add('plain-text');
      container.textContent = source;
    }
  }

  function renderArticle(item) {
    const title = text(item.title) || 'タイトル未設定';
    get('article-title').textContent = title;
    document.title = `${title}｜走って、つくって。`;
    const summary = text(item.summary);
    get('article-summary').textContent = summary;
    get('article-summary').hidden = !hasValue(summary);
    document.querySelector('meta[name="description"]').content = summary;
    const category = text(item.making_info?.category);
    get('article-category').textContent = category;
    get('article-category').hidden = !hasValue(category);
    const date = formatDate(item.date);
    get('article-date').textContent = date?.label || '公開日未設定';
    if (date) get('article-date').setAttribute('datetime', date.datetime);

    const hero = safeUrl(item.hero_image) || safeUrl(item.image);
    if (hero) {
      const image = get('hero-image');
      image.alt = text(item.hero_image_alt || item.image_alt || title);
      image.addEventListener('error', () => { get('article-hero').hidden = true; }, { once: true });
      image.src = hero;
      get('article-hero').hidden = false;
      get('hero-caption').textContent = text(item.hero_image_caption);
      get('hero-caption').hidden = !hasValue(item.hero_image_caption);
    }

    const production = item.making_info?.production_data;
    const entries = Array.isArray(production) ? production.filter((entry) =>
      entry && hasValue(entry.value)) : [];
    entries.forEach((entry) => {
      const label = document.createElement('dt');
      const value = document.createElement('dd');
      label.textContent = hasValue(entry.label) ? text(entry.label) : 'その他';
      value.textContent = text(entry.value);
      get('production-data').append(label, value);
    });
    get('production-info').hidden = entries.length === 0;
    renderBody(get('article-body'), item.body);
    const disclosure = window.AffiliateDisclosure?.html(item.body) || '';
    if (disclosure) get('article-body').insertAdjacentHTML('afterbegin', disclosure);
    get('article-status').hidden = true;
    get('making-article').hidden = false;
  }

  async function load() {
    const main = get('making-main');
    if (!main) return;
    try {
      const slug = new URLSearchParams(window.location.search).get('slug');
      if (!slug || !slug.trim()) {
        get('article-status').textContent = '記事が指定されていません。制作記事一覧から記事を選んでください。';
        return;
      }
      const response = await fetch('/content/site.json', { cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!data || (data.making_articles != null && !Array.isArray(data.making_articles))) {
        throw new Error('making_articles must be an array');
      }
      const item = (data.making_articles || []).find((entry) => entry && entry.slug === slug);
      if (!item) {
        get('article-status').textContent = '記事が見つかりません。制作記事一覧から記事を選び直してください。';
        return;
      }
      renderArticle(item);
    } catch (error) {
      console.error('制作記事の取得・表示に失敗しました:', error);
      get('making-article').hidden = true;
      get('article-status').hidden = false;
      get('article-status').textContent = '記事を読み込めませんでした。時間をおいて再度お試しください。';
    } finally {
      main.setAttribute('aria-busy', 'false');
    }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', load, { once: true });
  else load();
})();

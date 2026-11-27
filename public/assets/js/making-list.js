(() => {
  'use strict';

  const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char]);

  // CMSの日付の年月を保持し、閲覧者のタイムゾーンによる月ずれを避ける。
  const publicationDate = (value) => {
    if (typeof value !== 'string') return null;
    const match = value.match(/^(\d{4})-(\d{2})-(\d{2})(?:T|$)/);
    const timestamp = Date.parse(value);
    if (!match || !Number.isFinite(timestamp)) return null;
    const [, year, month, day] = match;
    const date = new Date(`${year}-${month}-${day}T00:00:00Z`);
    if (date.toISOString().slice(0, 10) !== `${year}-${month}-${day}`) return null;
    return { timestamp, label: `${year}.${month}`, datetime: `${year}-${month}-${day}` };
  };

  const imageUrl = (value) => {
    if (typeof value !== 'string' || !value.trim()) return '';
    try {
      const url = new URL(value.trim(), window.location.origin + '/');
      return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
    } catch {
      return '';
    }
  };

  const renderCard = (item, top = false) => {
    // URLも属性への挿入前にエスケープする（encodeURIComponentは引用符をすべては変換しない）。
    const url = escapeHTML(`/making-article/?slug=${encodeURIComponent(item.slug)}`);
    const title = escapeHTML(item.title || 'タイトル未設定');
    const category = escapeHTML(item.making_info?.category || '道具とものづくり');
    const image = imageUrl(item.image);
    const date = publicationDate(item.date);
    const html = `<article class="making-card">
      ${image ? `<a class="making-card-photo" href="${url}" tabindex="-1" aria-hidden="true">
        <img src="${escapeHTML(image)}" alt="${escapeHTML(item.image_alt || item.title || '記事の写真')}" loading="lazy" decoding="async">
      </a>` : ''}
      <div class="making-card-copy">
        <span class="pill">${category}</span>
        <h2><a href="${url}">${title}</a></h2>
        <p>${escapeHTML(item.summary || '')}</p>
        <div class="card-meta">${date ? `公開 <time datetime="${date.datetime}">${date.label}</time>` : '公開日未設定'}</div>
        <a class="card-link" href="${url}" aria-label="${title}の記事を読む">記事を読む　↗</a>
      </div>
    </article>`;
    // トップでは旅の記事と同じカードCSSを使い、一覧の見た目は維持する。
    return top ? html.replaceAll('class="making-card', 'class="journey-card')
      .replaceAll('<h2>', '<h3>').replaceAll('</h2>', '</h3>') : html;
  };

  async function loadMakingArticles() {
    const topGrid = document.querySelector('#latest-making');
    const grid = topGrid || document.querySelector('#all-making-articles');
    if (!grid) return;
    try {
      const response = await fetch('/content/site.json', { cache: 'no-store' });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!data || (data.making_articles != null && !Array.isArray(data.making_articles))) {
        throw new Error('making_articles must be an array');
      }
      const articles = (data.making_articles || [])
        .filter((item) => item && typeof item.slug === 'string' && item.slug.trim())
        .slice()
        .sort((a, b) => (publicationDate(b.date)?.timestamp ?? -Infinity) -
          (publicationDate(a.date)?.timestamp ?? -Infinity));
      const visible = topGrid ? articles.slice(0, 3) : articles;
      const messageClass = topGrid ? 'journey-empty' : 'making-message';
      grid.innerHTML = visible.length ? visible.map((item) => renderCard(item, !!topGrid)).join('') :
        `<p class="${messageClass}">記事はまだありません。</p>`;
      grid.querySelectorAll('img').forEach((img) => {
        img.addEventListener('error', () => { img.hidden = true; img.style.display = 'none'; }, { once: true });
      });
    } catch (error) {
      console.error('道具とものづくりの記事一覧を読み込めませんでした:', error);
      grid.innerHTML = `<p class="${topGrid ? 'journey-empty' : 'making-message'}">記事を読み込めませんでした。時間をおいて再度お試しください。</p>`;
    } finally {
      grid.setAttribute('aria-busy', 'false');
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadMakingArticles, { once: true });
  } else {
    loadMakingArticles();
  }
})();

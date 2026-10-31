(() => {
  'use strict';

  const escapeHTML = (value) =>
    String(value ?? '').replace(/[&<>"']/g, (char) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    })[char]);

  const formatDate = (value) => {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);

    return `${date.getFullYear()}.${String(date.getMonth() + 1).padStart(2, '0')}`;
  };

  const formatTitle = (value) =>
    escapeHTML(value || 'タイトル未設定').replace(/\r?\n/g, '<br>');

  const articleUrl = (slug) =>
    `/journeys/${encodeURIComponent(slug)}/`;

  const imageUrl = (value) => {
    if (!value) return '/assets/hero.webp';
    if (/^(https?:)?\/\//i.test(value) || value.startsWith('/')) return value;
    return `/${value.replace(/^\.?\//, '')}`;
  };

  const getSortedJourneys = (journeys) =>
    [...journeys]
      .filter((item) => item && item.slug)
      .sort((a, b) => {
        const dateA = Date.parse(a.date || '') || 0;
        const dateB = Date.parse(b.date || '') || 0;
        return dateB - dateA;
      });

  const renderCard = (item) => {
    const title = escapeHTML(item.title || 'タイトル未設定');
    const category = escapeHTML(item.category || '旅の記録');
    const summary = escapeHTML(item.summary || '');
    const date = formatDate(item.date);
    const distance = escapeHTML(item.distance || '—');
    const ascent = escapeHTML(item.ascent || '—');
    const image = escapeHTML(imageUrl(item.image));
    const alt = escapeHTML(item.image_alt || item.title || '記事の写真');
    const url = articleUrl(item.slug);

    return `
      <article class="journey-card">
        <a class="journey-card-photo" href="${url}" tabindex="-1" aria-hidden="true">
          <img src="${image}" alt="${alt}" loading="lazy">
        </a>
        <div class="journey-card-copy">
          <span class="pill">${category}</span>
          <h3><a href="${url}">${formatTitle(item.title)}</a></h3>
          <p>${summary}</p>
          <div class="card-meta">
            <span>${date}</span>
            <span>距離 ${distance}</span>
            <span>獲得標高 ${ascent}</span>
          </div>
          <a class="card-link" href="${url}">記事を読む　↗</a>
        </div>
      </article>
    `;
  };

  async function loadJourneyCards() {
    const topGrid = document.querySelector('#latest-journeys');
    const listingGrid = document.querySelector('#all-journeys');

    if (!topGrid && !listingGrid) return;

    try {
      const response = await fetch('/content/site.json', {
        cache: 'no-store'
      });

      if (!response.ok) {
        throw new Error(`記事データの読み込みに失敗しました (${response.status})`);
      }

      const data = await response.json();
      const journeys = getSortedJourneys(data.journeys || []);

      if (topGrid) {
        const latest = journeys.slice(0, 3);

        topGrid.innerHTML = latest.length
          ? latest.map(renderCard).join('')
          : '<p class="journey-empty">記事はまだありません。</p>';
      }

      if (listingGrid) {
        listingGrid.innerHTML = journeys.length
          ? journeys.map(renderCard).join('')
          : '<p class="journey-empty">記事はまだありません。</p>';
      }

      // 画像の読み込みに失敗した場合は、画像枠が崩れないようにする
      document.querySelectorAll('.journey-card-photo img').forEach((img) => {
        img.addEventListener('error', () => {
          img.style.display = 'none';
        }, { once: true });
      });

    } catch (error) {
      console.error('記事一覧の表示に失敗しました:', error);

      const message =
        '<p class="journey-empty">記事を読み込めませんでした。時間をおいて再度お試しください。</p>';

      if (topGrid) topGrid.innerHTML = message;
      if (listingGrid) listingGrid.innerHTML = message;
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadJourneyCards);
  } else {
    loadJourneyCards();
  }
})();

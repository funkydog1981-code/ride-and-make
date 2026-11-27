(() => {
  const esc = (v) =>
    String(v ?? '').replace(/[&<>"']/g, c => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[c]));

  const breaks = (v) =>
    esc(v).replace(/\r?\n/g, '<br>');

  const set = (sel, v, asBreaks = false) => {
    const e = document.querySelector(sel);

    if (e) {
      e.innerHTML = asBreaks
        ? breaks(v)
        : esc(v).replace(/\r?\n/g, '<br>');
    }
  };

  const dateLabel = (v) => {
    if (!v) return '';

    const d = new Date(v);

    return isNaN(d)
      ? v
      : `${d.getFullYear()}.${String(d.getMonth() + 1).padStart(2, '0')}`;
  };

  // すべての記事をCMS共通テンプレートで表示する。
  const articleUrl = (slug) =>
    `/journey/?slug=${encodeURIComponent(slug)}`;

  const getSlug = () => {
    const q = new URLSearchParams(location.search).get('slug');

    if (q) return q;

    const m = location.pathname.match(/\/journeys\/([^/]+)\/?$/);

    return m ? m[1] : '';
  };

  const safeMarkdown = (s) => {
    if (!window.marked) {
      return esc(s).replace(/\n/g, '<br>');
    }

    const raw = window.marked.parse(s || '');

    return window.DOMPurify && window.RakutenLinks
      ? window.RakutenLinks.sanitize(raw, {
          ADD_TAGS: ['video', 'source', 'iframe'],
          ADD_ATTR: [
            'controls',
            'muted',
            'playsinline',
            'preload',
            'poster',
            'src',
            'type',
            'allow',
            'allowfullscreen',
            'frameborder',
            'target', 'rel'
          ]
        })
      : esc(s).replace(/\n/g, '<br>');
  };

  function fixArticleImages(article) {
    if (!article) return;
    article.querySelectorAll('a').forEach(anchor => {
      if (window.RakutenLinks?.check(anchor).valid) return;
      const rel = (anchor.getAttribute('rel') || '').toLowerCase().split(/\s+/).filter(v => ['nofollow', 'sponsored', 'ugc', 'noopener', 'noreferrer'].includes(v));
      if (anchor.getAttribute('target') === '_blank') {
        if (!rel.includes('noopener')) rel.push('noopener');
      } else anchor.removeAttribute('target');
      anchor.setAttribute('rel', [...new Set(rel)].join(' ') || 'noopener noreferrer');
    });

    article.querySelectorAll('img').forEach(img => {
      if (img.closest('.product-card')) return;
      img.style.maxWidth = '100%';
      img.style.height = 'auto';
      img.style.width = 'auto';
      img.style.display = 'block';
      img.style.objectFit = 'contain';
      img.style.margin = '24px auto';
    });

    article.querySelectorAll('table').forEach(table => {
      table.style.maxWidth = '100%';
      table.style.width = '100%';
      table.style.display = 'block';
      table.style.overflowX = 'auto';
    });

    article.querySelectorAll('video, iframe').forEach(media => {
      media.style.maxWidth = '100%';
    });

    article.querySelectorAll('iframe').forEach(frame => {
      let url;
      try { url = new URL(frame.getAttribute('src') || ''); } catch { return; }
      if (!['youtube.com', 'www.youtube.com', 'youtube-nocookie.com', 'www.youtube-nocookie.com'].includes(url.hostname)) return;
      if (url.protocol !== 'https:' || url.port || url.username || url.password || !/^\/embed\/[A-Za-z0-9_-]{11}$/.test(url.pathname)) {
        frame.remove(); return;
      }
      if (!frame.title.trim()) frame.title = 'YouTube動画';
      frame.loading = 'lazy';
      frame.setAttribute('referrerpolicy', 'strict-origin-when-cross-origin');
    });

    article.querySelectorAll('video').forEach(video => {
      video.style.width = '100%';
    });
  }

  function fixHeroImage(img) {
    if (!img) return;

    img.style.width = '100%';
    img.style.height = '100%';
    img.style.maxWidth = '100%';
    img.style.objectFit = 'cover';
    img.style.display = 'block';
  }

  function addHeroCaptionStyle() {
    if (document.getElementById('cms-hero-caption-style')) return;

    const style = document.createElement('style');
    style.id = 'cms-hero-caption-style';

    style.textContent = `
      .hero-image-caption {
        max-width: 1200px;
        margin: 8px auto 0;
        padding: 0 28px;
        color: #64716b;
        font-size: 11px;
        line-height: 1.7;
        text-align: right;
      }

      @media (max-width: 800px) {
        .hero-image-caption {
          padding: 0 24px;
        }
      }
    `;

    document.head.appendChild(style);
  }

  async function load() {
    let data;

    try {
      const r = await fetch('/content/site.json', {
        cache: 'no-store'
      });

      if (!r.ok) throw Error('content missing');

      data = await r.json();
    } catch (e) {
      console.error('site.json の読み込みに失敗しました', e);
      return;
    }

    const hero = data.hero || {};

    // ========================================
    // トップページ・旅の記録ページ
    // ========================================

    if (
      document.querySelector('#journeys')
    ) {
      set('.hero-copy .eyebrow', hero.eyebrow);
      set('.hero-copy h1', hero.title, true);
      set('.hero-copy p', hero.description, true);

      const heroButton = document.querySelector('.hero-copy .button');

      if (heroButton) {
        heroButton.innerHTML =
          esc(hero.button_label) +
          ' <span aria-hidden="true">↘</span>';
      }

      set('.hero-caption', hero.caption);

      const hi = document.querySelector('.hero-image img');

      if (hi) {
        hi.src = hero.image || hi.src;
        hi.alt = hero.image_alt || '';
        fixHeroImage(hi);
      }

      const js = data.journey_section || {};

      set('#journeys .section-head .eyebrow', js.eyebrow);
      set('#journeys .section-head h2', js.title);
      set('#journeys .section-head p', js.description);

      // 記事を日付の新しい順に並べる
      const journeys = (data.journeys || [])
        .slice()
        .sort((a, b) =>
          (Date.parse(b.date) || 0) -
          (Date.parse(a.date) || 0)
        );

      const j = journeys[0];
      const feature = document.querySelector('#journeys .feature');

      if (j && feature) {
        feature.href = articleUrl(j.slug);

        const im = feature.querySelector('.feature-photo img');

        if (im) {
          im.src = j.image || '';
          im.alt = j.image_alt || '';
          im.style.maxWidth = '100%';
          im.style.height = 'auto';
        }

        const cp = feature.querySelector('.feature-copy');

        if (cp) {
          const pill = cp.querySelector('.pill');

          if (pill) {
            pill.textContent =
              [j.region, j.ride_category].filter(Boolean).join(' / ');
          }

          const h3 = cp.querySelector('h3');

          if (h3) h3.innerHTML = breaks(j.title || '');

          const p = cp.querySelector('p');

          if (p) p.textContent = j.summary || '';

          const metas = cp.querySelectorAll('.meta b');

          if (metas[0]) metas[0].textContent = j.distance || '—';
          if (metas[1]) metas[1].textContent = j.ascent || '—';
          if (metas[2]) metas[2].textContent = j.period || dateLabel(j.date);
        }
      }

      const latest = document.querySelector('#journeys .latest');

      if (latest) {
        latest.innerHTML =
          '<span>記事一覧</span>' +
          journeys.map(x =>
            `<a href="${articleUrl(x.slug)}">${esc(x.title)}　→</a>`
          ).join('');
      }

      // ========================================
      // 道具とものづくり
      // ========================================

      const making = data.making || {};

      set('#making .wrap > div:first-child .eyebrow', making.eyebrow);
      set('#making .wrap > div:first-child h2', making.title, true);

      const makingIntro = document.querySelector(
        '#making .wrap > div:first-child'
      );

      if (makingIntro) {
        const old = [...makingIntro.querySelectorAll('p')];

        (making.intro_paragraphs || []).forEach((p, i) => {
          if (old[i]) old[i].innerHTML = breaks(p);
        });

        for (
          let i = (making.intro_paragraphs || []).length;
          i < old.length;
          i++
        ) {
          old[i].remove();
        }
      }

      const projWrap = document.querySelector(
        '#making .wrap > .project-list'
      );

      if (projWrap) {
        projWrap.innerHTML = (making.projects || []).map(p =>
          `<div class="project">
            <span class="status">${esc(p.status)}</span>
            <h3>${breaks(p.title)}</h3>
            <p>${esc(p.description)}</p>
            <details class="project-details">
              <summary>${esc(p.details_summary)}</summary>
              <p>${esc(p.details)}</p>
            </details>
          </div>`
        ).join('');
      }

      // ========================================
      // 愛車と装備
      // ========================================

      const gear = data.gear || {};

      set('#gear .eyebrow', gear.eyebrow);
      set('#gear h2', gear.title, true);
      set('#gear > div p', gear.description);

      const gi = document.querySelector('#gear .gear-photo img');

      if (gi) {
        gi.src = gear.image || gi.src;
        gi.alt = gear.image_alt || '';
        gi.style.maxWidth = '100%';
        gi.style.height = 'auto';
      }

      const gl = document.querySelector('#gear .gear-list');

      if (gl) {
        gl.innerHTML = (gear.items || []).map(i =>
          `<div>
            <b>${esc(i.label)}</b>
            <span>${esc(i.value)}</span>
          </div>`
        ).join('');
      }

      // ========================================
      // このサイトについて
      // ========================================

      const about = data.about || {};

      set('#about .eyebrow', about.eyebrow);
      set('#about h2', about.title, true);

      const exp = document.querySelector('#about .experience');

      if (exp) {
        exp.innerHTML = (about.experience || []).map(i =>
          `<div>
            <strong>${esc(i.value)}</strong>
            <small>${esc(i.label)}</small>
          </div>`
        ).join('');
      }

      const aboutText = document.querySelector(
        '#about .about-inner > div:nth-child(2)'
      );

      if (aboutText) {
        const channel = aboutText.querySelector('.youtube-channel');
        aboutText.innerHTML = (about.paragraphs || []).map(p =>
          `<p>${esc(p)}</p>`
        ).join('');
        if (channel) aboutText.appendChild(channel);
      }
    }

    // ========================================
    // 個別記事ページ
    // ========================================

    const article = document.querySelector('#article-body');

    if (article) {
      const slug = getSlug();
      console.log('記事のslug:', slug);

      const item = (data.journeys || []).find(x => x.slug === slug);

      if (!item) {
        article.innerHTML =
          '<p>記事が見つかりません。管理画面で記事のURL用IDを確認してください。</p>';
        return;
      }

      document.title = `${item.title}｜走って、つくって。`;

      const meta = document.querySelector('meta[name="description"]');

      if (meta) meta.content = item.summary || '';

      const heroImg = document.querySelector('.hero > img');

      if (heroImg) {
        heroImg.src =
          item.hero_image ||
          item.image ||
          hero.image ||
          heroImg.src;

        // 記事トップ画像と一覧画像のALTを分ける。
        // 旧記事は従来のALTを引き継ぐ。
        heroImg.alt = item.hero_image_alt || item.image_alt || '';

        fixHeroImage(heroImg);
      }

      // 記事トップ画像の説明（未入力なら表示しない）
      addHeroCaptionStyle();

      const heroSection = document.querySelector('.hero');
      let heroCaption = document.querySelector('.hero-image-caption');

      if (item.hero_image_caption && heroSection) {
        if (!heroCaption) {
          heroCaption = document.createElement('p');
          heroCaption.className = 'hero-image-caption';
          heroSection.insertAdjacentElement('afterend', heroCaption);
        }

        heroCaption.textContent = item.hero_image_caption;
      } else if (heroCaption) {
        heroCaption.remove();
      }

      const tag = document.querySelector('.hero-copy .tag');

      if (tag) {
        tag.remove();
      }

      // 記事上部のカテゴリー表示を自動生成
      const articleCategoryLabel = document.querySelector('#article-category-label');

      if (articleCategoryLabel) {
        articleCategoryLabel.textContent =
          [item.region, item.ride_category].filter(Boolean).join(' / ');
      }

      const h = document.querySelector('.hero-copy h1');

      if (h) h.innerHTML = breaks(item.title || '');

      const hp = document.querySelector('.hero-copy p');

      if (hp) {
        hp.innerHTML = (item.summary || '')
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;')
          .replace(/\r\n|\r|\n/g, '<br>');
      }

      const breadcrumb = document.querySelector('#article-breadcrumb');

      if (breadcrumb) breadcrumb.textContent = item.title || '';

      const articleDate = document.querySelector('#article-date');

      if (articleDate) {
        articleDate.textContent = item.period || dateLabel(item.date);
      }

      // ========================================
      // 記事冒頭の概要・数値
      // ========================================

      const intro = document.querySelector('.intro');

      if (intro) {
        const h2 = intro.querySelector('h2');

        if (h2) {
          h2.innerHTML = breaks(item.intro_title || item.title);
        }

        const p = intro.querySelector('p');

        if (p) {
          p.innerHTML = (item.intro || item.summary || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/\r\n|\r|\n/g, '<br>');
        }

        const factsWrap = intro.querySelector('.facts');

        const rideDetails = Array.isArray(item.ride_details)
          ? item.ride_details.filter(x => x && x.label && x.value)
          : [];

        // すべての記事でCMSの走行情報から基本情報欄を生成。
        if (factsWrap) {
          const entries = [];

          if (item.distance) {
            entries.push({
              label: '走行距離',
              value: item.distance
            });
          }

          if (item.ascent) {
            entries.push({
              label: '獲得標高',
              value: item.ascent
            });
          }

          const periodValue = item.period || (
            item.date
              ? (() => {
                  const d = new Date(item.date);
                  return Number.isNaN(d.getTime())
                    ? ''
                    : `${d.getFullYear()}年${d.getMonth() + 1}月`;
                })()
              : ''
          );

          if (periodValue) {
            entries.push({
              label: '旅の時期',
              value: periodValue
            });
          }

          rideDetails.forEach(x => {
            entries.push({
              label: x.label,
              value: x.value
            });
          });

          factsWrap.innerHTML = entries.map(x =>
            `<div>
              <small>${esc(x.label)}</small>
              <strong>${esc(x.value)}</strong>
            </div>`
          ).join('');

                   factsWrap.hidden = entries.length === 0;
        }

        // 別府の記事だけに往復航路の案内を表示
        const beppuRouteNote = intro.querySelector('#beppu-route-note');

        if (beppuRouteNote && item.slug === 'beppu') {
          beppuRouteNote.innerHTML = `
            <span class="eyebrow">この旅を成立させた、往復別航路の工夫</span>
            <h3>大阪から出発して、神戸へ帰る。</h3>

            <div class="route-pair">
              <div>
                <small>往路 / 船中1泊目</small>
                <strong>大阪南港・ATC → 別府港</strong>
                <span>別府に着いたら、ここからライド開始。</span>
              </div>

              <div>
                <small>復路 / 船中2泊目</small>
                <strong>大分港 → 神戸港</strong>
                <span>走行後は豊後竹田から輪行し、大分港へ。</span>
              </div>
            </div>

            <p>
              今回の走行行程では、別府発の帰りの便は出港時刻が早く、間に合いません。
              そこで復路は大分港発を選びました。
              その代わり、翌朝の到着地は大阪ではなく神戸。
              神戸から自宅までの移動も含めて組んだ旅です。
            </p>

            <p class="small">
              この旅での航路選択の理由です。予約時は利用日のダイヤを確認してください。
            </p>
          `;

          beppuRouteNote.hidden = false;
        }
      }

      // ========================================
      // 本文の画像・目次
      // ========================================

      article.innerHTML = (window.AffiliateDisclosure?.html(item.body || '') || '') + safeMarkdown(item.body || '');

      // Stravaの埋め込みがある場合、記事本文の表示後に読み込む
      if (article.querySelector('.strava-embed-placeholder')) {
        const script = document.createElement('script');
        script.src = 'https://strava-embeds.com/embed.js';
        script.async = true;
        document.body.appendChild(script);
      }

      fixArticleImages(article);

      const toc = document.querySelector('.toc');

      if (toc) {
        const heads = [...article.querySelectorAll('h2, h3')];

        toc.innerHTML =
          '<p>IN THIS JOURNAL</p>' +
          heads.map((h, i) => {
            const id = 'article-section-' + (i + 1);

            h.id = id;

            return `<a href="#${id}">${esc(h.textContent)}</a>`;
          }).join('');
      }
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else {
    load();
  }
})();
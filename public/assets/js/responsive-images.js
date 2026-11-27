(() => {
  'use strict';
  // CMSのJSが差し替えた画像にも、生成時と同じサイズ・srcsetを適用する。
  fetch('/assets/image-manifest.json', { cache: 'no-cache' })
    .then((response) => { if (!response.ok) throw new Error('image manifest'); return response.json(); })
    .then(({ images, vectors = {} }) => {
      const lookup = new Map();
      Object.entries({ ...vectors, ...images }).forEach(([source, record]) => {
        lookup.set(source, record);
        record.variants.forEach((variant) => lookup.set(variant.src, record));
      });
      function enhance(image) {
        let record;
        try {
          const url = new URL(image.getAttribute('src') || '', location.href);
          if (url.origin !== location.origin) return;
          record = lookup.get(decodeURIComponent(url.pathname));
        } catch { return; }
        if (!record) return;
        const hero = image.fetchPriority === 'high' || image.id === 'hero-image' ||
          !!image.closest('.hero,.hero-image');
        const card = !!image.closest('.journey-card-photo,.making-card-photo');
        const compact = !!image.closest('.discovery-thumb');
        const gear = !!image.closest('.gear-photo');
        const splitHero = !!image.closest('.hero-image');
        const bodySizes = `(max-width:650px) min(${record.width}px, calc(100vw - 44px)), (max-width:1000px) min(${record.width}px, calc(100vw - 56px)), ${Math.min(record.width, 900)}px`;
        const values = {
          width: record.width, height: record.height,
          srcset: record.variants.map((v) => `${v.src} ${v.width}w`).join(', '),
          sizes: compact ? '88px' : splitHero ? '(max-width:650px) 100vw, 57.5vw' : hero ? '100vw' :
            card ? '(max-width:650px) calc(100vw - 44px), 370px' :
            gear ? '(max-width:650px) calc(100vw - 44px), (max-width:1100px) calc(50vw - 60px), 520px' : bodySizes,
          loading: hero ? 'eager' : 'lazy', decoding: 'async'
        };
        if (hero) values.fetchpriority = 'high';
        Object.entries(values).forEach(([name, value]) => {
          if (image.getAttribute(name) !== String(value)) image.setAttribute(name, value);
        });
      }
      const scan = (node) => {
        if (node.nodeType !== 1) return;
        if (node.tagName === 'IMG') enhance(node);
        node.querySelectorAll('img').forEach(enhance);
      };
      scan(document.documentElement);
      new MutationObserver((changes) => {
        changes.forEach((change) => {
          if (change.type === 'attributes') enhance(change.target);
          else change.addedNodes.forEach(scan);
        });
      }).observe(document.documentElement, { subtree: true, childList: true, attributes: true, attributeFilter: ['src'] });
    })
    .catch(() => { /* 静的HTMLと軽量化済みsrcは、マニフェスト取得失敗時も使用できる。 */ });
})();

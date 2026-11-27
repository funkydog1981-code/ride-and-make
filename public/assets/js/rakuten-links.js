/* 楽天のテキスト商品リンクだけに適用する限定的な属性保持。 */
(() => {
  'use strict';
  const allowed = ['href', 'rel', 'target', 'style', 'title'];
  const marker = 'data-rakuten-verified';
  function check(anchor) {
    const attrs = Object.fromEntries([...anchor.attributes].map(a => [a.name, a.value]));
    const bad = reason => ({ valid: false, reason });
    if (anchor.children.length || [...anchor.childNodes].some(n => n.nodeType !== 3) || !anchor.textContent.trim()) {
      return bad('画像や追加タグを含まない「テキストのみ」のaタグが必要です。');
    }
    if (Object.keys(attrs).some(k => !allowed.includes(k))) return bad('リンクに未対応の属性があります。');
    const href = attrs.href || '';
    try {
      const u = new URL(href);
      if (!/^https:\/\/hb\.afl\.rakuten\.co\.jp\//i.test(href) || u.hostname !== 'hb.afl.rakuten.co.jp' ||
          u.protocol !== 'https:' || u.username || u.password || u.port || u.hash ||
          !/^\/ichiba\/[A-Za-z0-9._/-]+$/.test(u.pathname) ||
          /[\s\\\u0000-\u001f\u007f]/.test(href) || /(?:^|\/)(?:\.|%2e){1,2}(?:\/|$)/i.test(href.split('?')[0])) {
        return bad('HTTPSの楽天市場アフィリエイトURLを確認してください。');
      }
      if (u.searchParams.getAll('link_type').length !== 1 || u.searchParams.get('link_type') !== 'text' ||
          u.searchParams.getAll('pc').length !== 1) return bad('楽天の「テキストのみ」の商品リンクが必要です。');
      const pc = u.searchParams.get('pc');
      const product = new URL(pc);
      if (!/^https?:\/\/item\.rakuten\.co\.jp\//i.test(pc) || product.hostname !== 'item.rakuten.co.jp' ||
          product.username || product.password || product.port || product.hash ||
          /[\s\\\u0000-\u001f\u007f]/.test(pc) || product.pathname.split('/').filter(Boolean).length < 2 ||
          /(?:^|\/)(?:\.|%2e){1,2}(?:\/|$)/i.test(pc.split('?')[0])) return bad('リンク先の商品URLを確認してください。');
    } catch { return bad('楽天リンクのURLを確認してください。'); }
    const rel = (attrs.rel || '').toLowerCase().split(/\s+/).filter(Boolean);
    if (!rel.includes('nofollow') || !rel.includes('sponsored') ||
        rel.some(x => !['nofollow', 'sponsored', 'noopener', 'noreferrer', 'ugc'].includes(x)) ||
        (attrs.target && attrs.target !== '_blank') || (attrs.target === '_blank' && !rel.includes('noopener'))) {
      return bad('発行リンクのrel・targetを確認してください。別タブにはnoopenerが必要です。');
    }
    if ('style' in attrs && !/^\s*word-wrap\s*:\s*break-word\s*;?\s*$/i.test(attrs.style)) {
      return bad('リンクのCSSはword-wrap:break-wordだけが使用できます。');
    }
    return { valid: true, attrs };
  }
  function candidate(anchor) {
    if (anchor.closest('.product-card')) return true;
    try { return new URL(anchor.getAttribute('href')).hostname === 'hb.afl.rakuten.co.jp'; }
    catch { return false; }
  }
  function sanitize(raw, options = {}) {
    const template = document.createElement('template');
    template.innerHTML = raw; // 不活性なDOMで事前検証する。
    const records = new Map();
    template.content.querySelectorAll('a').forEach(a => {
      const result = check(a);
      a.removeAttribute(marker); // 入力のマーカーは検証に使わず、必ず除去する。
      if (result.valid) {
        const id = String(records.size);
        records.set(id, result.attrs);
        [...a.attributes].forEach(attr => a.removeAttribute(attr.name));
        a.setAttribute(marker, id);
      } else if (candidate(a)) {
        a.replaceWith(document.createTextNode(a.textContent)); // 補正してリンクを通さない。
      } else {
        a.removeAttribute('style'); // 任意CSSへの許可を広げない。
      }
    });
    const config = { ...options, RETURN_DOM_FRAGMENT: true };
    if (config.ALLOWED_ATTR) config.ALLOWED_ATTR = [...config.ALLOWED_ATTR, marker];
    else config.ADD_ATTR = [...(config.ADD_ATTR || []), marker];
    const fragment = window.DOMPurify.sanitize(template.innerHTML, config);
    fragment.querySelectorAll(`a[${marker}]`).forEach(a => {
      const attrs = records.get(a.getAttribute(marker));
      [...a.attributes].forEach(attr => a.removeAttribute(attr.name));
      if (attrs) Object.entries(attrs).forEach(([name, value]) => a.setAttribute(name, value));
    });
    if (options.RETURN_DOM_FRAGMENT) return fragment;
    const holder = document.createElement('div');
    holder.append(fragment);
    return holder.innerHTML;
  }
  window.RakutenLinks = { check, sanitize };
})();

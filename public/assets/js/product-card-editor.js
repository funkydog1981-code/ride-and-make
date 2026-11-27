/* Decap公式のブロック拡張。記事データのフィールド・形式は変更しない。 */
(() => {
  'use strict';
  const esc = value => String(value || '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
  const fragment = value => {
    const template = document.createElement('template');
    template.innerHTML = String(value || ''); // template内は不活性。DOMへは挿入しない。
    return template.content;
  };
  // 編集中の発行リンク文字を確認ダイアログで参照する。記事データには追加しない。
  const sourceLabels = new Map();
  const cardPattern = /^<div class="product-card(?: product-card--no-image)?">\s*([\s\S]*?)<\/figure>\s*<\/div>$/m;
  function parseLink(value, name) {
    const nodes = [...fragment(value).childNodes].filter(n => n.nodeType !== 3 || n.textContent.trim());
    const a = nodes[0];
    if (nodes.length !== 1 || a?.nodeName !== 'A' || a.children.length ||
        [...a.childNodes].some(n => n.nodeType !== 3)) {
      throw new Error('楽天が発行した「テキストのみ」のaタグを1個貼り付けてください。');
    }
    const result = window.RakutenLinks?.check(a);
    if (!result?.valid) throw new Error(result?.reason || 'リンク検証処理を読み込めません。CMSを再読み込みしてください。');
    // 許可されたテキスト部分だけを変更し、URLと許可属性の値は保持する。
    return '<a' + [...a.attributes].map(attr => ` ${attr.name}="${esc(attr.value)}"`).join('') +
      '>' + esc(name == null ? a.textContent : `${String(name).trim()}を楽天市場で見る`) + '</a>';
  }
  function imagePath(value) {
    const path = String(value || '');
    if (!path) return '';
    let decoded;
    try { decoded = decodeURIComponent(path); } catch { throw new Error('画像のパスを確認してください。'); }
    if (!path.startsWith('/assets/') || /[?#\\\u0000-\u001f\u007f]/.test(decoded) ||
        decoded.split('/').some(part => part === '..' || part === '.')) {
      throw new Error('画像はCMSのメディアライブラリから選択してください（/assets/内）。');
    }
    return path;
  }
  function validate(data) {
    if (!String(data.name || '').trim()) throw new Error('商品名を入力してください。');
    imagePath(data.image);
    parseLink(data.link, data.name);
  }
  function plain(node) {
    if (!node) return '';
    const copy = node.cloneNode(true);
    copy.querySelectorAll('br').forEach(br => br.replaceWith('\n'));
    return copy.textContent;
  }
  function readCard(card) {
    return {
      name: card.querySelector('h3')?.textContent || '',
      image: card.querySelector('img')?.getAttribute('src') || '',
      alt: card.querySelector('img')?.getAttribute('alt') || '',
      description: plain(card.querySelector('.product-card__description')) ||
        [...card.querySelectorAll('figure > p')].find(p => !p.querySelector('a') &&
          !p.classList.contains('product-card__invalid-link'))?.textContent || '',
      link: card.querySelector('a')?.outerHTML ||
        card.querySelector('.product-card__invalid-link')?.textContent || ''
    };
  }
  function toBlock(data) {
    let link;
    try {
      const original = fragment(parseLink(data.link)).querySelector('a');
      sourceLabels.set(original.getAttribute('href'), original.textContent);
      link = parseLink(data.link, data.name);
    }
    catch { link = `<span class="product-card__invalid-link">${esc(data.link)}</span>`; }
    let image = '';
    try { image = imagePath(data.image); } catch { /* 安全な下書きを表示し、保存時に検証する。 */ }
    // 不正な画像パスもテキストとして保持し、保存前に検出する。
    const invalidImage = data.image && !image ? `<span class="product-card__invalid-image">${esc(data.image)}</span>` : '';
    return `<div class="product-card${image ? '' : ' product-card--no-image'}">\n` +
      (image ? `<img src="${esc(image)}" alt="${esc(data.alt)}">\n` : invalidImage) +
      `<figure class="product-card__body">\n<h3>${esc(data.name)}</h3>\n` +
      (data.description ? `<p class="product-card__description">${esc(data.description).replace(/\r?\n/g, '<br>')}</p>\n` : '') +
      `<p>${link}</p>\n</figure>\n</div>`;
  }
  const LinkControl = window.createClass({
    isValid() {
      try { parseLink(this.props.value); return true; }
      catch (error) { return { error: { message: error.message } }; }
    },
    render() {
      let error = '';
      try { parseLink(this.props.value); } catch (e) { error = e.message; }
      return window.h('div', {},
        window.h('textarea', {
          id: this.props.forID, className: this.props.classNameWrapper,
          rows: 5, value: this.props.value || '', 'aria-invalid': !!error,
          onChange: event => this.props.onChange(event.target.value)
        }),
        window.h('p', {}, '表示文字は「商品名を楽天市場で見る」に自動更新します。商品名と実際のリンク先商品が一致することを確認してください。価格・特典等は商品名に追加しないでください。'),
        error ? window.h('p', { role: 'status' }, error) : null);
    }
  });
  CMS.registerWidget('rakuten-text-link', LinkControl);
  CMS.registerEditorComponent({
    id: 'product-card', label: '商品カードを挿入',
    fields: [
      { name: 'name', label: '商品名', widget: 'string', required: true },
      { name: 'image', label: '商品画像（利用許可のある画像）', widget: 'image', required: false },
      { name: 'alt', label: '画像のALTテキスト', widget: 'string', required: false },
      { name: 'description', label: '短い商品説明', widget: 'text', required: false },
      { name: 'link', label: '楽天発行のテキストリンク（aタグ全体）', widget: 'rakuten-text-link', required: true }
    ],
    pattern: cardPattern,
    fromBlock(match) {
      const card = fragment(match[0]).querySelector('.product-card');
      const data = readCard(card);
      data.image = card.querySelector('.product-card__invalid-image')?.textContent || data.image;
      return data;
    },
    toBlock,
    toPreview(data, getAsset) {
      const card = fragment(toBlock(data));
      const img = card.querySelector('img');
      if (img && getAsset) img.setAttribute('src', String(getAsset(data.image)));
      // CMS内の商品リンクは操作中の誤クリックを防ぐ。保存HTMLには影響しない。
      card.querySelectorAll('a').forEach(a => { a.removeAttribute('href'); a.removeAttribute('target'); });
      const wrapper = document.createElement('div');
      wrapper.append(card);
      return wrapper.innerHTML;
    }
  });
  CMS.registerPreviewStyle('/assets/css/product-card.css');
  CMS.registerEventListener({
    name: 'preSave',
    handler: ({ entry }) => {
      if (entry.get('collection') !== 'site') return entry.get('data');
      let data = entry.get('data');
      const confirmations = [];
      ['journeys', 'making_articles'].forEach(group => {
        const items = data.get(group);
        if (!items) return;
        items.forEach((item, index) => {
          const body = item.get('body') || '';
          if (!body.includes('product-card')) return;
          // コード例として書いたHTMLは、実際の広告カードとして検証しない。
          let fence = null;
          // 除外部分も同じ文字数で残し、本文中のカード位置を維持する。
          const content = body.split('\n').map(line => {
            const marker = line.match(/^ {0,3}(`{3,}|~{3,})/);
            if (fence) {
              if (marker && marker[1][0] === fence[0] && marker[1].length >= fence.length &&
                  /^ {0,3}(?:`+|~+)\s*$/.test(line)) fence = null;
              return ' '.repeat(line.length);
            }
            if (marker) { fence = marker[1]; return ' '.repeat(line.length); }
            return /^(?: {4}|\t)/.test(line) ? ' '.repeat(line.length) : line;
          }).join('\n').replace(/(`+)[^`]*?\1/g, match => match.replace(/[^\n]/g, ' '));
          fragment(content).querySelectorAll('.product-card').forEach(card => {
            try {
              if (card.querySelector('.product-card__invalid-image')) throw new Error('画像のパスを確認してください。');
              const product = readCard(card);
              validate(product);
              const anchor = card.querySelector('a');
              const original = sourceLabels.get(anchor.getAttribute('href')) || anchor.textContent;
              const mismatch = !original.normalize('NFKC').includes(product.name.trim().normalize('NFKC'));
              confirmations.push(`${mismatch ? '【商品名の対応を要確認】' : '・'}${product.name}\n　貼り付けたリンクの文字：${original.slice(0, 160)}`);
            } catch (error) { throw new Error(`${group === 'journeys' ? '旅' : '制作'}記事${index + 1}件目の商品カード：${error.message}`); }
          });
          // Rich Text以外の編集経路でも保存直前に表示文字を統一する。
          // aタグの開始・終了タグと、それ以外の本文は文字列のまま保持する。
          let normalized = body;
          const matches = [...content.matchAll(new RegExp(cardPattern.source, 'gm'))];
          matches.reverse().forEach(match => {
            const original = body.slice(match.index, match.index + match[0].length);
            const product = readCard(fragment(original).querySelector('.product-card'));
            const fixed = original.replace(/(<a\b(?:[^"'<>]|"[^"]*"|'[^']*')*>)[\s\S]*?(<\/a\s*>)/i,
              (_, open, close) => open + esc(`${product.name.trim()}を楽天市場で見る`) + close);
            normalized = normalized.slice(0, match.index) + fixed + normalized.slice(match.index + original.length);
          });
          if (normalized !== body) data = data.setIn([group, index, 'body'], normalized);
        });
      });
      if (confirmations.length && !window.confirm('商品名が実際のリンク先商品を正しく表していることを確認してください。リンク先の内容は自動照合していません。異なる商品や未確認のリンクがある場合はキャンセルしてください。\n\n' + [...new Set(confirmations)].join('\n\n'))) {
        throw new Error('商品名とリンク先商品の確認が完了していないため、保存を中止しました。');
      }
      return data;
    }
  });
})();

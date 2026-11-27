/* 本文の広告の目印をサニタイズ前に確認する。外部通信やCookieは使用しない。 */
(() => {
  'use strict';
  const notice = 'この記事にはアフィリエイト広告が含まれています。';
  const markup = `<aside class="affiliate-disclosure" aria-label="広告について"><p>${notice}</p><a href="/privacy/#advertising">広告・アフィリエイトについて</a></aside>`;
  function cleanSource(value) {
    let fence = null;
    return String(value || '').split(/\r?\n/).filter(line => {
      const m = line.match(/^ {0,3}(`{3,}|~{3,})/);
      if (fence) {
        if (m && m[1][0] === fence[0] && m[1].length >= fence.length && /^ {0,3}(?:`+|~+)\s*$/.test(line)) fence = null;
        return false;
      }
      if (m) { fence = m[1]; return false; }
      return !/^(?: {4}|\t)/.test(line);
    }).join('\n').replace(/(`+)[^`]*?\1/g, '');
  }
  function rakutenUrl(value) {
    try {
      const u = new URL(value.trim());
      return ['https:', 'http:'].includes(u.protocol) && !u.username && !u.password && !u.port &&
        ['hb.afl.rakuten.co.jp', 'hbb.afl.rakuten.co.jp', 'a.r10.to'].includes(u.hostname);
    } catch { return false; }
  }
  function detect(value) {
    const source = cleanSource(value);
    const template = document.createElement('template');
    template.innerHTML = source; // templateは不活性。入力HTMLを画面へ挿入しない。
    template.content.querySelectorAll('script,style,pre,code').forEach(n => n.remove());
    const ad = !!template.content.querySelector('.product-card') || [...template.content.querySelectorAll('a')].some(a =>
      (a.getAttribute('rel') || '').toLowerCase().split(/\s+/).includes('sponsored') || rakutenUrl(a.getAttribute('href') || ''));
    const markdown = source.replace(/<!--[\s\S]*?-->|<(script|style|pre|code)\b[^>]*>[\s\S]*?<\/\1\s*>/gi, '');
    const urls = [...markdown.matchAll(/\]\(\s*<?([^\s)>]+)|^ {0,3}\[[^\]]+\]:\s*<?([^\s>]+)|<(https?:\/\/[^\s<>]+)>/gmi)];
    const manual = /(?:この記事|本記事|本ページ|当記事)(?:には|は)(?:アフィリエイト広告|広告|PR|プロモーション)(?:が|を)?(?:含まれ(?:てい)?ます|含みます|利用しています)/i.test(template.content.textContent.replace(/\s+/g, ''));
    return { advertising: ad || urls.some(m => rakutenUrl(m[1] || m[2] || m[3])), manual };
  }
  function html(source) { const s = detect(source); return s.advertising && !s.manual ? markup : ''; }
  window.AffiliateDisclosure = { detect, html };
  // ファイルコレクションの公式プレビューAPI。既存の各フィールドのプレビューを再利用する。
  if (window.CMS && window.createClass && window.h) {
    CMS.registerPreviewStyle('/assets/css/affiliate-disclosure.css');
    CMS.registerPreviewTemplate('content', window.createClass({
      render() {
        const data = this.props.entry.get('data');
        return window.h('div', {}, data.keySeq().toArray().map(key => {
          if (!['journeys', 'making_articles'].includes(key)) return window.h('section', { key }, this.props.widgetFor(key));
          return window.h('section', { key }, this.props.widgetsFor(key).map((item, index) => {
            const show = !!html(item.getIn(['data', 'body']));
            return window.h('article', { key: index },
              window.h('h2', {}, item.getIn(['data', 'title'])),
              show ? window.h('aside', { className: 'affiliate-disclosure' },
                window.h('p', {}, notice), window.h('a', { href: '/privacy/#advertising' }, '広告・アフィリエイトについて')) : null,
              item.get('widgets').entrySeq().toArray().map(([name, widget]) => window.h('div', { key: name }, widget)));
          }));
        }));
      }
    }));
  }
})();

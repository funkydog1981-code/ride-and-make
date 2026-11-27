// Netlify組み込みAPIだけを利用。キャッシュ失敗でも通常の画像生成へ戻す。
module.exports = {
  async onPreBuild({ utils }) {
    try { await utils.cache.restore('.image-cache'); }
    catch (error) { console.warn('画像キャッシュを復元できないため再生成します:', error.message); }
  },
  async onPostBuild({ utils }) {
    try { await utils.cache.save('.image-cache'); }
    catch (error) { console.warn('画像キャッシュの保存をスキップしました:', error.message); }
  }
};

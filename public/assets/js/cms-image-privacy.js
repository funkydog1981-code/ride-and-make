/* CMS内部APIを上書きせず、標準のファイル入力境界で画像を処理する。 */
(() => {
  'use strict';
  const passed = new WeakSet();
  const isImage = file => file.type.startsWith('image/') || /\.(jpe?g|png|webp|svg|gif|heic|heif|avif|tiff?|bmp|jxl)$/i.test(file.name);
  async function handle(event) {
    if (passed.has(event)) return;
    const input = event.type === 'change' && event.target instanceof HTMLInputElement && event.target.type === 'file' ? event.target : null;
    const source = input?.files || event.dataTransfer?.files || event.clipboardData?.files;
    const files = source ? [...source] : [];
    if (!files.some(isImage)) return;
    event.preventDefault(); event.stopImmediatePropagation();
    try {
      if (!window.ImagePrivacy || typeof DataTransfer !== 'function') throw new Error('位置情報除去機能を読み込めません。再読み込みしてください。');
      const cleaned = await Promise.all(files.map(async file => {
        if (!isImage(file)) return file;
        if (file.size > 100 * 1024 * 1024) throw new Error('100MB以下の画像を選択してください。');
        const before = new Uint8Array(await file.arrayBuffer()), after = ImagePrivacy.clean(before, file.name);
        const verified = ImagePrivacy.clean(after, file.name);
        if (verified.length !== after.length || verified.some((x, i) => x !== after[i])) throw new Error('位置情報の除去結果を確認できません。');
        return after.length === before.length && after.every((x, i) => x === before[i]) ? file :
          new File([after], file.name, {type:file.type, lastModified:file.lastModified});
      }));
      const transfer = new DataTransfer(); cleaned.forEach(file => transfer.items.add(file));
      document.getElementById('image-privacy-error')?.remove();
      let next;
      if (input) { input.files = transfer.files; next = new Event('change', {bubbles:true}); }
      else if (event.type === 'drop') next = new DragEvent('drop', {bubbles:true,cancelable:true,dataTransfer:transfer,clientX:event.clientX,clientY:event.clientY});
      else {
        for (const type of event.clipboardData.types) if (type !== 'Files') transfer.setData(type, event.clipboardData.getData(type));
        next = new ClipboardEvent('paste', {bubbles:true,cancelable:true,clipboardData:transfer});
      }
      passed.add(next); event.target.dispatchEvent(next);
    } catch (error) {
      if (input) input.value = '';
      let message = document.getElementById('image-privacy-error');
      if (!message) { message = document.createElement('div'); message.id = 'image-privacy-error'; message.setAttribute('role','alert'); message.style.cssText = 'position:fixed;z-index:99999;left:12px;right:12px;bottom:12px;padding:16px;background:#fff3f0;border:2px solid #a33;color:#611;'; document.body.appendChild(message); }
      message.textContent = '画像は保存していません。' + error.message;
    }
  }
  for (const name of ['change','drop','paste']) document.addEventListener(name, handle, true);
})();

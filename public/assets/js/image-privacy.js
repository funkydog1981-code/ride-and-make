/* 画像本体を再エンコードせず、標準の位置メタデータを除去する。NodeとCMSで共用。 */
(function (root) {
  'use strict';
  const ascii = bytes => Array.from(bytes, x => String.fromCharCode(x)).join('');
  const bytes = text => Uint8Array.from(text, x => x.charCodeAt(0));
  const concat = parts => { const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0)); let i = 0; for (const p of parts) { out.set(p, i); i += p.length; } return out; };
  const fail = () => { throw new Error('画像メタデータを安全に検証できません。JPEG・PNG・WebPへ書き出すか、位置情報を除去できるツールで確認してください。'); };
  const location = /GPS|latitude|longitude|geotag|geolocation|location(?:shown|created)?|sublocation|\bcity\b|\bcountry\b|\bstate\b|province|ISO6709/i;
  function tiff(input) {
    const out = input.slice(), view = new DataView(out.buffer, out.byteOffset, out.byteLength);
    const le = ascii(out.slice(0, 2)) === 'II';
    if (!le && ascii(out.slice(0, 2)) !== 'MM') fail();
    const bound = (i, n) => { if (!Number.isSafeInteger(i) || !Number.isSafeInteger(n) || i < 0 || n < 0 || i + n > out.length) fail(); };
    const u16 = i => { bound(i, 2); return view.getUint16(i, le); };
    const u32 = i => { bound(i, 4); return view.getUint32(i, le); };
    const sizes = {1:1,2:1,3:2,4:4,5:8,6:1,7:1,8:2,9:4,10:8,11:4,12:8,13:4};
    if (u16(2) !== 42) fail();
    const seen = new Set(), clear = [], dirs = [], protectedRanges = [[0, 8]];
    function walk(offset, gps = false) {
      if (!offset) return;
      if (seen.has(offset) || seen.size > 100) fail();
      seen.add(offset); const count = u16(offset); if (count > 4096) fail();
      bound(offset, 2 + count * 12 + 4); const entries = [];
      if (gps) clear.push([offset, 2 + count * 12 + 4]); else protectedRanges.push([offset, 2 + count * 12 + 4]);
      for (let n = 0; n < count; n++) {
        const pos = offset + 2 + n * 12, tag = u16(pos), type = u16(pos + 2), number = u32(pos + 4);
        if (!sizes[type]) fail(); const len = sizes[type] * number;
        const valuePos = len > 4 ? u32(pos + 8) : pos + 8; bound(valuePos, len);
        const isGPS = tag === 34853;
        const rawText = ascii(out.slice(valuePos, valuePos + len)).replace(/\x00/g, '');
        const maker = tag === 37500 || tag === 33723 || tag === 34377 ||
          (tag === 700 && location.test(rawText)) ||
          ([270,37510,40091,40092,40093,40094,40095].includes(tag) && location.test(rawText));
        // MakerNoteにはメーカー独自の位置情報が入り得るため、安全側で除去する。
        if (gps || isGPS || maker) { if (len > 4) clear.push([valuePos, len]); }
        else if (len > 4) protectedRanges.push([valuePos, len]);
        if (isGPS) { if (type !== 4 || number !== 1) fail(); walk(u32(pos + 8), true); }
        else if ([34665,40965,330].includes(tag)) {
          if (![4,13].includes(type) || number > 100) fail();
          for (let k = 0; k < number; k++) walk(u32(valuePos + k * 4), gps);
        }
        if (!gps && !isGPS && !maker) entries.push(out.slice(pos, pos + 12));
      }
      const next = u32(offset + 2 + count * 12); if (next) walk(next, gps);
      if (!gps) dirs.push({offset, count, entries, next});
    }
    walk(u32(4));
    // 別の非位置情報とデータ領域が重なる異常なEXIFは変更せず拒否する。
    for (const [start, len] of clear) {
      if (protectedRanges.some(([p, n]) => start < p + n && p < start + len)) fail();
      out.fill(0, start, start + len);
    }
    for (const d of dirs) {
      if (d.entries.length === d.count) continue;
      view.setUint16(d.offset, d.entries.length, le);
      let pos = d.offset + 2; for (const entry of d.entries) { out.set(entry, pos); pos += 12; }
      out.fill(0, pos, d.offset + 2 + d.count * 12 + 4); view.setUint32(pos, d.next, le);
    }
    return out;
  }
  function exif(data) {
    const prefix = ascii(data.slice(0, 6)) === 'Exif\x00\x00' ? 6 : 0;
    return concat([data.slice(0, prefix), tiff(data.slice(prefix))]);
  }
  function xmp(data) {
    const text = ascii(data);
    // 分割された拡張XMPはフィールド名が境界をまたぐ場合があるため、全断片を除去する。
    return location.test(text) || /xmp\/extension\/|HasExtendedXMP/.test(text) ? null : data;
  }
  function iptc(data) {
    const parts = []; let i = 0;
    while (i < data.length) {
      if (data[i] !== 0x1c || i + 5 > data.length) fail();
      const record = data[i + 1], dataset = data[i + 2]; let length = data[i + 3] * 256 + data[i + 4], head = 5;
      if (length & 0x8000) { const n = length & 0x7fff; if (!n || n > 4 || i + 5 + n > data.length) fail(); length = 0; for (let j = 0; j < n; j++) length = length * 256 + data[i + 5 + j]; head += n; }
      if (i + head + length > data.length) fail();
      if (!(record === 2 && [26,27,90,92,95,100,101].includes(dataset))) parts.push(data.slice(i, i + head + length));
      i += head + length;
    }
    return concat(parts);
  }
  function photoshop(data) {
    const header = 'Photoshop 3.0\x00'; if (ascii(data.slice(0, 14)) !== header) fail();
    const parts = [data.slice(0, 14)]; let i = 14;
    while (i < data.length) {
      if (ascii(data.slice(i, i + 4)) !== '8BIM' || i + 7 > data.length) fail();
      const start = i, id = data[i + 4] * 256 + data[i + 5], nameLen = data[i + 6]; i += 6 + 1 + nameLen; if ((1 + nameLen) % 2) i++;
      if (i + 4 > data.length) fail(); const sizePos = i, size = new DataView(data.buffer, data.byteOffset + i, 4).getUint32(0); i += 4;
      if (i + size > data.length) fail(); const raw = data.slice(i, i + size); i += size + size % 2;
      if (id === 0x0404) {
        const cleaned = iptc(raw), prefix = data.slice(start, sizePos + 4); new DataView(prefix.buffer).setUint32(prefix.length - 4, cleaned.length);
        parts.push(prefix, cleaned); if (cleaned.length % 2) parts.push(new Uint8Array(1));
      } else if (id === 0x0424) { const cleaned = xmp(raw); if (cleaned) parts.push(data.slice(start, i)); }
      else parts.push(data.slice(start, i));
    }
    return concat(parts);
  }
  function jpeg(data) {
    const parts = [data.slice(0, 2)]; let i = 2;
    while (i < data.length) {
      const start = i; if (data[i++] !== 255) fail(); while (data[i] === 255) i++;
      const marker = data[i++];
      if (marker === 0xd9) { if (i !== data.length) fail(); parts.push(data.slice(start, i)); return concat(parts); }
      if (marker === 0xda) {
        if (i + 2 > data.length) fail(); const n = data[i] * 256 + data[i + 1]; if (n < 2 || i + n > data.length) fail(); i += n;
        while (i < data.length) {
          if (data[i] !== 255) { i++; continue; }
          let j = i + 1; while (data[j] === 255) j++;
          if (data[j] === 0 || (data[j] >= 0xd0 && data[j] <= 0xd7)) { i = j + 1; continue; }
          break;
        }
        parts.push(data.slice(start, i)); continue;
      }
      if (i + 2 > data.length) fail(); const length = data[i] * 256 + data[i + 1]; if (length < 2 || i + length > data.length) fail();
      let body = data.slice(i + 2, i + length); i += length;
      if (marker === 0xe1) {
        if (ascii(body.slice(0, 6)) === 'Exif\x00\x00') body = exif(body);
        else if (ascii(body.slice(0, 40)).startsWith('http://ns.adobe.com/')) { body = xmp(body); if (!body) continue; }
        else fail();
      } else if (marker === 0xed) body = photoshop(body);
      else if (marker === 0xe2 && !ascii(body.slice(0, 12)).startsWith('ICC_PROFILE')) fail();
      else if (marker >= 0xe3 && marker <= 0xef && marker !== 0xee) fail();
      else if (marker === 0xfe && location.test(ascii(body))) continue;
      // 現在のセグメントマーカーと、必要時だけ更新した長さを連結。
      const prefix = data.slice(start, i - length); parts.push(prefix, Uint8Array.of((body.length + 2) >> 8, (body.length + 2) & 255), body);
    }
    fail();
  }
  function crc32(data) { let c = 0xffffffff; for (const b of data) { c ^= b; for (let k = 0; k < 8; k++) c = (c >>> 1) ^ (0xedb88320 & -(c & 1)); } return (c ^ 0xffffffff) >>> 0; }
  function png(data) {
    const parts = [data.slice(0, 8)]; let i = 8, ended = false;
    while (i < data.length) {
      if (i + 12 > data.length) fail(); const view = new DataView(data.buffer, data.byteOffset + i), n = view.getUint32(0), type = ascii(data.slice(i + 4, i + 8));
      if (i + 12 + n > data.length) fail(); const chunk = data.slice(i + 4, i + 8 + n); if (crc32(chunk) !== view.getUint32(8 + n)) fail();
      let body = data.slice(i + 8, i + 8 + n); i += n + 12;
      // 圧縮テキストも含め、任意スキーマのPNGテキストメタデータは保存しない。
      if (['tEXt','zTXt','iTXt'].includes(type)) continue;
      if (type === 'eXIf') body = exif(body);
      else if (!['IHDR','PLTE','IDAT','IEND','tRNS','cHRM','gAMA','iCCP','sBIT','sRGB','bKGD','hIST','pHYs','sPLT','sTER','tIME','acTL','fcTL','fdAT'].includes(type)) fail();
      const out = new Uint8Array(body.length + 12), v = new DataView(out.buffer); v.setUint32(0, body.length); out.set(bytes(type), 4); out.set(body, 8); v.setUint32(body.length + 8, crc32(out.slice(4, body.length + 8))); parts.push(out);
      if (type === 'IEND') { ended = true; if (i !== data.length) fail(); break; }
    }
    if (!ended) fail(); return concat(parts);
  }
  function webp(data) {
    if (new DataView(data.buffer, data.byteOffset).getUint32(4, true) + 8 !== data.length) fail();
    const parts = []; let i = 12, removedXmp = false;
    while (i < data.length) {
      if (i + 8 > data.length) fail(); const type = ascii(data.slice(i, i + 4)), n = new DataView(data.buffer, data.byteOffset + i).getUint32(4, true); if (i + 8 + n + n % 2 > data.length) fail();
      let body = data.slice(i + 8, i + 8 + n); i += 8 + n + n % 2;
      if (type === 'EXIF') body = exif(body);
      else if (type === 'XMP ') { body = xmp(body); if (!body) { removedXmp = true; continue; } }
      else if (!['VP8 ','VP8L','VP8X','ALPH','ANIM','ANMF','ICCP'].includes(type)) fail();
      const chunk = new Uint8Array(8 + body.length + body.length % 2); chunk.set(bytes(type)); new DataView(chunk.buffer).setUint32(4, body.length, true); chunk.set(body, 8); parts.push(chunk);
    }
    if (removedXmp) for (const part of parts) if (ascii(part.slice(0, 4)) === 'VP8X') part[8] &= ~4;
    const body = concat(parts), header = data.slice(0, 12); new DataView(header.buffer).setUint32(4, body.length + 4, true); return concat([header, body]);
  }
  function clean(input, name = '') {
    const data = new Uint8Array(input);
    if (data[0] === 255 && data[1] === 216) return jpeg(data);
    if (ascii(data.slice(0, 8)) === '\x89PNG\r\n\x1a\n') return png(data);
    if (ascii(data.slice(0, 4)) === 'RIFF' && ascii(data.slice(8, 12)) === 'WEBP') return webp(data);
    if (/\.svg$/i.test(name)) {
      const text = new TextDecoder('utf-8', {fatal:true}).decode(data);
      if (!/<svg\b/i.test(text) || /<metadata\b|GPS|latitude|longitude|geotag|geolocation/i.test(text)) fail();
      return data; // メタデータを持たない既存SVGのみ。SVGメタデータの自動編集は行わない。
    }
    fail();
  }
  const api = {clean};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.ImagePrivacy = api;
})(typeof globalThis !== 'undefined' ? globalThis : this);

if (typeof module !== 'undefined' && require.main === module) {
  const fs = require('fs'), mode = process.argv[2];
  const paths = process.argv[3] === '--json' ? JSON.parse(fs.readFileSync(0, 'utf8')) : process.argv.slice(3), result = [];
  for (const path of paths) {
    try {
      const before = fs.readFileSync(path), after = module.exports.clean(before, path), dirty = !before.equals(Buffer.from(after));
      if (mode === '--clean' && dirty) fs.writeFileSync(path, after);
      result.push({path, dirty, cleaned: mode === '--clean' && dirty});
    } catch (error) { result.push({path, error: error.message}); }
  }
  process.stdout.write(JSON.stringify(result));
  if (result.some(x => x.error || (mode !== '--clean' && x.dirty))) process.exitCode = 1;
}

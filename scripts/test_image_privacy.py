"""合成画像のみでメタデータ・画素保持と拒否動作を確認する。実座標は使用しない。"""
from pathlib import Path
from io import BytesIO
import json
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image, TiffImagePlugin
from check_image_privacy import inspect, assert_clean, staged


class ImagePrivacyTests(unittest.TestCase):
    def fixture(self, path, fmt='JPEG', gps=True):
        image = Image.new('RGB', (19, 13), (40, 120, 200))
        exif = Image.Exif()
        exif[274] = 6
        exif[272] = 'Synthetic camera'
        exif[306] = '2000:01:01 00:00:00'
        if gps:
            q = TiffImagePlugin.IFDRational
            exif[34853] = {0: b'\x02\x03\x00\x00', 1: 'N', 2: (q(0, 1), q(0, 1), q(0, 1))}
        image.save(path, format=fmt, exif=exif)

    def test_jpeg_png_webp_preserve_pixels_orientation_and_dates(self):
        with tempfile.TemporaryDirectory() as d:
            for fmt, suffix in [('JPEG','.jpg'), ('PNG','.png'), ('WEBP','.webp')]:
                p = Path(d) / ('fixture' + suffix)
                self.fixture(p, fmt)
                before = p.read_bytes()
                self.assertTrue(inspect([p])[0]['dirty'])
                self.assertTrue(inspect([p], clean=True)[0]['cleaned'])
                with Image.open(BytesIO(before)) as a, Image.open(p) as b:
                    self.assertEqual(a.tobytes(), b.tobytes())
                    self.assertEqual(a.size, b.size)
                    self.assertFalse(b.getexif().get(34853))
                    for key in [274,272,306]:
                        self.assertEqual(a.getexif()[key], b.getexif()[key])
                self.assertFalse(inspect([p])[0]['dirty'])

    def test_clean_images_are_byte_identical(self):
        with tempfile.TemporaryDirectory() as d:
            for fmt, suffix in [('JPEG','.jpg'), ('PNG','.png'), ('WEBP','.webp')]:
                p = Path(d) / ('fixture' + suffix)
                self.fixture(p, fmt, gps=False)
                before = p.read_bytes()
                self.assertFalse(inspect([p], clean=True)[0]['dirty'])
                self.assertEqual(before, p.read_bytes())

    def test_xmp_after_scan_and_iptc_locations_are_removed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'fixture.jpg'
            self.fixture(p, gps=False)
            raw = p.read_bytes()
            xmp = b'http://ns.adobe.com/xap/1.0/\0<rdf:Description exif:GPSLatitude="TEST"/>'
            segment = b'\xff\xe1' + struct.pack('>H', len(xmp) + 2) + xmp
            # SOS以降に置かれたメタデータも検査する。
            p.write_bytes(raw[:-2] + segment + raw[-2:])
            self.assertTrue(inspect([p], clean=True)[0]['dirty'])
            self.assertEqual(raw, p.read_bytes())
            extended = b'http://ns.adobe.com/xmp/extension/\0SPLIT-METADATA'
            segment = b'\xff\xe1' + struct.pack('>H', len(extended) + 2) + extended
            p.write_bytes(raw[:2] + segment + raw[2:])
            inspect([p], clean=True)
            self.assertEqual(raw, p.read_bytes())
            iptc = b'\x1c\x02\x5a\x00\x04TEST' + b'\x1c\x02\x50\x00\x04KEEP'
            resource = b'Photoshop 3.0\0' + b'8BIM\x04\x04\0\0' + struct.pack('>I', len(iptc)) + iptc
            p.write_bytes(raw[:2] + b'\xff\xed' + struct.pack('>H', len(resource) + 2) + resource + raw[2:])
            inspect([p], clean=True)
            self.assertNotIn(b'TEST', p.read_bytes())
            self.assertIn(b'KEEP', p.read_bytes())

    def test_png_compressed_text_and_unknown_formats_fail_safe(self):
        from PIL.PngImagePlugin import PngInfo
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'text.png'
            info = PngInfo(); info.add_text('GPSLatitude', 'TEST', zip=True)
            Image.new('RGB', (3, 2)).save(p, pnginfo=info)
            self.assertTrue(inspect([p], clean=True)[0]['dirty'])
            with Image.open(p) as image:
                self.assertFalse(image.info)
            q = Path(d) / 'unsupported.heic'; q.write_bytes(b'unsupported')
            before = q.read_bytes()
            self.assertIn('error', inspect([q], clean=True)[0])
            self.assertEqual(before, q.read_bytes())

    def test_build_guard_and_staged_bytes_not_worktree(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'fixture.jpg'; self.fixture(p)
            with self.assertRaisesRegex(ValueError, '位置情報検査で停止'):
                assert_clean(Path(d))
            raw = p.read_bytes()
            # 作業ツリーがクリーンでも、Gitインデックスに残る元データを検査する。
            inspect([p], clean=True)
            with patch('check_image_privacy.subprocess.check_output', side_effect=[
                b'100644 ' + b'a' * 40 + b' 0\tpublic/fixture.jpg\0', raw]):
                self.assertTrue(staged()[0]['dirty'])

    def test_large_path_list_avoids_windows_command_line_limit(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ('fixture-' + 'x' * 80 + '.jpg')
            self.fixture(p, gps=False)
            result = inspect([p] * 500)
            self.assertEqual(len(result), 500)
            self.assertFalse(any(x.get('dirty') or x.get('error') for x in result))


if __name__ == '__main__':
    unittest.main()

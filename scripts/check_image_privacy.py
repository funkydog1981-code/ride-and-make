"""画像を再圧縮しない位置メタデータ検査。--stagedはGitインデックスを検査。"""
from pathlib import Path
import argparse
import json
import subprocess
import tempfile
import sys

ROOT = Path(__file__).resolve().parent.parent
FORMATS = {'.jpg', '.jpeg', '.png', '.webp', '.svg', '.gif', '.heic', '.heif', '.avif', '.tif', '.tiff', '.bmp', '.jxl'}


def images(root):
    return sorted(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in FORMATS)


def inspect(paths, clean=False):
    paths = list(paths)
    if not paths:
        return []
    # Windowsのコマンドライン長上限を避けるため、一覧は標準入力で渡す。
    result = subprocess.run(['node', str(ROOT / 'public/assets/js/image-privacy.js'),
                             '--clean' if clean else '--check', '--json'],
                            input=json.dumps(list(map(str, paths))),
                            capture_output=True, encoding='utf-8', timeout=120)
    if result.returncode not in {0, 1} or not result.stdout:
        raise ValueError('画像位置情報検査を実行できません。Node.jsの利用を確認してください。')
    return json.loads(result.stdout)


def assert_clean(root):
    problems = [x for x in inspect(images(root)) if x.get('dirty') or x.get('error')]
    if problems:
        names = '\n'.join(str(Path(x['path']).relative_to(root)) +
                          ('：非対応形式またはメタデータ異常' if x.get('error') else '：除去対象の位置・非公開メタデータあり') for x in problems)
        raise ValueError('画像の位置情報検査で停止しました。\n' + names +
                         '\nバックアップ後、python -B scripts/check_image_privacy.py --clean 対象画像 で除去し、画像を選別してgit addしてください。非対応形式はJPEG・PNG・WebPへ書き出して確認してください。')


def staged():
    with tempfile.TemporaryDirectory(prefix='image-privacy-index-') as directory:
        paths, labels = [], {}
        rows = subprocess.check_output(['git', 'ls-files', '--stage', '-z'], cwd=ROOT)
        for row in rows.split(b'\0'):
            if not row:
                continue
            meta, raw = row.split(b'\t', 1)
            mode, oid, stage = meta.split()
            name = raw.decode('utf-8')
            if Path(name).suffix.lower() not in FORMATS:
                continue
            if stage != b'0':
                raise ValueError('競合中の画像があります。Gitの競合を解消してください。')
            p = Path(directory) / (str(len(paths)) + Path(name).suffix)
            p.write_bytes(subprocess.check_output(['git', 'cat-file', 'blob', oid.decode()], cwd=ROOT))
            paths.append(p)
            labels[str(p)] = name
        result = inspect(paths)
        for item in result:
            item['path'] = labels[item['path']]
        return result


def pending_history():
    """現在のupstreamへ未送信のコミット内の画像も検査。fetch・履歴変更はしない。"""
    rows = subprocess.check_output(['git', 'rev-list', '--objects', '@{upstream}..HEAD'], cwd=ROOT)
    with tempfile.TemporaryDirectory(prefix='image-privacy-history-') as directory:
        paths, labels = [], {}
        for row in rows.splitlines():
            fields = row.split(b' ', 1)
            if len(fields) != 2:
                continue
            oid, raw = fields
            name = raw.decode('utf-8')
            if Path(name).suffix.lower() not in FORMATS:
                continue
            p = Path(directory) / (str(len(paths)) + Path(name).suffix)
            p.write_bytes(subprocess.check_output(['git', 'cat-file', 'blob', oid.decode()], cwd=ROOT))
            paths.append(p)
            labels[str(p)] = name + '（未送信のGit履歴）'
        result = inspect(paths)
        for item in result:
            item['path'] = labels[item['path']]
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged', action='store_true', help='push前にGitインデックスの全画像を検査（書換えなし）')
    parser.add_argument('--pre-push', action='store_true', help='インデックスとupstream未送信履歴を検査（書換え・通信なし）')
    parser.add_argument('--clean', action='store_true', help='明示した画像のみ位置メタデータを除去（事前バックアップ必須）')
    parser.add_argument('files', nargs='*')
    args = parser.parse_args()
    if (args.staged or args.pre_push) and (args.clean or args.files) or args.staged and args.pre_push or args.clean and not args.files:
        parser.error('--stagedは単独、--cleanには対象ファイルを指定してください。')
    try:
        result = staged() + pending_history() if args.pre_push else staged() if args.staged else inspect([Path(x) for x in args.files] if args.files else images(ROOT / 'public'), args.clean)
    except subprocess.CalledProcessError:
        print('Gitの送信対象を確認できないため停止しました。upstream設定と履歴を確認してください。')
        return 1
    bad = False
    for item in result:
        if item.get('error'):
            print(item['path'] + '：検証できません（非対応形式・メタデータ異常）。保存・公開を停止してください。')
            bad = True
        elif item.get('dirty'):
            print(item['path'] + ('：メタデータ除去済み' if args.clean else '：位置・非公開メタデータあり。--cleanで除去後、選別登録してください。'))
            if '未送信のGit履歴' in item['path']:
                print('  現在の画像を直すだけでは過去版は消えません。pushせず、履歴の取り扱いを確認してください。')
            bad |= not args.clean
    if not bad:
        print('画像位置情報検査：合格（' + str(len(result)) + '件）。座標値は出力しません。')
    return 1 if bad else 0


if __name__ == '__main__':
    raise SystemExit(main())

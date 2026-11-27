"""生成済み_siteをlocalhostだけへ配信。旧URL転送と404もローカルで確認する。"""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, quote
import argparse
import re

OUTPUT = Path(__file__).resolve().parent.parent / '_site'


class Handler(SimpleHTTPRequestHandler):
    def list_directory(self, path):
        self.send_error(404)
        return None

    def do_GET(self):
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        # Netlifyのクエリ条件と同様、slug以外のパラメーターがある場合は対象外。
        if url.path.rstrip('/') in {'/journey', '/making-article'} and set(query) == {'slug'} and len(query['slug']) == 1:
            slug = query['slug'][0]
            prefix = '/journeys/' if url.path.rstrip('/') == '/journey' else '/making/'
            self.send_response(301)
            self.send_header('Location', prefix + quote(slug, safe='') + '/')
            self.end_headers()
            return
        return super().do_GET()

    def send_error(self, code, message=None, explain=None):
        if code == 404 and (OUTPUT / '404.html').is_file():
            body = (OUTPUT / '404.html').read_bytes()
            self.send_response(404)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            if self.command != 'HEAD':
                self.wfile.write(body)
            return
        return super().send_error(code, message, explain)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=4174)
    args = parser.parse_args()
    if not (OUTPUT / '.seo-build.json').is_file():
        parser.error('先に python -B scripts/build_seo.py を実行してください。')
    server = ThreadingHTTPServer(('127.0.0.1', args.port), partial(Handler, directory=str(OUTPUT)))
    print(f'ローカル確認: http://127.0.0.1:{args.port}/ （Ctrl+Cで終了）', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

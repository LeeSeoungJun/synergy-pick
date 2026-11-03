"""Local web app with a GET-only LCU bridge."""
import argparse,json
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit
from lcu_bridge import Bridge
ROOT=Path(__file__).parent
class Handler(SimpleHTTPRequestHandler):
    bridge=None
    def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(ROOT/'dist'),**kwargs)
    def do_GET(self):
        if urlsplit(self.path).path=='/api/draft':
            allowed={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
            origin=self.headers.get('Origin')
            if self.headers.get('Host','') not in allowed or (origin and origin not in {'http://'+h for h in allowed}):
                self.send_error(403);return
            payload=json.dumps(self.bridge.snapshot()).encode()
            self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        else:super().do_GET()
    def log_message(self,format,*args):
        if not self.path.startswith('/api/draft'):super().log_message(format,*args)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8765);p.add_argument('--lockfile');p.add_argument('--open-browser',action='store_true');args=p.parse_args()
    Handler.bridge=Bridge(args.lockfile)
    server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'Local: http://127.0.0.1:{args.port}',flush=True)
    if args.open_browser:
        import webbrowser
        from threading import Timer
        Timer(.5,lambda:webbrowser.open(f'http://127.0.0.1:{args.port}')).start()
    try:server.serve_forever()
    except KeyboardInterrupt:server.server_close()

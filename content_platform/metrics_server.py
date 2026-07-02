import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .metrics import render_metrics
from .store import Store


def make_server(db_path, host="127.0.0.1", port=9108):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/metrics":
                self.send_error(404)
                return
            store = Store(db_path)
            store.init()
            body = render_metrics(store).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    return ThreadingHTTPServer((host, int(port)), Handler)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9108)
    args = parser.parse_args(argv)
    server = make_server(args.db, args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()


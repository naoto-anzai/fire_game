#!/usr/bin/env python3
"""fire.html を UTF-8 明示で配信する。python -m http.server は charset を送らない。"""
import http.server, socketserver

class H(http.server.SimpleHTTPRequestHandler):
    def guess_type(self, path):
        t = super().guess_type(path)
        if t and t.startswith("text/") and "charset" not in t:
            t += "; charset=utf-8"
        return t
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

if __name__ == "__main__":
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", 8777), H) as s:
        print("http://localhost:8777/fire.html", flush=True)
        s.serve_forever()

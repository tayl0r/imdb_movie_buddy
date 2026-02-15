#!/usr/bin/env python3
"""Minimal dev server: static files + POST /save-csv endpoint."""

import json
import os
from http.server import SimpleHTTPRequestHandler, HTTPServer

PORT = 8000


class Handler(SimpleHTTPRequestHandler):
    def send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        if self.path == "/api/lists":
            data_dir = os.path.join(os.path.dirname(__file__) or ".", "data")
            list_files = []
            for fname in sorted(os.listdir(data_dir)):
                if not fname.endswith(".json"):
                    continue
                fpath = os.path.join(data_dir, fname)
                try:
                    with open(fpath) as f:
                        obj = json.load(f)
                    if "source" in obj:
                        list_files.append(fname)
                except Exception:
                    pass
            self.send_json(list_files)
        else:
            super().do_GET()

    def do_POST(self):
        if self.path == "/save-csv":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            os.makedirs("lists", exist_ok=True)
            with open(os.path.join("lists", "want_to_watch.csv"), "w") as f:
                f.write(body)
            self.send_json({"ok": True})
        else:
            self.send_error(404)


if __name__ == "__main__":
    print(f"Serving on http://localhost:{PORT}")
    HTTPServer(("", PORT), Handler).serve_forever()

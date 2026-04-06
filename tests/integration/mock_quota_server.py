"""Mock quota server for integration testing. Returns static OK quota data."""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler

QUOTA_DATA = json.dumps({
    "status": "ok",
    "five_hour": {"utilization": 42.5, "resets_at": "2026-04-06T05:00:00Z"},
    "seven_day": {"utilization": 67.3, "resets_at": "2026-04-12T00:00:00Z"},
    "timestamp": 1743897600,
}).encode()

HEALTH_DATA = json.dumps({
    "status": "ok",
    "uptime_seconds": 100,
    "version": "0.1.0-test",
}).encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/quota":
            self._respond(200, QUOTA_DATA)
        elif self.path == "/health":
            self._respond(200, HEALTH_DATA)
        else:
            self._respond(404, b'{"error":"not_found"}')

    def _respond(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.write = self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # silence request logging


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 7850), Handler)
    print("Mock quota server listening on :7850", flush=True)
    server.serve_forever()

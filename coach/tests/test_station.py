import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from teach_task_coach.station import StationClient


def test_station_client_reads_real_http_status():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == "/status"
            body = json.dumps({"state": "idle", "arms": {"left": True}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        result = StationClient(f"http://127.0.0.1:{server.server_port}").status()
        assert result["state"] == "idle"
        assert result["arms"] == {"left": True}
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_station_client_rejects_non_http_url(tmp_path):
    with pytest.raises(ValueError, match="HTTP or HTTPS"):
        StationClient(tmp_path.as_uri())

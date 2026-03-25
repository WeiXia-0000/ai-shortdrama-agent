"""
本地只读 Dashboard HTTP 服务（标准库，无额外依赖）。

- 仅提供 GET：静态页 + /api/dashboard JSON
- 启动时绑定 --series-dir，不暴露写操作、不触发模型
"""

from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from .dashboard_readonly import build_dashboard_payload

_STATIC_DIR = Path(__file__).resolve().parent / "dashboard_static"


class _Handler(BaseHTTPRequestHandler):
    server_version = "ProductionConsoleDashboard/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        # 降噪：仅错误到 stderr
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _series_dir_from_request(self) -> Path:
        assert isinstance(self.server, _Server)
        q = urlparse(self.path).query
        if q:
            ps = parse_qs(q)
            raw_list = ps.get("series_dir")
            if raw_list:
                raw = (raw_list[0] or "").strip()
                # ?series_dir= 空字符串时不能 Path('')，否则会落到 cwd，造成「永远像另一个剧」的错觉
                if raw:
                    return Path(raw).expanduser().resolve()
        return self.server.series_dir

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/api/dashboard":
            try:
                assert isinstance(self.server, _Server)
                sd = self._series_dir_from_request()
                startup = self.server.series_dir.resolve()
                eff = sd.resolve()
                payload = build_dashboard_payload(sd)
                payload["dashboard_bind"] = {
                    "startup_series_dir": str(startup),
                    "effective_series_dir": str(eff),
                    "query_overrode_path": eff != startup,
                    "note": "若 effective 仍是旧剧路径，说明 8765 上仍是先前启动的进程；请先结束旧进程或换 --port。",
                }
                raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self._send(200, raw, "application/json; charset=utf-8")
            except Exception as e:
                err: Dict[str, Any] = {"ok": False, "error": str(e)}
                raw = json.dumps(err, ensure_ascii=False).encode("utf-8")
                self._send(500, raw, "application/json; charset=utf-8")
            return

        if path == "/api/health":
            assert isinstance(self.server, _Server)
            body = json.dumps(
                {"ok": True, "series_dir": str(self.server.series_dir)},
                ensure_ascii=False,
            ).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
            return

        if path == "/" or path == "/index.html":
            p = _STATIC_DIR / "index.html"
            if not p.is_file():
                self._send(404, b"index missing", "text/plain; charset=utf-8")
                return
            self._send(200, p.read_bytes(), "text/html; charset=utf-8")
            return

        if path.startswith("/static/"):
            rel = path[len("/static/") :].lstrip("/")
            safe = Path(rel).name
            for ext, ctype in (
                (".css", "text/css; charset=utf-8"),
                (".js", "application/javascript; charset=utf-8"),
            ):
                if safe.endswith(ext):
                    fp = _STATIC_DIR / safe
                    if fp.is_file() and fp.resolve().parent == _STATIC_DIR.resolve():
                        self._send(200, fp.read_bytes(), ctype)
                        return
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return

        self._send(404, b"not found", "text/plain; charset=utf-8")


class _Server(ThreadingHTTPServer):
    def __init__(self, server_address: Any, series_dir: Path) -> None:
        super().__init__(server_address, _Handler)
        self.series_dir = series_dir


def main() -> None:
    ap = argparse.ArgumentParser(description="短剧/漫剧生产控制台（只读）本地 Dashboard")
    ap.add_argument(
        "--series-dir",
        type=Path,
        required=True,
        help="剧根目录（含 L3_series 或平铺大纲）",
    )
    ap.add_argument("--host", default="127.0.0.1", help="监听地址")
    ap.add_argument("--port", type=int, default=8765, help="端口")
    args = ap.parse_args()
    sd = args.series_dir.expanduser().resolve()
    if not sd.is_dir():
        raise SystemExit(f"--series-dir 不是目录: {sd}")

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    httpd = _Server((args.host, args.port), sd)
    print(f"Dashboard: http://{args.host}:{args.port}/", flush=True)
    try:
        print(f"[dashboard] bound_series_dir={sd}", flush=True)
    except UnicodeEncodeError:
        print("[dashboard] bound (unicode path); see GET /api/dashboard -> dashboard_bind", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止", flush=True)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import argparse
import json
import logging
import os
import platform
import socket
import socketserver
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import urlsplit

try:
    import yaml  # type: ignore
except Exception:
    yaml = None

DEFAULT_WARNING_HTML = """<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <title>Access Restricted</title>
  <style>
    body { font-family: -apple-system, Segoe UI, Arial, sans-serif; background: #111; color: #f5f5f5; padding: 40px; }
    .card { background: #1c1c1c; padding: 24px; border-radius: 12px; max-width: 700px; margin: 0 auto; }
    h1 { margin: 0 0 12px; font-size: 28px; }
    p { line-height: 1.5; }
    code { background: #2b2b2b; padding: 2px 6px; border-radius: 6px; }
  </style>
</head>
<body>
  <div class=\"card\">
    <h1>Access to this website is restricted due to adult content.</h1>
    <p>If you believe this is a mistake, update your filter configuration and restart the filter.</p>
  </div>
</body>
</html>"""


def _load_config(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if path.lower().endswith(".json"):
        return json.loads(text)
    if path.lower().endswith(".yaml") or path.lower().endswith(".yml"):
        if yaml is None:
            raise RuntimeError("PyYAML not installed. Install with: pip install pyyaml")
        return yaml.safe_load(text)
    raise ValueError("Unsupported config format (use .json or .yaml)")


def _normalize_host(host: str) -> str:
    h = host.lower().strip()
    if h.startswith("www."):
        h = h[4:]
    return h


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class FilterRules:
    def __init__(self, cfg: Dict[str, Any]):
        self.enabled = bool(cfg.get("enabled", True))
        self.blocked_sites = [_normalize_host(x) for x in cfg.get("blocked_sites", [])]
        self.blocked_keywords = [x.lower() for x in cfg.get("blocked_keywords", [])]

    def match(self, host: str, url: str, title: Optional[str] = None) -> Optional[str]:
        if not self.enabled:
            return None
        host_n = _normalize_host(host)
        if host_n in self.blocked_sites:
            return "domain"
        for kw in self.blocked_keywords:
            if kw in host_n or kw in url.lower() or (title and kw in title.lower()):
                return "keyword"
        return None


def check_url(url: str, config_path: str) -> Optional[str]:
    cfg = _load_config(config_path)
    rules = FilterRules(cfg)
    parts = urlsplit(url)
    host = parts.hostname or url
    return rules.match(host, url)


class BlockLogger:
    def __init__(self, path: Optional[str] = None):
        self.path = path

    def log(self, url: str, reason: str):
        msg = f"[{_now()}] BLOCKED {url} reason={reason}"
        logging.warning(msg)
        if self.path:
            try:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(msg + "\n")
            except Exception:
                pass


class WarningHandler(BaseHTTPRequestHandler):
    warning_html = DEFAULT_WARNING_HTML

    def do_GET(self):
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(self.warning_html.encode("utf-8"))

    def log_message(self, format, *args):
        return


class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


class ProxyHandler(BaseHTTPRequestHandler):
    rules: FilterRules = None  # type: ignore
    logger: BlockLogger = None  # type: ignore
    warning_url: str = None  # type: ignore

    def _block(self, url: str, reason: str, redirect: bool = False):
        self.logger.log(url, reason)
        if redirect:
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", self.warning_url)
            self.end_headers()
            return
        self.send_error(HTTPStatus.UNAVAILABLE_FOR_LEGAL_REASONS, "Blocked by filter")

    def do_CONNECT(self):
        host, _, port = self.path.partition(":")
        url = f"https://{host}:{port}"
        reason = self.rules.match(host, url)
        if reason:
            return self._block(url, reason, redirect=False)
        # Tunnel TCP
        try:
            remote = socket.create_connection((host, int(port)))
        except Exception:
            return self.send_error(HTTPStatus.BAD_GATEWAY)
        self.send_response(200, "Connection established")
        self.end_headers()
        self._tunnel(self.connection, remote)

    def _tunnel(self, client, remote):
        sockets = [client, remote]
        client.setblocking(False)
        remote.setblocking(False)
        while True:
            readable, _, _ = socket.select(sockets, [], [], 0.1)
            if not readable:
                continue
            for s in readable:
                other = remote if s is client else client
                try:
                    data = s.recv(8192)
                    if not data:
                        remote.close()
                        client.close()
                        return
                    other.sendall(data)
                except Exception:
                    remote.close()
                    client.close()
                    return

    def do_GET(self):
        self._handle_http()

    def do_POST(self):
        self._handle_http()

    def do_PUT(self):
        self._handle_http()

    def do_DELETE(self):
        self._handle_http()

    def _handle_http(self):
        # For proxy requests, self.path is a full URL
        url = self.path
        parts = urlsplit(url)
        host = parts.hostname or ""
        reason = self.rules.match(host, url)
        if reason:
            return self._block(url, reason, redirect=True)
        # Forward the request
        try:
            self._forward_request(parts)
        except Exception:
            self.send_error(HTTPStatus.BAD_GATEWAY)

    def _forward_request(self, parts):
        host = parts.hostname
        port = parts.port or (443 if parts.scheme == "https" else 80)
        if not host:
            return self.send_error(HTTPStatus.BAD_REQUEST)
        # Build outbound request line
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        outbound = f"{self.command} {path} {self.request_version}\r\n"
        # Copy headers
        headers = ""
        for k, v in self.headers.items():
            if k.lower() == "proxy-connection":
                continue
            headers += f"{k}: {v}\r\n"
        outbound += headers + "\r\n"
        body = None
        if "Content-Length" in self.headers:
            length = int(self.headers["Content-Length"])
            body = self.rfile.read(length)
        with socket.create_connection((host, port)) as sock:
            sock.sendall(outbound.encode("utf-8"))
            if body:
                sock.sendall(body)
            while True:
                data = sock.recv(8192)
                if not data:
                    break
                self.wfile.write(data)

    def log_message(self, format, *args):
        return


def start_warning_server(port: int, warning_html_path: Optional[str]) -> ThreadedHTTPServer:
    if warning_html_path and os.path.exists(warning_html_path):
        with open(warning_html_path, "r", encoding="utf-8") as f:
            WarningHandler.warning_html = f.read()
    server = ThreadedHTTPServer(("127.0.0.1", port), WarningHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def start_proxy_server(host: str, port: int, rules: FilterRules, logger: BlockLogger, warning_url: str):
    class _Handler(ProxyHandler):
        pass
    _Handler.rules = rules
    _Handler.logger = logger
    _Handler.warning_url = warning_url
    with socketserver.ThreadingTCPServer((host, port), _Handler) as httpd:
        httpd.serve_forever()


def write_hosts(blocked_sites: List[str], warning_host: str = "127.0.0.1"):
    system = platform.system().lower()
    if system == "windows":
        hosts_path = os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "System32", "drivers", "etc", "hosts")
    else:
        hosts_path = "/etc/hosts"

    start = "# BEGIN ADULT BLOCK"
    end = "# END ADULT BLOCK"
    entry_lines = [f"{warning_host} {s}" for s in blocked_sites]
    block = "\n".join([start] + entry_lines + [end]) + "\n"

    with open(hosts_path, "r", encoding="utf-8") as f:
        content = f.read()
    if start in content and end in content:
        pre = content.split(start)[0]
        post = content.split(end)[1]
        content = pre + block + post
    else:
        content = content + "\n" + block
    with open(hosts_path, "w", encoding="utf-8") as f:
        f.write(content)


def main():
    parser = argparse.ArgumentParser(description="Safe browsing filter (proxy + warning page)")
    parser.add_argument("--config", default="backend/filter_config.yaml", help="Path to filter config")
    parser.add_argument("--proxy-host", default="127.0.0.1")
    parser.add_argument("--proxy-port", type=int, default=8080)
    parser.add_argument("--warning-port", type=int, default=8081)
    parser.add_argument("--write-hosts", action="store_true", help="Write hosts file entries (requires admin)")
    parser.add_argument("--check-url", help="Check a URL and exit with nonzero if blocked")
    args = parser.parse_args()

    cfg = _load_config(args.config)
    rules = FilterRules(cfg)
    logger = BlockLogger(cfg.get("log_file"))

    if args.check_url:
        reason = rules.match(urlsplit(args.check_url).hostname or args.check_url, args.check_url)
        if reason:
            print("Blocked: adult rated content")
            return 2
        print("Allowed")
        return 0

    warning_html = cfg.get("warning_page")
    warning_server = start_warning_server(args.warning_port, warning_html)
    warning_url = f"http://127.0.0.1:{args.warning_port}/"

    if args.write_hosts:
        write_hosts(rules.blocked_sites, "127.0.0.1")
        logging.info("Hosts file updated with %d blocked domains", len(rules.blocked_sites))

    logging.info("Filter enabled=%s", rules.enabled)
    logging.info("Proxy listening on %s:%d", args.proxy_host, args.proxy_port)
    logging.info("Warning page at %s", warning_url)
    start_proxy_server(args.proxy_host, args.proxy_port, rules, logger, warning_url)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    main()

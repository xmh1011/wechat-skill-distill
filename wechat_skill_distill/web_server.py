from __future__ import annotations

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path


def web_root() -> Path:
    return Path(str(files("wechat_skill_distill").joinpath("web")))


def serve_chat_ui(host: str, port: int) -> None:
    root = web_root()
    if not (root / "index.html").exists():
        raise RuntimeError(f"chat UI assets not found: {root}")
    handler = partial(SimpleHTTPRequestHandler, directory=str(root))
    server = ThreadingHTTPServer((host, port), handler)
    actual_host, actual_port = server.server_address
    print(f"chat UI: http://{actual_host}:{actual_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("chat UI stopped")

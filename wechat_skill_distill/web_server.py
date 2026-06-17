from __future__ import annotations

from functools import partial
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .memory_recall import MemoryRecallError, memory_runtime_status, recall_for_chat
from .model_client import ModelCallError, ModelConfigError, generate_chat_reply, load_env_file, runtime_status


def web_root() -> Path:
    return Path(str(files("wechat_skill_distill").joinpath("web")))


def load_skill_assets(skill_paths: list[Path] | None = None) -> list[dict[str, str]]:
    assets = []
    for index, path in enumerate(skill_paths or [], start=1):
        if not path.exists():
            raise RuntimeError(f"skill file not found: {path}")
        if not path.is_file():
            raise RuntimeError(f"skill path is not a file: {path}")
        assets.append(
            {
                "id": f"server-skill-{index}",
                "file_name": path.name,
                "text": path.read_text(encoding="utf-8"),
            }
        )
    return assets


class ChatUIHandler(SimpleHTTPRequestHandler):
    preloaded_skills: list[dict[str, str]] = []

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/runtime":
            self._write_json(200, {**runtime_status(), "memory": memory_runtime_status()})
            return
        if path == "/api/skills":
            self._write_json(200, {"skills": self.preloaded_skills})
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/chat":
            self._write_json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0:
            self._write_json(400, {"error": "request body is required"})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._write_json(400, {"error": "request body must be valid JSON"})
            return
        if not isinstance(payload, dict):
            self._write_json(400, {"error": "request body must be a JSON object"})
            return
        try:
            server_hits = recall_for_chat(payload)
            existing_hits = payload.get("memory_hits") if isinstance(payload, dict) else []
            if not isinstance(existing_hits, list):
                existing_hits = []
            enriched_payload = {**payload, "memory_hits": [*existing_hits, *server_hits]}
            reply = generate_chat_reply(enriched_payload)
            reply["memory"] = {"server_hits": len(server_hits), "local_hits": len(existing_hits)}
        except MemoryRecallError as exc:
            self._write_json(502, {"error": str(exc), "kind": "memory"})
            return
        except ModelConfigError as exc:
            self._write_json(400, {"error": str(exc), "kind": "config"})
            return
        except ModelCallError as exc:
            self._write_json(502, {"error": str(exc), "kind": "provider"})
            return
        self._write_json(200, reply)


def serve_chat_ui(host: str, port: int, *, env_file: Path | None = None, skill_paths: list[Path] | None = None) -> None:
    load_env_file(env_file)
    root = web_root()
    if not (root / "index.html").exists():
        raise RuntimeError(f"chat UI assets not found: {root}")
    preloaded_skills = load_skill_assets(skill_paths)
    handler_class = type("ConfiguredChatUIHandler", (ChatUIHandler,), {"preloaded_skills": preloaded_skills})
    handler = partial(handler_class, directory=str(root))
    server = ThreadingHTTPServer((host, port), handler)
    actual_host, actual_port = server.server_address
    print(f"chat UI: http://{actual_host}:{actual_port}", flush=True)
    if preloaded_skills:
        print(f"loaded skills: {', '.join(item['file_name'] for item in preloaded_skills)}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("chat UI stopped")

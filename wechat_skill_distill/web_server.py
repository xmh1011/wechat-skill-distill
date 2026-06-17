from __future__ import annotations

from functools import partial
import json
import os
import re
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from typing import Any, Mapping
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


def _frontmatter_value(text: str, key: str) -> str:
    match = re.search(rf"^{key}:\s*(.+?)\s*$", text, re.MULTILINE)
    if not match:
        return ""
    raw = match.group(1).strip()
    if raw.startswith(('"', "'")):
        try:
            return str(json.loads(raw))
        except json.JSONDecodeError:
            return raw.strip("\"'")
    return raw


def _skill_title_name(text: str, file_name: str) -> str:
    match = re.search(r"^#\s+(.+?)\s+(?:Chat\s+)?Skill\s*$", text, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return file_name.replace(".chat-memory.skill", "").replace(".skill", "")


def _skill_user_id(text: str) -> str:
    frontmatter_user_id = _frontmatter_value(text, "user_id")
    if frontmatter_user_id:
        return frontmatter_user_id
    match = re.search(r"userID=([^\s，。`]+)", text)
    return match.group(1) if match else "-"


def _skill_phrases(text: str) -> list[str]:
    match = re.search(r"常见表达：([^\n]+)", text)
    if not match:
        return []
    line = re.sub(r"[。.;；]\s*$", "", match.group(1))
    return [item.strip() for item in re.split(r"[、,，]", line) if item.strip()][:16]


def _skill_sample_count(text: str) -> int:
    return len(re.findall(r"```text\n[\s\S]*?\n```", text))


def _skill_summary(asset: Mapping[str, str]) -> dict[str, Any]:
    text = str(asset.get("text") or "")
    file_name = str(asset.get("file_name") or "skill")
    return {
        "id": str(asset.get("id") or ""),
        "file_name": file_name,
        "name": _frontmatter_value(text, "display_name") or _skill_title_name(text, file_name),
        "userId": _skill_user_id(text),
        "memoryAware": "## 记忆检索" in text,
        "phrases": _skill_phrases(text),
        "sampleCount": _skill_sample_count(text),
    }


def public_skill_assets(assets: list[dict[str, str]]) -> list[dict[str, Any]]:
    return [_skill_summary(asset) for asset in assets]


def resolve_preloaded_skill_payload(payload: dict[str, Any], assets: list[dict[str, str]]) -> dict[str, Any]:
    if not assets:
        return payload
    skill_id = str(payload.get("skill_id") or payload.get("skillId") or "").strip()
    if not skill_id and len(assets) == 1:
        skill_id = assets[0]["id"]
    selected = next((asset for asset in assets if asset.get("id") == skill_id), None)
    if not selected:
        raise ModelConfigError("requested skill_id is not loaded on this server")
    summary = _skill_summary(selected)
    return {
        **payload,
        "skill": selected.get("text") or "",
        "persona": {"name": summary["name"], "userId": summary["userId"]},
    }


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _as_string_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip() for item in value if str(item).strip()}
    text = str(value).strip()
    return {text} if text else set()


def _hit_matches_persona(hit: dict[str, Any], user_id: str) -> bool:
    if not user_id:
        return True
    metadata = hit.get("metadata") or {}
    metadata = metadata if isinstance(metadata, Mapping) else {}
    scoped_user_ids: set[str] = set()
    for key in ("userID", "user_id", "userId"):
        scoped_user_ids.update(_as_string_set(metadata.get(key)))
        scoped_user_ids.update(_as_string_set(hit.get(key)))
    if scoped_user_ids and user_id not in scoped_user_ids:
        return False
    scoped_participants: set[str] = set()
    scoped_participants.update(_as_string_set(metadata.get("participants")))
    scoped_participants.update(_as_string_set(hit.get("participants")))
    if scoped_participants and user_id not in scoped_participants:
        return False
    raw_tags = []
    for value in (hit.get("tags"), metadata.get("tags")):
        raw_tags.extend(_as_string_set(value))
    user_tags = {tag.removeprefix("user:") for tag in raw_tags if tag.startswith("user:")}
    if user_tags and user_id not in user_tags:
        return False
    return True


def _filter_hits_for_persona(hits: list[dict[str, Any]], payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    persona = payload.get("persona") or {}
    user_id = str(persona.get("userId") or persona.get("user_id") or "").strip() if isinstance(persona, Mapping) else ""
    return [hit for hit in hits if _hit_matches_persona(hit, user_id)]


def build_enriched_chat_payload(payload: dict[str, Any], server_hits: list[dict[str, Any]], *, env: Mapping[str, str] | None = None) -> tuple[dict[str, Any], dict[str, int]]:
    current_env = env or os.environ
    local_hits: list[dict[str, Any]] = []
    if _truthy(str(current_env.get("WSD_ALLOW_CLIENT_MEMORY_HITS", ""))):
        raw_hits = payload.get("memory_hits")
        if isinstance(raw_hits, list):
            local_hits = [hit for hit in raw_hits if isinstance(hit, dict)]
    filtered_local_hits = _filter_hits_for_persona(local_hits, payload)
    filtered_server_hits = _filter_hits_for_persona(server_hits, payload)
    enriched = {**payload, "memory_hits": [*filtered_local_hits, *filtered_server_hits]}
    return enriched, {"server_hits": len(filtered_server_hits), "local_hits": len(filtered_local_hits)}


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
            self._write_json(200, {"skills": public_skill_assets(self.preloaded_skills)})
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
            resolved_payload = resolve_preloaded_skill_payload(payload, self.preloaded_skills)
            server_hits = recall_for_chat(resolved_payload)
            enriched_payload, memory_counts = build_enriched_chat_payload(resolved_payload, server_hits)
            reply = generate_chat_reply(enriched_payload)
            reply["memory"] = memory_counts
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

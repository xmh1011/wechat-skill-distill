import json
from pathlib import Path
import tempfile
import unittest

from wechat_skill_distill.inspection import inspect_weflow_export
from wechat_skill_distill.memory import build_memory_items, write_jsonl
from wechat_skill_distill.skills import generate_skill_texts, write_skill_files
from wechat_skill_distill.weflow import load_weflow_messages
from wechat_skill_distill.web_server import web_root


class ToolkitCoreTest(unittest.TestCase):
    def sample_export(self) -> dict:
        return {
            "messages": [
                {
                    "localId": 1,
                    "formattedTime": "2026-04-18 01:51:44",
                    "type": "文本消息",
                    "content": "哈哈哈哈今天又被拉去改材料了",
                    "isSend": 0,
                    "senderUsername": "wxid_a",
                    "senderDisplayName": "Participant A",
                },
                {
                    "localId": 2,
                    "formattedTime": "2026-04-18 01:52:01",
                    "type": "文本消息",
                    "content": "确实，这种需求反复改很折磨",
                    "isSend": 1,
                    "senderUsername": "wxid_b",
                    "senderDisplayName": "Participant B",
                },
                {
                    "localId": 3,
                    "formattedTime": "2026-04-18 01:53:01",
                    "type": "系统消息",
                    "content": "系统消息不应导入",
                    "isSend": 0,
                },
            ]
        }

    def test_load_weflow_messages_maps_participants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chat.json"
            path.write_text(json.dumps(self.sample_export(), ensure_ascii=False), encoding="utf-8")

            messages = load_weflow_messages(
                path,
                participants={
                    "0": {"user_id": "user-a", "name": "Participant A"},
                    "1": {"user_id": "user-b", "name": "Participant B"},
                },
            )

        self.assertEqual([m.user_id for m in messages], ["user-a", "user-b"])
        self.assertEqual(messages[0].sender_name, "Participant A")
        self.assertEqual(messages[1].sender_name, "Participant B")
        self.assertEqual(len(messages), 2)

    def test_generate_plain_skill_texts_are_independent_and_memory_free(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chat.json"
            path.write_text(json.dumps(self.sample_export(), ensure_ascii=False), encoding="utf-8")
            messages = load_weflow_messages(
                path,
                participants={
                    "0": {"user_id": "user-a", "name": "Participant A"},
                    "1": {"user_id": "user-b", "name": "Participant B"},
                },
            )

        skills = generate_skill_texts(messages, include_memory=False)

        self.assertIn("Participant A Skill", skills["user-a"])
        self.assertIn("Participant B Skill", skills["user-b"])
        self.assertNotIn("Participant B Skill", skills["user-a"])
        self.assertNotIn("Participant A Skill", skills["user-b"])
        self.assertNotIn("## 记忆检索", skills["user-a"])
        self.assertNotIn("记忆", skills["user-a"])
        self.assertNotIn("HINDSIGHT_API_KEY", skills["user-a"])

    def test_generate_memory_chat_skills_include_backend_recall(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chat.json"
            out_dir = Path(tmp) / "skills"
            path.write_text(json.dumps(self.sample_export(), ensure_ascii=False), encoding="utf-8")
            messages = load_weflow_messages(
                path,
                participants={
                    "0": {"user_id": "user-a", "name": "Participant A"},
                    "1": {"user_id": "user-b", "name": "Participant B"},
                },
            )

            skills = generate_skill_texts(messages, include_memory=True, memory_backend="hindsight")
            written = write_skill_files(skills, out_dir, suffix="chat-memory.skill")

        self.assertIn("Participant A Chat Skill", skills["user-a"])
        self.assertIn("HINDSIGHT_API_KEY", skills["user-a"])
        self.assertTrue(any(path.name == "Participant A.chat-memory.skill" for path in written))

    def test_memory_items_write_jsonl_with_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chat.json"
            out = Path(tmp) / "memory.jsonl"
            path.write_text(json.dumps(self.sample_export(), ensure_ascii=False), encoding="utf-8")
            messages = load_weflow_messages(
                path,
                participants={
                    "0": {"user_id": "user-a", "name": "Participant A"},
                    "1": {"user_id": "user-b", "name": "Participant B"},
                },
            )
            items = build_memory_items(messages, group_by="message")

            write_jsonl(items, out)
            rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["metadata"]["userID"], "user-a")
        self.assertEqual(rows[1]["metadata"]["userID"], "user-b")
        self.assertIn("timestamp", rows[0]["metadata"])
        self.assertEqual(rows[0]["timestamp"], "2026-04-18T01:51:44+08:00")
        self.assertEqual(rows[0]["participants"], ["user-a"])

    def test_inspect_weflow_export_reports_importable_and_skipped_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chat.json"
            path.write_text(json.dumps(self.sample_export(), ensure_ascii=False), encoding="utf-8")

            report = inspect_weflow_export(
                path,
                participants={
                    "0": {"user_id": "user-a", "name": "Participant A"},
                    "1": {"user_id": "user-b", "name": "Participant B"},
                },
            )

        self.assertEqual(report["raw_messages"], 3)
        self.assertEqual(report["importable_messages"], 2)
        self.assertEqual(report["skipped_messages"], 1)
        self.assertEqual(report["skipped_by_reason"], {"unsupported_type": 1})
        self.assertEqual(report["message_types"], {"文本消息": 2, "系统消息": 1})
        self.assertEqual(report["date_range"]["start"], "2026-04-18T01:51:44+08:00")
        self.assertEqual(report["participants"][0]["user_id"], "user-a")
        self.assertEqual(report["unmapped_sender_keys"], [])
        self.assertIn("wxid_a", report["observed_sender_keys"])

    def test_chat_ui_assets_are_packaged(self) -> None:
        root = web_root()
        self.assertTrue((root / "index.html").exists())
        self.assertTrue((root / "app.js").exists())
        self.assertTrue((root / "styles.css").exists())


if __name__ == "__main__":
    unittest.main()

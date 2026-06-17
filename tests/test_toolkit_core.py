import json
from pathlib import Path
import tempfile
import unittest

from wechat_skill_distill.evaluation import collect_skill_paths, evaluate_skills
from wechat_skill_distill.inspection import inspect_weflow_export
from wechat_skill_distill.memory import build_memory_items, write_jsonl
from wechat_skill_distill.redaction import redact_weflow_export
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

    def test_evaluate_skills_reports_pass_and_identity_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            chat_path = root / "chat.json"
            skills_dir = root / "skills"
            chat_path.write_text(json.dumps(self.sample_export(), ensure_ascii=False), encoding="utf-8")
            messages = load_weflow_messages(
                chat_path,
                participants={
                    "0": {"user_id": "user-a", "name": "Participant A"},
                    "1": {"user_id": "user-b", "name": "Participant B"},
                },
            )
            skills = generate_skill_texts(messages, include_memory=False)
            written = write_skill_files(skills, skills_dir, suffix="skill")

            report = evaluate_skills(written, messages=messages)
            leaked = skills_dir / "Participant A.skill"
            leaked.write_text(leaked.read_text(encoding="utf-8") + "\nParticipant B\n", encoding="utf-8")
            leaked_report = evaluate_skills([leaked], messages=messages)

        self.assertEqual(report["summary"]["failed"], 0)
        self.assertEqual(report["summary"]["passed"], 2)
        self.assertEqual(leaked_report["summary"]["failed"], 1)
        self.assertIn("contains other participant names", leaked_report["skills"][0]["issues"][0])

    def test_collect_skill_paths_deduplicates_chat_memory_suffix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "A.skill").write_text("plain", encoding="utf-8")
            (root / "B.chat-memory.skill").write_text("chat", encoding="utf-8")

            paths = collect_skill_paths(root)

        self.assertEqual([path.name for path in paths], ["A.skill", "B.chat-memory.skill"])

    def test_redact_weflow_export_masks_common_sensitive_values(self) -> None:
        data = self.sample_export()
        data["messages"][0]["content"] = "电话 13800138000，邮箱 alice@example.com，链接 https://x.test?a=secret"
        data["messages"][1]["content"] = "身份证 11010519491231002X，卡号 6222020202020202020"
        redacted, report = redact_weflow_export(data)

        contents = "\n".join(message["content"] for message in redacted["messages"])

        self.assertIn("[PHONE]", contents)
        self.assertIn("[EMAIL]", contents)
        self.assertIn("[URL]", contents)
        self.assertIn("[ID_CARD]", contents)
        self.assertIn("[BANK_CARD]", contents)
        self.assertNotIn("13800138000", contents)
        self.assertEqual(report["summary"]["messages_changed"], 2)
        self.assertEqual(report["summary"]["total_replacements"], 5)


if __name__ == "__main__":
    unittest.main()

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from wechat_skill_distill.evaluation import collect_skill_paths, evaluate_skills
from wechat_skill_distill.inspection import inspect_weflow_export
from wechat_skill_distill.memory import build_memory_items, write_jsonl
from wechat_skill_distill.memory_recall import memory_runtime_status, recall_for_chat
from wechat_skill_distill.model_client import build_companion_prompt, generate_chat_reply, runtime_status
from wechat_skill_distill.redaction import redact_weflow_export
from wechat_skill_distill.skills import generate_skill_texts, write_skill_files
from wechat_skill_distill.weflow import load_weflow_messages
from wechat_skill_distill.web_server import load_skill_assets, web_root


class MockResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self._payload


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
        self.assertIn("## 事实边界", skills["user-a"])
        self.assertIn("用户问题里的事实前提不自动成立", skills["user-a"])
        self.assertIn("### 深聊和关系判断", skills["user-a"])
        self.assertIn("适用：", skills["user-a"])
        self.assertIn("边界：", skills["user-a"])
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

    def test_chat_ui_preloads_skill_assets_from_startup_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Participant A.chat-memory.skill"
            path.write_text("# Participant A Chat Skill\n\n模拟 userID=user-a 的回复。\n", encoding="utf-8")

            assets = load_skill_assets([path])

        self.assertEqual(assets[0]["id"], "server-skill-1")
        self.assertEqual(assets[0]["file_name"], "Participant A.chat-memory.skill")
        self.assertIn("Participant A Chat Skill", assets[0]["text"])

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

    def test_runtime_status_masks_model_keys(self) -> None:
        report = runtime_status(
            {
                "WSD_OPENAI_API_KEY": "secret",
                "WSD_OPENAI_MODEL": "deepseek-v4-flash",
                "WSD_MODEL_PROVIDER": "openai",
            }
        )

        self.assertEqual(report["default_provider"], "openai")
        self.assertTrue(report["providers"][0]["configured"])
        self.assertNotIn("secret", json.dumps(report))

    def test_companion_prompt_includes_skill_and_memory_constraints(self) -> None:
        prompt = build_companion_prompt(
            {
                "persona": {"name": "Participant A", "userId": "user-a"},
                "skill": "## 说话风格画像\n- 常见表达：可以。",
                "memory_hits": [{"content": "2026-04-18 user-a: 记得周末约过咖啡", "metadata": {"timestamp": "2026-04-18"}}],
            }
        )

        self.assertIn("Participant A", prompt)
        self.assertIn("常见表达", prompt)
        self.assertIn("记得周末约过咖啡", prompt)
        self.assertIn("不要编造", prompt)
        self.assertIn("事实不是风格", prompt)
        self.assertIn("用户问题里的事实前提不自动成立", prompt)

    def test_hindsight_recall_uses_precise_query_and_strict_user_scope(self) -> None:
        skill = """
        # Participant A Chat Skill
        - Bank：`memory-bank-test`
        - `tags`：`["conversation:chat-a-b"]`
        """
        with patch("wechat_skill_distill.memory_recall.requests.post") as post:
            post.return_value = MockResponse({"results": [{"id": "m1", "text": "Participant A提到周末可能有空", "type": "world", "metadata": {"userID": "user-a"}}]})

            hits = recall_for_chat(
                {
                    "message": "讲讲你之前提过的那件事",
                    "skill": skill,
                    "persona": {"name": "Participant A", "userId": "user-a"},
                    "history": [{"role": "user", "text": "上次说到周末安排"}, {"role": "assistant", "text": "可以先看时间"}],
                },
                env={
                    "HINDSIGHT_API_URL": "https://memory.example.test/api",
                    "HINDSIGHT_API_KEY": "secret",
                    "HINDSIGHT_BANK_ID": "memory-bank-test",
                },
            )

        self.assertEqual([hit["content"] for hit in hits], ["Participant A提到周末可能有空"])
        self.assertTrue(memory_runtime_status({"HINDSIGHT_API_KEY": "secret"})["configured"])
        first_body = post.call_args.kwargs["json"]
        self.assertEqual(post.call_args_list[0].args[0], "https://memory.example.test/api/v1/default/banks/memory-bank-test/memories/recall")
        self.assertEqual(first_body["tags"], ["user:user-a"])
        self.assertEqual(first_body["tags_match"], "all_strict")
        self.assertIn("当前用户原话：讲讲你之前提过的那件事", first_body["query"])
        self.assertIn("最近对话上下文", first_body["query"])
        self.assertIn("只寻找能够直接回答当前原话", first_body["query"])
        self.assertIn("忽略仅同属该人物但与当前原话无直接关系", first_body["query"])

    def test_hindsight_recall_falls_back_to_skill_conversation_tags(self) -> None:
        skill = """
        # Participant A Chat Skill
        - Bank：`memory-bank-test`
        - `tags`：`["conversation:chat-a-b"]`
        """
        with patch("wechat_skill_distill.memory_recall.requests.post") as post:
            post.side_effect = [
                MockResponse({"results": []}),
                MockResponse({"results": [{"id": "m1", "text": "Participant A和Participant B周末聊过安排", "type": "world"}]}),
            ]

            hits = recall_for_chat(
                {
                    "message": "讲讲你们之前提过的周末安排",
                    "skill": skill,
                    "persona": {"name": "Participant A", "userId": "user-a"},
                },
                env={
                    "HINDSIGHT_API_URL": "https://memory.example.test/api",
                    "HINDSIGHT_API_KEY": "secret",
                    "HINDSIGHT_BANK_ID": "memory-bank-test",
                },
            )

        self.assertEqual([hit["content"] for hit in hits], ["Participant A和Participant B周末聊过安排"])
        first_body = post.call_args_list[0].kwargs["json"]
        second_body = post.call_args_list[1].kwargs["json"]
        self.assertEqual(first_body["tags"], ["user:user-a"])
        self.assertEqual(first_body["tags_match"], "all_strict")
        self.assertEqual(second_body["tags"], ["conversation:chat-a-b"])
        self.assertEqual(second_body["tags_match"], "any_strict")

    def test_hindsight_recall_skips_small_talk_by_default(self) -> None:
        with patch("wechat_skill_distill.memory_recall.requests.post") as post:
            hits = recall_for_chat(
                {
                    "message": "你好",
                    "skill": "# Participant A Chat Skill",
                    "persona": {"name": "Participant A", "userId": "user-a"},
                },
                env={
                    "HINDSIGHT_API_URL": "https://memory.example.test/api",
                    "HINDSIGHT_API_KEY": "secret",
                    "HINDSIGHT_BANK_ID": "memory-bank-test",
                },
            )

        self.assertEqual(hits, [])
        post.assert_not_called()

    def test_openai_compatible_chat_call_uses_server_side_protocol(self) -> None:
        with patch("wechat_skill_distill.model_client.requests.post") as post:
            post.return_value = MockResponse({"choices": [{"message": {"content": "可以，先看下周末时间"}}], "usage": {"total_tokens": 12}})

            reply = generate_chat_reply(
                {
                    "provider": "openai",
                    "message": "周末要不要出去？",
                    "skill": "## 说话风格画像\n- 常见表达：可以。",
                    "persona": {"name": "Participant A", "userId": "user-a"},
                    "history": [{"role": "user", "text": "最近忙吗"}],
                    "memory_hits": [],
                },
                env={
                    "WSD_OPENAI_API_KEY": "secret",
                    "WSD_OPENAI_MODEL": "deepseek-v4-flash",
                    "WSD_OPENAI_BASE_URL": "https://oneapi.example.test/v1",
                },
            )

        self.assertEqual(reply["text"], "可以，先看下周末时间")
        self.assertEqual(reply["provider"], "openai")
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://oneapi.example.test/v1/chat/completions")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(kwargs["json"]["model"], "deepseek-v4-flash")
        self.assertEqual(kwargs["json"]["messages"][-1]["content"], "周末要不要出去？")

    def test_openai_prompt_carries_grounding_contract_without_keyword_guard(self) -> None:
        with patch("wechat_skill_distill.model_client.requests.post") as post:
            post.return_value = MockResponse({"choices": [{"message": {"content": "这个我不太确定"}}]})

            reply = generate_chat_reply(
                {
                    "provider": "openai",
                    "message": "讲讲你之前提过的那件事",
                    "skill": "## 说话风格画像\n- 常见表达：这个我不太确定。",
                    "persona": {"name": "Participant A", "userId": "user-a"},
                    "memory_hits": [{"content": "Participant B提到过一次旅行安排", "metadata": {"userID": "user-b"}}],
                },
                env={
                    "WSD_OPENAI_API_KEY": "secret",
                    "WSD_OPENAI_MODEL": "deepseek-v4-flash",
                    "WSD_OPENAI_BASE_URL": "https://oneapi.example.test/v1",
                },
            )

        system_prompt = post.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertEqual(reply["text"], "这个我不太确定")
        self.assertNotIn("guarded", reply)
        self.assertIn("事实不是风格", system_prompt)
        self.assertIn("只使用与当前人物和当前问题直接相关的命中", system_prompt)
        self.assertIn("用户问题里的事实前提不自动成立", system_prompt)

    def test_anthropic_chat_call_uses_messages_protocol(self) -> None:
        with patch("wechat_skill_distill.model_client.requests.post") as post:
            post.return_value = MockResponse({"content": [{"type": "text", "text": "嗯，可以先别定太死"}], "usage": {"input_tokens": 10}})

            reply = generate_chat_reply(
                {"provider": "anthropic", "message": "怎么安排？", "skill": "## 说话风格画像\n- 短句。"},
                env={
                    "WSD_ANTHROPIC_API_KEY": "secret",
                    "WSD_ANTHROPIC_MODEL": "claude-sonnet-test",
                },
            )

        self.assertEqual(reply["text"], "嗯，可以先别定太死")
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.anthropic.com/v1/messages")
        self.assertEqual(kwargs["headers"]["x-api-key"], "secret")
        self.assertEqual(kwargs["headers"]["anthropic-version"], "2023-06-01")
        self.assertEqual(kwargs["json"]["model"], "claude-sonnet-test")

    def test_gemini_chat_call_uses_generate_content_protocol(self) -> None:
        with patch("wechat_skill_distill.model_client.requests.post") as post:
            post.return_value = MockResponse({"candidates": [{"content": {"parts": [{"text": "可以，先看看你几点方便"}]}}]})

            reply = generate_chat_reply(
                {"provider": "gemini", "message": "今晚聊会儿？", "skill": "## 说话风格画像\n- 常见表达：可以。"},
                env={
                    "WSD_GEMINI_API_KEY": "secret",
                    "WSD_GEMINI_MODEL": "gemini-test",
                },
            )

        self.assertEqual(reply["text"], "可以，先看看你几点方便")
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent")
        self.assertEqual(kwargs["headers"]["x-goog-api-key"], "secret")
        self.assertEqual(kwargs["json"]["contents"][-1]["parts"][0]["text"], "今晚聊会儿？")


if __name__ == "__main__":
    unittest.main()

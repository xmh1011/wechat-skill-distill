import json
from pathlib import Path
import re
import sys
import tempfile
from types import ModuleType
import unittest
from unittest.mock import patch

from wechat_skill_distill.evaluation import collect_skill_paths, evaluate_skills
from wechat_skill_distill.inspection import inspect_weflow_export
from wechat_skill_distill.memory import build_memory_items, write_jsonl
from wechat_skill_distill.memory_recall import memory_runtime_status, recall_for_chat
from wechat_skill_distill.model_client import build_companion_prompt, build_recall_query_planner_prompt, generate_chat_reply, generate_recall_query_variants, runtime_status
from wechat_skill_distill.redaction import redact_weflow_export
from wechat_skill_distill.skills import generate_skill_texts, write_skill_files
from wechat_skill_distill.weflow import load_weflow_messages
from wechat_skill_distill.web_server import build_enriched_chat_payload, load_skill_assets, public_skill_assets, resolve_preloaded_skill_payload, web_root


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

    def test_generated_skill_artifacts_escape_path_hostile_identity_fields(self) -> None:
        export = self.sample_export()
        export["messages"][0]["senderDisplayName"] = "A/B:测试\n人"
        export["messages"] = [export["messages"][0]]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chat.json"
            out_dir = Path(tmp) / "skills"
            path.write_text(json.dumps(export, ensure_ascii=False), encoding="utf-8")
            messages = load_weflow_messages(
                path,
                participants={
                    "0": {"user_id": "tenant/a b:01", "name": "A/B:测试\n人"},
                },
            )

            skills = generate_skill_texts(messages, include_memory=True, memory_backend="jsonl")
            written = write_skill_files(skills, out_dir, suffix="chat-memory.skill")

            skill_text = skills["tenant/a b:01"]
            self.assertIn("name: chat-user-tenant-a-b-01", skill_text)
            self.assertIn('user_id: "tenant/a b:01"', skill_text)
            self.assertIn('display_name: "A/B:测试 人"', skill_text)
            self.assertIn("# A/B:测试 人 Chat Skill", skill_text)
            self.assertEqual(len(written), 1)
            self.assertEqual(written[0].parent, out_dir)
            self.assertEqual(written[0].name, "A_B_测试 人.chat-memory.skill")
            self.assertTrue(written[0].exists())
            report = evaluate_skills(written, messages=messages)
            self.assertEqual(report["summary"]["failed"], 0)
            self.assertEqual(report["skills"][0]["user_id"], "tenant/a b:01")
            self.assertEqual(report["skills"][0]["name"], "A/B:测试 人")

    def test_generated_skill_artifacts_do_not_collide_for_duplicate_display_names(self) -> None:
        export = self.sample_export()
        export["messages"] = export["messages"][:2]
        export["messages"][0]["senderDisplayName"] = "Alex/Dev"
        export["messages"][1]["senderDisplayName"] = "Alex/Dev"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chat.json"
            out_dir = Path(tmp) / "skills"
            path.write_text(json.dumps(export, ensure_ascii=False), encoding="utf-8")
            messages = load_weflow_messages(
                path,
                participants={
                    "0": {"user_id": "team/a", "name": "Alex/Dev"},
                    "1": {"user_id": "team:a", "name": "Alex/Dev"},
                },
            )

            skills = generate_skill_texts(messages, include_memory=True, memory_backend="jsonl")
            written = write_skill_files(skills, out_dir, suffix="chat-memory.skill")

            skill_names = [re.search(r"^name:\s*(.+)$", text, re.MULTILINE).group(1) for text in skills.values()]
            written_names = [path.name for path in written]
            written_texts = [path.read_text(encoding="utf-8") for path in written]

        self.assertEqual(len(skills), 2)
        self.assertEqual(len(set(skill_names)), 2)
        self.assertEqual(len(written), 2)
        self.assertEqual(len(set(written_names)), 2)
        self.assertTrue(all(name.startswith("Alex_Dev") for name in written_names))
        self.assertTrue(any('user_id: "team/a"' in text for text in written_texts))
        self.assertTrue(any('user_id: "team:a"' in text for text in written_texts))

    def test_memory_chat_skill_templates_describe_backend_neutral_recall_contracts(self) -> None:
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

            mem0_skill = generate_skill_texts(messages, include_memory=True, memory_backend="mem0")["user-a"]
            generic_skill = generate_skill_texts(messages, include_memory=True, memory_backend="generic-http")["user-a"]
            jsonl_skill = generate_skill_texts(messages, include_memory=True, memory_backend="jsonl")["user-a"]
            hindsight_skill = generate_skill_texts(messages, include_memory=True, memory_backend="hindsight")["user-a"]

        self.assertIn("client.search", mem0_skill)
        self.assertIn("user_id：当前 skill 对应的 userID", mem0_skill)
        self.assertIn("query：包含目标人物、userID、当前用户原话和必要的最近用户追问", mem0_skill)
        self.assertIn("MEMORY_RECALL_URL", generic_skill)
        self.assertIn("请求字段建议：`query`、`queries`、`user_id`、`persona`、`history`、`tags`、`limit`、`max_tokens`", generic_skill)
        self.assertIn("不要在 skill 或代码里维护固定领域词表", generic_skill)
        self.assertIn("排序和 rerank 交给记忆后端", generic_skill)
        self.assertIn("query planner 只整理指代和上下文", hindsight_skill)
        self.assertIn("宿主运行时或 agent", jsonl_skill)
        self.assertNotIn("宿主 agent 先在 JSONL", jsonl_skill)

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

    def test_public_skill_assets_hide_raw_skill_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "A.chat-memory.skill"
            path.write_text(
                '---\nname: chat-user-user-a\nuser_id: "user-a"\ndisplay_name: "Participant A"\n---\n'
                "# Participant A Chat Skill\n\n## 记忆检索\n\n## 说话风格画像\n\n- 常见表达：可以、哈哈。\n\n"
                "## 真实样本\n\n```text\n这是不应发送到浏览器的完整样本\n```\n",
                encoding="utf-8",
            )
            assets = load_skill_assets([path])

        public = public_skill_assets(assets)

        self.assertEqual(public[0]["id"], "server-skill-1")
        self.assertEqual(public[0]["name"], "Participant A")
        self.assertEqual(public[0]["userId"], "user-a")
        self.assertTrue(public[0]["memoryAware"])
        self.assertEqual(public[0]["sampleCount"], 1)
        self.assertEqual(public[0]["phrases"], ["可以", "哈哈"])
        self.assertNotIn("text", public[0])
        self.assertNotIn("raw", json.dumps(public, ensure_ascii=False))
        self.assertNotIn("这是不应发送到浏览器的完整样本", json.dumps(public, ensure_ascii=False))

    def test_skill_metadata_parser_is_consistent_across_public_api_and_evaluator(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy-title.chat-memory.skill"
            path.write_text(
                '---\nname: chat-user-team-a-01\nuser_id: "team/a 01"\ndisplay_name: "A \\"quoted\\": Persona"\n---\n'
                "# Legacy Title Chat Skill\n\n"
                "## 目标\n\nx\n\n## 使用时机\n\nx\n\n## 记忆检索\n\nx\n\n## 说话风格画像\n\n- 常见表达：可以、哈哈。\n\n"
                "## 场景模板\n\nx\n\n## 真实样本\n\n```text\n可以\n```\n\n## 生成规则\n\nx\n\n## 硬边界\n\nx\n\n## 自检\n\nx\n",
                encoding="utf-8",
            )
            assets = load_skill_assets([path])

            public = public_skill_assets(assets)
            report = evaluate_skills([path])

        self.assertEqual(public[0]["name"], 'A "quoted": Persona')
        self.assertEqual(report["skills"][0]["name"], 'A "quoted": Persona')
        self.assertEqual(public[0]["userId"], "team/a 01")
        self.assertEqual(report["skills"][0]["user_id"], "team/a 01")

    def test_skill_metadata_parser_ignores_body_lines_that_look_like_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.chat-memory.skill"
            path.write_text(
                "# Legacy Title Chat Skill\n\n"
                "模拟 userID=legacy-user 的回复。\n\n"
                "## 说话风格画像\n\n"
                "- 常见表达：可以。\n\n"
                "## 真实样本\n\n"
                "```text\n"
                "display_name: Wrong Name\n"
                "user_id: wrong-user\n"
                "```\n",
                encoding="utf-8",
            )
            assets = load_skill_assets([path])

            public = public_skill_assets(assets)
            report = evaluate_skills([path])

        self.assertEqual(public[0]["name"], "Legacy Title")
        self.assertEqual(report["skills"][0]["name"], "Legacy Title")
        self.assertEqual(public[0]["userId"], "legacy-user")
        self.assertEqual(report["skills"][0]["user_id"], "legacy-user")

    def test_chat_payload_resolves_preloaded_skill_server_side(self) -> None:
        assets = [
            {
                "id": "server-skill-1",
                "file_name": "A.chat-memory.skill",
                "text": '---\nuser_id: "user-a"\ndisplay_name: "Participant A"\n---\n# Participant A Chat Skill\n\n真实 skill 内容',
            }
        ]
        payload = {
            "skill_id": "server-skill-1",
            "skill": "# Forged Skill",
            "persona": {"name": "Forged", "userId": "forged-user"},
        }

        resolved = resolve_preloaded_skill_payload(payload, assets)

        self.assertIn("真实 skill 内容", resolved["skill"])
        self.assertEqual(resolved["persona"], {"name": "Participant A", "userId": "user-a"})

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
        self.assertIn("命中由记忆后端按自身策略返回，本地不重排", prompt)
        self.assertNotIn("云记忆服务", prompt)
        self.assertIn("先通读全部命中", prompt)
        self.assertIn("只能引用记忆命中里的直接陈述", prompt)

    def test_hindsight_recall_uses_precise_query_and_strict_user_scope(self) -> None:
        skill = """
        # Participant A Chat Skill
        - Bank：`memory-bank-test`
        - `tags`：`["conversation:chat-a-b"]`
        """
        with patch("wechat_skill_distill.memory_recall.requests.post") as post:
            post.return_value = MockResponse(
                {
                    "results": [
                        {"id": "m0", "text": "Participant A和Participant B初次认识时互相介绍过名字", "type": "world"},
                        {"id": "m1", "text": "Participant A在Acme公司工作", "type": "world", "metadata": {"userID": "user-a"}},
                    ]
                }
            )

            hits = recall_for_chat(
                {
                    "message": "在哪家公司呢",
                    "skill": skill,
                    "persona": {"name": "Participant A", "userId": "user-a"},
                    "history": [{"role": "user", "text": "你是做什么工作的"}, {"role": "assistant", "text": "我是学生"}],
                },
                env={
                    "HINDSIGHT_API_URL": "https://memory.example.test/api",
                    "HINDSIGHT_API_KEY": "secret",
                    "HINDSIGHT_BANK_ID": "memory-bank-test",
                },
            )

        self.assertEqual([hit["content"] for hit in hits], ["Participant A和Participant B初次认识时互相介绍过名字", "Participant A在Acme公司工作"])
        self.assertTrue(memory_runtime_status({"HINDSIGHT_API_KEY": "secret"})["configured"])
        first_body = post.call_args.kwargs["json"]
        self.assertEqual(post.call_args_list[0].args[0], "https://memory.example.test/api/v1/default/banks/memory-bank-test/memories/recall")
        self.assertEqual(first_body["tags"], ["user:user-a"])
        self.assertEqual(first_body["tags_match"], "all_strict")
        self.assertIn("当前用户原话：在哪家公司呢", first_body["query"])
        self.assertIn("最近用户追问", first_body["query"])
        self.assertIn("你是做什么工作的", first_body["query"])
        self.assertNotIn("我是学生", first_body["query"])
        self.assertIn("只寻找能直接回答当前问题", first_body["query"])
        self.assertNotIn("相关表达", first_body["query"])
        self.assertNotIn("就职", first_body["query"])
        self.assertEqual(first_body["max_tokens"], 3200)
        self.assertIn("chunks", first_body["include"])
        self.assertIn("source_facts", first_body["include"])

    def test_hindsight_recall_can_use_model_planned_query_without_static_rules(self) -> None:
        skill = """
        # Participant A Chat Skill
        - Bank：`memory-bank-test`
        """
        with patch("wechat_skill_distill.memory_recall.generate_recall_query_variants") as planner, patch("wechat_skill_distill.memory_recall.requests.post") as post:
            planner.return_value = ["Participant A userID=user-a 当前问题：在哪家公司呢；上一问：你是做什么工作的"]
            post.return_value = MockResponse({"results": [{"id": "m1", "text": "Participant A在Acme公司工作", "type": "world"}]})

            hits = recall_for_chat(
                {
                    "message": "在哪家公司呢",
                    "skill": skill,
                    "persona": {"name": "Participant A", "userId": "user-a"},
                },
                env={
                    "HINDSIGHT_API_URL": "https://memory.example.test/api",
                    "HINDSIGHT_API_KEY": "secret",
                    "HINDSIGHT_BANK_ID": "memory-bank-test",
                    "WSD_RECALL_QUERY_PLANNER": "llm",
                },
            )

        self.assertEqual([hit["content"] for hit in hits], ["Participant A在Acme公司工作"])
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args_list[0].kwargs["json"]["query"], "Participant A userID=user-a 当前问题：在哪家公司呢；上一问：你是做什么工作的")
        self.assertNotIn("就职", post.call_args_list[0].kwargs["json"]["query"])
        planner.assert_called_once()

    def test_recall_query_planner_prompt_delegates_expansion_to_memory_backend(self) -> None:
        prompt = build_recall_query_planner_prompt()

        self.assertIn("默认只生成 1 条 query", prompt)
        self.assertIn("不要做本地 rerank", prompt)
        for forbidden in ["同义词", "上位词", "拆成检索词", "字段词", "常见记录字段"]:
            self.assertNotIn(forbidden, prompt)

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

    def test_mem0_runtime_status_requires_configuration(self) -> None:
        missing = memory_runtime_status({"WSD_MEMORY_RECALL_BACKEND": "mem0"})
        configured = memory_runtime_status({"WSD_MEMORY_RECALL_BACKEND": "mem0", "MEM0_API_KEY": "secret"})

        self.assertEqual(missing["backend"], "mem0")
        self.assertFalse(missing["configured"])
        self.assertTrue(configured["configured"])

    def test_prd_keeps_chat_ui_memory_recall_server_side(self) -> None:
        text = Path("PRD.md").read_text(encoding="utf-8")

        self.assertIn("前端不上传记忆文件、不做浏览器侧检索", text)
        self.assertIn("JSONL 记忆通过服务端 `JSONL_MEMORY_PATH` 接入", text)
        self.assertNotIn("页面能加载本地 `memory.jsonl` 并在回复时展示命中结果", text)
        self.assertNotIn("本地检索结果和服务端 recall 结果", text)
        self.assertNotIn("JSONL contract 说明宿主 agent 需要先做本地检索再注入上下文", text)

    def test_docs_keep_memory_backend_responsible_for_ranking(self) -> None:
        readme = Path("README.md").read_text(encoding="utf-8")
        prd = Path("PRD.md").read_text(encoding="utf-8")
        env_example = Path(".env.example").read_text(encoding="utf-8")

        self.assertIn("WSD_MEMORY_QUERY_VARIANTS=1", readme)
        self.assertIn("WSD_MEMORY_QUERY_VARIANTS=1", env_example)
        self.assertIn("默认单 query", readme)
        self.assertIn("排序和 rerank 交给记忆后端", readme)
        self.assertIn("默认单 query", prd)
        self.assertNotIn("WSD_MEMORY_QUERY_VARIANTS=3", readme)
        self.assertNotIn("WSD_MEMORY_QUERY_VARIANTS=3", env_example)

    def test_docs_describe_memory_hit_identity_filtering(self) -> None:
        readme = Path("README.md").read_text(encoding="utf-8")
        prd = Path("PRD.md").read_text(encoding="utf-8")

        self.assertIn("服务端会按 metadata、participants 和 user:<id> tags 过滤明确属于其他 user 的命中", readme)
        self.assertIn("不基于记忆文本做业务关键词过滤", readme)
        self.assertIn("模型请求前必须过滤明确属于其他 userID 的 memory hits", prd)
        self.assertIn("过滤只基于 metadata、participants 和 user:<id> tags", prd)

    def test_docs_keep_raw_skill_server_side(self) -> None:
        readme = Path("README.md").read_text(encoding="utf-8")
        prd = Path("PRD.md").read_text(encoding="utf-8")

        self.assertIn("浏览器只接收 persona 摘要和 skill_id，不接收完整 skill 文本", readme)
        self.assertIn("聊天请求只提交 skill_id", readme)
        self.assertIn("完整 skill 文本只保存在本地服务端", prd)
        self.assertIn("浏览器不得接收或回传 raw skill 文本", prd)

    def test_docs_require_shared_skill_metadata_parser(self) -> None:
        readme = Path("README.md").read_text(encoding="utf-8")
        prd = Path("PRD.md").read_text(encoding="utf-8")

        self.assertIn("前端摘要和评估报告使用同一套 skill metadata 解析规则", readme)
        self.assertIn("优先使用 frontmatter 的 display_name 和 user_id", readme)
        self.assertIn("只解析文件开头的 frontmatter block", readme)
        self.assertIn("服务端 public persona 摘要和 evaluate-skills 必须复用同一套 skill metadata parser", prd)
        self.assertIn("metadata parser 只读取文件开头 frontmatter block", prd)

    def test_docs_describe_persona_scoped_chat_sessions(self) -> None:
        readme = Path("README.md").read_text(encoding="utf-8")
        prd = Path("PRD.md").read_text(encoding="utf-8")

        self.assertIn("每个 persona 维护独立对话历史", readme)
        self.assertIn("切换对象不会把上一位对象的 history 传给下一位", readme)
        self.assertIn("多 persona UI 必须按 skill_id 隔离 transcript 和 recall 状态", prd)

    def test_docs_describe_safe_skill_artifact_identity_metadata(self) -> None:
        readme = Path("README.md").read_text(encoding="utf-8")
        prd = Path("PRD.md").read_text(encoding="utf-8")

        self.assertIn("输出文件名会从展示名派生并做文件系统安全转义", readme)
        self.assertIn("真实展示名和 user_id 保存在 skill frontmatter", readme)
        self.assertIn("同名或安全化后同名时会追加短 hash 防止覆盖", readme)
        self.assertIn("skill frontmatter 必须包含稳定 `name`、`user_id` 和 `display_name`", prd)
        self.assertIn("输出文件名必须做文件系统安全转义", prd)
        self.assertIn("同名或 slug 碰撞时必须追加稳定短 hash", prd)

    def test_generic_http_recall_backend_uses_common_runtime_contract(self) -> None:
        with patch("wechat_skill_distill.memory_recall.requests.post") as post:
            post.return_value = MockResponse(
                {
                    "results": [
                        {
                            "id": "g1",
                            "text": "Participant A提到自己更喜欢晚饭后散步",
                            "metadata": {"userID": "user-a", "timestamp": "2026-04-19T20:00:00+08:00"},
                            "score": 0.8,
                        }
                    ]
                }
            )

            hits = recall_for_chat(
                {
                    "message": "你晚上一般喜欢干嘛",
                    "skill": "# Participant A Chat Skill",
                    "persona": {"name": "Participant A", "userId": "user-a"},
                    "history": [{"role": "user", "text": "之前聊过散步吗"}],
                },
                env={
                    "WSD_MEMORY_RECALL_BACKEND": "generic-http",
                    "MEMORY_RECALL_URL": "https://memory.example.test/recall",
                    "MEMORY_API_KEY": "secret",
                    "WSD_MEMORY_RESULT_LIMIT": "9",
                },
            )

        self.assertEqual(hits[0]["content"], "Participant A提到自己更喜欢晚饭后散步")
        self.assertEqual(hits[0]["source"], "generic-http")
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://memory.example.test/recall")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret")
        self.assertEqual(kwargs["json"]["user_id"], "user-a")
        self.assertEqual(kwargs["json"]["persona"]["name"], "Participant A")
        self.assertEqual(kwargs["json"]["limit"], 9)
        self.assertIn("当前用户原话：你晚上一般喜欢干嘛", kwargs["json"]["query"])
        self.assertIn("之前聊过散步吗", kwargs["json"]["history"])

    def test_generic_http_recall_sends_query_variants_once_for_backend_ranking(self) -> None:
        with patch("wechat_skill_distill.memory_recall.generate_recall_query_variants") as planner, patch("wechat_skill_distill.memory_recall.requests.post") as post:
            planner.return_value = ["Participant A userID=user-a 当前问题：在哪家公司呢", "Participant A userID=user-a 上一问：做什么工作"]
            post.return_value = MockResponse({"results": [{"id": "g1", "text": "Participant A在Acme公司工作"}]})

            hits = recall_for_chat(
                {
                    "message": "在哪家公司呢",
                    "skill": "# Participant A Chat Skill",
                    "persona": {"name": "Participant A", "userId": "user-a"},
                    "history": [{"role": "user", "text": "你是做什么工作的"}],
                },
                env={
                    "WSD_MEMORY_RECALL_BACKEND": "generic-http",
                    "MEMORY_RECALL_URL": "https://memory.example.test/recall",
                    "WSD_RECALL_QUERY_PLANNER": "llm",
                    "WSD_MEMORY_QUERY_VARIANTS": "3",
                },
            )

        self.assertEqual([hit["content"] for hit in hits], ["Participant A在Acme公司工作"])
        self.assertEqual(post.call_count, 1)
        body = post.call_args.kwargs["json"]
        self.assertEqual(len(body["queries"]), 3)
        self.assertIn("当前用户原话：在哪家公司呢", body["queries"][0])
        self.assertEqual(body["queries"][1:], ["Participant A userID=user-a 当前问题：在哪家公司呢", "Participant A userID=user-a 上一问：做什么工作"])

    def test_mem0_recall_backend_uses_client_search_when_configured(self) -> None:
        class FakeMemoryClient:
            last_init = {}
            last_search = {}

            def __init__(self, api_key=None):
                FakeMemoryClient.last_init = {"api_key": api_key}

            def search(self, query, **kwargs):
                FakeMemoryClient.last_search = {"query": query, **kwargs}
                return {
                    "results": [
                        {
                            "id": "m1",
                            "memory": "Participant A说自己喜欢安静一点的咖啡馆",
                            "metadata": {"userID": "user-a"},
                        }
                    ]
                }

        fake_mem0 = ModuleType("mem0")
        fake_mem0.MemoryClient = FakeMemoryClient
        original_mem0 = sys.modules.get("mem0")
        sys.modules["mem0"] = fake_mem0
        try:
            hits = recall_for_chat(
                {
                    "message": "你喜欢什么样的咖啡馆",
                    "skill": "# Participant A Chat Skill",
                    "persona": {"name": "Participant A", "userId": "user-a"},
                },
                env={
                    "WSD_MEMORY_RECALL_BACKEND": "mem0",
                    "MEM0_API_KEY": "secret",
                    "WSD_MEMORY_RESULT_LIMIT": "7",
                },
            )
        finally:
            if original_mem0 is None:
                sys.modules.pop("mem0", None)
            else:
                sys.modules["mem0"] = original_mem0

        self.assertEqual(hits[0]["content"], "Participant A说自己喜欢安静一点的咖啡馆")
        self.assertEqual(hits[0]["source"], "mem0")
        self.assertEqual(FakeMemoryClient.last_init, {"api_key": "secret"})
        self.assertEqual(FakeMemoryClient.last_search["user_id"], "user-a")
        self.assertEqual(FakeMemoryClient.last_search["limit"], 7)
        self.assertIn("你喜欢什么样的咖啡馆", FakeMemoryClient.last_search["query"])

    def test_frontend_copy_and_defaults_are_persona_neutral(self) -> None:
        root = web_root()
        source = (root / "index.html").read_text(encoding="utf-8") + "\n" + (root / "app.js").read_text(encoding="utf-8")

        for private_name in ["肖明浩", "胡翔川", "牧之", "661", "662", "Skill Companion Lab"]:
            self.assertNotIn(private_name, source)
        self.assertIn("persona.name", source)
        self.assertIn("normalizePersona", source)
        self.assertIn("persona.sampleCount", source)
        self.assertIn("skill_id: personaId", source)
        self.assertIn("已配置 ${persona.sampleCount} 条风格样本", source)
        self.assertNotIn("persona.raw", source)
        self.assertNotIn("parseSkill", source)
        self.assertNotIn("frontmatterValue", source)
        self.assertNotIn("组场景示例", source)
        self.assertNotIn("后台模型未配置", source)

    def test_frontend_does_not_run_browser_side_memory_retrieval(self) -> None:
        root = web_root()
        source = (root / "index.html").read_text(encoding="utf-8") + "\n" + (root / "app.js").read_text(encoding="utf-8")

        self.assertNotIn("memoryFile", source)
        self.assertNotIn("searchMemory", source)
        self.assertNotIn("keywordSet", source)
        self.assertNotIn("memory_hits:", source)
        self.assertNotIn("记忆 JSONL", source)
        self.assertNotIn("skill: persona.raw", source)
        self.assertNotIn("raw: text", source)
        self.assertIn("记忆由本地服务端按配置检索", source)

    def test_frontend_scopes_chat_history_to_active_persona(self) -> None:
        source = (web_root() / "app.js").read_text(encoding="utf-8")

        self.assertIn("transcriptsByPersona", source)
        self.assertIn("lastRecallByPersona", source)
        self.assertIn("function transcriptForPersona", source)
        self.assertIn("function activeTranscript()", source)
        self.assertIn("function switchPersona", source)
        self.assertIn("renderTranscript()", source)
        recent_history_source = source[source.index("function recentHistory"): source.index("async function sendMessage")]
        self.assertIn("activeTranscript()", recent_history_source)
        self.assertNotIn("state.transcript\n    .filter", source)

    def test_frontend_records_async_reply_to_original_persona(self) -> None:
        source = (web_root() / "app.js").read_text(encoding="utf-8")
        send_source = source[source.index("async function sendMessage"): source.index("function setComposerEnabled")]

        self.assertIn("const personaId = persona.id;", send_source)
        self.assertIn("setRecallForPersona(personaId", send_source)
        self.assertIn("transcriptForPersona(personaId).push", send_source)
        self.assertNotIn("activeTranscript().push({\n      role: \"assistant\"", send_source)

    def test_chat_server_ignores_client_memory_hits_by_default(self) -> None:
        payload = {
            "message": "你之前说过什么",
            "memory_hits": [{"content": "浏览器伪造的事实"}],
        }

        enriched, counts = build_enriched_chat_payload(payload, [{"content": "服务端召回的事实"}], env={})

        self.assertEqual(enriched["memory_hits"], [{"content": "服务端召回的事实"}])
        self.assertEqual(counts, {"server_hits": 1, "local_hits": 0})

    def test_chat_server_can_explicitly_allow_client_memory_hits(self) -> None:
        payload = {
            "message": "你之前说过什么",
            "memory_hits": [{"content": "显式允许的本地事实"}],
        }

        enriched, counts = build_enriched_chat_payload(payload, [{"content": "服务端召回的事实"}], env={"WSD_ALLOW_CLIENT_MEMORY_HITS": "1"})

        self.assertEqual([hit["content"] for hit in enriched["memory_hits"]], ["显式允许的本地事实", "服务端召回的事实"])
        self.assertEqual(counts, {"server_hits": 1, "local_hits": 1})

    def test_chat_server_filters_memory_hits_scoped_to_other_users(self) -> None:
        payload = {
            "message": "你之前说过什么",
            "persona": {"name": "Participant A", "userId": "user-a"},
            "memory_hits": [
                {"content": "客户端里别人的事实", "metadata": {"userID": "user-b"}},
                {"content": "客户端当前人的事实", "metadata": {"userID": "user-a"}},
            ],
        }
        server_hits = [
            {"content": "服务端当前人的事实", "metadata": {"userID": "user-a"}},
            {"content": "服务端别人的事实", "metadata": {"userID": "user-b"}},
            {"content": "服务端别人的标签事实", "tags": ["user:user-b"]},
            {"content": "服务端未标注事实"},
        ]

        enriched, counts = build_enriched_chat_payload(payload, server_hits, env={"WSD_ALLOW_CLIENT_MEMORY_HITS": "1"})

        self.assertEqual(
            [hit["content"] for hit in enriched["memory_hits"]],
            ["客户端当前人的事实", "服务端当前人的事实", "服务端未标注事实"],
        )
        self.assertEqual(counts, {"server_hits": 2, "local_hits": 1})

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

    def test_openai_recall_query_planner_outputs_json_queries(self) -> None:
        with patch("wechat_skill_distill.model_client.requests.post") as post:
            post.return_value = MockResponse({"choices": [{"message": {"content": '["Participant A userID=user-a 学校 本科 专业", "Participant A userID=user-a 求学 经历"]'}}]})

            queries = generate_recall_query_variants(
                {
                    "persona": {"name": "Participant A", "userId": "user-a"},
                    "message": "你的求学经历是啥样的",
                    "history": "无",
                },
                env={
                    "WSD_OPENAI_API_KEY": "secret",
                    "WSD_OPENAI_MODEL": "deepseek-v4-flash",
                    "WSD_OPENAI_BASE_URL": "https://oneapi.example.test/v1",
                    "WSD_MODEL_PROVIDER": "openai",
                },
            )

        self.assertEqual(queries, ["Participant A userID=user-a 学校 本科 专业", "Participant A userID=user-a 求学 经历"])
        system_prompt = post.call_args.kwargs["json"]["messages"][0]["content"]
        self.assertIn("不能加入输入中没有出现的具体公司", system_prompt)
        self.assertIn("只输出 JSON 数组", system_prompt)

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

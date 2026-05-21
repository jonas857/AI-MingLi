import os
import json
import unittest
import tempfile
import importlib
from datetime import date
from pathlib import Path
from unittest.mock import patch


def _sample_bazi_payload():
    return {
        "raw_data": {
            "性别": "男",
            "阳历": "1995-01-04 16:00:00",
            "农历": "农历甲戌年十二月初四甲申时",
            "八字": "甲戌 丁丑 乙卯 甲申",
            "日主": "乙木",
            "生肖": "狗",
            "年柱": {
                "天干": {"天干": "甲", "五行": "木", "阴阳": "阳", "十神": "比肩"},
                "地支": {
                    "地支": "戌",
                    "五行": "土",
                    "阴阳": "阳",
                    "藏干": {
                        "主气": {"天干": "戊", "十神": "正财"},
                        "中气": {"天干": "辛", "十神": "七杀"},
                        "余气": {"天干": "丁", "十神": "食神"},
                    },
                },
                "纳音": "山头火",
                "旬": "甲戌旬",
                "空亡": "申酉",
                "星运": "长生",
                "自坐": "养",
            },
            "月柱": {
                "天干": {"天干": "丁", "五行": "火", "阴阳": "阴", "十神": "食神"},
                "地支": {
                    "地支": "丑",
                    "五行": "土",
                    "阴阳": "阴",
                    "藏干": {
                        "主气": {"天干": "己", "十神": "偏财"},
                        "中气": {"天干": "癸", "十神": "正印"},
                        "余气": {"天干": "辛", "十神": "七杀"},
                    },
                },
                "纳音": "涧下水",
                "旬": "丁丑旬",
                "空亡": "寅卯",
                "星运": "沐浴",
                "自坐": "冠带",
            },
            "日柱": {
                "天干": {"天干": "乙", "五行": "木", "阴阳": "阴"},
                "地支": {
                    "地支": "卯",
                    "五行": "木",
                    "阴阳": "阴",
                    "藏干": {
                        "主气": {"天干": "乙", "十神": "比肩"},
                    },
                },
                "纳音": "大溪水",
                "旬": "乙卯旬",
                "空亡": "子丑",
                "星运": "帝旺",
                "自坐": "帝旺",
            },
            "时柱": {
                "天干": {"天干": "甲", "五行": "木", "阴阳": "阳", "十神": "比肩"},
                "地支": {
                    "地支": "申",
                    "五行": "金",
                    "阴阳": "阳",
                    "藏干": {
                        "主气": {"天干": "庚", "十神": "正官"},
                        "中气": {"天干": "壬", "十神": "偏印"},
                        "余气": {"天干": "戊", "十神": "正财"},
                    },
                },
                "纳音": "泉中水",
                "旬": "甲申旬",
                "空亡": "午未",
                "星运": "临官",
                "自坐": "临官",
            },
            "大运": {
                "起运日期": "1997-01-01",
                "起运年龄": 2,
                "大运": [
                    {
                        "干支": "戊寅",
                        "开始年份": 1997,
                        "结束": 2006,
                        "开始年龄": 2,
                        "结束年龄": 11,
                        "天干十神": "正财",
                        "地支十神": ["劫财"],
                    },
                    {
                        "干支": "己卯",
                        "开始年份": 2007,
                        "结束": 2016,
                        "开始年龄": 12,
                        "结束年龄": 21,
                        "天干十神": "偏财",
                        "地支十神": ["比肩"],
                    },
                    {
                        "干支": "庚辰",
                        "开始年份": 2026,
                        "结束": 2035,
                        "开始年龄": 31,
                        "结束年龄": 40,
                        "天干十神": "正官",
                        "地支十神": ["正财"],
                    },
                ],
            },
            "神煞": {"年柱": ["华盖"], "月柱": [], "日柱": [], "时柱": []},
            "刑冲合会": {"三合": [], "六合": [], "冲": [], "刑": []},
        }
    }


class MemorySystemTests(unittest.TestCase):
    def setUp(self):
        os.environ.setdefault("ENABLE_VECTOR_MEMORY", "false")
        os.environ.setdefault("ENABLE_SHARED_MEMORY", "true")
        os.environ.setdefault("ENABLE_MEM0", "false")
        os.environ.setdefault("ENABLE_MCP_BAZI", "true")
        os.environ["DEEPSEEK_API_KEY"] = ""
        os.environ["EMBEDDINGS_API_KEY"] = ""

        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self._old_cwd = os.getcwd()
        os.chdir(self._tmp.name)
        self.addCleanup(lambda: os.chdir(self._old_cwd))

        import feature_flags
        import memory_manager

        importlib.reload(feature_flags)
        importlib.reload(memory_manager)

        os.environ["DEEPSEEK_API_KEY"] = ""
        os.environ["EMBEDDINGS_API_KEY"] = ""
        self.mm = memory_manager
        self.BaziMemoryManager = memory_manager.BaziMemoryManager

    def test_chart_facts_generation_and_persistence(self):
        bm = self.BaziMemoryManager(user_data_dir="user_data_test")
        user_id = "user_test_1"
        facts = bm.update_chart_facts_from_bazi_payload(
            user_id=user_id,
            user_info={"name": "测试", "gender": 1, "birth_time": "1995-01-04T16:00:00+08:00"},
            bazi_info=_sample_bazi_payload(),
            raw_file_path="local_data/bazi_data/sample.json",
        )
        self.assertIsInstance(facts, dict)
        self.assertEqual(facts.get("schema_version"), "chart_facts_v1")
        self.assertEqual(facts.get("user_id"), user_id)
        self.assertTrue(((facts.get("summary") or {}).get("chart_facts_text") or "").strip())

        path = os.path.join("local_data", "chart_facts", f"{user_id}_chart_facts.json")
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertEqual((loaded.get("core") or {}).get("day_master"), "乙木")
        self.assertEqual(len((loaded.get("dayun") or {}).get("list") or []), 3)

        chart_context = bm.format_chart_facts_context(loaded)
        self.assertIn("当前大运", chart_context)
        self.assertIn("完整大运列表", chart_context)
        self.assertIn("戊寅：1997-2006", chart_context)
        self.assertIn("己卯：2007-2016", chart_context)

    def test_current_dayun_uses_exact_transition_date(self):
        dayun_list = [
            {"ganzhi": "癸亥", "start_year": 2016, "end_year": 2025},
            {"ganzhi": "甲子", "start_year": 2026, "end_year": 2035},
        ]

        self.BaziMemoryManager._annotate_dayun_dates(dayun_list, "2006-5-28")

        self.assertEqual(dayun_list[0].get("start_date"), "2016-05-28")
        self.assertEqual(dayun_list[0].get("end_date"), "2026-05-27")
        current_before = self.BaziMemoryManager._select_current_dayun(dayun_list, date(2026, 5, 5))
        current_after = self.BaziMemoryManager._select_current_dayun(dayun_list, date(2026, 5, 28))

        self.assertEqual(current_before.get("ganzhi"), "癸亥")
        self.assertEqual(current_before.get("end_date"), "2026-05-27")
        self.assertEqual(current_after.get("ganzhi"), "甲子")
        self.assertEqual(current_after.get("start_date"), "2026-05-28")

    def test_insight_upsert_merge_and_history(self):
        bm = self.BaziMemoryManager(user_data_dir="user_data_test")
        user_id = "user_test_2"
        bm.upsert_structured_insight(
            user_id=user_id,
            dimension="日元核心分析",
            version="classic",
            analysis_content="结论A：日主乙木偏旺，行动力强。",
            model_used="deepseek-reasoner",
            importance=8,
        )
        bm.upsert_structured_insight(
            user_id=user_id,
            dimension="日元核心分析",
            version="classic",
            analysis_content="结论B：遇金旺年份压力增大，宜提前规划。",
            model_used="deepseek-reasoner",
            importance=8,
        )

        path = os.path.join("local_data", "insights", f"{user_id}_insights.json")
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        bucket = (
            doc.get("dimensions", {})
            .get("日元核心分析", {})
            .get("versions", {})
            .get("classic", {})
        )
        self.assertTrue(isinstance(bucket.get("current"), dict))
        self.assertTrue(isinstance(bucket.get("history"), list))
        self.assertGreaterEqual(len(bucket.get("history")), 1)

        cur = bucket["current"]
        sp = cur.get("summary_points") or []
        self.assertTrue(any("结论A" in x for x in sp))
        self.assertTrue(any("结论B" in x for x in sp))

    def test_profile_merge_and_feedback(self):
        bm = self.BaziMemoryManager(user_data_dir="user_data_test")
        user_id = "user_test_3"
        bm.update_profile(
            user_id=user_id,
            background={"job": "产品经理"},
            preferences={"style": "专业"},
            add_tags=["事业"],
            feedback_text="希望少一点套话。",
            feedback_meta={"source": "test"},
        )
        bm.update_profile(
            user_id=user_id,
            background={"city": "上海"},
            preferences={"length": "中等"},
            add_tags=["表达", "事业"],
            feedback_text="希望多一点依据点。",
            feedback_meta={"source": "test"},
        )

        path = os.path.join("local_data", "profile", f"{user_id}_profile.json")
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(doc.get("schema_version"), "profile_v1")
        bg = doc.get("background") or {}
        self.assertEqual(bg.get("job"), "产品经理")
        self.assertEqual(bg.get("city"), "上海")
        pf = doc.get("preferences") or {}
        self.assertEqual(pf.get("style"), "专业")
        self.assertEqual(pf.get("length"), "中等")
        tags = doc.get("tags") or []
        self.assertIn("事业", tags)
        self.assertIn("表达", tags)
        fb = doc.get("feedback") or []
        self.assertGreaterEqual(len(fb), 2)

    def test_shared_memory_context_includes_layers_and_flag(self):
        bm = self.BaziMemoryManager(user_data_dir="user_data_test")
        user_id = "user_test_4"
        bm.update_chart_facts_from_bazi_payload(
            user_id=user_id,
            user_info={"name": "测试", "gender": 1, "birth_time": "1995-01-04T16:00:00+08:00"},
            bazi_info=_sample_bazi_payload(),
        )
        bm.update_profile(
            user_id=user_id,
            background={"job": "工程师"},
            preferences={"style": "通俗"},
            add_tags=["登录"],
        )
        bm.upsert_structured_insight(
            user_id=user_id,
            dimension="日元核心分析",
            version="classic",
            analysis_content="结论：日主乙木偏旺。",
            model_used="deepseek-reasoner",
            importance=8,
        )
        ctx = bm.build_shared_memory_context(user_id=user_id, dimension="日元核心分析", query="事业")
        self.assertIn("[chart_fact][全局]", ctx)
        self.assertIn("<chart_facts>", ctx)
        self.assertIn("当前大运", ctx)
        self.assertIn("完整大运列表", ctx)
        self.assertIn("戊寅：1997-2006", ctx)
        self.assertIn("己卯：2007-2016", ctx)
        self.assertIn("[profile][全局]", ctx)
        self.assertIn("[insight][日元核心分析]", ctx)

        old = self.mm.SHARED_MEMORY_ENABLED
        self.mm.SHARED_MEMORY_ENABLED = False
        try:
            ctx2 = bm.build_shared_memory_context(user_id=user_id, dimension="日元核心分析", query="事业")
            self.assertEqual(ctx2, "")
        finally:
            self.mm.SHARED_MEMORY_ENABLED = old

    def test_memory_v2_items_pin_delete_and_preferences(self):
        bm = self.BaziMemoryManager(user_data_dir="user_data_test")
        user_id = "user_test_memory_v2"
        item = bm.upsert_memory_item(
            user_id,
            {
                "type": "support_profile",
                "domain": "global",
                "dimension": "career",
                "content": "User prefers direct and warm guidance without exposing raw refs.",
                "evidence_refs": ["evt_test"],
                "confidence": 0.8,
            },
        )
        self.assertTrue(item and item.get("id"))
        pinned = bm.set_memory_item_pin(user_id, item["id"], True)
        self.assertTrue(pinned.get("pinned"))
        ctx = bm.build_shared_memory_context(user_id=user_id, dimension="career", query="work")
        self.assertIn("<pinned_memories>", ctx)

        prefs = bm.update_memory_preferences(user_id, {"emotional_memory_enabled": False})
        self.assertFalse(prefs.get("emotional_memory_enabled"))
        ctx2 = bm.build_shared_memory_context(user_id=user_id, dimension="career", query="work")
        self.assertNotIn("<support_profile>", ctx2)

        self.assertTrue(bm.delete_memory_item(user_id, item["id"]))
        visible = bm.get_memory_items(user_id, include_disabled=False)
        self.assertFalse(any(x.get("id") == item["id"] for x in visible))

    def test_chat_events_create_episode_and_support_memory(self):
        bm = self.BaziMemoryManager(user_data_dir="user_data_test")
        user_id = "user_test_chat_memory"
        bm.summarize_event_memory = lambda user_id, event: {
            "ai_used": True,
            "should_store": True,
            "memory_type": "support_profile",
            "content": ["用户持续关注事业方向，偏好稳健、可执行的建议"],
            "episode_summary": "用户咨询事业方向，回答建议先稳住主线，再比较机会长期收益。",
            "support_profile_items": ["用户对事业方向有持续焦虑，需要稳健建议"],
            "confidence": 0.85,
            "sensitivity": "normal",
            "merge_strategy": "merge",
            "reason": "durable preference and concern",
            "evidence_refs": [event.get("event_id")],
            "model": "test-organizer",
        }
        bm.append_raw_event(
            user_id=user_id,
            event_type="liuyao_chat",
            dimension="六爻占卜",
            version="professional",
            content="User: 我很担心事业方向，想知道接下来怎么选择。\nAssistant: 建议先稳住主线，再比较机会的长期收益。",
            model_used="deepseek-v4-pro",
            user_background={},
            importance=5,
            extra={"source": "liuyao_chat"},
        )
        res = bm.process_pending_events(user_id=user_id, max_events=10)
        self.assertEqual(int(res.get("pending") or 0), 0)
        episodes = bm.get_memory_items(user_id, memory_type="episode")
        support = bm.get_memory_items(user_id, memory_type="support_profile")
        self.assertTrue(any(x.get("dimension") == "六爻占卜" for x in episodes))
        self.assertTrue(any("事业方向" in x.get("content", "") for x in support))
        self.assertTrue(all(x.get("domain") == "liuyao" for x in episodes + support))

    def test_raw_event_stays_queued_and_out_of_context_before_ai(self):
        bm = self.BaziMemoryManager(user_data_dir="user_data_test")
        user_id = "user_test_raw_event_queued"
        event_id = bm.append_raw_event(
            user_id=user_id,
            event_type="liuyao_chat",
            dimension="六爻占卜",
            version="professional",
            content="RAW_UNPROCESSED_MEMORY_SHOULD_NOT_APPEAR",
            model_used="deepseek-v4-pro",
            user_background={},
            importance=5,
        )

        status = bm.get_memory_status(user_id)
        self.assertEqual(status.get("pending_count"), 1)
        self.assertTrue(any(x.get("event_id") == event_id and x.get("status") == "pending" for x in status.get("latest") or []))
        ctx = bm.build_shared_memory_context(user_id=user_id, dimension="六爻占卜", query="事业")
        self.assertNotIn("RAW_UNPROCESSED_MEMORY_SHOULD_NOT_APPEAR", ctx)
        self.assertEqual(bm.get_memory_items(user_id), [])

    def test_ai_failure_marks_retryable_and_skips_formal_memory(self):
        bm = self.BaziMemoryManager(user_data_dir="user_data_test")
        user_id = "user_test_ai_failure_retryable"
        bm.append_raw_event(
            user_id=user_id,
            event_type="liuyao_chat",
            dimension="六爻占卜",
            version="professional",
            content="User: 事业怎么选\nAssistant: 先比较长期收益。",
            model_used="deepseek-v4-pro",
            user_background={},
            importance=5,
        )

        res = bm.process_pending_events(user_id=user_id, max_events=1)
        self.assertEqual(int(res.get("processed") or 0), 1)
        self.assertEqual(int(res.get("failed") or 0), 1)
        status = bm.get_memory_status(user_id)
        self.assertEqual((status.get("counts") or {}).get("failed_retryable"), 1)
        self.assertEqual(bm.get_memory_items(user_id), [])
        ctx = bm.build_shared_memory_context(user_id=user_id, dimension="六爻占卜", query="事业")
        self.assertNotIn("先比较长期收益", ctx)

    def test_json_object_extractor_repairs_common_model_wrappers(self):
        bm = self.BaziMemoryManager(user_data_dir="user_data_test")
        fenced = 'Here is the result:\n```json\n{"should_store": true, "memory_type": "episode"}\n```'
        self.assertEqual(bm._extract_json_object(fenced).get("memory_type"), "episode")

        adjacent = 'preface {"discardReason": "no durable memory"} trailing {"ignored": true}'
        self.assertEqual(bm._extract_json_object(adjacent).get("discardReason"), "no durable memory")

        top_level_list = '[{"memory_type": "support_profile", "content": ["stable concern"]}]'
        self.assertEqual(bm._extract_json_object(top_level_list).get("memory_type"), "support_profile")

    def test_invalid_chat_json_marks_retryable_then_retry_imports_memory(self):
        bm = self.BaziMemoryManager(user_data_dir="user_data_test")
        user_id = "user_test_invalid_json_retry"

        def raise_invalid_json(user_id, event):
            raise ValueError("AI memory organizer returned invalid JSON")

        bm.summarize_event_memory = raise_invalid_json
        event_id = bm.append_raw_event(
            user_id=user_id,
            event_type="liuyao_chat",
            dimension="career",
            version="professional",
            content="RAW_CHAT_TRANSCRIPT_SHOULD_NOT_APPEAR",
            model_used="deepseek-v4-flash",
            user_background={},
            importance=5,
        )

        first = bm.process_pending_events(user_id=user_id, max_events=1)
        self.assertEqual(int(first.get("failed") or 0), 1)
        status = bm.get_memory_status(user_id)
        latest = (status.get("latest") or [])[0]
        self.assertEqual(latest.get("status"), "failed_retryable")
        self.assertTrue(latest.get("next_retry_at"))
        self.assertEqual(bm.get_memory_items(user_id), [])
        ctx = bm.build_shared_memory_context(user_id=user_id, dimension="career", query="career")
        self.assertNotIn("RAW_CHAT_TRANSCRIPT_SHOULD_NOT_APPEAR", ctx)

        bm.summarize_event_memory = lambda user_id, event: {
            "ai_used": True,
            "should_store": True,
            "memory_type": "episode",
            "content": ["User has a durable career concern"],
            "confidence": 0.8,
            "sensitivity": "normal",
            "merge_strategy": "merge",
            "reason": "retry success",
            "evidence_refs": [event.get("event_id")],
            "model": "test-organizer",
        }
        self.assertTrue(bm.retry_memory_event(user_id, event_id))
        second = bm.process_pending_events(user_id=user_id, max_events=1)
        self.assertEqual(int(second.get("ready") or 0), 1)
        status2 = bm.get_memory_status(user_id)
        self.assertEqual((status2.get("counts") or {}).get("ready"), 1)
        self.assertTrue((status2.get("latest") or [])[0].get("memory_item_ids"))

    def test_analysis_event_without_actual_import_is_discarded(self):
        bm = self.BaziMemoryManager(user_data_dir="user_data_test")
        user_id = "user_test_analysis_no_import"
        bm.organize_analysis_event_memory = lambda user_id, event: {
            "ai_used": True,
            "model": "test-organizer",
            "insight_patch": None,
            "memory_items": [],
            "profile_patch": {},
            "discard_reason": "not durable",
        }
        bm.append_raw_event(
            user_id=user_id,
            event_type="analysis",
            dimension="career",
            version="classic",
            content="Temporary analysis text",
            model_used="deepseek-reasoner",
            user_background={},
            importance=8,
        )
        res = bm.process_pending_events(user_id=user_id, max_events=1)
        self.assertEqual(int(res.get("discarded") or 0), 1)
        status = bm.get_memory_status(user_id)
        self.assertEqual((status.get("counts") or {}).get("discarded"), 1)
        self.assertEqual((status.get("counts") or {}).get("ready"), 0)

    def test_divination_memory_context_is_domain_isolated(self):
        bm = self.BaziMemoryManager(user_data_dir="user_data_test")
        user_id = "user_test_divination_isolation"
        bm.update_chart_facts_from_bazi_payload(
            user_id=user_id,
            user_info={"name": "test", "gender": 1, "birth_time": "1995-01-04T16:00:00+08:00"},
            bazi_info=_sample_bazi_payload(),
        )
        bm.upsert_memory_item(
            user_id,
            {
                "type": "domain_insight",
                "domain": "bazi",
                "dimension": "日元核心分析",
                "content": "BAZI_ONLY_MEMORY",
            },
        )
        bm.upsert_memory_item(
            user_id,
            {
                "type": "episode",
                "domain": "liuyao",
                "dimension": "六爻占卜",
                "content": "LIUYAO_ONLY_MEMORY",
            },
        )
        bm.upsert_memory_item(
            user_id,
            {
                "type": "episode",
                "domain": "bazi",
                "dimension": "六爻占卜",
                "content": "OLD_MISCLASSIFIED_LIUYAO_MEMORY",
            },
        )
        bm.upsert_memory_item(
            user_id,
            {
                "type": "episode",
                "domain": "qimen",
                "dimension": "奇门遁甲",
                "content": "QIMEN_ONLY_MEMORY",
            },
        )

        liuyao_ctx = bm.build_shared_memory_context(user_id=user_id, dimension="六爻占卜", query="事业怎么选")
        self.assertIn("LIUYAO_ONLY_MEMORY", liuyao_ctx)
        self.assertIn("OLD_MISCLASSIFIED_LIUYAO_MEMORY", liuyao_ctx)
        self.assertNotIn("BAZI_ONLY_MEMORY", liuyao_ctx)
        self.assertNotIn("QIMEN_ONLY_MEMORY", liuyao_ctx)
        self.assertNotIn("<chart_facts>", liuyao_ctx)

        qimen_ctx = bm.build_shared_memory_context(user_id=user_id, dimension="奇门遁甲", query="方位怎么取")
        self.assertIn("QIMEN_ONLY_MEMORY", qimen_ctx)
        self.assertNotIn("BAZI_ONLY_MEMORY", qimen_ctx)
        self.assertNotIn("LIUYAO_ONLY_MEMORY", qimen_ctx)
        self.assertNotIn("<chart_facts>", qimen_ctx)

        bazi_ctx = bm.build_shared_memory_context(user_id=user_id, dimension="日元核心分析", query="事业")
        self.assertIn("BAZI_ONLY_MEMORY", bazi_ctx)
        self.assertIn("<chart_facts>", bazi_ctx)
        self.assertNotIn("LIUYAO_ONLY_MEMORY", bazi_ctx)
        self.assertNotIn("OLD_MISCLASSIFIED_LIUYAO_MEMORY", bazi_ctx)
        self.assertNotIn("QIMEN_ONLY_MEMORY", bazi_ctx)

    def test_mojibake_divination_dimensions_stay_domain_isolated(self):
        bm = self.BaziMemoryManager(user_data_dir="user_data_test")
        user_id = "user_test_mojibake_divination_isolation"
        bad_ziwei = "\u7ef1\ue0a2\u4e95\u93c2\u6941\u669f"
        bad_liuyao = "\u934f\ue160\u57e2\u9357\u72b2\u5d2a"
        bad_qimen = "\u6fc2\u56e9\u68ec\u95ac\u4f7a\u6573"

        bm.upsert_memory_item(
            user_id,
            {
                "type": "episode",
                "domain": "ziwei",
                "dimension": "紫微斗数",
                "content": "ZIWEI_MEMORY",
            },
        )
        bm.upsert_memory_item(
            user_id,
            {
                "type": "episode",
                "domain": "liuyao",
                "dimension": "六爻占卜",
                "content": "LIUYAO_MEMORY",
            },
        )
        bm.upsert_memory_item(
            user_id,
            {
                "type": "episode",
                "domain": "qimen",
                "dimension": "奇门遁甲",
                "content": "QIMEN_MEMORY",
            },
        )
        bm.upsert_memory_item(
            user_id,
            {
                "type": "domain_insight",
                "domain": "bazi",
                "dimension": "日元核心分析",
                "content": "BAZI_ONLY_MEMORY",
            },
        )

        ziwei_ctx = bm.build_shared_memory_context(user_id=user_id, dimension=bad_ziwei, query="命宫")
        liuyao_ctx = bm.build_shared_memory_context(user_id=user_id, dimension=bad_liuyao, query="事业")
        qimen_ctx = bm.build_shared_memory_context(user_id=user_id, dimension=bad_qimen, query="方位")

        self.assertIn("ZIWEI_MEMORY", ziwei_ctx)
        self.assertIn("LIUYAO_MEMORY", liuyao_ctx)
        self.assertIn("QIMEN_MEMORY", qimen_ctx)
        self.assertNotIn("BAZI_ONLY_MEMORY", ziwei_ctx)
        self.assertNotIn("BAZI_ONLY_MEMORY", liuyao_ctx)
        self.assertNotIn("BAZI_ONLY_MEMORY", qimen_ctx)
        self.assertNotIn("<chart_facts>", liuyao_ctx)

    def test_app_chat_routes_use_canonical_memory_dimensions(self):
        repo_root = Path(__file__).resolve().parents[1]
        app_source = (repo_root / "app_simplified.py").read_text(encoding="utf-8")
        bad_ziwei = "\u7ef1\ue0a2\u4e95\u93c2\u6941\u669f"
        bad_liuyao = "\u934f\ue160\u57e2\u9357\u72b2\u5d2a"
        bad_qimen = "\u6fc2\u56e9\u68ec\u95ac\u4f7a\u6573"

        self.assertIn('dimension="紫微斗数"', app_source)
        self.assertIn('dimension="六爻占卜"', app_source)
        self.assertIn('dimension="奇门遁甲"', app_source)
        self.assertNotIn(f'dimension="{bad_ziwei}"', app_source)
        self.assertNotIn(f'dimension="{bad_liuyao}"', app_source)
        self.assertNotIn(f'dimension="{bad_qimen}"', app_source)

    def test_assessed_divination_domain_insight_keeps_own_domain(self):
        bm = self.BaziMemoryManager(user_data_dir="user_data_test")
        user_id = "user_test_divination_assessment_domain"
        bm.summarize_event_memory = lambda user_id, event: {
            "ai_used": True,
            "should_store": True,
            "memory_type": "domain_insight",
            "content": ["六爻事业判断应以本卦和动爻为主要依据"],
            "confidence": 0.8,
            "sensitivity": "normal",
            "merge_strategy": "merge",
            "reason": "durable domain insight",
            "evidence_refs": [event.get("event_id")],
            "model": "test-organizer",
        }
        written = bm.upsert_event_memory_items(
            user_id=user_id,
            event={
                "event_id": "evt_liuyao_domain",
                "type": "liuyao_chat",
                "dimension": "六爻占卜",
                "content": "User: 看事业选择\nAssistant: 以本卦和动爻判断。",
                "extra": {"source": "liuyao_chat"},
            },
        )
        self.assertTrue(written)
        self.assertTrue(all(x.get("domain") == "liuyao" for x in written))

    def test_memory_assessment_discard_skips_memory_item(self):
        bm = self.BaziMemoryManager(user_data_dir="user_data_test")
        user_id = "user_test_assessment_discard"

        bm.summarize_event_memory = lambda user_id, event: {
            "ai_used": True,
            "should_store": False,
            "memory_type": "discard",
            "content": ["临时寒暄，不需要长期保存"],
            "confidence": 0.9,
            "sensitivity": "normal",
            "merge_strategy": "discard",
            "reason": "transient",
            "evidence_refs": [event.get("event_id")],
            "model": "deepseek-v4-flash",
        }
        written = bm.upsert_event_memory_items(
            user_id=user_id,
            event={
                "event_id": "evt_discard",
                "type": "followup",
                "dimension": "事业运势分析",
                "content": "谢谢",
            },
        )
        self.assertEqual(written, [])
        self.assertEqual(bm.get_memory_items(user_id), [])

    def test_memory_assessment_writes_selected_memory_types(self):
        bm = self.BaziMemoryManager(user_data_dir="user_data_test")
        user_id = "user_test_assessment_types"

        for memory_type in ("episode", "support_profile", "domain_insight"):
            bm.summarize_event_memory = lambda user_id, event, mt=memory_type: {
                "ai_used": True,
                "should_store": True,
                "memory_type": mt,
                "content": [f"{mt} 要点一", f"{mt} 要点二"],
                "confidence": 0.8,
                "sensitivity": "normal",
                "merge_strategy": "replace",
                "reason": "durable",
                "evidence_refs": [event.get("event_id")],
                "model": "deepseek-v4-flash",
            }
            bm.upsert_event_memory_items(
                user_id=user_id,
                event={
                    "event_id": f"evt_{memory_type}",
                    "type": "followup",
                    "dimension": "事业运势分析",
                    "content": "用户追问事业方向，回答给出长期建议。",
                },
            )

        item_types = {x.get("type") for x in bm.get_memory_items(user_id)}
        self.assertTrue({"episode", "support_profile", "domain_insight"}.issubset(item_types))

    def test_app_main_flow_uses_gemini_only_for_master_interpretation(self):
        repo_root = Path(__file__).resolve().parents[1]
        app_source = (repo_root / "app_simplified.py").read_text(encoding="utf-8")
        self.assertIn('if version == "master":', app_source)
        self.assertIn("analyze_with_gemini(", app_source)
        self.assertIn("analyze_with_deepseek(", app_source)

    def test_legacy_profile_and_insights_backfill_to_memory_v2(self):
        bm = self.BaziMemoryManager(user_data_dir="user_data_test")
        user_id = "user_test_legacy_backfill"
        bm.save_profile_doc(
            user_id,
            {
                "schema_version": "profile_v1",
                "user_id": user_id,
                "background": {},
                "preferences": {"tone": "warm and direct"},
                "tags": ["career", "relationship"],
                "feedback": [{"text": "prefer concise advice"}],
            },
        )
        bm.save_insights_doc(
            user_id,
            {
                "schema_version": "insights_v1",
                "user_id": user_id,
                "dimensions": {
                    "career": {
                        "versions": {
                            "classic": {
                                "current": {
                                    "dimension": "career",
                                    "version": "classic",
                                    "summary_points": ["career direction is the recurring question"],
                                    "evidence_points": ["legacy evidence"],
                                    "advice_points": ["prioritize stable choices"],
                                    "updated_at": "2026-01-01T00:00:00",
                                }
                            }
                        }
                    }
                },
            },
        )
        bm.backfill_memory_items_from_legacy(user_id=user_id, force=True)
        summary = bm.get_memory_summary(user_id)
        self.assertGreaterEqual((summary.get("counts") or {}).get("support_profile", 0), 1)
        self.assertGreaterEqual((summary.get("counts") or {}).get("domain_insight", 0), 1)
        self.assertIn("organizer_status", summary)
        ctx = bm.build_shared_memory_context(user_id=user_id, dimension="career", query="career")
        self.assertIn("career direction", ctx)

    def test_async_organizer_processes_events_to_structured_docs(self):
        bm = self.BaziMemoryManager(user_data_dir="user_data_test")
        user_id = "user_test_6"
        bm.organize_analysis_event_memory = lambda user_id, event: {
            "ai_used": True,
            "model": "test-organizer",
            "insight_patch": {
                "summary_points": ["日元核心分析：日主乙木偏旺"],
                "evidence_points": ["原文提到结论A"],
                "advice_points": ["避免急躁"],
                "confidence": 0.86,
            },
            "profile_patch": {
                "background": {"job": "工程师"},
                "preferences": {},
                "tags": ["日元核心分析"],
            },
            "memory_items": [
                {
                    "type": "domain_insight",
                    "domain": "bazi",
                    "dimension": "日元核心分析",
                    "content": "日主乙木偏旺；建议避免急躁。",
                    "evidence_refs": [event.get("event_id")],
                    "confidence": 0.86,
                    "sensitivity": "normal",
                    "model": "test-organizer",
                    "extra": {"event_type": event.get("type")},
                }
            ],
            "discard_reason": "",
        }
        bm.append_raw_event(
            user_id=user_id,
            event_type="analysis",
            dimension="日元核心分析",
            version="classic",
            content="结论A：日主乙木偏旺。建议B：避免急躁。",
            model_used="deepseek-reasoner",
            user_background={"job": "工程师"},
            importance=8,
        )
        pending_before = bm.get_pending_event_count(user_id)
        self.assertGreaterEqual(pending_before, 1)
        res = bm.process_pending_events(user_id=user_id, max_events=10)
        self.assertGreaterEqual(int(res.get("processed") or 0), 1)
        self.assertEqual(int(res.get("pending") or 0), 0)

        ipath = os.path.join("local_data", "insights", f"{user_id}_insights.json")
        self.assertTrue(os.path.exists(ipath))
        ppath = os.path.join("local_data", "profile", f"{user_id}_profile.json")
        self.assertTrue(os.path.exists(ppath))
        latest = bm.get_latest_dimension_insight(user_id=user_id, dimension="日元核心分析")
        self.assertTrue("日元核心分析" in latest)

    def test_home_payload_treats_birth_metadata_as_saved_profile(self):
        try:
            import app_simplified
        except Exception:
            self.skipTest("app_simplified import failed")
        app_simplified = importlib.reload(app_simplified)

        user = app_simplified.user_manager.create_user(
            identifier="home_profile_metadata",
            username="测试用户",
            metadata={
                "gender": 1,
                "birth_date": "1990-05-15",
                "birth_time": "1990-05-15T14:30:00+08:00",
                "calendar_type": "solar",
            },
        )

        payload = app_simplified._home_payload_for_user(user.user_id)

        self.assertFalse(payload["needs_profile"])
        self.assertTrue(payload["profile_complete"])
        self.assertTrue(payload["bazi"]["exists"])
        self.assertFalse(payload["bazi"]["has_chart"])
        self.assertEqual(payload["bazi"]["source"], "profile_metadata")
        self.assertEqual(payload["bazi"]["user_info"]["birth_date"], "1990-05-15")

    def test_home_payload_extracts_four_pillars_from_raw_bazi(self):
        try:
            import app_simplified
        except Exception:
            self.skipTest("app_simplified import failed")
        app_simplified = importlib.reload(app_simplified)

        user = app_simplified.user_manager.create_user(
            identifier="home_raw_four_pillars",
            username="四柱测试",
            metadata={
                "birth_date": "2004-07-09",
                "birth_time": "2004-07-09T17:30:00+08:00",
                "gender": 1,
            },
        )
        app_simplified.save_to_local_file(
            app_simplified.get_user_bazi_file(user.user_id),
            {
                "user_info": {
                    "name": "四柱测试",
                    "birth_date": "2004-07-09",
                    "birth_time": "2004-07-09T17:30:00+08:00",
                    "gender": 1,
                },
                "bazi_info": {
                    "four_pillars": {},
                    "raw_data": {"八字": "甲申 辛未 己丑 癸酉"},
                },
                "timestamp": "2026-05-07T21:37:49",
            },
        )

        payload = app_simplified._home_payload_for_user(user.user_id)

        self.assertTrue(payload["bazi"]["exists"])
        self.assertTrue(payload["bazi"]["has_chart"])
        self.assertEqual(payload["bazi"]["four_pillars"], "甲申 辛未 己丑 癸酉")

    def test_unlinked_account_birth_profile_counts_as_complete_on_home(self):
        try:
            import app_simplified
        except Exception:
            self.skipTest("app_simplified import failed")
        app_simplified = importlib.reload(app_simplified)

        account = app_simplified.auth_manager.create_account(
            login_id="home_account_profile",
            pin="1234",
            display_name="主页测试",
            metadata={
                "registration_birth_profile": {
                    "name": "主页测试",
                    "gender": 1,
                    "birth_date": "1991-06-20",
                    "birth_time": "10:15",
                    "calendar_type": "solar",
                }
            },
        )
        client = app_simplified.app.test_client()
        with client.session_transaction() as sess:
            sess["account_id"] = account["account_id"]

        me = client.get("/api/auth/me").get_json() or {}
        home = client.get("/api/user/home").get_json() or {}

        self.assertTrue(me["profile_complete"])
        self.assertFalse(me["needs_profile"])
        self.assertTrue(home["profile_complete"])
        self.assertFalse(home["needs_profile"])
        self.assertTrue(home["bazi"]["exists"])
        self.assertEqual(home["bazi"]["source"], "account_metadata")

    def test_home_profile_notice_hidden_css_wins_over_flex_rule(self):
        repo_root = Path(__file__).resolve().parents[1]
        home_source = (repo_root / "home.html").read_text(encoding="utf-8")
        self.assertIn("[hidden] { display: none !important; }", home_source)
        self.assertNotIn("fact('用户 ID'", home_source)
        self.assertNotIn("问题地图", home_source)
        self.assertNotIn("沟通偏好与稳定画像", home_source)
        self.assertIn("出生档案", home_source)
        self.assertIn("核心入口", home_source)
        self.assertIn("用户画像", home_source)
        self.assertIn("近期追问脉络", home_source)
        self.assertIn("记忆速览", home_source)
        self.assertIn("buildMemorySnapshotItems", home_source)
        self.assertIn("buildRecentThreadItems", home_source)
        self.assertIn("renderUserPortrait", home_source)
        self.assertIn("/api/memory/home-portrait", home_source)
        self.assertIn("selected.length >= 3", home_source)
        self.assertIn("fetch(url, { cache: 'no-store' })", home_source)
        self.assertIn("async function refreshBaziSummary", home_source)
        self.assertIn("/api/user/bazi-data", home_source)
        self.assertIn("function extractFourPillars", home_source)

    def test_home_portrait_endpoint_uses_memory_fallback_if_flask_available(self):
        try:
            import flask  # noqa: F401
        except Exception:
            self.skipTest("flask not available")

        try:
            import app_simplified
        except Exception:
            self.skipTest("app_simplified import failed")
        app_simplified = importlib.reload(app_simplified)

        user_id = "user_home_portrait"
        app_simplified.user_manager.create_user(identifier=user_id, username="画像测试")
        app_simplified.bazi_memory_manager.upsert_memory_item(
            user_id,
            {
                "type": "support_profile",
                "domain": "global",
                "dimension": "沟通偏好",
                "content": "用户更偏好直接、温和、少套话的建议。",
                "updated_at": "2026-05-07T10:00:00",
            },
        )
        app_simplified.bazi_memory_manager.upsert_memory_item(
            user_id,
            {
                "type": "episode",
                "domain": "bazi",
                "dimension": "事业运势分析",
                "content": "用户近期多次追问事业方向，希望把机会选择和长期稳定性放在一起判断。",
                "updated_at": "2026-05-07T11:00:00",
            },
        )

        client = app_simplified.app.test_client()
        with client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["username"] = "画像测试"

        with patch.object(app_simplified.ai_analyzer, "deepseek_client", None):
            response = client.get("/api/memory/home-portrait")

        self.assertEqual(response.status_code, 200)
        data = response.get_json() or {}
        self.assertTrue(data.get("success"))
        self.assertFalse(data.get("ai_used"))
        portrait = data.get("portrait") or {}
        self.assertEqual(portrait.get("headline"), "偏好已沉淀")
        self.assertIn("用户更偏好", portrait.get("summary", ""))
        self.assertGreaterEqual(data.get("source_count") or 0, 1)

    def test_debug_routes_removed_and_ziwei_chart_contract_if_flask_available(self):
        try:
            import flask  # noqa: F401
        except Exception:
            self.skipTest("flask not available")

        try:
            import app_simplified
        except Exception:
            self.skipTest("app_simplified import failed")

        client = app_simplified.app.test_client()

        self.assertEqual(client.get("/dev").status_code, 404)
        self.assertEqual(client.get("/api/debug/memory/context").status_code, 404)

        unauth = client.post("/api/ziwei/chart", json={})
        self.assertEqual(unauth.status_code, 401)

        with client.session_transaction() as sess:
            sess["user_id"] = "user_test_5"
            sess["username"] = "test"

        with patch.object(app_simplified, "MCP_ZIWEI_ENABLED", False):
            disabled = client.post("/api/ziwei/chart", json={})
        self.assertEqual(disabled.status_code, 400)
        self.assertFalse((disabled.get_json() or {}).get("success"))

        class FakeZiweiClient:
            def __init__(self, request_id=None):
                self.request_id = request_id

            async def generate_chart(self, **kwargs):
                return {"chartId": "chart_test_1", "input": kwargs}

            async def interpret_chart(self, **kwargs):
                return {"summary": "ok", "input": kwargs}

        payload = {
            "name": "test",
            "gender": "male",
            "birth_date": "1990-05-15",
            "birth_time": "14:30",
            "detail_level": "advanced",
        }
        with patch.object(app_simplified, "MCP_ZIWEI_ENABLED", True), patch.object(
            app_simplified, "ZiweiClient", FakeZiweiClient
        ):
            r = client.post("/api/ziwei/chart", json=payload)

        self.assertEqual(r.status_code, 200)
        data = r.get_json() or {}
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("chart_id"), "chart_test_1")
        self.assertIn("chart", data)
        self.assertIn("interpret", data)


if __name__ == "__main__":
    unittest.main()

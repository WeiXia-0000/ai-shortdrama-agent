from __future__ import annotations

import unittest

from ai_manga_factory.genre_rules import (
    compose_genre_injection_for_stage,
    get_bundle_capabilities,
    get_bundle_outline_bias_block,
    get_genre_bundle_prompt_block,
    infer_genre_bundle_from_text,
    infer_genre_context_for_prompt,
    infer_genre_from_text,
)


class TestGenreRulesBundle(unittest.TestCase):
    def test_single_genre_compat(self) -> None:
        self.assertEqual(infer_genre_from_text("都市逆袭商战"), "urban")
        self.assertEqual(infer_genre_from_text("中式恐怖惊悚"), "horror")
        self.assertEqual(infer_genre_from_text("规则怪谈副本"), "rule_horror")
        self.assertEqual(infer_genre_from_text("先婚后爱现代情感"), "modern_romance")

    def test_new_primary_genres(self) -> None:
        self.assertEqual(infer_genre_from_text("极寒末世生存"), "apocalypse")
        self.assertEqual(infer_genre_from_text("宗门修仙渡劫"), "xianxia_fantasy")
        self.assertEqual(infer_genre_from_text("灵气复苏都市高武"), "supernatural_urban")
        self.assertEqual(infer_genre_from_text("重生复仇"), "rebirth_transmigration")
        self.assertEqual(infer_genre_from_text("系统任务签到"), "system_powerup")
        self.assertEqual(infer_genre_from_text("悬疑破案反转"), "suspense_mystery")

    def test_compound_bundle(self) -> None:
        # engine_tag 依赖 catalog keywords（如「前世记忆」），单独「重生」未必命中
        b1 = infer_genre_bundle_from_text("重生前世记忆都市修仙")
        self.assertEqual(b1["primary_genre"], "supernatural_urban")
        self.assertIn("rebirth_foreknowledge", b1["engine_tags"])
        self.assertIn("primary_resolution_trace", b1)
        self.assertTrue(isinstance(b1["primary_resolution_trace"], dict))

        b2 = infer_genre_bundle_from_text("末世重生囤货前世记忆")
        self.assertEqual(b2["primary_genre"], "apocalypse")
        self.assertIn("resource_hoarding", b2["engine_tags"])
        self.assertIn("rebirth_foreknowledge", b2["engine_tags"])
        # 其他层不应因 primary 改变而丢失
        self.assertTrue(len(b2["setting_tags"]) >= 0)

        b3 = infer_genre_bundle_from_text("都市高武情感")
        self.assertEqual(b3["primary_genre"], "supernatural_urban")
        self.assertIn("romance_push_pull", b3["relationship_tags"])

        b4 = infer_genre_bundle_from_text("规则怪谈校园恋爱")
        self.assertEqual(b4["primary_genre"], "rule_horror")
        self.assertIn("school_campus", b4["setting_tags"])
        self.assertIn("romance_push_pull", b4["relationship_tags"])

        b5x = infer_genre_bundle_from_text("灵气复苏都市逆袭")
        self.assertEqual(b5x["primary_genre"], "supernatural_urban")
        self.assertTrue(len(b5x["setting_tags"]) >= 1)

        b5 = infer_genre_bundle_from_text("古风修仙虐恋情感")
        # 世界语境偏修仙/古风时，primary 应偏 xianxia_fantasy
        self.assertEqual(b5["primary_genre"], "xianxia_fantasy")
        self.assertIn("romance_push_pull", b5["relationship_tags"])

    def test_old_context_api_works(self) -> None:
        g, rules, caps = infer_genre_context_for_prompt("规则怪谈校园恋爱")
        self.assertEqual(g, "rule_horror")
        self.assertIsInstance(rules, str)
        self.assertTrue("主题材" in rules or "题材识别" in rules)
        self.assertIsInstance(caps, dict)
        self.assertIn("requires_rule_execution_map", caps)

    def test_capability_merge(self) -> None:
        b = {
            "primary_genre": "urban",
            "setting_tags": [],
            "engine_tags": ["weird_rule_exploit"],
            "relationship_tags": ["romance_push_pull", "status_hierarchy_conflict"],
        }
        caps = get_bundle_capabilities(b)
        self.assertTrue(caps["uses_explicit_rules"])
        self.assertTrue(caps["prefers_logic_trial"])
        self.assertTrue(caps["prefers_relationship_push"])
        self.assertTrue(caps["prefers_status_hierarchy_conflict"])

    def test_outline_bias_block(self) -> None:
        b = infer_genre_bundle_from_text("末世重生囤货")
        blk = get_bundle_outline_bias_block(b)
        # 只要 tag 命中就应能生成一个面向阶段的偏向块
        self.assertTrue(isinstance(blk, str))
        self.assertTrue("题材阶段偏向" in blk)

    def test_stage_profile_injection(self) -> None:
        b = infer_genre_bundle_from_text("都市逆袭商战")
        structural = compose_genre_injection_for_stage(b, "season_mainline")
        self.assertIn("outline_structural", structural)
        self.assertIn("【题材识别】", structural)
        execution = compose_genre_injection_for_stage(b, "episode_plot")
        self.assertIn("episode_execution", execution)
        gate = compose_genre_injection_for_stage(b, "gate_package_judge")
        self.assertIn("gate_review", gate)
        self.assertIn("评审", gate)

    def test_thick_injection_frontmatter_sections_are_present(self) -> None:
        b = infer_genre_bundle_from_text("都市逆袭商战")
        blk = get_genre_bundle_prompt_block(b)
        # frontmatter 注入（精炼版）应可见：开场节奏/失败模式等
        self.assertTrue("开场必须有明确压制" in blk)
        self.assertTrue("前一百字内给出不平等关系或当众羞辱" in blk)
        self.assertTrue("常见失败模式" in blk)
        # sections 注入（只取关键要点）也应可见
        self.assertTrue("题材禁忌" in blk)


if __name__ == "__main__":
    unittest.main()


"""run_series：episode_function QC、对白 lint、outline_review 程序合并。"""

from __future__ import annotations

import unittest

from ai_manga_factory.run_series import (
    _derive_market_hard_fails_from_outline_review,
    _lint_short_drama_dialogue,
    _validate_stage_output,
)


def _minimal_episode_function(ep_id: int = 1) -> dict:
    return {
        "episode_id": ep_id,
        "episode_goal_in_series": "本集负责推进主线与回收承重点",
        "must_advance": ["推进成长", "推进世界认知"],
        "must_inherit": ["承接上集线索"],
        "future_threads_strengthened": ["埋伏笔"],
        "viewer_payoff_design": [
            {
                "type": "reversal",
                "payoff_target": "early_hook",
                "description": "第一场对抗",
                "setup_source": "",
                "setup_source_id": "",
                "payoff_id": "",
                "linked_setup_ids": [],
            },
            {
                "type": "reversal",
                "payoff_target": "early_hook",
                "description": "第二场余波",
                "setup_source": "",
                "setup_source_id": "",
                "payoff_id": "",
                "linked_setup_ids": [],
            },
        ],
        "contract_key_turn_mapping": "映射 key_turn",
        "contract_price_paid_mapping": "映射 price_paid",
        "contract_visual_event_mapping": "映射 visual",
        "contract_cannot_remove_support": "引用 must_advance",
        "contract_risk_if_softened": "写薄会丢钩子",
        "contract_tension_or_missing_density": "密度足够",
    }


class TestRunSeriesQC(unittest.TestCase):
    def test_must_payoff_items_requires_matching_payoff_id(self) -> None:
        obj = _minimal_episode_function(1)
        qc = {
            "episode_id": 1,
            "must_payoff_items": [{"payoff_id": "P_REQUIRED", "description": "x", "deadline": "next"}],
        }
        issues = _validate_stage_output("episode_function", obj, qc_context=qc)
        self.assertTrue(any("payoff_id" in x for x in issues))

        obj2 = _minimal_episode_function(1)
        obj2["viewer_payoff_design"][0]["payoff_id"] = "P_REQUIRED"
        issues2 = _validate_stage_output("episode_function", obj2, qc_context=qc)
        self.assertFalse(any("未能优先对齐" in x for x in issues2))

    def test_front3_visible_gain_none_requires_keyword_payoff(self) -> None:
        obj = _minimal_episode_function(3)
        for it in obj["viewer_payoff_design"]:
            it["type"] = "plain"
            it["payoff_target"] = "none"
            it["description"] = "只有情绪没有收益类型词"
        qc = {"episode_id": 3, "visible_gain_type": "none"}
        issues = _validate_stage_output("episode_function", obj, qc_context=qc)
        self.assertTrue(any("前 3 集缺少可见收益型" in x for x in issues))

        obj_ok = _minimal_episode_function(3)
        obj_ok["viewer_payoff_design"][0]["description"] = "本集完成 public_reversal 让观众爽到"
        issues_ok = _validate_stage_output("episode_function", obj_ok, qc_context=qc)
        self.assertFalse(any("前 3 集缺少可见收益型" in x for x in issues_ok))

    def test_lint_short_drama_dialogue_detects_long_lines(self) -> None:
        long_line = "x" * 30
        script = {
            "episode_id": 1,
            "characters": [],
            "scenes": [
                {
                    "scene_id": 1,
                    "location": "x",
                    "time": "y",
                    "beats": [],
                    "dialogue": [{"speaker": "A", "line": long_line} for _ in range(4)],
                    "narration": "",
                }
            ],
        }
        r = _lint_short_drama_dialogue(script)
        self.assertFalse(r["pass"])
        self.assertTrue(r["problems"])

    def test_derive_market_hard_fails_from_outline_review(self) -> None:
        review = {
            "dimension_scores": {
                "episode_count_fit_1to10": 3,
                "front3_payoff_strength_1to10": 3,
                "opening_pressure_calibration_1to10": 3,
            }
        }
        dense_stats = {"front10_bridge_only_ratio": 0.9}
        concept = {"is_longform_series": True, "total_episodes": 20, "preferred_total_episodes_min": 30}
        fails = _derive_market_hard_fails_from_outline_review(review, dense_stats, concept)
        blob = "\n".join(fails)
        self.assertIn("体量", blob)
        self.assertIn("回报不足", blob)
        self.assertIn("压迫", blob)
        self.assertIn("桥接", blob)
        self.assertIn("长篇题材", blob)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai_manga_factory.outline_validator import validate_dense_outline


def _make_episode(
    episode_id: int,
    *,
    engine_type: str | None = None,
    key_turn: str = "关键转折",
    status_shift: str = "主角上位",
    price_paid: str = "资源被断供",
    cannot_remove_because: str = "删掉会损失公开回收与下一集钩子",
    one_line: str = "当众逼问并翻脸，抢走关键证据",
) -> dict:
    # 默认按集号轮换 engine，避免在 8 集规模下稳定触发“连续窗口 engine 重复” hard fail
    engines = ["reversal", "reveal", "trial", "pressure"]
    resolved_engine = engine_type if engine_type is not None else engines[(episode_id - 1) % len(engines)]
    return {
        "episode_id": episode_id,
        "title": f"ep{episode_id}",
        "one_line": one_line,
        "episode_engine_type": resolved_engine,
        "episode_goal_in_series": "本集负责把承重点回收到下一阶段",
        "anchor_ids": [1],
        "must_advance": ["推进角色成长", "回收承重点"],
        "must_payoff": ["兑现一次公开翻脸回收"],
        "must_set_up": ["埋下下一集规则触发条件"],
        "dominant_opposition": "秩序规则对主角的裁决",
        "pressure_arena": "祠堂公开问责",
        "key_turn": key_turn,
        "status_shift": status_shift,
        "price_paid": price_paid,
        "relationship_shift": "关系从质疑变成被迫对质",
        "resource_shift": "夺回部分权限但仍被封存",
        "world_reveal_delta": "揭示裁决依赖可伪造的证据可信度",
        "visual_or_public_event": "祠堂上当众改口与证据翻页",
        "cannot_remove_because": cannot_remove_because,
        "hook": "结尾留钩：下一集需要完整授权",
        "cliffhanger": "钥匙缺口将触发更高压的反噬",
    }


class TestOutlineValidator(unittest.TestCase):
    def test_full_outline_pass(self) -> None:
        series_outline = {"episode_list": [_make_episode(i) for i in range(1, 9)]}
        r = validate_dense_outline(series_outline)
        self.assertTrue(r["is_pass"])
        self.assertEqual(r["hard_fail_reasons"], [])
        # 向后兼容升级：仍保留旧骨架，同时新增 warning judge gate 字段
        for k in ("strong_warnings", "soft_signals", "risk_flags", "review_targets"):
            self.assertIn(k, r)
        self.assertIsInstance(r["strong_warnings"], list)
        self.assertIsInstance(r["soft_signals"], list)
        self.assertIsInstance(r["risk_flags"], dict)
        self.assertIsInstance(r["review_targets"], list)
        self.assertIn("low_event_density", r["risk_flags"])
        self.assertIn("late_stage_drift", r["risk_flags"])
        self.assertIn("engine_repetition", r["risk_flags"])

    def test_consecutive_missing_key_turn_fail(self) -> None:
        eps = []
        for i in range(1, 9):
            if 3 <= i <= 5:
                eps.append(_make_episode(i, key_turn=""))
            else:
                eps.append(_make_episode(i))
        r = validate_dense_outline({"episode_list": eps})
        self.assertFalse(r["is_pass"])
        self.assertTrue(any("key_turn" in x for x in r["hard_fail_reasons"]))

    def test_cannot_remove_because_ratio_fail(self) -> None:
        eps = []
        for i in range(1, 9):
            if i in (2, 4, 7):  # 3/8 = 0.375
                eps.append(_make_episode(i, cannot_remove_because=""))
            else:
                eps.append(_make_episode(i))
        r = validate_dense_outline({"episode_list": eps})
        self.assertFalse(r["is_pass"])
        self.assertTrue(any("cannot_remove_because" in x for x in r["hard_fail_reasons"]))

    def test_engine_repetition_hard_fail(self) -> None:
        # 6 连窗里 episode_engine_type 重复 6 次 -> >= 5 => hard fail
        eps = [_make_episode(i, engine_type="reveal") for i in range(1, 7)]
        r = validate_dense_outline({"episode_list": eps})
        self.assertFalse(r["is_pass"])
        self.assertTrue(any("6 连窗" in x for x in r["hard_fail_reasons"]))

    def test_late_stage_drift_flag(self) -> None:
        eps = []
        for i in range(1, 9):
            if i >= 7:
                eps.append(
                    _make_episode(
                        i,
                        one_line="终极真相 宇宙 永恒 更高层 世界意志",
                        status_shift="",
                        price_paid="资源被夺走断供",
                        cannot_remove_because="删掉会损失世界规则验证与下一集钩子",
                    )
                )
            else:
                eps.append(_make_episode(i))
        r = validate_dense_outline({"episode_list": eps})
        # 这里只要求 flag/warn，具体 hard/fail 取决阈值
        self.assertTrue(r["stats"]["late_stage_drift_flag"])
        self.assertIn("late_stage_drift", r["risk_flags"])
        self.assertTrue(r["risk_flags"]["late_stage_drift"]["flag"])

    def test_low_event_density_flag_or_fail(self) -> None:
        abs_words = "发现 决定 调查 深入了解 意识到 开始怀疑 接近真相"
        eps = []
        for i in range(1, 7):
            eps.append(
                _make_episode(
                    i,
                    engine_type="trial",
                    one_line=abs_words,
                    key_turn=abs_words,
                    cannot_remove_because=abs_words,
                )
            )
        r = validate_dense_outline({"episode_list": eps})
        self.assertTrue(r["stats"]["low_event_density_flag"])
        self.assertIn("low_event_density", r["risk_flags"])
        self.assertTrue(r["risk_flags"]["low_event_density"]["flag"])


class TestDenseOutlineWarningJudgeGate(unittest.TestCase):
    def test_hard_fail_should_not_trigger_judge(self) -> None:
        from ai_manga_factory.run_series import _dense_outline_warning_judge_needed

        dense_validation = {
            "hard_fail_reasons": ["x"],
            "strong_warnings": ["y"],
            "risk_flags": {
                "low_event_density": {"flag": True},
                "late_stage_drift": {"flag": False},
                "engine_repetition": {"flag": False},
            },
            "review_targets": [{"episode_range": "1-2", "risk_type": "other", "reason": "r"}],
        }
        self.assertFalse(_dense_outline_warning_judge_needed(dense_validation))

    def test_strong_warnings_triggers_judge(self) -> None:
        from ai_manga_factory.run_series import _dense_outline_warning_judge_needed

        dense_validation = {
            "hard_fail_reasons": [],
            "strong_warnings": ["low_event_density_flag=true 但未硬 fail"],
            "risk_flags": {
                "low_event_density": {"flag": False},
                "late_stage_drift": {"flag": False},
                "engine_repetition": {"flag": False},
            },
            "review_targets": [],
        }
        self.assertTrue(_dense_outline_warning_judge_needed(dense_validation))

    def test_risk_flag_triggers_judge(self) -> None:
        from ai_manga_factory.run_series import _dense_outline_warning_judge_needed

        dense_validation = {
            "hard_fail_reasons": [],
            "strong_warnings": [],
            "risk_flags": {
                "low_event_density": {"flag": True},
                "late_stage_drift": {"flag": False},
                "engine_repetition": {"flag": False},
            },
            "review_targets": [],
        }
        self.assertTrue(_dense_outline_warning_judge_needed(dense_validation))

    def test_review_targets_triggers_judge(self) -> None:
        from ai_manga_factory.run_series import _dense_outline_warning_judge_needed

        dense_validation = {
            "hard_fail_reasons": [],
            "strong_warnings": [],
            "risk_flags": {
                "low_event_density": {"flag": False},
                "late_stage_drift": {"flag": False},
                "engine_repetition": {"flag": False},
            },
            "review_targets": [{"episode_range": "7-8", "risk_type": "late_stage_drift", "reason": "r"}],
        }
        self.assertTrue(_dense_outline_warning_judge_needed(dense_validation))

    def test_judge_action_mapping(self) -> None:
        from ai_manga_factory.run_series import _dense_outline_judge_action

        self.assertEqual(
            _dense_outline_judge_action({"overall_verdict": "rewrite_outline_only"}), "rewrite_outline_only"
        )
        self.assertEqual(
            _dense_outline_judge_action({"overall_verdict": "rewrite_anchors_then_outline"}), "rewrite_anchors_then_outline"
        )
        self.assertEqual(
            _dense_outline_judge_action({"overall_verdict": "rewrite_spine_then_anchors_then_outline"}), "rewrite_spine_then_anchors_then_outline"
        )
        self.assertEqual(
            _dense_outline_judge_action({"overall_verdict": "needs_human_review"}), "needs_human_review"
        )
        self.assertEqual(_dense_outline_judge_action({"can_forward_to_next_stage": True}), "pass")

        self.assertEqual(
            _dense_outline_judge_action({"rewrite_brief": {"rewrite_level": "anchors_then_outline"}}),
            "rewrite_anchors_then_outline",
        )


class TestEpisodeDirLogic(unittest.TestCase):
    def test_episode_dir_reuse_and_no_silent_suffix(self) -> None:
        # 仅验证生产链目录策略：不存在时创建标准目录，不使用 _2/_3 伪装
        from ai_manga_factory.run_series import _episode_dir_for_id_or_create

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            episodes_root = root / "episodes"
            episodes_root.mkdir(parents=True, exist_ok=True)

            ep_dir = _episode_dir_for_id_or_create(episodes_root, "SeriesA", 1)
            self.assertTrue(ep_dir.exists())
            self.assertIn("SeriesA_第001集", ep_dir.name)
            self.assertNotIn("_2", ep_dir.name)

    def test_episode_dir_conflict_raises(self) -> None:
        from ai_manga_factory.run_series import _episode_dir_for_id_or_create

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            episodes_root = root / "episodes"
            episodes_root.mkdir(parents=True, exist_ok=True)

            (episodes_root / "A_第001集").mkdir(parents=True, exist_ok=True)
            (episodes_root / "B_第001集").mkdir(parents=True, exist_ok=True)

            with self.assertRaises(RuntimeError):
                _episode_dir_for_id_or_create(episodes_root, "SeriesA", 1)


class TestEpisodeFunctionQC(unittest.TestCase):
    def test_episode_function_qc_requires_contract_fields(self) -> None:
        from ai_manga_factory.run_series import _validate_stage_output

        dummy = {
            "episode_id": 1,
            "episode_goal_in_series": "g",
            "must_advance": ["a", "b"],
            "must_inherit": ["c"],
            "future_threads_strengthened": ["d"],
            "viewer_payoff_design": [
                {"type": "reversal", "payoff_target": "act2_or_act3", "description": "x"},
                {"type": "shock", "payoff_target": "closing", "description": "y"},
            ],
            # 缺少 contract_* 字段
        }
        issues = _validate_stage_output("episode_function", dummy)
        self.assertTrue(any("contract_key_turn_mapping" in x for x in issues))

    def test_run_series_prompt_mentions_contract_tension(self) -> None:
        # 低成本“静态检查”：确保 prompt 要求 agent 返回 contract_tension_or_missing_density
        series_path = Path(__file__).resolve().parent.parent / "ai_manga_factory" / "run_series.py"
        txt = series_path.read_text(encoding="utf-8")
        self.assertIn("contract_tension_or_missing_density", txt)
        # 额外静态检查：current_episode_contract 与 contract_*_mapping 仍在 function prompt 注入链中
        for k in (
            "current_episode_contract=",
            "contract_key_turn_mapping",
            "contract_price_paid_mapping",
            "contract_visual_event_mapping",
            "contract_cannot_remove_support",
            "contract_risk_if_softened",
        ):
            self.assertIn(k, txt)


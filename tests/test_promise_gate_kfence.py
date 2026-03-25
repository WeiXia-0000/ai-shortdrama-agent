"""promise 状态、knowledge_fence 刷新、gate 指纹与人工 override。"""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from ai_manga_factory.carry_registry import (
    apply_promise_manual_overrides,
    build_empty_shell,
    save_registry,
    validate_registry,
)
from ai_manga_factory.carry_structured_refresh import (
    refresh_knowledge_fence_minimal,
    refresh_promise_lane_structured,
)
from ai_manga_factory.gate_artifacts import append_gate_entry, build_gate_trend_summary


def _meta() -> dict:
    return {
        "provenance": "test",
        "last_updated_by": "test",
        "last_updated_at": "2099-01-01T00:00:00Z",
    }


class TestPromiseTransitions(unittest.TestCase):
    def tearDown(self) -> None:
        shutil.rmtree(Path(__file__).resolve().parent / "_tmp_pgk", ignore_errors=True)

    def test_paid_off_from_longterm_and_evidence(self) -> None:
        root = Path(__file__).resolve().parent / "_tmp_pgk" / "paid"
        root.mkdir(parents=True)
        (root / "L4_episodes").mkdir(parents=True)
        ep = root / "L4_episodes" / "T_第001集"
        ep.mkdir(parents=True)
        (root / "L3_series").mkdir(parents=True)
        reg_path = root / "L3_series" / "03b_production_carry_registry.json"
        shell = build_empty_shell(series_slug="t", display_title="T")
        save_registry(reg_path, shell)
        paths = {
            "episodes_root": root / "L4_episodes",
            "series_dir": root,
            "series_outline": root / "L3_series" / "01_series_outline.json",
            "character_bible": root / "L3_series" / "02_character_bible.json",
            "series_memory": root / "L3_series" / "03_series_memory.json",
            "production_carry_registry": reg_path,
        }
        desc = "主角必须在决赛前找回信物"
        (ep / "01_episode_function.json").write_text(
            json.dumps(
                {
                    "viewer_payoff_design": [
                        {
                            "type": "hook",
                            "description": desc,
                            "setup_source": "初赛",
                            "payoff_target": "决赛前",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (ep / "02_plot.json").write_text(
            json.dumps(
                {
                    "logic_check": {
                        "what_new_longterm_change_is_created": "回收闭环：主角必须在决赛前找回信物，已落实成立",
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        refresh_promise_lane_structured(
            reg, paths=paths, layout="layered", source="test", meta_row=_meta()
        )
        prs = reg["promise_lane"]["promises"]
        self.assertTrue(prs)
        self.assertEqual(prs[0]["status"], "paid_off")

    def test_stale_window(self) -> None:
        root = Path(__file__).resolve().parent / "_tmp_pgk" / "stale"
        root.mkdir(parents=True)
        (root / "L4_episodes").mkdir(parents=True)
        (root / "L3_series").mkdir(parents=True)
        reg_path = root / "L3_series" / "03b_production_carry_registry.json"
        save_registry(reg_path, build_empty_shell(series_slug="t", display_title="T"))
        paths = {
            "episodes_root": root / "L4_episodes",
            "series_dir": root,
            "series_outline": root / "L3_series" / "01_series_outline.json",
            "character_bible": root / "L3_series" / "02_character_bible.json",
            "series_memory": root / "L3_series" / "03_series_memory.json",
            "production_carry_registry": reg_path,
        }
        ep1 = root / "L4_episodes" / "T_第001集"
        ep1.mkdir(parents=True)
        (ep1 / "01_episode_function.json").write_text(
            json.dumps(
                {
                    "viewer_payoff_design": [
                        {"type": "hook", "description": "一条长期未再出现的承诺X" * 2}
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (ep1 / "02_plot.json").write_text("{}", encoding="utf-8")
        for n in range(2, 9):
            ep = root / "L4_episodes" / f"T_第{n:03d}集"
            ep.mkdir(parents=True)
            (ep / "01_episode_function.json").write_text("{}", encoding="utf-8")
            (ep / "02_plot.json").write_text("{}", encoding="utf-8")
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        refresh_promise_lane_structured(
            reg, paths=paths, layout="layered", source="test", meta_row=_meta()
        )
        st = {p["status"] for p in reg["promise_lane"]["promises"]}
        self.assertIn("stale", st)

    def test_broken_explicit(self) -> None:
        root = Path(__file__).resolve().parent / "_tmp_pgk" / "broken"
        root.mkdir(parents=True)
        (root / "L4_episodes").mkdir(parents=True)
        (root / "L3_series").mkdir(parents=True)
        reg_path = root / "L3_series" / "03b_production_carry_registry.json"
        save_registry(reg_path, build_empty_shell(series_slug="t", display_title="T"))
        paths = {
            "episodes_root": root / "L4_episodes",
            "series_dir": root,
            "series_outline": root / "L3_series" / "01_series_outline.json",
            "character_bible": root / "L3_series" / "02_character_bible.json",
            "series_memory": root / "L3_series" / "03_series_memory.json",
            "production_carry_registry": reg_path,
        }
        ep1 = root / "L4_episodes" / "T_第001集"
        ep1.mkdir(parents=True)
        (ep1 / "01_episode_function.json").write_text(
            json.dumps(
                {
                    "viewer_payoff_design": [
                        {"description": "反派与主角的同盟关系必须维持到终局"}
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (ep1 / "02_plot.json").write_text("{}", encoding="utf-8")
        ep2 = root / "L4_episodes" / "T_第002集"
        ep2.mkdir(parents=True)
        (ep2 / "01_episode_function.json").write_text("{}", encoding="utf-8")
        (ep2 / "02_plot.json").write_text(
            json.dumps(
                {
                    "logic_check": "主角与反派公开决裂，反派与主角的同盟关系无法维持到终局"
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        refresh_promise_lane_structured(
            reg, paths=paths, layout="layered", source="test", meta_row=_meta()
        )
        st = [p["status"] for p in reg["promise_lane"]["promises"]]
        self.assertIn("broken", st)

    def test_manual_override(self) -> None:
        root = Path(__file__).resolve().parent / "_tmp_pgk" / "manual"
        root.mkdir(parents=True)
        (root / "L4_episodes").mkdir(parents=True)
        (root / "L3_series").mkdir(parents=True)
        reg_path = root / "L3_series" / "03b_production_carry_registry.json"
        save_registry(reg_path, build_empty_shell(series_slug="t", display_title="T"))
        paths = {
            "episodes_root": root / "L4_episodes",
            "series_dir": root,
            "series_outline": root / "L3_series" / "01_series_outline.json",
            "character_bible": root / "L3_series" / "02_character_bible.json",
            "series_memory": root / "L3_series" / "03_series_memory.json",
            "production_carry_registry": reg_path,
        }
        ep = root / "L4_episodes" / "T_第001集"
        ep.mkdir(parents=True)
        (ep / "01_episode_function.json").write_text(
            json.dumps(
                {"viewer_payoff_design": [{"description": "人工标记测试承诺"}]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (ep / "02_plot.json").write_text("{}", encoding="utf-8")
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        refresh_promise_lane_structured(
            reg, paths=paths, layout="layered", source="test", meta_row=_meta()
        )
        pid = reg["promise_lane"]["promises"][0]["promise_id"]
        save_registry(reg_path, reg)
        apply_promise_manual_overrides(
            paths,
            patch={
                "overrides": [
                    {
                        "promise_id": pid,
                        "status": "paid_off",
                        "resolved_episode": 9,
                        "manual_status_lock": True,
                    }
                ],
                "updated_by": "test_human",
            },
        )
        reg2 = json.loads(reg_path.read_text(encoding="utf-8"))
        row = reg2["promise_lane"]["promises"][0]
        self.assertEqual(row["status"], "paid_off")
        self.assertTrue(row.get("manual_status_lock"))
        self.assertEqual(row.get("resolved_episode"), 9)
        self.assertEqual(row.get("provenance"), "manual:promise_override")
        refresh_promise_lane_structured(
            reg2, paths=paths, layout="layered", source="refr", meta_row=_meta()
        )
        row2 = next(p for p in reg2["promise_lane"]["promises"] if p["promise_id"] == pid)
        self.assertEqual(row2["status"], "paid_off")


class TestGateFingerprint(unittest.TestCase):
    def tearDown(self) -> None:
        shutil.rmtree(Path(__file__).resolve().parent / "_tmp_pgk_fp", ignore_errors=True)

    def test_repeated_failure_same_signature(self) -> None:
        root = Path(__file__).resolve().parent / "_tmp_pgk_fp"
        root.mkdir(parents=True)
        er = root / "eps"
        er.mkdir(parents=True)
        ep_dir = er / "X_第001集"
        ep_dir.mkdir(parents=True)
        gr = {"pass": False, "summary": "结构问题", "must_fix": ["节奏断裂"], "issues": []}
        append_gate_entry(
            episodes_root=er,
            ep_dir=ep_dir,
            layout="layered",
            episode_id=1,
            gate_type="plot_gate",
            gate_result=gr,
            generator="t",
            source_inputs={},
        )
        append_gate_entry(
            episodes_root=er,
            ep_dir=ep_dir,
            layout="layered",
            episode_id=1,
            gate_type="plot_gate",
            gate_result=dict(gr),
            generator="t",
            source_inputs={},
        )
        doc = json.loads((ep_dir / "07_gate_artifacts.json").read_text(encoding="utf-8"))
        e0, e1 = doc["entries"][0], doc["entries"][1]
        self.assertEqual(e0["failure_signature"], e1["failure_signature"])
        self.assertTrue(doc["trend_summary"].get("repeated_same_failure_as_immediate_previous"))
        ts = build_gate_trend_summary(doc)
        self.assertEqual(ts.get("failure_trend_label"), "repeated_same_failure")
        self.assertIn("latest_verdict", ts)


class TestKnowledgeFence(unittest.TestCase):
    def tearDown(self) -> None:
        shutil.rmtree(Path(__file__).resolve().parent / "_tmp_kf", ignore_errors=True)

    def test_minimal_facts_validate(self) -> None:
        root = Path(__file__).resolve().parent / "_tmp_kf"
        root.mkdir(parents=True)
        (root / "L4_episodes").mkdir(parents=True)
        (root / "L3_series").mkdir(parents=True)
        (root / "L3_series" / "02_character_bible.json").write_text(
            json.dumps({"main_characters": [{"name": "主角"}, {"name": "配角"}]}, ensure_ascii=False),
            encoding="utf-8",
        )
        reg_path = root / "L3_series" / "03b_production_carry_registry.json"
        shell = build_empty_shell(series_slug="t", display_title="T")
        save_registry(reg_path, shell)
        ep = root / "L4_episodes" / "T_第001集"
        ep.mkdir(parents=True)
        (ep / "01_episode_function.json").write_text(
            json.dumps(
                {
                    "what_is_learned": ["主角知道了密室口令"],
                    "what_is_mislearned": ["观众以为反派已死"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (ep / "02_plot.json").write_text(
            json.dumps({"logic_check": {"note": "规则层未闭合"}}, ensure_ascii=False),
            encoding="utf-8",
        )
        (root / "L3_series" / "03_series_memory.json").write_text(
            json.dumps(
                {"episodes": [{"episode_id": 1, "knowledge_delta": "观众知悉真凶身份"}]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        paths = {
            "episodes_root": root / "L4_episodes",
            "series_dir": root,
            "character_bible": root / "L3_series" / "02_character_bible.json",
            "series_memory": root / "L3_series" / "03_series_memory.json",
            "production_carry_registry": reg_path,
        }
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        refresh_knowledge_fence_minimal(
            reg, paths=paths, layout="layered", source="test", meta_row=_meta()
        )
        self.assertTrue(reg["knowledge_fence"]["facts"])
        learned_rows = [
            f
            for f in reg["knowledge_fence"]["facts"]
            if any((r.get("kind") == "episode_function.what_is_learned") for r in (f.get("source_refs") or []))
        ]
        self.assertTrue(learned_rows)
        self.assertEqual(learned_rows[0].get("known_by"), ["主角"])
        aud = [f for f in reg["knowledge_fence"]["facts"] if f.get("visibility") == "audience_only"]
        self.assertTrue(aud)
        self.assertEqual(aud[0].get("known_by"), [])
        self.assertEqual(validate_registry(reg), [])

    def test_ambiguous_two_names_skips_known_by(self) -> None:
        root = Path(__file__).resolve().parent / "_tmp_kf"
        root.mkdir(parents=True)
        (root / "L4_episodes").mkdir(parents=True)
        (root / "L3_series").mkdir(parents=True)
        (root / "L3_series" / "02_character_bible.json").write_text(
            json.dumps({"main_characters": [{"name": "主角"}, {"name": "配角"}]}, ensure_ascii=False),
            encoding="utf-8",
        )
        reg_path = root / "L3_series" / "03b_production_carry_registry.json"
        save_registry(reg_path, build_empty_shell(series_slug="t", display_title="T"))
        ep = root / "L4_episodes" / "T_第001集"
        ep.mkdir(parents=True)
        (ep / "01_episode_function.json").write_text(
            json.dumps(
                {"what_is_learned": ["主角与配角同时确认了交易内容"]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (ep / "02_plot.json").write_text("{}", encoding="utf-8")
        paths = {
            "episodes_root": root / "L4_episodes",
            "series_dir": root,
            "character_bible": root / "L3_series" / "02_character_bible.json",
            "series_memory": root / "L3_series" / "03_series_memory.json",
            "production_carry_registry": reg_path,
        }
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        refresh_knowledge_fence_minimal(
            reg, paths=paths, layout="layered", source="test", meta_row=_meta()
        )
        row = reg["knowledge_fence"]["facts"][0]
        self.assertEqual(row.get("known_by"), [])


class TestPromiseSupersedes(unittest.TestCase):
    def tearDown(self) -> None:
        shutil.rmtree(Path(__file__).resolve().parent / "_tmp_sup", ignore_errors=True)

    def test_supersedes_marks_stale(self) -> None:
        root = Path(__file__).resolve().parent / "_tmp_sup"
        root.mkdir(parents=True)
        (root / "L3_series").mkdir(parents=True)
        reg_path = root / "L3_series" / "03b_production_carry_registry.json"
        reg = build_empty_shell(series_slug="t", display_title="T")
        reg["promise_lane"] = {
            "promises": [
                {"promise_id": "p_old", "status": "open", "compound_key": "a", "linked_anchor_ids": []},
                {"promise_id": "p_new", "status": "open", "compound_key": "b", "linked_anchor_ids": []},
            ]
        }
        save_registry(reg_path, reg)
        paths = {
            "series_dir": root,
            "production_carry_registry": reg_path,
            "character_bible": root / "L3_series" / "02_character_bible.json",
            "series_memory": root / "L3_series" / "03_series_memory.json",
            "episodes_root": root / "L4_episodes",
        }
        paths["character_bible"].write_text('{"main_characters":[]}', encoding="utf-8")
        paths["series_memory"].write_text("{}", encoding="utf-8")
        (paths["episodes_root"]).mkdir(parents=True)

        from ai_manga_factory.carry_registry import apply_promise_manual_overrides

        apply_promise_manual_overrides(
            paths,
            patch={
                "supersedes": [
                    {"old_promise_id": "p_old", "new_promise_id": "p_new", "note": "人工改线"}
                ],
                "updated_by": "test",
            },
        )
        reg2 = json.loads(reg_path.read_text(encoding="utf-8"))
        olds = [p for p in reg2["promise_lane"]["promises"] if p["promise_id"] == "p_old"][0]
        self.assertEqual(olds["status"], "stale")
        self.assertEqual(olds.get("superseded_by_promise_id"), "p_new")
        self.assertEqual(olds.get("override_source"), "patch_json:supersedes")


if __name__ == "__main__":
    unittest.main()

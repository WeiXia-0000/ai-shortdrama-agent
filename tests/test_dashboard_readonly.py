"""只读 dashboard 数据层：缺文件、空数据不崩。"""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from ai_manga_factory.carry_registry import SCHEMA_VERSION, build_empty_shell, save_registry
from ai_manga_factory.dashboard_readonly import (
    build_dashboard_payload,
    load_registry_readonly,
    validate_payload_minimal,
)
from ai_manga_factory.gate_artifacts import append_gate_entry


class TestDashboardReadonly(unittest.TestCase):
    def tearDown(self) -> None:
        root = Path(__file__).resolve().parent / "_tmp_dash_ro"
        shutil.rmtree(root, ignore_errors=True)

    def test_empty_series_dir_graceful(self) -> None:
        root = Path(__file__).resolve().parent / "_tmp_dash_ro" / "empty"
        root.mkdir(parents=True)
        payload = build_dashboard_payload(root)
        self.assertEqual(payload.get("schema"), "dashboard_readonly.v1")
        self.assertEqual(validate_payload_minimal(payload), [])
        self.assertEqual(payload["episodes"], [])
        self.assertIn("episode_details", payload)
        self.assertEqual(payload["episode_details"], {})
        self.assertIn("character_details", payload)
        self.assertEqual(payload["character_details"], {})
        self.assertEqual(payload["promises"]["summary_counts"].get("open"), 0)
        self.assertEqual(payload["knowledge_fence"]["stats"]["total"], 0)
        self.assertEqual(payload["visual_lock"]["counts"]["complete"], 0)

    def test_registry_loose_json_and_promises(self) -> None:
        root = Path(__file__).resolve().parent / "_tmp_dash_ro" / "loose"
        (root / "L3_series").mkdir(parents=True)
        reg_path = root / "L3_series" / "03b_production_carry_registry.json"
        bad = {
            "schema_version": SCHEMA_VERSION,
            "series_identity": {"series_slug": "x", "display_title": "T", "genre_key": "general"},
            "sync_meta": {},
            "story_thrust": {"drift_flag": False},
            "asset_ledger": {"items": []},
            "promise_lane": {
                "promises": [
                    {
                        "promise_id": "p1",
                        "status": "stale",
                        "description": "d",
                        "created_episode": 1,
                        "last_seen_episode": 1,
                        "linked_episode_ids": [1],
                    },
                    {
                        "promise_id": "p2",
                        "status": "broken",
                        "description": "b",
                        "created_episode": 2,
                        "last_seen_episode": 2,
                        "override_reason": "人工",
                    },
                ]
            },
            "relation_pressure_map": {"relations": []},
            "knowledge_fence": {
                "facts": [
                    {
                        "fact_id": "f1",
                        "fact_text": "低置信",
                        "confidence": "low",
                        "visibility": "character",
                        "first_seen_episode": 1,
                        "last_seen_episode": 1,
                    },
                    {
                        "fact_text": "观众知",
                        "confidence": "high",
                        "visibility": "audience_only",
                        "first_seen_episode": 1,
                        "last_seen_episode": 1,
                    },
                ]
            },
            "visual_lock_registry": {
                "characters": [
                    {"cast_id": "a", "display_name": "A", "lock_status": "complete"},
                    {"cast_id": "b", "display_name": "B", "lock_status": "partial"},
                ]
            },
        }
        reg_path.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
        (root / "L3_series" / "01_series_outline.json").write_text(
            json.dumps({"title": "测剧", "episode_list": [{"id": 1}, {"id": 2}]}, ensure_ascii=False),
            encoding="utf-8",
        )

        payload = build_dashboard_payload(root)
        self.assertGreaterEqual(payload["knowledge_fence"]["stats"]["low_confidence"], 1)
        self.assertGreaterEqual(payload["knowledge_fence"]["stats"]["audience_only"], 1)
        self.assertEqual(payload["promises"]["summary_counts"]["stale"], 1)
        self.assertEqual(payload["promises"]["summary_counts"]["broken"], 1)
        self.assertGreaterEqual(payload["promises"]["manual_override_count"], 1)

    def test_gate_rows_without_crash(self) -> None:
        root = Path(__file__).resolve().parent / "_tmp_dash_ro" / "gate"
        (root / "L3_series").mkdir(parents=True)
        (root / "L3_series" / "01_series_outline.json").write_text(
            json.dumps({"title": "G"}, ensure_ascii=False), encoding="utf-8"
        )
        shell = build_empty_shell(series_slug="g", display_title="G")
        save_registry(root / "L3_series" / "03b_production_carry_registry.json", shell)

        ep_root = root / "L4_episodes"
        ep_dir = ep_root / "G_第001集"
        ep_dir.mkdir(parents=True)
        (ep_dir / "01_episode_function.json").write_text("{}", encoding="utf-8")

        append_gate_entry(
            episodes_root=ep_root,
            ep_dir=ep_dir,
            layout="layered",
            episode_id=1,
            gate_type="plot_gate",
            gate_result={"pass": False, "overall_score_1to10": 3, "summary": "fail", "issues": [], "must_fix": ["x"]},
            generator="t",
            source_inputs={},
        )

        payload = build_dashboard_payload(root)
        self.assertEqual(len(payload["episodes"]), 1)
        ep = payload["episodes"][0]
        self.assertEqual(ep["episode_id"], 1)
        self.assertFalse(ep["plot_gate_pass"])
        self.assertTrue(ep.get("repeated_failure_active") in (True, False))
        self.assertIn("episode_details", payload)
        self.assertIn("1", payload["episode_details"])
        d = payload["episode_details"]["1"]
        self.assertIn("header", d)
        self.assertIn("story_summary", d)
        self.assertIn("key_turns", d)
        self.assertIn("story_script_detail", d)
        self.assertIn("promise_snapshot", d)
        self.assertIn("knowledge_snapshot", d)
        self.assertIn("visual_snapshot", d)
        self.assertIn("gate_snapshot", d)
        self.assertIn("artifacts_presence", d)
        self.assertIn("character_details", payload)

    def test_load_registry_readonly_missing(self) -> None:
        root = Path(__file__).resolve().parent / "_tmp_dash_ro" / "nom"
        root.mkdir(parents=True)
        (root / "L3_series").mkdir(exist_ok=True)
        p = root / "L3_series" / "03b_production_carry_registry.json"
        reg, warns, ok = load_registry_readonly(p, root)
        self.assertFalse(ok)
        self.assertTrue(warns)
        self.assertIn("promise_lane", reg)


if __name__ == "__main__":
    unittest.main()

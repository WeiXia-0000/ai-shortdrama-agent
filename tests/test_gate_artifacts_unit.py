"""gate artifact 落盘与 query 摘要（无 LLM）。"""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from ai_manga_factory.gate_artifacts import (
    append_gate_entry,
    load_gate_artifact,
    summarize_gate_artifact,
    validate_gate_artifact_location,
)
from ai_manga_factory.studio_operations import _run_query_gate_status


class TestGateArtifacts(unittest.TestCase):
    def tearDown(self) -> None:
        root = Path(__file__).resolve().parent / "_tmp_gate_art_unit"
        shutil.rmtree(root, ignore_errors=True)

    def test_append_summarize_and_query(self) -> None:
        root = Path(__file__).resolve().parent / "_tmp_gate_art_unit"
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
        (root / "L3_series").mkdir(parents=True)
        (root / "L3_series" / "01_series_outline.json").write_text(
            json.dumps({"title": "测"}, ensure_ascii=False),
            encoding="utf-8",
        )
        ep_root = root / "L4_episodes"
        ep_dir = ep_root / "测_第001集"
        ep_dir.mkdir(parents=True)

        append_gate_entry(
            episodes_root=ep_root,
            ep_dir=ep_dir,
            layout="layered",
            episode_id=1,
            gate_type="plot_gate",
            gate_result={
                "pass": True,
                "overall_score_1to10": 7,
                "summary": "结构可接受",
                "issues": ["a"],
                "must_fix": [],
            },
            generator="episode_plot_judge_agent",
            source_inputs={"plot": str(ep_dir / "02_plot.json")},
        )
        append_gate_entry(
            episodes_root=ep_root,
            ep_dir=ep_dir,
            layout="layered",
            episode_id=1,
            gate_type="package_gate",
            gate_result={
                "pass": False,
                "overall_score_1to10": 4,
                "summary": "需修",
                "issues": [],
                "must_fix": ["x"],
            },
            generator="episode_package_judge_agent",
            source_inputs={"package": str(ep_dir / "06_package.json")},
        )

        doc = load_gate_artifact(ep_dir, "layered")
        summ = summarize_gate_artifact(doc)
        self.assertEqual(summ["episode_id"], 1)
        self.assertIsNotNone(summ["latest_plot_gate"])
        self.assertIsNotNone(summ["latest_package_gate"])
        self.assertEqual(summ["latest_plot_gate"]["gate_type"], "plot_gate")
        self.assertEqual(summ["latest_package_gate"]["gate_type"], "package_gate")
        self.assertEqual(summ["total_entries"], 2)
        self.assertIn("trend_summary", summ)
        self.assertEqual(summ["trend_summary"]["total_entries"], 2)

        out = _run_query_gate_status(root, 1)
        self.assertIsNone(out.get("error"), msg=str(out))
        self.assertTrue(out.get("artifact_exists"))
        self.assertEqual(out["summary"]["total_entries"], 2)
        self.assertIsNotNone(out.get("trend_summary"))

    def test_validate_rejects_bad_path(self) -> None:
        root = Path(__file__).resolve().parent / "_tmp_gate_art_unit"
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
        ep_root = root / "L4_episodes"
        ep_root.mkdir(parents=True)
        bad = root / "outside.json"
        with self.assertRaises(ValueError):
            validate_gate_artifact_location(ep_root, bad)


if __name__ == "__main__":
    unittest.main()

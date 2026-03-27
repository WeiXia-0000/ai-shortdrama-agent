"""carry_structured_refresh：payoff_id/setup_id 优先与 stale 保护。"""

from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path

from ai_manga_factory.carry_registry import build_empty_shell, save_registry
from ai_manga_factory.carry_structured_refresh import (
    _stable_payoff_compound_key,
    refresh_promise_lane_structured,
)


def _meta() -> dict:
    return {
        "provenance": "test",
        "last_updated_by": "test",
        "last_updated_at": "2099-01-01T00:00:00Z",
    }


class TestCarryIdFirst(unittest.TestCase):
    def tearDown(self) -> None:
        shutil.rmtree(Path(__file__).resolve().parent / "_tmp_carry_id", ignore_errors=True)

    def test_outline_must_payoff_items_seed_uses_stable_compound_key(self) -> None:
        root = Path(__file__).resolve().parent / "_tmp_carry_id" / "seed"
        root.mkdir(parents=True)
        (root / "L4_episodes").mkdir(parents=True)
        (root / "L3_series").mkdir(parents=True)
        outline = {
            "episode_list": [
                {
                    "episode_id": 1,
                    "must_payoff_items": [{"payoff_id": "P_OUTLINE", "description": "回收伏笔A", "deadline": "next"}],
                }
            ]
        }
        (root / "L3_series" / "01_series_outline.json").write_text(
            json.dumps(outline, ensure_ascii=False), encoding="utf-8"
        )
        ep1 = root / "L4_episodes" / "T_第001集"
        ep1.mkdir(parents=True)
        (ep1 / "01_episode_function.json").write_text(
            json.dumps(
                {
                    "viewer_payoff_design": [
                        {
                            "payoff_id": "P_OUTLINE",
                            "type": "reversal",
                            "description": "完全不同的措辞但仍同一 ID",
                            "payoff_target": "x",
                            "setup_source": "",
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (ep1 / "02_plot.json").write_text("{}", encoding="utf-8")
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
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        refresh_promise_lane_structured(reg, paths=paths, layout="layered", source="test", meta_row=_meta())
        prs = reg["promise_lane"]["promises"]
        pids = {p.get("promise_id") for p in prs}
        self.assertIn("payoff:P_OUTLINE", pids)
        cks = [p.get("compound_key") for p in prs if p.get("payoff_id") == "P_OUTLINE"]
        self.assertTrue(cks)
        self.assertEqual(cks[0], _stable_payoff_compound_key("P_OUTLINE"))

    def test_same_payoff_id_in_later_ep_prevents_stale_window(self) -> None:
        root = Path(__file__).resolve().parent / "_tmp_carry_id" / "nostale"
        root.mkdir(parents=True)
        (root / "L4_episodes").mkdir(parents=True)
        (root / "L3_series").mkdir(parents=True)
        (root / "L3_series" / "01_series_outline.json").write_text("{}", encoding="utf-8")
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

        def write_ep(n: int, vpd: list) -> None:
            ep = root / "L4_episodes" / f"T_第{n:03d}集"
            ep.mkdir(parents=True)
            (ep / "01_episode_function.json").write_text(
                json.dumps({"viewer_payoff_design": vpd}, ensure_ascii=False),
                encoding="utf-8",
            )
            (ep / "02_plot.json").write_text("{}", encoding="utf-8")

        write_ep(
            1,
            [
                {
                    "payoff_id": "P_STALE_GUARD",
                    "type": "hook",
                    "description": "旧措辞描述很长但后面会改说法",
                    "payoff_target": "t",
                    "setup_source": "",
                }
            ],
        )
        for n in range(2, 8):
            write_ep(n, [])
        write_ep(
            8,
            [
                {
                    "payoff_id": "P_STALE_GUARD",
                    "type": "hook",
                    "description": "完全改写后的文本",
                    "payoff_target": "t",
                    "setup_source": "",
                }
            ],
        )
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
        refresh_promise_lane_structured(reg, paths=paths, layout="layered", source="test", meta_row=_meta())
        row = next(p for p in reg["promise_lane"]["promises"] if p.get("payoff_id") == "P_STALE_GUARD")
        self.assertNotEqual(row.get("status"), "stale")


if __name__ == "__main__":
    unittest.main()

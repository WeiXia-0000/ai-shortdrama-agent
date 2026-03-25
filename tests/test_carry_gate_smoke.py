"""Smoke：registry、集目录定位、最小同步、视觉锁分级。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from ai_manga_factory.carry_registry import (
    build_empty_shell,
    classify_bible_character_visual_lock,
    sync_carry_registry_minimal,
    validate_registry,
)
from ai_manga_factory.genre_rules import GENRE_REFERENCE_CANDIDATES, _load_genre_reference
from ai_manga_factory.run_series import find_episode_dir_for_id, parse_episode_id_from_dirname
from ai_manga_factory.studio_operations import _run_query_episode_lane


class TestRegistryValidate(unittest.TestCase):
    def test_empty_shell_validates(self) -> None:
        shell = build_empty_shell(series_slug="t", display_title="T", genre_key="general")
        err = validate_registry(shell)
        self.assertEqual(err, [])


class TestEpisodeDirResolve(unittest.TestCase):
    def test_conflict_two_dirs_same_episode(self) -> None:
        root = Path(__file__).resolve().parent / "_tmp_ep_resolve"
        root.mkdir(exist_ok=True)
        try:
            (root / "剧_第001集").mkdir(exist_ok=True)
            (root / "剧_第001集_2").mkdir(exist_ok=True)
            p, err = find_episode_dir_for_id(root, 1)
            self.assertIsNone(p)
            self.assertIsNotNone(err)
            self.assertIn("多个目录", err or "")
        finally:
            import shutil

            shutil.rmtree(root, ignore_errors=True)

    def test_query_lane_uses_existing_dir_not_suffix(self) -> None:
        root = Path(__file__).resolve().parent / "_tmp_query_lane"
        root.mkdir(exist_ok=True)
        try:
            (root / "L3_series").mkdir(parents=True)
            (root / "L4_episodes").mkdir(parents=True)
            (root / "L3_series" / "01_series_outline.json").write_text(
                json.dumps({"title": "我的剧"}, ensure_ascii=False),
                encoding="utf-8",
            )
            real_ep = root / "L4_episodes" / "我的剧_第001集"
            real_ep.mkdir(parents=True)
            (real_ep / "01_episode_function.json").write_text("{}", encoding="utf-8")
            out = _run_query_episode_lane(root, 1)
            self.assertIsNone(out.get("error"), msg=str(out))
            self.assertEqual(Path(out["episode_dir"]).name, "我的剧_第001集")
            self.assertNotIn("_2", out["episode_dir"])
        finally:
            import shutil

            shutil.rmtree(root, ignore_errors=True)


class TestSyncMinimal(unittest.TestCase):
    def test_episode_batch_tail_fills_three_slices(self) -> None:
        root = Path(__file__).resolve().parent / "_tmp_sync_carry"
        if root.exists():
            import shutil

            shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
        (root / "L3_series").mkdir(parents=True)
        (root / "L4_episodes").mkdir(parents=True)
        outline = {
            "title": "测剧",
            "logline": "规则怪谈 系统",
            "overall_arc": "求生",
            "episode_list": [],
        }
        (root / "L3_series" / "01_series_outline.json").write_text(
            json.dumps(outline, ensure_ascii=False), encoding="utf-8"
        )
        bible = {
            "main_characters": [
                {
                    "name": "主角",
                    "appearance_lock": {
                        "face_shape": "方",
                        "hair": "黑",
                        "eyes": "深",
                        "body_type": "中",
                        "default_outfit": "夹克",
                    },
                    "face_triptych_prompt_cn": "脸三视图提示词内容足够长度测试用",
                    "body_triptych_prompt_cn": "全身三视图提示词内容足够长度测试用",
                    "negative_prompt_cn": "不要变形",
                    "consistency_rules": ["须保持发型"],
                }
            ]
        }
        (root / "L3_series" / "02_character_bible.json").write_text(
            json.dumps(bible, ensure_ascii=False), encoding="utf-8"
        )
        memory = {"episodes": [], "characters": [{"name": "主角"}, {"name": "配角"}]}
        (root / "L3_series" / "03_series_memory.json").write_text(
            json.dumps(memory, ensure_ascii=False), encoding="utf-8"
        )
        ep_dir = root / "L4_episodes" / "测剧_第001集"
        ep_dir.mkdir(parents=True)
        fn = {
            "episode_id": 1,
            "viewer_payoff_design": [{"type": "hook", "description": "本集钩子"}],
        }
        (ep_dir / "01_episode_function.json").write_text(
            json.dumps(fn, ensure_ascii=False), encoding="utf-8"
        )
        paths = {
            "series_dir": root,
            "layout": "layered",
            "series_outline": root / "L3_series" / "01_series_outline.json",
            "character_bible": root / "L3_series" / "02_character_bible.json",
            "series_memory": root / "L3_series" / "03_series_memory.json",
            "production_carry_registry": root / "L3_series" / "03b_production_carry_registry.json",
            "episodes_root": root / "L4_episodes",
        }
        sync_carry_registry_minimal(paths, series_title="测剧", layout="layered")
        reg = json.loads(paths["production_carry_registry"].read_text(encoding="utf-8"))
        self.assertEqual(validate_registry(reg), [])
        self.assertTrue(reg["promise_lane"]["promises"])
        self.assertTrue(reg["relation_pressure_map"]["relations"])
        self.assertTrue(reg["visual_lock_registry"]["characters"])
        import shutil

        shutil.rmtree(root, ignore_errors=True)


class TestVisualLockClassify(unittest.TestCase):
    def test_complete_vs_partial(self) -> None:
        full = {
            "name": "x",
            "face_triptych_prompt_cn": "x" * 22,
            "body_triptych_prompt_cn": "y" * 22,
            "negative_prompt_cn": "不要变形",
            "appearance_lock": {
                "face_shape": "a",
                "hair": "b",
                "eyes": "c",
                "body_type": "d",
                "default_outfit": "e",
            },
            "consistency_rules": ["锁脸"],
        }
        self.assertEqual(classify_bible_character_visual_lock(full), "complete")
        weak = {"name": "y", "face_triptych_prompt_cn": "短"}
        self.assertEqual(classify_bible_character_visual_lock(weak), "partial")


class TestGenreReferenceLoad(unittest.TestCase):
    def test_load_returns_general(self) -> None:
        ref = _load_genre_reference()
        self.assertIn("general", ref)
        # 仓库内通常存在 ai_manga_factory/genres/genre_reference.json
        self.assertTrue(any(p.is_file() for p in GENRE_REFERENCE_CANDIDATES))


class TestParseDirname(unittest.TestCase):
    def test_parse(self) -> None:
        self.assertEqual(parse_episode_id_from_dirname("剧_第001集"), 1)
        self.assertIsNone(parse_episode_id_from_dirname("bad"))


if __name__ == "__main__":
    unittest.main()

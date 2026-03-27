"""ownership_guard：切片权限与报错文案一致性。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ai_manga_factory.ownership_guard import (
    FORBIDDEN_REGISTRY_SLICES,
    validate_carry_refresh_slice_name,
    validate_op_for_execution,
)


class TestOwnershipGuard(unittest.TestCase):
    def test_carry_refresh_slice_allows_knowledge_fence(self) -> None:
        validate_carry_refresh_slice_name("knowledge_fence")

    def test_forbidden_error_does_not_list_knowledge_fence_as_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reg = root / "reg.json"
            reg.write_text("{}", encoding="utf-8")
            series_paths = {
                "production_carry_registry": reg,
                "character_bible": root / "b.json",
                "episodes_root": root / "ep",
            }
            (root / "ep").mkdir(parents=True, exist_ok=True)
            op_def = {
                "state_touch_list": [{"mode": "write", "slice": "story_thrust"}],
                "writes_to": [],
            }
            with self.assertRaises(PermissionError) as ctx:
                validate_op_for_execution("carry.refresh_slice", op_def, series_paths=series_paths)
            msg = str(ctx.exception)
            self.assertIn("story_thrust", msg)
            self.assertNotIn("knowledge_fence", msg)

    def test_carry_refresh_may_write_knowledge_fence_touch(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            reg = root / "reg.json"
            reg.write_text("{}", encoding="utf-8")
            series_paths = {
                "production_carry_registry": reg,
                "character_bible": root / "b.json",
                "episodes_root": root / "ep",
            }
            (root / "ep").mkdir(parents=True, exist_ok=True)
            op_def = {
                "state_touch_list": [{"mode": "write", "slice": "knowledge_fence"}],
                "writes_to": [],
            }
            validate_op_for_execution("carry.refresh_slice", op_def, series_paths=series_paths)

    def test_forbidden_set_excludes_knowledge_fence(self) -> None:
        self.assertIn("story_thrust", FORBIDDEN_REGISTRY_SLICES)
        self.assertIn("asset_ledger", FORBIDDEN_REGISTRY_SLICES)
        self.assertNotIn("knowledge_fence", FORBIDDEN_REGISTRY_SLICES)


if __name__ == "__main__":
    unittest.main()

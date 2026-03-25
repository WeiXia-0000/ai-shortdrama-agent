"""分层注册表中的相对路径 → resolve_series_paths 键（平铺布局自动落到正确绝对路径）。"""

from __future__ import annotations

from typing import Any, Dict

# operations_registry / ownership 共用的「分层规范路径」映射
LAYERED_REL_TO_PATH_KEY: Dict[str, str] = {
    "L3_series/03b_production_carry_registry.json": "production_carry_registry",
    "L3_series/03_series_memory.json": "series_memory",
    "L3_series/02_character_bible.json": "character_bible",
    "L3_series/01_series_outline.json": "series_outline",
    "L3_series/04_episode_batch.json": "episode_batch",
}


def resolve_catalog_rel(paths: Dict[str, Any], rel: str) -> Any:
    key = LAYERED_REL_TO_PATH_KEY.get(rel)
    if key:
        return paths[key]
    return paths["series_dir"] / rel

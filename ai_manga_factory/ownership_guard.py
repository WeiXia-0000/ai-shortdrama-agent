"""
op run 前校验：state_touch_list 与 writes_to 不得越权。
注意：当前架构中 `carry.refresh_slice` 允许写入 `knowledge_fence`（用于 promise / 关系 / 知识栅栏的同步更新）。
因此这里的“禁写”口径以 ALLOWED_REGISTRY_SLICES / FORBIDDEN_REGISTRY_SLICES 为准：
- 禁止：story_thrust / asset_ledger
- 允许：knowledge_fence（carry.refresh_slice）
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Set

from .path_catalog import resolve_catalog_rel

FORBIDDEN_REGISTRY_SLICES = frozenset({"story_thrust", "asset_ledger"})

ALLOWED_REGISTRY_SLICES: Dict[str, Set[str]] = {
    "carry.refresh_slice": {"promise_lane", "relation_pressure_map", "knowledge_fence"},
    "cast.scan_visual_coverage": {"visual_lock_registry"},
    "cast.patch_visual_lock": {"visual_lock_registry"},
}

def validate_carry_refresh_slice_name(slice_name: str) -> None:
    allowed = ALLOWED_REGISTRY_SLICES.get("carry.refresh_slice", set())
    if slice_name not in allowed:
        raise PermissionError(
            f"carry.refresh_slice 仅允许切片: {sorted(allowed)}，收到: {slice_name!r}"
        )


ALLOWED_PATH_KEYS_BY_OP: Dict[str, Set[str]] = {
    "query.episode_lane_status": set(),
    "query.promise_lane_snapshot": set(),
    "query.carry_slice": set(),
    "query.visual_lock_status": set(),
    "query.gate_status": set(),
    "query.gate_trend": set(),
    "query.promise_status": set(),
    "query.knowledge_fence": set(),
    "query.genre_bundle": set(),
    "carry.apply_promise_overrides": {"production_carry_registry"},
    "gate.run_plot_gate": {"episodes_root"},
    "gate.run_package_gate": {"episodes_root"},
    "cast.scan_visual_coverage": {"production_carry_registry"},
    "cast.patch_visual_lock": {"production_carry_registry", "character_bible"},
    "carry.refresh_slice": {"production_carry_registry"},
}

# 允许实际落盘的 path 类别：production_carry_registry / character_bible / episodes_root 下文件


def validate_op_for_execution(
    op_id: str,
    op_def: Dict[str, Any],
    *,
    series_paths: Dict[str, Any],
) -> None:
    allowed_keys = ALLOWED_PATH_KEYS_BY_OP.get(op_id)
    if allowed_keys is None:
        raise PermissionError(f"未知 operation_id: {op_id}")

    allowed_reg = ALLOWED_REGISTRY_SLICES.get(op_id, set())

    for touch in op_def.get("state_touch_list") or []:
        if not isinstance(touch, dict):
            continue
        mode = str(touch.get("mode") or "")
        slice_name = touch.get("slice")
        if mode not in ("write", "derive"):
            continue
        if slice_name is None or slice_name == "":
            continue
        sn = str(slice_name)
        if sn in FORBIDDEN_REGISTRY_SLICES:
            raise PermissionError(
                f"[{op_id}] 禁止写入切片: {sn}（MVP 冻结：story_thrust / knowledge_fence / asset_ledger）"
            )
        if sn not in allowed_reg:
            raise PermissionError(f"[{op_id}] 未授权写入 registry 切片: {sn}")

    reg_path = series_paths["production_carry_registry"].resolve()
    bible_path = series_paths["character_bible"].resolve()
    ep_root = series_paths["episodes_root"].resolve()

    gate_ops = frozenset({"gate.run_plot_gate", "gate.run_package_gate"})
    for rel in op_def.get("writes_to") or []:
        if not isinstance(rel, str) or not rel.strip():
            continue
        if op_id in gate_ops and "<" in rel:
            # 集目录占位符：实写在 gate_artifacts.append_gate_entry 内校验路径与文件名
            continue
        full = resolve_catalog_rel(series_paths, rel).resolve()
        ok = False
        if "production_carry_registry" in allowed_keys and full == reg_path:
            ok = True
        if "character_bible" in allowed_keys and full == bible_path:
            ok = True
        if "episodes_root" in allowed_keys:
            try:
                full.relative_to(ep_root)
                ok = True
            except ValueError:
                pass
        if not ok:
            raise PermissionError(
                f"[{op_id}] writes_to 越权或未解析: {rel!r}（允许 keys={allowed_keys!r}）"
            )

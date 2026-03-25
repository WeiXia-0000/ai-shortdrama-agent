"""
首批 studio operation：list / run（支持 --dry-run）。
reads_from / writes_to 在 operations_registry.json 中采用分层布局相对路径（相对 series_dir）。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .carry_registry import (
    apply_promise_manual_overrides,
    apply_visual_lock_patch,
    build_empty_shell,
    load_registry,
    refresh_registry_slice,
    scan_visual_lock_only,
)
from .gate_artifacts import (
    build_gate_trend_summary,
    compact_gate_entry_for_query,
    load_gate_artifact,
    summarize_gate_artifact,
)
from .ownership_guard import validate_carry_refresh_slice_name, validate_op_for_execution
from .path_catalog import resolve_catalog_rel
from .run_series import (
    _episode_json_paths,
    find_episode_dir_for_id,
    resolve_series_paths,
)

_REGISTRY_FILE = Path(__file__).resolve().parent / "operations_registry.json"

QUERY_SLICES = frozenset(
    {
        "story_thrust",
        "asset_ledger",
        "promise_lane",
        "relation_pressure_map",
        "knowledge_fence",
        "visual_lock_registry",
    }
)


def _load_definitions() -> Dict[str, Any]:
    data = json.loads(_REGISTRY_FILE.read_text(encoding="utf-8"))
    by_id = {o["operation_id"]: o for o in data.get("operations", [])}
    return {"raw": data, "by_id": by_id}


def _series_title(paths: Dict[str, Any]) -> str:
    p = paths["series_outline"]
    if not p.exists():
        return paths["series_dir"].name
    try:
        ol = json.loads(p.read_text(encoding="utf-8"))
        return str(ol.get("title") or paths["series_dir"].name)
    except (OSError, json.JSONDecodeError):
        return paths["series_dir"].name


def _op_def(op_id: str) -> Dict[str, Any]:
    data = _load_definitions()
    op = data["by_id"].get(op_id)
    if not op:
        raise SystemExit(f"未知 operation_id: {op_id}（先 op list）")
    return op


def cmd_list() -> None:
    data = _load_definitions()
    for o in data["raw"].get("operations", []):
        impl = "yes" if o.get("implemented") else "NO"
        print(f"{o['operation_id']}\timplemented={impl}")


def _print_json(obj: Any) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _run_query_episode_lane(series_dir: Path, episode_id: int) -> Dict[str, Any]:
    paths = resolve_series_paths(series_dir)
    ep_dir, err = find_episode_dir_for_id(paths["episodes_root"], episode_id)
    if err:
        return {
            "series_dir": str(series_dir),
            "episode_id": episode_id,
            "error": err,
            "episode_dir": None,
        }
    layout = str(paths.get("layout", "flat"))
    ep_files = _episode_json_paths(ep_dir, layout)
    return {
        "series_dir": str(series_dir),
        "episode_id": episode_id,
        "episode_dir": str(ep_dir),
        "artifacts": {k: str(v) for k, v in ep_files.items()},
        "exists": {k: v.exists() for k, v in ep_files.items()},
    }


def _run_query_promise_lane(series_dir: Path) -> Dict[str, Any]:
    paths = resolve_series_paths(series_dir)
    reg_path = paths["production_carry_registry"]
    if not reg_path.exists():
        shell = build_empty_shell(
            series_slug=series_dir.name,
            display_title=_series_title(paths),
        )
        return shell.get("promise_lane") or {"promises": []}
    reg = load_registry(reg_path)
    return reg.get("promise_lane") or {"promises": []}


def _run_query_carry_slice(series_dir: Path, slice_name: Optional[str]) -> Any:
    paths = resolve_series_paths(series_dir)
    reg_path = paths["production_carry_registry"]
    if not reg_path.exists():
        return None if slice_name else {"missing_file": True}
    reg = load_registry(reg_path)
    if not slice_name:
        return reg
    if slice_name not in QUERY_SLICES:
        raise SystemExit(f"slice 不在白名单: {sorted(QUERY_SLICES)}")
    return reg.get(slice_name)


def _promise_row_manual_override(p: Dict[str, Any]) -> bool:
    if p.get("override_reason"):
        return True
    if p.get("override_source"):
        return True
    prov = str(p.get("provenance") or "")
    return "manual" in prov


def _run_query_promise_status(
    series_dir: Path,
    *,
    episode_id: Optional[int] = None,
    status_filter: str = "all",
    promise_id: Optional[str] = None,
    promise_filter: str = "all",
    anchor_id: Optional[str] = None,
) -> Dict[str, Any]:
    paths = resolve_series_paths(series_dir)
    reg_path = paths["production_carry_registry"]
    if not reg_path.exists():
        promises: List[Any] = []
    else:
        reg = load_registry(reg_path)
        pl = reg.get("promise_lane") or {}
        promises = [p for p in (pl.get("promises") or []) if isinstance(p, dict)]
    if promise_id:
        detail = next(
            (p for p in promises if str(p.get("promise_id")) == str(promise_id)),
            None,
        )
        return {
            "series_dir": str(series_dir),
            "promise_id": promise_id,
            "found": detail is not None,
            "detail": detail,
        }
    out = list(promises)
    if episode_id is not None:
        out = [p for p in out if p.get("created_episode") == episode_id]
    if status_filter and status_filter != "all":
        out = [p for p in out if (p.get("status") or "open") == status_filter]
    if anchor_id is not None:
        aid = str(anchor_id)
        out = [p for p in out if aid in [str(x) for x in (p.get("linked_anchor_ids") or [])]]
    if promise_filter == "manual_only":
        out = [p for p in out if _promise_row_manual_override(p)]
    elif promise_filter == "supersede":
        out = [
            p
            for p in out
            if p.get("superseded_by_promise_id") or p.get("supersedes_promise_ids")
        ]
    summary_counts: Dict[str, int] = {}
    for st in ("open", "paid_off", "broken", "stale"):
        summary_counts[st] = sum(
            1 for p in promises if (p.get("status") or "open") == st
        )
    supersede_digest = {
        "with_superseded_by": sum(1 for p in promises if p.get("superseded_by_promise_id")),
        "with_supersedes_list": sum(1 for p in promises if p.get("supersedes_promise_ids")),
    }
    return {
        "series_dir": str(series_dir),
        "filter": {
            "episode_created": episode_id,
            "status": status_filter,
            "promise_filter": promise_filter,
            "anchor_id": anchor_id,
        },
        "summary_counts": summary_counts,
        "supersede_digest": supersede_digest,
        "count_returned": len(out),
        "promises": out,
    }


def _run_query_knowledge_fence(
    series_dir: Path,
    *,
    episode_id: Optional[int] = None,
    kf_mode: str = "all",
    character_name: Optional[str] = None,
) -> Dict[str, Any]:
    paths = resolve_series_paths(series_dir)
    reg_path = paths["production_carry_registry"]
    if not reg_path.exists():
        facts: List[Any] = []
    else:
        reg = load_registry(reg_path)
        kf = reg.get("knowledge_fence") or {}
        facts = [f for f in (kf.get("facts") or []) if isinstance(f, dict)]
    note = ""
    if kf_mode == "first_seen_episode" and episode_id is not None:
        facts = [f for f in facts if f.get("first_seen_episode") == episode_id]
    elif kf_mode == "touched_on_episode" and episode_id is not None:
        facts = [
            f
            for f in facts
            if f.get("first_seen_episode") == episode_id
            or f.get("last_seen_episode") == episode_id
        ]
    elif kf_mode == "audience_only":
        facts = [f for f in facts if f.get("visibility") == "audience_only"]
    elif kf_mode == "low_confidence":
        facts = [f for f in facts if f.get("confidence") == "low"]
        note = "低置信度条目建议人工复核 known_by / visibility"
    elif kf_mode == "known_by_character" and character_name:
        facts = [
            f
            for f in facts
            if character_name in [str(x) for x in (f.get("known_by") or [])]
        ]
    elif kf_mode == "recent_changes":
        facts = [
            f
            for f in facts
            if f.get("first_seen_episode") != f.get("last_seen_episode")
        ]
    elif kf_mode == "new_on_episode" and episode_id is not None:
        facts = [f for f in facts if f.get("first_seen_episode") == episode_id]
    elif kf_mode not in (
        "all",
        "",
        "first_seen_episode",
        "touched_on_episode",
        "audience_only",
        "low_confidence",
        "known_by_character",
        "recent_changes",
        "new_on_episode",
    ):
        note = f"未知 kf_mode={kf_mode!r}，已回退为全部"
    return {
        "series_dir": str(series_dir),
        "kf_mode": kf_mode,
        "episode_id": episode_id,
        "character_name": character_name,
        "count": len(facts),
        "note": note,
        "facts": facts,
    }


def _run_query_gate_status(series_dir: Path, episode_id: int) -> Dict[str, Any]:
    paths = resolve_series_paths(series_dir)
    ep_dir, err = find_episode_dir_for_id(paths["episodes_root"], episode_id)
    if err:
        return {
            "series_dir": str(series_dir),
            "episode_id": episode_id,
            "error": err,
            "summary": None,
        }
    layout = str(paths.get("layout", "flat"))
    ep_files = _episode_json_paths(ep_dir, layout)
    ga = ep_files["gate_artifacts"]
    doc = load_gate_artifact(ep_dir, layout)
    summ = summarize_gate_artifact(doc)
    return {
        "series_dir": str(series_dir),
        "episode_id": episode_id,
        "episode_dir": str(ep_dir),
        "artifact_path": str(ga),
        "artifact_exists": ga.is_file(),
        "summary": summ,
        "trend_summary": summ.get("trend_summary"),
    }


def _run_query_gate_trend(series_dir: Path, episode_id: int) -> Dict[str, Any]:
    base = _run_query_gate_status(series_dir, episode_id)
    if base.get("error"):
        return base
    paths = resolve_series_paths(series_dir)
    ep_dir = Path(base["episode_dir"])
    layout = str(paths.get("layout", "flat"))
    doc = load_gate_artifact(ep_dir, layout)
    trend = build_gate_trend_summary(doc)
    entries = [e for e in (doc.get("entries") or []) if isinstance(e, dict)]
    tail = entries[-8:]
    tail_compact = [compact_gate_entry_for_query(dict(e)) for e in tail]
    recent_fail_compact = [c for c in tail_compact if not c.get("pass")]
    lv = trend.get("latest_verdict") or {}
    return {
        **base,
        "trend_summary": trend,
        "latest_verdict_digest": lv,
        "entries_tail_compact": tail_compact,
        "recent_failed_entries_compact": recent_fail_compact,
        "repeated_failure_active": bool(
            trend.get("repeated_same_failure_as_immediate_previous")
        ),
        "failure_trend_label": trend.get("failure_trend_label"),
        "entries_tail": tail,
        "recent_failed_entries": [e for e in tail if not e.get("pass")],
    }


def _run_query_visual_lock(series_dir: Path, cast_id: Optional[str]) -> Any:
    paths = resolve_series_paths(series_dir)
    reg_path = paths["production_carry_registry"]
    if not reg_path.exists():
        return {"characters": []}
    reg = load_registry(reg_path)
    chars = (reg.get("visual_lock_registry") or {}).get("characters") or []
    if not cast_id:
        return {"characters": chars}
    return {"characters": [c for c in chars if isinstance(c, dict) and c.get("cast_id") == cast_id]}


def _dry_run_plan(op: Dict[str, Any], series_dir: Path) -> Dict[str, Any]:
    paths = resolve_series_paths(series_dir)
    sd = paths["series_dir"]
    reads = op.get("reads_from") or []
    writes = op.get("writes_to") or []
    return {
        "operation_id": op["operation_id"],
        "series_dir": str(sd),
        "layout": paths.get("layout"),
        "reads_from_resolved": [
            str(resolve_catalog_rel(paths, r).resolve())
            for r in reads
            if isinstance(r, str) and "<" not in r
        ],
        "writes_to_resolved": [
            str(resolve_catalog_rel(paths, r).resolve())
            for r in writes
            if isinstance(r, str) and "<" not in r
        ],
        "state_touch_list": op.get("state_touch_list"),
        "implemented": op.get("implemented", True),
    }


def cmd_run(
    op_id: str,
    *,
    series_dir: Path,
    dry_run: bool,
    episode_id: Optional[int],
    slice_name: Optional[str],
    cast_id: Optional[str],
    patch_json: Optional[Path],
    promise_status: str,
    promise_id: Optional[str],
    kf_query_mode: str,
    promise_filter: str,
    anchor_id: Optional[str],
) -> None:
    op = _op_def(op_id)
    paths = resolve_series_paths(series_dir)

    if op_id == "carry.refresh_slice":
        if not slice_name:
            raise SystemExit(
                "carry.refresh_slice 需要 --slice promise_lane|relation_pressure_map|knowledge_fence"
            )
        validate_carry_refresh_slice_name(slice_name)

    validate_op_for_execution(op_id, op, series_paths=paths)

    if op_id == "gate.run_plot_gate":
        if episode_id is None:
            raise SystemExit("gate.run_plot_gate 需要 --episode-id")
        if dry_run:
            from .gate_runner import plan_plot_gate

            _print_json(plan_plot_gate(series_dir, episode_id))
            return

    if op_id == "gate.run_package_gate":
        if episode_id is None:
            raise SystemExit("gate.run_package_gate 需要 --episode-id")
        if dry_run:
            from .gate_runner import plan_package_gate

            _print_json(plan_package_gate(series_dir, episode_id))
            return

    if dry_run:
        plan = _dry_run_plan(op, series_dir)
        plan["note"] = "含 <...> 占位符的路径需在实跑时按集解析"
        _print_json(plan)
        return

    if op_id == "carry.refresh_slice":
        validate_carry_refresh_slice_name(slice_name or "")
        refresh_registry_slice(
            paths,
            slice_name=slice_name or "",
            layout=str(paths.get("layout", "flat")),
            series_title=_series_title(paths),
            source="op:carry.refresh_slice",
        )
        print(f"[ok] {op_id} slice={slice_name}")
        return

    if not op.get("implemented", True):
        raise SystemExit(f"{op_id} 尚未实现（仅可 --dry-run）")

    if op_id == "query.episode_lane_status":
        if episode_id is None:
            raise SystemExit("需要 --episode-id")
        _print_json(_run_query_episode_lane(series_dir, episode_id))
        return

    if op_id == "query.promise_lane_snapshot":
        _print_json(_run_query_promise_lane(series_dir))
        return

    if op_id == "query.carry_slice":
        _print_json(_run_query_carry_slice(series_dir, slice_name))
        return

    if op_id == "query.gate_status":
        if episode_id is None:
            raise SystemExit("query.gate_status 需要 --episode-id")
        _print_json(_run_query_gate_status(series_dir, episode_id))
        return

    if op_id == "query.gate_trend":
        if episode_id is None:
            raise SystemExit("query.gate_trend 需要 --episode-id")
        _print_json(_run_query_gate_trend(series_dir, episode_id))
        return

    if op_id == "query.promise_status":
        _print_json(
            _run_query_promise_status(
                series_dir,
                episode_id=episode_id,
                status_filter=promise_status or "all",
                promise_id=promise_id,
                promise_filter=promise_filter or "all",
                anchor_id=anchor_id,
            )
        )
        return

    if op_id == "query.knowledge_fence":
        _print_json(
            _run_query_knowledge_fence(
                series_dir,
                episode_id=episode_id,
                kf_mode=kf_query_mode or "all",
                character_name=cast_id,
            )
        )
        return

    if op_id == "carry.apply_promise_overrides":
        if not patch_json or not patch_json.is_file():
            raise SystemExit("carry.apply_promise_overrides 需要有效 --patch-json")
        patch = json.loads(patch_json.read_text(encoding="utf-8"))
        apply_promise_manual_overrides(paths, patch=patch)
        print(f"[ok] {op_id}")
        return

    if op_id == "query.visual_lock_status":
        _print_json(_run_query_visual_lock(series_dir, cast_id))
        return

    if op_id == "cast.scan_visual_coverage":
        scan_visual_lock_only(
            paths,
            layout=str(paths.get("layout", "flat")),
            series_title=_series_title(paths),
            source="op:cast.scan_visual_coverage",
        )
        print(f"[ok] {op_id}")
        return

    if op_id == "cast.patch_visual_lock":
        if not patch_json or not patch_json.is_file():
            raise SystemExit("cast.patch_visual_lock 需要有效 --patch-json 文件")
        patch = json.loads(patch_json.read_text(encoding="utf-8"))
        apply_visual_lock_patch(paths, layout=str(paths.get("layout", "flat")), patch=patch)
        print(f"[ok] {op_id}")
        return

    if op_id == "gate.run_plot_gate":
        if episode_id is None:
            raise SystemExit("gate.run_plot_gate 需要 --episode-id")
        import asyncio

        from .gate_runner import run_plot_gate_standalone

        _print_json(asyncio.run(run_plot_gate_standalone(series_dir, episode_id)))
        return

    if op_id == "gate.run_package_gate":
        if episode_id is None:
            raise SystemExit("gate.run_package_gate 需要 --episode-id")
        import asyncio

        from .gate_runner import run_package_gate_standalone

        _print_json(asyncio.run(run_package_gate_standalone(series_dir, episode_id)))
        return

    raise SystemExit(f"未处理 operation: {op_id}")


def run_cli(argv: Optional[List[str]] = None) -> None:
    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(description="ai_manga_factory studio operations")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="列出已注册 operation_id")

    p_run = sub.add_parser("run", help="执行或 dry-run")
    p_run.add_argument("operation_id", type=str)
    p_run.add_argument("--series-dir", type=Path, required=True)
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--episode-id", type=int, default=None)
    p_run.add_argument("--slice", type=str, default=None, help="carry.refresh_slice / query.carry_slice")
    p_run.add_argument(
        "--cast-id",
        type=str,
        default=None,
        help="query.visual_lock_status / query.knowledge_fence known_by_character 时的角色名",
    )
    p_run.add_argument("--patch-json", type=Path, default=None)
    p_run.add_argument(
        "--promise-status",
        type=str,
        default="all",
        help="query.promise_status：open|paid_off|broken|stale|all",
    )
    p_run.add_argument("--promise-id", type=str, default=None, help="query.promise_status 单条详情")
    p_run.add_argument(
        "--promise-filter",
        type=str,
        default="all",
        help="query.promise_status：all|manual_only|supersede（与 status/episode 可组合）",
    )
    p_run.add_argument(
        "--anchor-id",
        type=str,
        default=None,
        help="query.promise_status：按 linked_anchor_ids 过滤",
    )
    p_run.add_argument(
        "--kf-query-mode",
        type=str,
        default="all",
        help="query.knowledge_fence：all|first_seen_episode|new_on_episode|touched_on_episode|recent_changes|audience_only|low_confidence|known_by_character",
    )

    args = parser.parse_args(argv)

    if args.cmd == "list":
        cmd_list()
        return

    if args.cmd == "run":
        cmd_run(
            args.operation_id,
            series_dir=args.series_dir.resolve(),
            dry_run=args.dry_run,
            episode_id=args.episode_id,
            slice_name=args.slice,
            cast_id=args.cast_id,
            patch_json=args.patch_json,
            promise_status=args.promise_status,
            promise_id=args.promise_id,
            kf_query_mode=args.kf_query_mode,
            promise_filter=args.promise_filter,
            anchor_id=args.anchor_id,
        )
        return


def main() -> None:
    run_cli()


if __name__ == "__main__":
    main()

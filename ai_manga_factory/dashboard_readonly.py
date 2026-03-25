"""
只读 Dashboard 数据适配层（薄层）。

数据源映射（各 UI 模块主要读取路径）：
---------------------------------------------------------------------------
1) 顶部系列总览
   - resolve_series_paths(series_dir)  → run_series
   - series_outline.json → 标题、episode_list 计划集数
   - production_carry_registry → carry_registry.load_registry 或降级 JSON
   - genre_key / capabilities → registry.series_identity + genre_rules.get_genre_capabilities
   - sync_meta、story_thrust.drift_flag → registry

2) Episode Lane（每集行）
   - carry_structured_refresh._iter_episode_dirs → 集目录列表
   - run_series._episode_json_paths → gate_artifacts 路径
   - gate_artifacts.load_gate_artifact / build_gate_trend_summary
   - 每集承诺/知识计数：由 registry.promise_lane、knowledge_fence 按 episode 聚合

3) Promise Panel
   - registry.promise_lane.promises（逻辑对齐 studio_operations._run_query_promise_status 的摘要字段）

4) Knowledge Fence Panel
   - registry.knowledge_fence.facts（对齐 query.knowledge_fence 的过滤维度由前端做）

5) Visual Lock Panel
   - registry.visual_lock_registry.characters
   - 可选：character_bible / series_memory 仅用于「仅 memory 未入圣经」类展示时由本层补全 display

6) Gate Trend
   - gate artifact JSON + build_gate_trend_summary（与 query.gate_status / query.gate_trend 同源）

本模块不执行任何写操作、不调用 LLM、不触发 carry refresh。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .carry_registry import build_empty_shell, load_registry
from .carry_structured_refresh import _iter_episode_dirs
from .gate_artifacts import build_gate_trend_summary, load_gate_artifact
from .genre_rules import get_genre_capabilities
from .run_series import _episode_json_paths, resolve_series_paths
from .studio_operations import _promise_row_manual_override


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _series_title(paths: Dict[str, Any]) -> str:
    p = paths["series_outline"]
    if not p.exists():
        return paths["series_dir"].name
    ol = _load_json(p)
    if not ol:
        return paths["series_dir"].name
    return str(ol.get("title") or paths["series_dir"].name)


def load_registry_readonly(
    reg_path: Path, series_dir: Path
) -> Tuple[Dict[str, Any], List[str], bool]:
    """
    尽力加载 registry；缺失或校验失败时降级为未校验 JSON 或空壳，不抛异常。
    返回 (registry, warnings, passed_strict_validation)。
    """
    warns: List[str] = []
    slug = series_dir.name
    paths = resolve_series_paths(series_dir)
    title = _series_title(paths)
    if not reg_path.exists():
        warns.append("production_carry_registry 文件不存在，已用空壳占位")
        return (
            build_empty_shell(series_slug=slug, display_title=title),
            warns,
            False,
        )
    try:
        raw_text = reg_path.read_text(encoding="utf-8")
    except OSError as e:
        warns.append(f"无法读取 registry: {e}")
        return build_empty_shell(series_slug=slug, display_title=title), warns, False
    try:
        reg = load_registry(reg_path)
        return reg, warns, True
    except (ValueError, json.JSONDecodeError) as e:
        warns.append(f"registry 校验或解析失败: {e}")
        try:
            data = json.loads(raw_text)
            if isinstance(data, dict):
                warns.append("已使用未通过 validate_registry 的 JSON（仅展示用）")
                return data, warns, False
        except json.JSONDecodeError:
            pass
        return build_empty_shell(series_slug=slug, display_title=title), warns, False


def _norm_ep_id(x: Any) -> Optional[int]:
    if x is None:
        return None
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _promise_touches_episode(p: Dict[str, Any], ep_id: int) -> bool:
    if _norm_ep_id(p.get("created_episode")) == ep_id:
        return True
    if _norm_ep_id(p.get("last_seen_episode")) == ep_id:
        return True
    for x in p.get("linked_episode_ids") or []:
        if _norm_ep_id(x) == ep_id:
            return True
    return False


def _episode_title_hint(ep_dir: Path, layout: str) -> str:
    paths = _episode_json_paths(ep_dir, layout)
    ef = paths.get("episode_function")
    if not ef or not ef.is_file():
        return ""
    d = _load_json(ef) or {}
    for k in ("episode_title", "title", "one_line", "logline"):
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()[:160]
    return ""


def _relation_signals_for_episode(
    relations: List[Dict[str, Any]], ep_id: int
) -> Dict[str, Any]:
    touched = 0
    high_conflict = 0
    for r in relations:
        if not isinstance(r, dict):
            continue
        lse = _norm_ep_id(r.get("last_seen_episode"))
        lce = _norm_ep_id(r.get("last_change_episode"))
        if lse == ep_id or lce == ep_id:
            touched += 1
        if lce == ep_id and int(r.get("conflict_level") or 0) >= 2:
            high_conflict += 1
    return {
        "relation_touch_count": touched,
        "continuity_pressure_signal": bool(high_conflict > 0),
    }


def _compact_promise_row(p: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "promise_id": str(p.get("promise_id") or ""),
        "description": str(p.get("description") or "")[:220],
        "status": str(p.get("status") or "open"),
        "created_episode": _norm_ep_id(p.get("created_episode")),
        "last_seen_episode": _norm_ep_id(p.get("last_seen_episode")),
        "manual_override": _promise_row_manual_override(p),
        "supersede_summary": {
            "superseded_by_promise_id": p.get("superseded_by_promise_id"),
            "supersedes_promise_ids": p.get("supersedes_promise_ids") or [],
        },
    }


def _compact_fact_row(f: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "fact_id": str(f.get("fact_id") or ""),
        "fact_text": str(f.get("fact_text") or f.get("text") or "")[:260],
        "visibility": str(f.get("visibility") or ""),
        "confidence": str(f.get("confidence") or ""),
        "fact_status": str(f.get("fact_status") or ""),
        "known_by": [str(x) for x in (f.get("known_by") or []) if x],
        "first_seen_episode": _norm_ep_id(f.get("first_seen_episode")),
        "last_confirmed_episode": _norm_ep_id(
            f.get("last_confirmed_episode") or f.get("last_seen_episode")
        ),
    }


def _to_iso_utc_from_ts(ts: float) -> str:
    return (
        datetime.fromtimestamp(ts, tz=timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _episode_risk_tags(ep: Dict[str, Any]) -> List[str]:
    tags: List[str] = []
    if ep.get("plot_gate_pass") is False or ep.get("package_gate_pass") is False:
        tags.append("gate_failed")
    if ep.get("repeated_failure_active"):
        tags.append("repeated_failure")
    if int(ep.get("stale_promise_count") or 0) > 0:
        tags.append("stale_promise")
    if int(ep.get("broken_promise_count") or 0) > 0:
        tags.append("broken_promise")
    if int(ep.get("low_confidence_knowledge_count") or 0) > 0:
        tags.append("low_confidence_knowledge")
    if ep.get("continuity_risk_signal"):
        tags.append("continuity_risk")
    if int(ep.get("visual_lock_incomplete_series") or 0) > 0:
        tags.append("visual_lock_incomplete_series")
    return tags


def _related_cast_names_for_episode(
    ep_id: int,
    *,
    facts_touching: List[Dict[str, Any]],
    relations: List[Dict[str, Any]],
    ef_json: Dict[str, Any],
) -> List[str]:
    names: List[str] = []
    for f in facts_touching:
        for n in f.get("known_by") or []:
            if isinstance(n, str) and n.strip():
                names.append(n.strip())
    for r in relations:
        if not isinstance(r, dict):
            continue
        lse = _norm_ep_id(r.get("last_seen_episode"))
        lce = _norm_ep_id(r.get("last_change_episode"))
        if lse == ep_id or lce == ep_id:
            for k in ("a", "b"):
                v = r.get(k)
                if isinstance(v, str) and v.strip():
                    names.append(v.strip())

    for key in (
        "characters",
        "cast",
        "cast_in_episode",
        "main_characters_in_episode",
        "characters_in_episode",
    ):
        v = ef_json.get(key)
        if isinstance(v, list):
            for item in v:
                if isinstance(item, str) and item.strip():
                    names.append(item.strip())
                elif isinstance(item, dict):
                    n = item.get("name") or item.get("display_name") or item.get("id")
                    if n:
                        names.append(str(n).strip())
    return sorted({n for n in names if n})


def _build_episode_detail(
    *,
    ep_row: Dict[str, Any],
    ep_dir: Path,
    ep_files: Dict[str, Path],
    gate_doc: Dict[str, Any],
    promises_raw: List[Dict[str, Any]],
    facts_raw: List[Dict[str, Any]],
    vl_chars: List[Dict[str, Any]],
    relations: List[Dict[str, Any]],
    reg_path: Path,
) -> Dict[str, Any]:
    ep_id = int(ep_row.get("episode_id") or 0)
    trend = ep_row.get("trend_summary") or {}
    lv = trend.get("latest_verdict") or {}
    ef_json = _load_json(ep_files["episode_function"]) or {}

    touched_promises = [p for p in promises_raw if _promise_touches_episode(p, ep_id)]
    new_promises = [p for p in touched_promises if _norm_ep_id(p.get("created_episode")) == ep_id]
    touched_promises_compact = [_compact_promise_row(p) for p in touched_promises]
    touched_promises_compact.sort(
        key=lambda x: (
            {"broken": 0, "stale": 1, "open": 2, "paid_off": 3}.get(str(x.get("status")), 9),
            0 if x.get("manual_override") else 1,
            -(x.get("last_seen_episode") or 0),
        )
    )
    highlights = touched_promises_compact[:5]

    facts_touching = [
        f
        for f in facts_raw
        if _norm_ep_id(f.get("first_seen_episode")) == ep_id
        or _norm_ep_id(f.get("last_seen_episode")) == ep_id
    ]
    facts_compact = [_compact_fact_row(f) for f in facts_touching]
    known_by_casts = sorted(
        {
            n
            for f in facts_compact
            for n in (f.get("known_by") or [])
            if isinstance(n, str) and n.strip()
        }
    )

    related_cast_names = _related_cast_names_for_episode(
        ep_id,
        facts_touching=facts_touching,
        relations=relations,
        ef_json=ef_json,
    )
    related_vl_rows: List[Dict[str, Any]] = []
    for c in vl_chars:
        if not isinstance(c, dict):
            continue
        dn = str(c.get("display_name") or "")
        cid = str(c.get("cast_id") or "")
        if dn in related_cast_names or cid in related_cast_names:
            lock = str(c.get("lock_status") or "")
            missing_items: List[str] = []
            if lock in ("partial", "missing"):
                if c.get("consistency_risk"):
                    missing_items.append("consistency_risk")
                if not c.get("bible_pointer"):
                    missing_items.append("missing_bible_pointer")
                if lock == "missing":
                    missing_items.append("not_in_bible")
            related_vl_rows.append(
                {
                    "cast_id": cid,
                    "display_name": dn or cid,
                    "visual_state": lock or "unknown",
                    "missing_items": missing_items,
                    "notes": str(c.get("notes") or ""),
                }
            )
    vl_counts = {
        "complete": sum(1 for x in related_vl_rows if x.get("visual_state") == "complete"),
        "partial": sum(1 for x in related_vl_rows if x.get("visual_state") == "partial"),
        "missing": sum(1 for x in related_vl_rows if x.get("visual_state") == "missing"),
    }

    entries = [e for e in (gate_doc.get("entries") or []) if isinstance(e, dict)]

    def latest_gate_compact(gate_type: str) -> Optional[Dict[str, Any]]:
        for e in reversed(entries):
            if str(e.get("gate_type") or "") == gate_type:
                return {
                    "gate_type": gate_type,
                    "pass": bool(e.get("pass")) if e.get("pass") is not None else None,
                    "overall_score_1to10": e.get("overall_score_1to10"),
                    "summary": str(e.get("summary") or "")[:220],
                    "must_fix_count": len(e.get("must_fix") or []) if isinstance(e.get("must_fix"), list) else 0,
                    "issues_count": len(e.get("issues") or []) if isinstance(e.get("issues"), list) else 0,
                    "generated_at": e.get("generated_at"),
                    "rerun_hint": e.get("rerun_hint"),
                }
        return None

    file_presence: Dict[str, Any] = {}
    mtime_ts: List[float] = []
    for k, p in ep_files.items():
        exists = p.is_file()
        row: Dict[str, Any] = {"path": str(p), "exists": exists}
        if exists:
            ts = p.stat().st_mtime
            mtime_ts.append(ts)
            row["updated_at"] = _to_iso_utc_from_ts(ts)
        file_presence[k] = row
    if ep_files["gate_artifacts"].is_file():
        ts = ep_files["gate_artifacts"].stat().st_mtime
        mtime_ts.append(ts)
    latest_artifact_update = _to_iso_utc_from_ts(max(mtime_ts)) if mtime_ts else None

    return {
        "episode_id": ep_id,
        "title": ep_row.get("title") or f"第{ep_id}集",
        "header": {
            "episode_overall_gate": ep_row.get("episode_overall_gate"),
            "plot_gate_pass": ep_row.get("plot_gate_pass"),
            "package_gate_pass": ep_row.get("package_gate_pass"),
            "failure_trend_label": ep_row.get("failure_trend_label"),
            "rerun_hint_summary": ep_row.get("rerun_hint_summary"),
            "risk_tags": _episode_risk_tags(ep_row),
        },
        "promise_snapshot": {
            "open_promise_count": sum(1 for p in touched_promises if (p.get("status") or "open") == "open"),
            "stale_promise_count": sum(1 for p in touched_promises if (p.get("status") or "") == "stale"),
            "broken_promise_count": sum(1 for p in touched_promises if (p.get("status") or "") == "broken"),
            "manual_override_count": sum(1 for p in touched_promises if _promise_row_manual_override(p)),
            "supersede_count": sum(
                1 for p in touched_promises if p.get("superseded_by_promise_id") or p.get("supersedes_promise_ids")
            ),
            "new_promises": [_compact_promise_row(p) for p in new_promises][:8],
            "touched_promises": touched_promises_compact[:12],
            "highlight_promises": highlights,
        },
        "knowledge_snapshot": {
            "total_facts_touching_episode": len(facts_compact),
            "low_confidence_count": sum(1 for f in facts_compact if f.get("confidence") == "low"),
            "audience_only_count": sum(1 for f in facts_compact if f.get("visibility") == "audience_only"),
            "recent_changes_count": sum(
                1
                for f in facts_compact
                if f.get("first_seen_episode") != f.get("last_confirmed_episode")
            ),
            "known_by_cast_count": len(known_by_casts),
            "facts": facts_compact[:16],
        },
        "visual_snapshot": {
            "related_cast_count": len(related_vl_rows),
            "complete_count": vl_counts["complete"],
            "partial_count": vl_counts["partial"],
            "missing_count": vl_counts["missing"],
            "missing_visual_roles": [
                x.get("display_name") for x in related_vl_rows if x.get("visual_state") == "missing"
            ],
            "memory_only_not_in_bible_roles": [
                x.get("display_name")
                for x in related_vl_rows
                if x.get("visual_state") == "missing" and "not_in_bible" in (x.get("missing_items") or [])
            ],
            "cast_rows": related_vl_rows[:16],
        },
        "gate_snapshot": {
            "latest_plot_gate": latest_gate_compact("plot_gate"),
            "latest_package_gate": latest_gate_compact("package_gate"),
            "last_failure_primary_cause": lv.get("last_failure_primary_cause"),
            "repeated_failure_active": bool(trend.get("repeated_same_failure_as_immediate_previous")),
            "recovery_light_hint": trend.get("recovery_light_hint"),
            "rerun_hint_summary": trend.get("rerun_hint_summary"),
        },
        "artifacts_presence": {
            "episode_dir": str(ep_dir),
            "gate_artifact_exists": ep_files["gate_artifacts"].is_file(),
            "carry_registry_exists": reg_path.is_file(),
            "files": file_presence,
            "latest_artifact_update_at": latest_artifact_update,
        },
        "raw_debug": {
            "episode_row": ep_row,
            "trend_summary": trend,
            "latest_verdict": lv,
        },
    }


def build_dashboard_payload(series_dir: Path) -> Dict[str, Any]:
    series_dir = series_dir.resolve()
    paths = resolve_series_paths(series_dir)
    layout = str(paths.get("layout", "flat"))
    reg_path = paths["production_carry_registry"]
    registry, reg_warns, registry_strict_ok = load_registry_readonly(reg_path, series_dir)

    outline = _load_json(paths["series_outline"]) or {}
    episode_list = outline.get("episode_list")
    planned_episodes: Optional[int] = None
    if isinstance(episode_list, list):
        planned_episodes = len(episode_list)

    si = registry.get("series_identity") or {}
    genre_key = str(si.get("genre_key") or "")
    display_title = str(si.get("display_title") or _series_title(paths))
    capabilities = get_genre_capabilities(genre_key or "general")

    sync_meta = registry.get("sync_meta") or {}
    st = registry.get("story_thrust") or {}
    drift_flag = bool(st.get("drift_flag"))

    promises_raw = [
        p for p in ((registry.get("promise_lane") or {}).get("promises") or []) if isinstance(p, dict)
    ]
    summary_counts: Dict[str, int] = {}
    for st_name in ("open", "paid_off", "broken", "stale"):
        summary_counts[st_name] = sum(
            1 for p in promises_raw if (p.get("status") or "open") == st_name
        )
    supersede_digest = {
        "with_superseded_by": sum(1 for p in promises_raw if p.get("superseded_by_promise_id")),
        "with_supersedes_list": sum(1 for p in promises_raw if p.get("supersedes_promise_ids")),
    }
    manual_override_count = sum(1 for p in promises_raw if _promise_row_manual_override(p))

    facts_raw = [
        f for f in ((registry.get("knowledge_fence") or {}).get("facts") or []) if isinstance(f, dict)
    ]
    kf_stats = {
        "total": len(facts_raw),
        "low_confidence": sum(1 for f in facts_raw if f.get("confidence") == "low"),
        "audience_only": sum(1 for f in facts_raw if f.get("visibility") == "audience_only"),
        "recent_changes": sum(
            1
            for f in facts_raw
            if f.get("first_seen_episode") != f.get("last_seen_episode")
        ),
    }

    vl = registry.get("visual_lock_registry") or {}
    vl_chars = [c for c in (vl.get("characters") or []) if isinstance(c, dict)]
    vl_counts = {"complete": 0, "partial": 0, "missing": 0}
    memory_only_names: List[str] = []
    for c in vl_chars:
        lock = str(c.get("lock_status") or "")
        if lock in vl_counts:
            vl_counts[lock] += 1
        if lock == "missing":
            memory_only_names.append(str(c.get("display_name") or c.get("cast_id") or ""))
    denom = len(vl_chars) if vl_chars else 0
    coverage_pct = round(100.0 * vl_counts["complete"] / denom, 1) if denom else None

    relations = [
        r for r in ((registry.get("relation_pressure_map") or {}).get("relations") or []) if isinstance(r, dict)
    ]

    ep_dirs = _iter_episode_dirs(paths["episodes_root"], layout)
    episode_dir_count = len(ep_dirs)
    gate_files_present = 0
    episodes_out: List[Dict[str, Any]] = []
    episode_details: Dict[str, Any] = {}

    for ep_id, ep_dir in ep_dirs:
        ep_files = _episode_json_paths(ep_dir, layout)
        ga_path = ep_files["gate_artifacts"]
        if ga_path.is_file():
            gate_files_present += 1
        doc = load_gate_artifact(ep_dir, layout)
        if "trend_summary" not in doc:
            doc["trend_summary"] = build_gate_trend_summary(doc)
        trend = doc.get("trend_summary") or build_gate_trend_summary(doc)
        lv = trend.get("latest_verdict") or {}

        open_p = sum(
            1
            for p in promises_raw
            if _promise_touches_episode(p, ep_id) and (p.get("status") or "open") == "open"
        )
        stale_p = sum(
            1
            for p in promises_raw
            if _promise_touches_episode(p, ep_id) and (p.get("status") or "") == "stale"
        )
        broken_p = sum(
            1
            for p in promises_raw
            if _promise_touches_episode(p, ep_id) and (p.get("status") or "") == "broken"
        )

        low_k = sum(
            1
            for f in facts_raw
            if f.get("confidence") == "low"
            and (
                _norm_ep_id(f.get("last_seen_episode")) == ep_id
                or _norm_ep_id(f.get("first_seen_episode")) == ep_id
            )
        )

        rel_sig = _relation_signals_for_episode(relations, ep_id)

        episodes_out.append(
            {
                "episode_id": ep_id,
                "title": _episode_title_hint(ep_dir, layout) or f"第{ep_id}集",
                "episode_dir": str(ep_dir),
                "gate_artifact_path": str(ga_path),
                "gate_artifact_exists": ga_path.is_file(),
                "plot_gate_pass": lv.get("plot_gate_pass"),
                "package_gate_pass": lv.get("package_gate_pass"),
                "episode_overall_gate": lv.get("episode_overall_gate"),
                "failure_trend_label": trend.get("failure_trend_label"),
                "repeated_failure_active": bool(trend.get("repeated_same_failure_as_immediate_previous")),
                "rerun_hint_summary": trend.get("rerun_hint_summary"),
                "recovery_light_hint": trend.get("recovery_light_hint"),
                "last_failure_primary_cause": lv.get("last_failure_primary_cause"),
                "open_promise_count": open_p,
                "stale_promise_count": stale_p,
                "broken_promise_count": broken_p,
                "low_confidence_knowledge_count": low_k,
                "visual_lock_incomplete_series": vl_counts["partial"] + vl_counts["missing"],
                "visual_lock_note": "系列级 visual_lock 未完整角色数（非逐集推断）",
                "continuity_risk_signal": rel_sig["continuity_pressure_signal"],
                "relation_touch_count": rel_sig["relation_touch_count"],
                "trend_summary": trend,
            }
        )
        ep_row = episodes_out[-1]
        episode_details[str(ep_id)] = _build_episode_detail(
            ep_row=ep_row,
            ep_dir=ep_dir,
            ep_files=ep_files,
            gate_doc=doc,
            promises_raw=promises_raw,
            facts_raw=facts_raw,
            vl_chars=vl_chars,
            relations=relations,
            reg_path=reg_path,
        )

    last_updates = [
        sync_meta.get("last_full_refresh_at"),
        sync_meta.get("last_incremental_at"),
    ]
    last_updates_s = [x for x in last_updates if isinstance(x, str) and x]

    overview = {
        "series_dir": str(series_dir),
        "layout": layout,
        "display_title": display_title,
        "genre_key": genre_key,
        "capabilities": capabilities,
        "planned_episodes_from_outline": planned_episodes,
        "episode_directories_scanned": episode_dir_count,
        "production_carry_registry_path": str(reg_path),
        "registry_file_exists": reg_path.exists(),
        "registry_strict_validation_ok": registry_strict_ok,
        "gate_artifact_files_present": gate_files_present,
        "gate_artifact_episode_dirs": episode_dir_count,
        "story_thrust_drift_flag": drift_flag,
        "sync_meta": sync_meta,
        "last_refresh_hint": max(last_updates_s) if last_updates_s else None,
    }

    return {
        "schema": "dashboard_readonly.v1",
        "generated_at": _utc_now_iso(),
        "warnings": reg_warns,
        "data_sources_note": "见模块 docstring：dashboard_readonly.py",
        "overview": overview,
        "episodes": episodes_out,
        "episode_details": episode_details,
        "promises": {
            "summary_counts": summary_counts,
            "supersede_digest": supersede_digest,
            "manual_override_count": manual_override_count,
            "promises": promises_raw,
        },
        "knowledge_fence": {
            "stats": kf_stats,
            "facts": facts_raw,
        },
        "visual_lock": {
            "counts": vl_counts,
            "coverage_complete_pct": coverage_pct,
            "memory_only_names": [n for n in memory_only_names if n],
            "characters": vl_chars,
        },
        "relation_pressure": {
            "relations": relations,
        },
    }


def validate_payload_minimal(obj: Dict[str, Any]) -> List[str]:
    """测试用：轻量结构检查。"""
    errs: List[str] = []
    if obj.get("schema") != "dashboard_readonly.v1":
        errs.append("schema")
    if "overview" not in obj or "episodes" not in obj:
        errs.append("missing keys")
    return errs

"""单集 gate 结果沉淀：07_gate_artifacts.json（分层）/ gate_artifacts.json（平铺）。"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .creative_constants import (
    GATE_ARTIFACT_FILENAME_FLAT,
    GATE_ARTIFACT_FILENAME_LAYERED,
    GATE_ARTIFACT_SCHEMA_VERSION,
    GATE_FAILURE_TREND_LABEL_ENUM,
    RERUN_HINT_ENUM,
)


def gate_artifact_filename(layout: str) -> str:
    return GATE_ARTIFACT_FILENAME_LAYERED if layout == "layered" else GATE_ARTIFACT_FILENAME_FLAT


def gate_artifact_path(ep_dir: Path, layout: str) -> Path:
    return ep_dir / gate_artifact_filename(layout)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_gate_artifact_location(episodes_root: Path, artifact_path: Path) -> None:
    """确保落盘在 episodes_root 下且为允许的 gate 文件名。"""
    er = episodes_root.resolve()
    ar = artifact_path.resolve()
    ar.relative_to(er)
    name = ar.name
    if name not in (GATE_ARTIFACT_FILENAME_LAYERED, GATE_ARTIFACT_FILENAME_FLAT):
        raise PermissionError(f"非法 gate artifact 文件名: {name}")


def gate_failure_fingerprint(entry: Dict[str, Any]) -> str:
    """基于 must_fix / issues / summary 的稳定指纹；pass 时为空。"""
    if entry.get("pass"):
        return ""
    parts: List[str] = []
    for k in ("must_fix", "must_fix_for_plot", "issues"):
        v = entry.get(k) or []
        if isinstance(v, list):
            parts.extend(str(x).strip() for x in v[:16] if x is not None)
        elif v is not None:
            parts.append(str(v).strip())
    parts.append(str(entry.get("summary") or "")[:320])
    blob = "|".join(parts)
    if not blob.strip():
        return ""
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:20]


def gate_rerun_hint(gate_type: str, entry: Dict[str, Any]) -> str:
    """规则式编排提示；保守、可解释。"""
    if entry.get("pass"):
        return "none"
    blob = str(entry.get("summary") or "")
    mf = entry.get("must_fix") or []
    iss = entry.get("issues") or []
    if isinstance(mf, list):
        blob += " " + " ".join(str(x) for x in mf[:8])
    if isinstance(iss, list):
        blob += " " + " ".join(str(x) for x in iss[:8])
    if gate_type == "plot_gate":
        if any(k in blob for k in ("分镜", "镜头", "storyboard", "对白密度", "脚本")):
            return "rerun_script_and_storyboard"
        if any(k in blob for k in ("function", "刚需", "episode_function", "功能设计")):
            return "rerun_episode_function_and_plot"
        return "rerun_plot_only"
    if gate_type == "package_gate":
        if any(k in blob for k in ("plot", "结构", "伏笔", "logic")) and any(
            k in blob for k in ("function", "功能", "刚需")
        ):
            return "rerun_episode_function_and_plot"
        if any(k in blob for k in ("分镜", "镜头", "视觉")):
            return "rerun_script_and_storyboard"
        return "rerun_package_only"
    if "人工" in blob or "审核" in blob or "停" in blob:
        return "manual_review_first"
    return "manual_review_first"


def _enrich_gate_entry(entry: Dict[str, Any]) -> None:
    entry["failure_signature"] = gate_failure_fingerprint(entry)
    hint = gate_rerun_hint(str(entry.get("gate_type") or ""), entry)
    entry["rerun_hint"] = hint if hint in RERUN_HINT_ENUM else "manual_review_first"


def compact_gate_entry_for_query(entry: Dict[str, Any]) -> Dict[str, Any]:
    """供 query.gate_trend 输出的精简失败/通过条目。"""
    _enrich_gate_entry(entry)
    return {
        "gate_type": entry.get("gate_type"),
        "pass": bool(entry.get("pass")),
        "generated_at": entry.get("generated_at"),
        "failure_signature": entry.get("failure_signature") or "",
        "rerun_hint": entry.get("rerun_hint"),
        "primary_cause": _primary_failure_cause(entry) or None,
    }


def _primary_failure_cause(entry: Optional[Dict[str, Any]]) -> str:
    if not entry or entry.get("pass"):
        return ""
    mf = entry.get("must_fix") or []
    if isinstance(mf, list) and mf:
        return str(mf[0])[:300]
    iss = entry.get("issues") or []
    if isinstance(iss, list) and iss:
        return str(iss[0])[:300]
    mfp = entry.get("must_fix_for_plot") or []
    if isinstance(mfp, list) and mfp:
        return str(mfp[0])[:300]
    return str(entry.get("summary") or "")[:300]


def _failure_trend_label(entries: List[Dict[str, Any]]) -> str:
    if not entries:
        return "no_runs"
    last = entries[-1]
    if len(entries) == 1:
        return "stable_pass" if last.get("pass") else "first_failure"
    prev = entries[-2]
    if last.get("pass") and not prev.get("pass"):
        return "recovered_after_failure"
    if not last.get("pass") and not prev.get("pass"):
        sa = gate_failure_fingerprint(last)
        sb = gate_failure_fingerprint(prev)
        if sa and sb and sa == sb:
            return "repeated_same_failure"
        return "shifted_failure_type"
    if not last.get("pass") and prev.get("pass"):
        return "intermittent_failures"
    if last.get("pass") and prev.get("pass"):
        return "stable_pass"
    return "intermittent_failures"


def build_gate_trend_summary(doc: Dict[str, Any]) -> Dict[str, Any]:
    entries = [e for e in (doc.get("entries") or []) if isinstance(e, dict)]

    def latest_of(gt: str) -> Optional[Dict[str, Any]]:
        for e in reversed(entries):
            if e.get("gate_type") == gt:
                return e
        return None

    latest_plot = latest_of("plot_gate")
    latest_pkg = latest_of("package_gate")

    def slim(e: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not e:
            return None
        _enrich_gate_entry(e)
        return {
            "gate_type": e.get("gate_type"),
            "pass": bool(e.get("pass")),
            "generated_at": e.get("generated_at"),
            "overall_score_1to10": e.get("overall_score_1to10"),
            "failure_signature": e.get("failure_signature") or "",
            "rerun_hint": e.get("rerun_hint"),
            "summary_one_line": str(e.get("summary") or "")[:280],
        }

    sp, sk = slim(latest_plot), slim(latest_pkg)
    overall = "pass"
    if latest_plot and latest_pkg:
        lp, kp = bool(latest_plot.get("pass")), bool(latest_pkg.get("pass"))
        if lp and kp:
            overall = "pass"
        elif not lp and not kp:
            overall = "fail"
        else:
            overall = "partial"
    elif latest_plot:
        overall = "pass" if latest_plot.get("pass") else "fail"
    elif latest_pkg:
        overall = "pass" if latest_pkg.get("pass") else "fail"

    times: List[str] = []
    for e in (latest_plot, latest_pkg):
        if e and e.get("generated_at"):
            times.append(str(e["generated_at"]))
    latest_gen = max(times) if times else None

    latest_fail_sig = ""
    if latest_pkg and not latest_pkg.get("pass"):
        latest_fail_sig = latest_pkg.get("failure_signature") or gate_failure_fingerprint(latest_pkg)
    elif latest_plot and not latest_plot.get("pass"):
        latest_fail_sig = latest_plot.get("failure_signature") or gate_failure_fingerprint(latest_plot)

    consec = 0
    if latest_fail_sig:
        for e in reversed(entries):
            if e.get("pass"):
                break
            fs = e.get("failure_signature") or gate_failure_fingerprint(e)
            if fs == latest_fail_sig:
                consec += 1
            else:
                break

    prev_sig = None
    repeated_immediate = False
    if len(entries) >= 2:
        a, b = entries[-1], entries[-2]
        if not a.get("pass") and not b.get("pass"):
            sa = a.get("failure_signature") or gate_failure_fingerprint(a)
            sb = b.get("failure_signature") or gate_failure_fingerprint(b)
            repeated_immediate = bool(sa and sa == sb)
            prev_sig = sb

    latest_fail_entry = None
    if latest_pkg and not latest_pkg.get("pass"):
        latest_fail_entry = latest_pkg
    elif latest_plot and not latest_plot.get("pass"):
        latest_fail_entry = latest_plot

    primary_cause = _primary_failure_cause(latest_fail_entry)
    last_hint = ""
    if latest_fail_entry:
        _enrich_gate_entry(latest_fail_entry)
        last_hint = str(latest_fail_entry.get("rerun_hint") or "")

    ftl = _failure_trend_label(entries)
    if ftl not in GATE_FAILURE_TREND_LABEL_ENUM:
        ftl = "intermittent_failures"

    recovery_hint = ""
    if len(entries) >= 2 and entries[-1].get("pass") and not entries[-2].get("pass"):
        recovery_hint = "最近一次 gate 已通过；若业务允许可继续下游，或按需抽查上一轮失败点。"

    same_class_as_previous = None
    if len(entries) >= 2:
        a, b = entries[-1], entries[-2]
        if not a.get("pass") and not b.get("pass"):
            sa = a.get("failure_signature") or gate_failure_fingerprint(a)
            sb = b.get("failure_signature") or gate_failure_fingerprint(b)
            same_class_as_previous = bool(sa and sb and sa == sb)

    return {
        "latest_plot_gate": sp,
        "latest_package_gate": sk,
        "latest_overall_pass_state": overall,
        "latest_generated_at": latest_gen,
        "latest_failure_signature": latest_fail_sig or None,
        "consecutive_same_failure_count": consec,
        "total_entries": len(entries),
        "repeated_same_failure_as_immediate_previous": repeated_immediate,
        "previous_entry_failure_signature": prev_sig,
        "failure_trend_label": ftl,
        "latest_failure_same_class_as_previous_failure": same_class_as_previous,
        "latest_verdict": {
            "plot_gate_pass": bool(latest_plot.get("pass")) if latest_plot else None,
            "package_gate_pass": bool(latest_pkg.get("pass")) if latest_pkg else None,
            "episode_overall_gate": overall,
            "last_failure_primary_cause": primary_cause or None,
            "last_suggested_rerun_hint": last_hint or None,
        },
        "recovery_light_hint": recovery_hint or None,
        "rerun_hint_summary": last_hint or None,
    }


def load_gate_artifact(ep_dir: Path, layout: str) -> Dict[str, Any]:
    p = gate_artifact_path(ep_dir, layout)
    if not p.is_file():
        return {
            "schema_version": GATE_ARTIFACT_SCHEMA_VERSION,
            "episode_id": None,
            "entries": [],
            "trend_summary": build_gate_trend_summary({"entries": []}),
        }
    doc = json.loads(p.read_text(encoding="utf-8"))
    if "trend_summary" not in doc:
        doc["trend_summary"] = build_gate_trend_summary(doc)
    return doc


def append_gate_entry(
    *,
    episodes_root: Path,
    ep_dir: Path,
    layout: str,
    episode_id: int,
    gate_type: str,
    gate_result: Dict[str, Any],
    generator: str,
    source_inputs: Dict[str, str],
) -> Path:
    path = gate_artifact_path(ep_dir, layout)
    validate_gate_artifact_location(episodes_root, path)

    doc = load_gate_artifact(ep_dir, layout)
    doc["schema_version"] = GATE_ARTIFACT_SCHEMA_VERSION
    doc["episode_id"] = episode_id

    issues: List[Any] = []
    must_fix: List[Any] = []
    must_fix_plot: List[Any] = []
    if isinstance(gate_result, dict):
        issues = list(gate_result.get("issues") or [])
        must_fix = list(gate_result.get("must_fix") or [])
        must_fix_plot = list(gate_result.get("must_fix_for_plot") or [])

    entry: Dict[str, Any] = {
        "gate_type": gate_type,
        "episode_id": episode_id,
        "pass": bool(gate_result.get("pass")) if isinstance(gate_result, dict) else False,
        "overall_score_1to10": int(gate_result.get("overall_score_1to10") or 0)
        if isinstance(gate_result, dict)
        else 0,
        "summary": str(gate_result.get("summary", "") if isinstance(gate_result, dict) else ""),
        "issues": issues,
        "must_fix": must_fix,
        "must_fix_for_plot": must_fix_plot,
        "generated_at": _utc_iso(),
        "generator": generator,
        "source_inputs": source_inputs,
        "schema_version": GATE_ARTIFACT_SCHEMA_VERSION,
        "raw_gate_result": gate_result if isinstance(gate_result, dict) else {},
    }
    _enrich_gate_entry(entry)

    entries = list(doc.get("entries") or [])
    entries.append(entry)
    doc["entries"] = entries[-30:]
    doc["trend_summary"] = build_gate_trend_summary(doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def summarize_gate_artifact(doc: Dict[str, Any]) -> Dict[str, Any]:
    trend = build_gate_trend_summary(doc)
    entries = doc.get("entries") or []
    latest_plot = None
    latest_pkg = None
    for e in reversed(entries):
        if not isinstance(e, dict):
            continue
        gt = e.get("gate_type")
        if gt == "plot_gate" and latest_plot is None:
            latest_plot = e
        if gt == "package_gate" and latest_pkg is None:
            latest_pkg = e
        if latest_plot and latest_pkg:
            break
    return {
        "schema_version": doc.get("schema_version"),
        "episode_id": doc.get("episode_id"),
        "latest_plot_gate": latest_plot,
        "latest_package_gate": latest_pkg,
        "total_entries": len(entries),
        "trend_summary": trend,
        "trend_summary_stored": doc.get("trend_summary"),
    }

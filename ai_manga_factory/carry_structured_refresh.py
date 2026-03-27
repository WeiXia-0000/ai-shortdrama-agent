"""
promise_lane / relation_pressure_map 结构化刷新（可解释、偏保守）。
不引入 NLP 模型；仅基于 episode_function、plot.logic_check、anchor_beats、series_memory 等已有 JSON。
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .creative_constants import (
    CARRY_KNOWLEDGE_FENCE_SCHEMA_NOTE,
    CARRY_PROMISE_SCHEMA_NOTE,
    CARRY_RELATION_SCHEMA_NOTE,
    KNOWLEDGE_CONFIDENCE_ENUM,
    KNOWLEDGE_FACT_STATUS_ENUM,
    PRESSURE_TAGS_VOCAB,
    RELATION_CURRENT_STATE_ENUM,
    STALE_PROMISE_EPISODE_WINDOW,
)


def _slug(n: str) -> str:
    x = re.sub(r"[^\w\u4e00-\u9fff]+", "_", (n or "").strip())
    return x[:48] or "x"


def _norm(s: Any) -> str:
    if not isinstance(s, str):
        s = str(s or "")
    return re.sub(r"\s+", "", s.strip())


def _logic_check_text(plot: Dict[str, Any]) -> str:
    lc = plot.get("logic_check")
    if isinstance(lc, str):
        return lc
    if not isinstance(lc, dict):
        return ""
    parts: List[str] = []
    for v in lc.values():
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            parts.extend(str(x) for x in v if x is not None)
    return "\n".join(parts)


def _acts_blob(plot: Dict[str, Any]) -> str:
    acts = plot.get("acts") or []
    if not isinstance(acts, list):
        return ""
    lines: List[str] = []
    for a in acts:
        if not isinstance(a, dict):
            continue
        for b in a.get("beats") or []:
            lines.append(str(b))
    return "\n".join(lines)


def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _episode_row_from_outline(paths: Dict[str, Any], ep_id: int) -> Dict[str, Any]:
    p = paths.get("series_outline")
    if p is None:
        return {}
    pp = Path(p)
    if not pp.is_file():
        return {}
    data = _load_json(pp) or {}
    for ep in data.get("episode_list") or []:
        if not isinstance(ep, dict):
            continue
        try:
            if int(ep.get("episode_id") or -1) == ep_id:
                return ep
        except (TypeError, ValueError):
            continue
    return {}


def _stable_payoff_compound_key(payoff_id: str) -> str:
    raw = f"payoff_id|{_norm(payoff_id)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:18]


def _stable_setup_compound_key(setup_id: str) -> str:
    raw = f"setup_id|{_norm(setup_id)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:18]


def _extract_payoff_setup_ids_from_episode_function(fn: Dict[str, Any]) -> Tuple[Set[str], Set[str]]:
    payoff_ids: Set[str] = set()
    setup_ids: Set[str] = set()
    vpd = fn.get("viewer_payoff_design") or []
    if isinstance(vpd, list):
        for item in vpd:
            if not isinstance(item, dict):
                continue
            pid = str(item.get("payoff_id") or "").strip()
            if pid:
                payoff_ids.add(pid)
            sid = str(item.get("setup_source_id") or "").strip()
            if sid:
                setup_ids.add(sid)
            for ls in item.get("linked_setup_ids") or []:
                if str(ls).strip():
                    setup_ids.add(str(ls).strip())
    fti = fn.get("future_threads_strengthened_items") or []
    if isinstance(fti, list):
        for item in fti:
            if isinstance(item, dict) and str(item.get("setup_id") or "").strip():
                setup_ids.add(str(item["setup_id"]).strip())
    return payoff_ids, setup_ids


def _collect_global_payoff_setup_id_refs(
    paths: Dict[str, Any],
    layout: str,
    ep_dirs: List[Tuple[int, Path]],
) -> Tuple[Set[str], Set[str]]:
    """全剧扫描：任意结构化产物仍引用某 payoff_id/setup_id 则用于 stale 保护。"""
    payoff_ids: Set[str] = set()
    setup_ids: Set[str] = set()
    op = paths.get("series_outline")
    if op and Path(op).is_file():
        data = _load_json(Path(op)) or {}
        for ep in data.get("episode_list") or []:
            if not isinstance(ep, dict):
                continue
            for it in ep.get("must_payoff_items") or []:
                if isinstance(it, dict) and str(it.get("payoff_id") or "").strip():
                    payoff_ids.add(str(it["payoff_id"]).strip())
            for it in ep.get("must_set_up_items") or []:
                if isinstance(it, dict) and str(it.get("setup_id") or "").strip():
                    setup_ids.add(str(it["setup_id"]).strip())
    fn_name = "01_episode_function.json" if layout == "layered" else "episode_function.json"
    pkg_name = "06_package.json" if layout == "layered" else "package.json"
    for _ep_id, d in ep_dirs:
        fn = _load_json(d / fn_name) or {}
        pids, sids = _extract_payoff_setup_ids_from_episode_function(fn)
        payoff_ids |= pids
        setup_ids |= sids
        pkg = _load_json(d / pkg_name)
        if isinstance(pkg, dict):
            ef2 = pkg.get("episode_function")
            if isinstance(ef2, dict):
                p2, s2 = _extract_payoff_setup_ids_from_episode_function(ef2)
                payoff_ids |= p2
                setup_ids |= s2
    return payoff_ids, setup_ids


def _iter_episode_dirs(episodes_root: Path, layout: str) -> List[Tuple[int, Path]]:
    if not episodes_root.is_dir():
        return []
    fn_ef = "01_episode_function.json" if layout == "layered" else "episode_function.json"
    rows: List[Tuple[int, Path]] = []
    for d in sorted(episodes_root.iterdir(), key=lambda p: p.name):
        if not d.is_dir():
            continue
        m = re.search(r"第(\d+)集", d.name)
        if not m:
            continue
        ep_id = int(m.group(1))
        if (d / fn_ef).is_file():
            rows.append((ep_id, d))
    rows.sort(key=lambda x: x[0])
    return rows


def _anchor_promises(anchor_path: Path) -> Dict[str, Dict[str, Any]]:
    data = _load_json(anchor_path) or {}
    out: Dict[str, Dict[str, Any]] = {}
    for a in data.get("anchors") or []:
        if not isinstance(a, dict):
            continue
        aid = a.get("anchor_id")
        if aid is None:
            continue
        sid = str(aid)
        out[sid] = {
            "anchor_name": str(a.get("anchor_name") or ""),
            "long_term_outputs": [str(x) for x in (a.get("long_term_outputs") or []) if x],
            "must_be_true_conditions": [
                str(x) for x in (a.get("must_be_true_conditions") or []) if x
            ],
        }
    return out


def _overlap_substring(a: str, b: str, min_len: int = 8) -> bool:
    if len(a) < min_len or len(b) < min_len:
        return bool(a and a in b) or bool(b and b in a)
    for i in range(0, len(a) - min_len + 1):
        chunk = a[i : i + min_len]
        if chunk in b:
            return True
    return False


def _collect_episode_signals(ep_id: int, fn: Dict[str, Any], plot: Dict[str, Any]) -> str:
    parts: List[str] = []
    for k in (
        "must_advance",
        "must_inherit",
        "what_changes_persistently",
        "what_is_mislearned",
        "what_is_learned",
        "what_is_lost",
        "future_threads_strengthened",
    ):
        v = fn.get(k)
        if isinstance(v, list):
            parts.extend(str(x) for x in v)
        elif isinstance(v, str) and v.strip():
            parts.append(v)
    parts.append(_logic_check_text(plot))
    parts.append(_acts_blob(plot))
    return _norm("".join(parts))


PAYOFF_STRONG = (
    "回收",
    "闭环",
    "兑现",
    "落实",
    "落地",
    "成立",
    "奏效",
    "已完成",
    "达成目标",
)
BROKEN_EXPLICIT = (
    "死亡",
    "身亡",
    "殒命",
    "遇难",
    "殉",
    "病逝",
    "失踪",
    "人间蒸发",
    "决裂",
    "恩断",
    "分道扬镳",
    "撕破脸",
    "主线改道",
    "推翻设定",
    "永久失效",
    "无法再兑现",
    "彻底失败",
)
BROKEN_SOFT = ("未能兑现", "落空", "失效", "破裂", "崩盘")


def _logic_check_longterm_blob(plot: Dict[str, Any]) -> str:
    lc = plot.get("logic_check")
    if isinstance(lc, dict):
        v = lc.get("what_new_longterm_change_is_created")
        if isinstance(v, str) and v.strip():
            return v
        if isinstance(v, list):
            return "\n".join(str(x) for x in v if x is not None)
    return ""


def _compound_promise_key(
    setup_source: str,
    payoff_target: str,
    description: str,
    source_type: str,
    source_stage: str,
    linked_anchor_ids: List[Any],
) -> str:
    anchors = "|".join(sorted(str(a) for a in (linked_anchor_ids or [])))
    body = "|".join(
        [
            _norm(setup_source),
            _norm(payoff_target),
            _norm(description)[:260],
            _norm(source_type),
            str(source_stage or ""),
            anchors,
        ]
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:18]


def _weak_identity_token(
    setup_source: str,
    payoff_target: str,
    linked_anchor_ids: List[Any],
) -> str:
    anchors = "|".join(sorted(str(a) for a in (linked_anchor_ids or [])))
    ss, pt = _norm(setup_source), _norm(payoff_target)
    if len(ss) < 2 and len(pt) < 2 and not anchors:
        return ""
    raw = f"{ss}|{pt}|{anchors}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:14]


def _desc_overlap(a: str, b: str, n: int = 12) -> bool:
    an, bn = _norm(a), _norm(b)
    if not an or not bn:
        return False
    if len(an) < 4 or len(bn) < 4:
        return an == bn
    if an in bn or bn in an:
        return True
    n_eff = min(n, len(an), len(bn))
    if n_eff < 8:
        return False
    return an[:n_eff] in bn or bn[:n_eff] in an


def _evidence_blob_for_episode(d: Path, layout: str) -> str:
    ef = _load_json(d / ("01_episode_function.json" if layout == "layered" else "episode_function.json")) or {}
    plot = _load_json(d / ("02_plot.json" if layout == "layered" else "plot.json")) or {}
    parts: List[str] = []
    parts.append(_logic_check_longterm_blob(plot))
    parts.append(_logic_check_text(plot))
    parts.append(_acts_blob(plot))
    fts = ef.get("future_threads_strengthened") or []
    if isinstance(fts, list):
        parts.extend(str(x) for x in fts)
    pkg = _load_json(d / ("06_package.json" if layout == "layered" else "package.json"))
    if isinstance(pkg, dict):
        ef2 = pkg.get("episode_function")
        if isinstance(ef2, dict):
            for k in (
                "what_is_learned",
                "must_advance",
                "viewer_payoff_design",
                "future_threads_strengthened",
            ):
                v = ef2.get(k)
                if isinstance(v, list):
                    parts.extend(str(x) for x in v)
                elif isinstance(v, str):
                    parts.append(v)
        for k in ("summary", "package_notes", "one_line", "notes"):
            v = pkg.get(k)
            if isinstance(v, str):
                parts.append(v)
    sc = _load_json(d / ("03_script.json" if layout == "layered" else "script.json"))
    if isinstance(sc, dict):
        for k in ("summary", "beat_summary", "episode_logline", "logline"):
            v = sc.get(k)
            if isinstance(v, str):
                parts.append(v)
    sb = _load_json(d / ("04_storyboard.json" if layout == "layered" else "storyboard.json"))
    if isinstance(sb, dict):
        for k in ("summary", "panel_outline", "notes"):
            v = sb.get(k)
            if isinstance(v, str):
                parts.append(v)
    return _norm("".join(parts))


def _promise_text_in_evidence(desc: str, payoff: str, setup: str, ev: str) -> bool:
    dn = _norm(desc)
    if len(dn) >= 10 and dn[:10] in ev:
        return True
    pt, st = _norm(payoff), _norm(setup)
    if len(pt) >= 6 and pt in ev:
        return True
    if len(st) >= 6 and st in ev:
        return True
    if len(dn) >= 14:
        upper = min(len(dn) - 13, 96)
        for i in range(0, max(upper, 1), 4):
            chunk = dn[i : i + 14]
            if chunk in ev:
                return True
    return False


def refresh_promise_lane_structured(
    registry: Dict[str, Any],
    *,
    paths: Dict[str, Any],
    layout: str,
    source: str,
    meta_row: Dict[str, str],
) -> None:
    episodes_root: Path = paths["episodes_root"]
    anchor_path = paths.get("anchor_beats")
    anchors = _anchor_promises(anchor_path) if anchor_path and anchor_path.exists() else {}

    prev_promises = list((registry.get("promise_lane") or {}).get("promises") or [])
    locked_by_pid = {
        str(p["promise_id"]): p
        for p in prev_promises
        if isinstance(p, dict) and p.get("promise_id") and p.get("manual_status_lock")
    }
    locked_by_ck = {
        str(p.get("compound_key")): p
        for p in prev_promises
        if isinstance(p, dict) and p.get("manual_status_lock") and p.get("compound_key")
    }

    by_ck: Dict[str, Dict[str, Any]] = {}
    ep_dirs = _iter_episode_dirs(episodes_root, layout)
    max_ep = max((e for e, _ in ep_dirs), default=0)
    global_payoff_ids, global_setup_ids = _collect_global_payoff_setup_id_refs(paths, layout, ep_dirs)

    def upsert_row(row: Dict[str, Any]) -> None:
        ck = row["compound_key"]
        wit = row.get("weak_identity_token") or ""
        if ck in by_ck:
            ex = by_ck[ck]
            le = list(ex.get("linked_episode_ids") or [])
            for x in row.get("linked_episode_ids") or []:
                if x not in le:
                    le.append(x)
            ex["linked_episode_ids"] = sorted(set(le))
            ex["last_seen_episode"] = max(
                ex.get("last_seen_episode") or 0, row.get("last_seen_episode") or 0
            )
            la = list(set(ex.get("linked_anchor_ids") or []) | set(row.get("linked_anchor_ids") or []))
            ex["linked_anchor_ids"] = sorted(la, key=lambda x: int(x) if str(x).isdigit() else 0)
            return
        if wit:
            for ex in list(by_ck.values()):
                if ex.get("weak_identity_token") != wit:
                    continue
                if ex["compound_key"] == ck:
                    continue
                if not _desc_overlap(
                    str(ex.get("description") or ""),
                    str(row.get("description") or ""),
                    12,
                ):
                    continue
                ld, rd = str(ex.get("description") or ""), str(row.get("description") or "")
                ex["description"] = ld if len(ld) >= len(rd) else rd
                le = list(set((ex.get("linked_episode_ids") or []) + (row.get("linked_episode_ids") or [])))
                ex["linked_episode_ids"] = sorted(le)
                ex["last_seen_episode"] = max(
                    ex.get("last_seen_episode") or 0, row.get("last_seen_episode") or 0
                )
                la = list(set(ex.get("linked_anchor_ids") or []) | set(row.get("linked_anchor_ids") or []))
                ex["linked_anchor_ids"] = sorted(la, key=lambda x: int(x) if str(x).isdigit() else 0)
                ex.setdefault("decision_trace", []).append(
                    "weak_identity_merge: setup/payoff/anchors 一致且 description 重叠，合并为单条"
                )
                return
        by_ck[ck] = row

    for ep_id, d in ep_dirs:
        fn_path = d / ("01_episode_function.json" if layout == "layered" else "episode_function.json")
        pl_path = d / ("02_plot.json" if layout == "layered" else "plot.json")
        fn = _load_json(fn_path) or {}
        plot = _load_json(pl_path) or {}

        outline_row = _episode_row_from_outline(paths, ep_id)
        for oitem in outline_row.get("must_payoff_items") or []:
            if not isinstance(oitem, dict):
                continue
            payoff_id_o = str(oitem.get("payoff_id") or "").strip()
            if not payoff_id_o:
                continue
            desc_o = str(oitem.get("description") or "")[:800]
            deadline_o = str(oitem.get("deadline") or "")
            ck_o = _stable_payoff_compound_key(payoff_id_o)
            row_o: Dict[str, Any] = {
                "promise_id": f"payoff:{payoff_id_o}",
                "compound_key": ck_o,
                "weak_identity_token": "",
                "created_episode": ep_id,
                "source_stage": "series_outline",
                "source_type": "outline_must_payoff",
                "setup_source": "",
                "setup_source_id": "",
                "payoff_target": f"[deadline={deadline_o}]" if deadline_o else "",
                "payoff_id": payoff_id_o,
                "setup_id": "",
                "linked_setup_ids": [],
                "description": desc_o if desc_o.strip() else f"[outline] payoff_id={payoff_id_o}",
                "source_ids": ["outline.must_payoff_items"],
                "status": "open",
                "last_seen_episode": ep_id,
                "resolved_episode": None,
                "stale_reason": None,
                "linked_anchor_ids": [],
                "linked_episode_ids": [ep_id],
                "linked_beat_refs": [],
                "decision_trace": [],
                "manual_status_lock": False,
            }
            row_o.update(meta_row)
            upsert_row(row_o)

        for oitem in outline_row.get("must_set_up_items") or []:
            if not isinstance(oitem, dict):
                continue
            setup_id_o = str(oitem.get("setup_id") or "").strip()
            if not setup_id_o:
                continue
            desc_o = str(oitem.get("description") or "")[:500]
            ck_s = _stable_setup_compound_key(setup_id_o)
            row_s: Dict[str, Any] = {
                "promise_id": f"setup:{setup_id_o}",
                "compound_key": ck_s,
                "weak_identity_token": "",
                "created_episode": ep_id,
                "source_stage": "series_outline",
                "source_type": "outline_setup",
                "setup_source": "",
                "setup_source_id": "",
                "payoff_target": "",
                "payoff_id": "",
                "setup_id": setup_id_o,
                "linked_setup_ids": [],
                "description": desc_o if desc_o.strip() else f"[outline] setup_id={setup_id_o}",
                "source_ids": ["outline.must_set_up_items"],
                "status": "open",
                "last_seen_episode": ep_id,
                "resolved_episode": None,
                "stale_reason": None,
                "linked_anchor_ids": [],
                "linked_episode_ids": [ep_id],
                "linked_beat_refs": [],
                "decision_trace": [],
                "manual_status_lock": False,
            }
            row_s.update(meta_row)
            upsert_row(row_s)

        vpd = fn.get("viewer_payoff_design") or []
        if isinstance(vpd, list):
            for item in vpd:
                if not isinstance(item, dict):
                    continue
                desc = str(item.get("description") or item.get("statement") or "")[:800]
                payoff_id = str(item.get("payoff_id") or "").strip()
                if not desc.strip() and not payoff_id:
                    continue
                setup = str(item.get("setup_source") or "")
                payoff = str(item.get("payoff_target") or "")
                setup_source_id = str(item.get("setup_source_id") or "").strip()
                linked_setup_ids = item.get("linked_setup_ids") or []
                linked_blob = ""
                if isinstance(linked_setup_ids, list):
                    linked_list = [str(x).strip() for x in linked_setup_ids if str(x).strip()]
                    if linked_list:
                        linked_blob = ",".join(sorted(set(linked_list)))

                if setup_source_id:
                    setup = f"[setup_id={setup_source_id}] {setup}"
                if payoff_id:
                    payoff = f"[payoff_id={payoff_id}] {payoff}"
                if linked_blob:
                    desc = (desc + f" [linked_setup_ids={linked_blob}]")[:800]
                if not str(desc).strip() and payoff_id:
                    desc = f"[episode_function] payoff_id={payoff_id}"
                stype = str(item.get("type") or "viewer_payoff")
                linked_anchors = []
                for aid, info in anchors.items():
                    blob = "\n".join(
                        info.get("long_term_outputs", [])
                        + info.get("must_be_true_conditions", [])
                    )
                    if blob and _overlap_substring(_norm(desc)[:40], _norm(blob), 6):
                        linked_anchors.append(aid)
                if payoff_id:
                    ck = _stable_payoff_compound_key(payoff_id)
                    promise_id_val = f"payoff:{payoff_id}"
                    wit = _weak_identity_token(setup, payoff, linked_anchors)
                else:
                    ck = _compound_promise_key(setup, payoff, desc, stype, "episode_function", linked_anchors)
                    promise_id_val = f"p_{ck}"
                    wit = _weak_identity_token(setup, payoff, linked_anchors)
                row = {
                    "promise_id": promise_id_val,
                    "compound_key": ck,
                    "weak_identity_token": wit,
                    "created_episode": ep_id,
                    "source_stage": "episode_function",
                    "source_type": stype,
                    "setup_source": setup,
                    "setup_source_id": setup_source_id,
                    "payoff_target": payoff,
                    "payoff_id": payoff_id,
                    "setup_id": "",
                    "linked_setup_ids": linked_setup_ids if isinstance(linked_setup_ids, list) else [],
                    "description": desc,
                    "source_ids": ["episode_function.viewer_payoff_design"],
                    "status": "open",
                    "last_seen_episode": ep_id,
                    "resolved_episode": None,
                    "stale_reason": None,
                    "linked_anchor_ids": linked_anchors,
                    "linked_episode_ids": [ep_id],
                    "linked_beat_refs": [],
                    "decision_trace": [],
                    "manual_status_lock": False,
                }
                row.update(meta_row)
                upsert_row(row)

        fti = fn.get("future_threads_strengthened_items") or []
        if isinstance(fti, list):
            for item in fti:
                if not isinstance(item, dict):
                    continue
                setup_id = str(item.get("setup_id") or "").strip()
                desc = str(item.get("description") or "")[:500]
                if setup_id:
                    ck = _stable_setup_compound_key(setup_id)
                    row = {
                        "promise_id": f"setup:{setup_id}",
                        "compound_key": ck,
                        "weak_identity_token": "",
                        "created_episode": ep_id,
                        "source_stage": "episode_function",
                        "source_type": "future_thread_item",
                        "setup_source": "",
                        "setup_source_id": "",
                        "payoff_target": str(item.get("payoff_window") or ""),
                        "payoff_id": "",
                        "setup_id": setup_id,
                        "linked_setup_ids": [],
                        "description": desc if desc.strip() else f"[fts_item] setup_id={setup_id}",
                        "source_ids": ["episode_function.future_threads_strengthened_items"],
                        "status": "open",
                        "last_seen_episode": ep_id,
                        "resolved_episode": None,
                        "stale_reason": None,
                        "linked_anchor_ids": [],
                        "linked_episode_ids": [ep_id],
                        "linked_beat_refs": [],
                        "decision_trace": [],
                        "manual_status_lock": False,
                    }
                    row.update(meta_row)
                    upsert_row(row)
                elif len(desc.strip()) >= 6:
                    setup, payoff, stype = "", "", "future_thread_item_str"
                    ck = _compound_promise_key(setup, payoff, desc, stype, "episode_function", [])
                    row = {
                        "promise_id": f"p_{ck}",
                        "compound_key": ck,
                        "weak_identity_token": "",
                        "created_episode": ep_id,
                        "source_stage": "episode_function",
                        "source_type": "future_thread",
                        "setup_source": "future_threads_strengthened_items",
                        "payoff_target": "",
                        "payoff_id": "",
                        "setup_id": "",
                        "description": desc[:500],
                        "status": "open",
                        "last_seen_episode": ep_id,
                        "resolved_episode": None,
                        "stale_reason": None,
                        "linked_anchor_ids": [],
                        "linked_episode_ids": [ep_id],
                        "linked_beat_refs": [],
                        "decision_trace": [],
                        "manual_status_lock": False,
                    }
                    row.update(meta_row)
                    upsert_row(row)

        fts = fn.get("future_threads_strengthened") or []
        if isinstance(fts, list):
            for thread in fts:
                t = str(thread).strip()
                if len(t) < 6:
                    continue
                setup, payoff, stype = "", "", "future_thread"
                ck = _compound_promise_key(setup, payoff, t, stype, "episode_function", [])
                row = {
                    "promise_id": f"p_{ck}",
                    "compound_key": ck,
                    "weak_identity_token": "",
                    "created_episode": ep_id,
                    "source_stage": "episode_function",
                    "source_type": stype,
                    "setup_source": "future_threads_strengthened",
                    "payoff_target": "",
                    "payoff_id": "",
                    "setup_id": "",
                    "description": t[:500],
                    "status": "open",
                    "last_seen_episode": ep_id,
                    "resolved_episode": None,
                    "stale_reason": None,
                    "linked_anchor_ids": [],
                    "linked_episode_ids": [ep_id],
                    "linked_beat_refs": [],
                    "decision_trace": [],
                    "manual_status_lock": False,
                }
                row.update(meta_row)
                upsert_row(row)

        ndesc_prefix = 10
        for row in by_ck.values():
            if row.get("status") not in (None, "open"):
                continue
            desc_n = _norm(row.get("description") or "")
            sig = _collect_episode_signals(ep_id, fn, plot)
            if len(desc_n) >= ndesc_prefix and desc_n[:ndesc_prefix] in sig:
                row["last_seen_episode"] = max(row.get("last_seen_episode") or ep_id, ep_id)

    for ep_id, d in ep_dirs:
        if not by_ck:
            break
        ev = _evidence_blob_for_episode(d, layout)
        if not ev:
            continue
        plot = _load_json(d / ("02_plot.json" if layout == "layered" else "plot.json")) or {}
        long_blob = _norm(_logic_check_longterm_blob(plot))

        for row in by_ck.values():
            if row.get("status") not in (None, "open"):
                continue
            if row.get("manual_status_lock"):
                continue
            desc = str(row.get("description") or "")
            payoff = str(row.get("payoff_target") or "")
            setup = str(row.get("setup_source") or "")
            cr = row.get("created_episode")
            if cr is not None and ep_id < int(cr):
                continue

            paid_sig = False
            if long_blob and any(k in long_blob for k in PAYOFF_STRONG):
                if _promise_text_in_evidence(desc, payoff, setup, long_blob):
                    paid_sig = True
            if not paid_sig and any(k in ev for k in PAYOFF_STRONG):
                if _promise_text_in_evidence(desc, payoff, setup, ev):
                    paid_sig = True
            if paid_sig:
                row["status"] = "paid_off"
                row["resolved_episode"] = ep_id
                row["decision_trace"] = (row.get("decision_trace") or [])[-6:] + [
                    f"ep{ep_id}: paid_off ← logic_check.what_new_longterm_change_is_created 或整集结构化证据 "
                    f"+ 强兑现词 + 文本对齐（setup/payoff/description）"
                ]
                continue

            broken_hard = False
            if any(k in ev for k in BROKEN_EXPLICIT):
                if _promise_text_in_evidence(desc, payoff, setup, ev):
                    broken_hard = True
            if not broken_hard and any(k in ev for k in BROKEN_SOFT):
                if _promise_text_in_evidence(desc, payoff, setup, ev) and len(_norm(desc)) >= 10:
                    broken_hard = True
            if broken_hard:
                row["status"] = "broken"
                row["resolved_episode"] = ep_id
                row["stale_reason"] = None
                row["decision_trace"] = (row.get("decision_trace") or [])[-6:] + [
                    f"ep{ep_id}: broken ← 明确断裂/失效类信号 + 与本承诺文本对齐（非暂时未提）"
                ]

    for row in by_ck.values():
        if row.get("manual_status_lock"):
            continue
        st = row.get("status") or "open"
        if st != "open":
            continue
        created = row.get("created_episode")
        last_seen = row.get("last_seen_episode") or created
        if max_ep and last_seen is not None and (max_ep - int(last_seen) >= STALE_PROMISE_EPISODE_WINDOW):
            pid_ref = str(row.get("payoff_id") or "").strip()
            sid_ref = str(row.get("setup_id") or "").strip()
            if pid_ref and pid_ref in global_payoff_ids:
                continue
            if sid_ref and sid_ref in global_setup_ids:
                continue
            row["status"] = "stale"
            row["stale_reason"] = (
                f"已超过 {STALE_PROMISE_EPISODE_WINDOW} 集未在结构化产物中出现可匹配承接 "
                f"（last_seen_episode={last_seen}, max_ep={max_ep}）；若同类承诺已更新见 superseded 标记"
            )
            row["decision_trace"] = (row.get("decision_trace") or [])[-6:] + [row["stale_reason"]]

    opens = [r for r in by_ck.values() if r.get("status") == "open"]
    by_anchor: Dict[Tuple[str, ...], List[Dict[str, Any]]] = {}
    for r in opens:
        aids = tuple(sorted(str(a) for a in (r.get("linked_anchor_ids") or [])))
        if len(aids) == 0:
            continue
        by_anchor.setdefault(aids, []).append(r)
    for group in by_anchor.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda x: (x.get("created_episode") or 0, x.get("last_seen_episode") or 0))
        newest = group[-1]
        for older in group[:-1]:
            if _desc_overlap(
                str(older.get("description") or ""),
                str(newest.get("description") or ""),
                14,
            ):
                older["status"] = "stale"
                older["stale_reason"] = (
                    f"同 linked_anchor_ids 下被 ep{newest.get('created_episode')} 更新的相近承诺替代（superseded）"
                )
                older["decision_trace"] = (older.get("decision_trace") or [])[-6:] + [
                    str(older.get("stale_reason") or "")
                ]

    for row in by_ck.values():
        pid = str(row.get("promise_id") or "")
        ck = str(row.get("compound_key") or "")
        src = locked_by_pid.get(pid) or (locked_by_ck.get(ck) if ck else None)
        if not src or not src.get("manual_status_lock"):
            continue
        row["status"] = src.get("status", row.get("status"))
        row["resolved_episode"] = src.get("resolved_episode", row.get("resolved_episode"))
        row["stale_reason"] = src.get("stale_reason", row.get("stale_reason"))
        row["manual_status_lock"] = True
        row["promise_id"] = src.get("promise_id", row["promise_id"])
        row["provenance"] = src.get("provenance", "manual")
        row["last_updated_by"] = src.get("last_updated_by", row.get("last_updated_by"))
        row["last_updated_at"] = src.get("last_updated_at", row.get("last_updated_at"))
        row["decision_trace"] = (row.get("decision_trace") or [])[-6:] + [
            "manual_status_lock: 保留人工终态（刷新未覆盖 status）"
        ]

    registry["promise_lane"] = {
        "schema_note": CARRY_PROMISE_SCHEMA_NOTE,
        "promises": list(by_ck.values()),
    }


def _bible_names(bible: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for c in bible.get("main_characters") or []:
        if isinstance(c, dict) and c.get("name"):
            out.append(str(c["name"]))
    return out


def _cast_names(bible: Dict[str, Any], memory: Dict[str, Any]) -> List[str]:
    """圣经主卡 + memory.characters，保序去重（短剧卡司共现种子）。"""
    out: List[str] = []
    for n in _bible_names(bible):
        if n not in out:
            out.append(n)
    for c in memory.get("characters") or []:
        if isinstance(c, dict) and c.get("name"):
            n = str(c["name"])
            if n not in out:
                out.append(n)
    return out


def _pairs_in_text(text: str, names: List[str]) -> Set[Tuple[str, str]]:
    if not text.strip() or len(names) < 2:
        return set()
    present = [n for n in names if n and n in text]
    present = list(dict.fromkeys(present))
    pairs: Set[Tuple[str, str]] = set()
    for i, a in enumerate(present):
        for b in present[i + 1 :]:
            x, y = sorted((a, b), key=lambda s: (len(s), s))
            pairs.add((x, y))
    return pairs


_TAG_RULES: List[Tuple[str, Tuple[str, ...]]] = [
    ("mistrust", ("怀疑", "不信", "猜忌", "隐瞒")),
    ("leverage", ("要挟", "把柄", "筹码", "威胁")),
    ("dependence", ("依赖", "只能靠", "离不开")),
    ("concealment", ("隐瞒", "不说", "装不知道")),
    ("betrayal_risk", ("背叛", "出卖", "反水")),
    ("status_gap", ("上下级", "阶层", "地位")),
    ("emotional_pull", ("拉扯", "心动", "放不下")),
    ("fear_link", ("害怕", "畏惧", "忌惮")),
    ("obligation", ("人情", "欠债", "欠他")),
    ("split_loyalty", ("两难", "站队", "选边")),
]

_STATE_RULES: List[Tuple[str, Tuple[str, ...]]] = [
    ("hostile", ("敌对", "撕破脸", "公开对立", "火并")),
    ("fractured", ("决裂", "分手", "恩断")),
    ("strained", ("冷战", "僵持", "紧张")),
    ("dependent", ("依附", "被控制", "离不开")),
    ("concealed_tension", ("表面", "装作", "暗涌")),
    ("aligned", ("同盟", "互信", "并肩", "合作")),
    ("unstable_alliance", ("临时", "互相利用", "各怀")),
    ("protector_dynamic", ("保护", "挡在前面", "护着")),
]


def _tags_from_text(text: str) -> List[str]:
    tags: List[str] = []
    for tag, kws in _TAG_RULES:
        if any(k in text for k in kws):
            if tag in PRESSURE_TAGS_VOCAB:
                tags.append(tag)
    return list(dict.fromkeys(tags))


def _state_from_text(text: str) -> str:
    for state, kws in _STATE_RULES:
        if any(k in text for k in kws):
            if state in RELATION_CURRENT_STATE_ENUM:
                return state
    return "unknown"


def refresh_relation_pressure_structured(
    registry: Dict[str, Any],
    *,
    paths: Dict[str, Any],
    layout: str,
    bible: Dict[str, Any],
    memory: Dict[str, Any],
    source: str,
    meta_row: Dict[str, str],
) -> None:
    names = _cast_names(bible, memory)
    name_set = set(names)
    rels: Dict[str, Dict[str, Any]] = {}

    def relation_key(x: str, y: str) -> str:
        a, b = sorted((x, y), key=lambda s: (len(s), s))
        return f"r__{_slug(a)}__{_slug(b)}"

    def touch_weak(x: str, y: str, ep_id: int, reason: str) -> None:
        rid = relation_key(x, y)
        if rid not in rels:
            rels[rid] = {
                "relation_id": rid,
                "a": sorted((x, y), key=lambda s: (len(s), s))[0],
                "b": sorted((x, y), key=lambda s: (len(s), s))[1],
                "first_seen_episode": ep_id,
                "last_seen_episode": ep_id,
                "current_state": "aligned",
                "pressure_tags": ["co_presence"],
                "trust_direction": "unclear",
                "dependency_direction": "unclear",
                "conflict_level": 0,
                "volatility": "low",
                "last_change_episode": ep_id,
                "last_change_reason": reason,
                "source_refs": [{"episode_id": ep_id, "kind": reason}],
                "decision_trace": [f"ep{ep_id}: {reason}（弱共现，仅 co_presence）"],
            }
            rels[rid].update(meta_row)
        else:
            row = rels[rid]
            row["last_seen_episode"] = max(row.get("last_seen_episode") or ep_id, ep_id)

    def touch_strong(x: str, y: str, ep_id: int, reason: str, text_blob: str) -> None:
        rid = relation_key(x, y)
        tags = _tags_from_text(text_blob)
        state = _state_from_text(text_blob)
        conflict = min(3, max(1, len(tags))) if tags else 1
        if rid not in rels:
            aa, bb = sorted((x, y), key=lambda s: (len(s), s))
            rels[rid] = {
                "relation_id": rid,
                "a": aa,
                "b": bb,
                "first_seen_episode": ep_id,
                "last_seen_episode": ep_id,
                "current_state": state if state != "unknown" else "strained",
                "pressure_tags": tags or ["co_presence"],
                "trust_direction": "unclear",
                "dependency_direction": "unclear",
                "conflict_level": conflict,
                "volatility": "medium" if conflict >= 2 else "low",
                "last_change_episode": ep_id,
                "last_change_reason": reason,
                "source_refs": [{"episode_id": ep_id, "kind": reason}],
                "decision_trace": [f"ep{ep_id}: {reason} → state={state} tags={tags}"],
            }
            rels[rid].update(meta_row)
        else:
            row = rels[rid]
            row["last_seen_episode"] = max(row.get("last_seen_episode") or ep_id, ep_id)
            old_c = int(row.get("conflict_level") or 0)
            if state != "unknown" and state != row.get("current_state"):
                row["current_state"] = state
                row["last_change_episode"] = ep_id
                row["last_change_reason"] = reason
            row["conflict_level"] = max(old_c, conflict)
            row["volatility"] = "high" if row["conflict_level"] >= 3 else row.get("volatility")
            merged = list(dict.fromkeys((row.get("pressure_tags") or []) + tags))
            row["pressure_tags"] = [t for t in merged if t in PRESSURE_TAGS_VOCAB][:12]
            sr = list(row.get("source_refs") or [])
            sr.append({"episode_id": ep_id, "kind": reason})
            row["source_refs"] = sr[-12:]
            dt = list(row.get("decision_trace") or [])
            dt.append(f"ep{ep_id}: {reason} state={row['current_state']}")
            row["decision_trace"] = dt[-8:]

    last_mem_ep = 0
    for e in memory.get("episodes") or []:
        if isinstance(e, dict) and e.get("episode_id") is not None:
            last_mem_ep = max(last_mem_ep, int(e["episode_id"]))

    for line in memory.get("relationship_shifts") or []:
        t = str(line)
        for m in re.finditer(
            r"([\u4e00-\u9fff\w·]{2,10})[与和跟对]([\u4e00-\u9fff\w·]{2,10})",
            t,
        ):
            a, b = m.group(1), m.group(2)
            if a in name_set and b in name_set:
                touch_strong(a, b, last_mem_ep or 1, "series_memory.relationship_shifts", t)

    ep_dirs = _iter_episode_dirs(paths["episodes_root"], layout)
    for ep_id, d in ep_dirs:
        fn = _load_json(d / ("01_episode_function.json" if layout == "layered" else "episode_function.json")) or {}
        for key in (
            "what_changes_persistently",
            "what_is_mislearned",
            "must_advance",
            "what_is_lost",
        ):
            v = fn.get(key)
            items = v if isinstance(v, list) else ([v] if isinstance(v, str) else [])
            for item in items:
                blob = str(item)
                for a, b in _pairs_in_text(blob, names):
                    rel_kw = ("关系", "信任", "误会", "站队", "撕", "依赖", "利用", "合作", "对立")
                    if any(k in blob for k in rel_kw):
                        touch_strong(a, b, ep_id, f"episode_function.{key}", blob)
                    else:
                        touch_weak(a, b, ep_id, f"episode_function.{key}:co_mention")

        plot = _load_json(d / ("02_plot.json" if layout == "layered" else "plot.json")) or {}
        lc = _logic_check_text(plot)
        if lc:
            for a, b in _pairs_in_text(lc, names):
                if any(k in lc for k in ("关系", "信任", "对立", "结盟", "误会")):
                    touch_strong(a, b, ep_id, "plot.logic_check", lc[:240])

    for e in memory.get("episodes") or []:
        if not isinstance(e, dict):
            continue
        ep_id = e.get("episode_id")
        if ep_id is None:
            continue
        summ = str(e.get("summary") or "")
        for a, b in _pairs_in_text(summ, names):
            rid = relation_key(a, b)
            if rid not in rels:
                touch_weak(a, b, int(ep_id), "series_memory.episode_summary:co_presence")

    # 卡司级弱种子：两角色均在结构化卡司中出现、但本集无文本共现时仍建 co_presence（conflict=0）
    seed_ep = max(last_mem_ep, 1)
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            rid = relation_key(a, b)
            if rid not in rels:
                touch_weak(a, b, seed_ep, "cast_universe:co_presence_seed")

    for row in rels.values():
        if row.get("current_state") == "unknown":
            row["current_state"] = "aligned"
        if not row.get("pressure_tags"):
            row["pressure_tags"] = ["co_presence"]
            row["conflict_level"] = 0

    registry["relation_pressure_map"] = {
        "schema_note": CARRY_RELATION_SCHEMA_NOTE,
        "relations": list(rels.values()),
    }


def _infer_known_by_learned(text: str, cast_names: List[str]) -> Tuple[List[str], List[str]]:
    """
    仅用于 what_is_learned：高置信度子串/句首模式；多角色同时命中则放弃。
    返回 (known_by, decision_trace_lines)。
    """
    trace: List[str] = []
    names = [n for n in cast_names if isinstance(n, str) and len(n.strip()) >= 2]
    names = sorted(names, key=lambda x: (-len(x), x))
    present = []
    for n in names:
        if n in text:
            present.append(n)
    present = list(dict.fromkeys(present))
    if len(present) == 1:
        trace.append(f"known_by: 全文仅命中单一卡司名「{present[0]}」（子串）")
        return [present[0]], trace
    if len(present) > 1:
        trace.append("known_by: 多卡司名同时出现，跳过推断")
        return [], trace
    m = re.match(
        r"^([\u4e00-\u9fff\w·]{2,16})(知道了|得知|已确认|确认|明白|获悉)",
        text.strip(),
    )
    if m:
        who = m.group(1)
        name_set = set(names)
        if who in name_set:
            trace.append("known_by: 句首「角色+得知」固定模式")
            return [who], trace
    return [], trace


def _script_character_updates(script: Dict[str, Any]) -> List[Tuple[str, str]]:
    """低成本：仅认可选结构化字段 character_knowledge_updates / character_revelations。"""
    out: List[Tuple[str, str]] = []
    for key in ("character_knowledge_updates", "character_revelations"):
        block = script.get(key)
        if not isinstance(block, list):
            continue
        for row in block:
            if not isinstance(row, dict):
                continue
            ch = row.get("character") or row.get("name")
            detail = row.get("detail") or row.get("text") or row.get("fact")
            if isinstance(ch, str) and isinstance(detail, str) and len(detail.strip()) >= 6:
                out.append((ch.strip(), detail.strip()[:600]))
    return out


def refresh_knowledge_fence_minimal(
    registry: Dict[str, Any],
    *,
    paths: Dict[str, Any],
    layout: str,
    source: str,
    meta_row: Dict[str, str],
) -> None:
    """从结构化 JSON 抽取最小 facts；what_is_learned 可高置信度推断 known_by。"""
    episodes_root: Path = paths["episodes_root"]
    mem_path = paths.get("series_memory")
    memory: Dict[str, Any] = {}
    if mem_path is not None and Path(mem_path).exists():
        memory = _load_json(Path(mem_path)) or {}
    bible: Dict[str, Any] = {}
    bp = paths.get("character_bible")
    if bp is not None and Path(bp).exists():
        bible = _load_json(Path(bp)) or {}
    cast_names = _cast_names(bible, memory)

    prev_facts = list((registry.get("knowledge_fence") or {}).get("facts") or [])
    prev_by_fid = {
        str(f["fact_id"]): f for f in prev_facts if isinstance(f, dict) and f.get("fact_id")
    }

    by_id: Dict[str, Dict[str, Any]] = {}
    ep_dirs = _iter_episode_dirs(episodes_root, layout)

    def add_fact(
        text: str,
        ep_id: int,
        visibility: str,
        confidence: str,
        kind: str,
        *,
        known_by: Optional[List[str]] = None,
        decision_trace: Optional[List[str]] = None,
    ) -> None:
        t = text.strip()
        if len(_norm(t)) < 8:
            return
        raw = f"{ep_id}|{kind}|{_norm(t)[:180]}"
        fid = "kf_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        conf = confidence if confidence in KNOWLEDGE_CONFIDENCE_ENUM else "low"
        kb = [str(x) for x in (known_by or []) if x]
        dt = list(decision_trace or [])
        if fid in by_id:
            prev = by_id[fid]
            prev["last_seen_episode"] = max(int(prev.get("last_seen_episode") or ep_id), ep_id)
            prev["last_confirmed_episode"] = max(
                int(prev.get("last_confirmed_episode") or ep_id), ep_id
            )
            sr = list(prev.get("source_refs") or [])
            sr.append({"episode_id": ep_id, "kind": kind})
            prev["source_refs"] = sr[-12:]
            if kb and not prev.get("known_by"):
                prev["known_by"] = kb
                prev["confidence"] = conf
            if dt:
                pdt = list(prev.get("decision_trace") or [])
                prev["decision_trace"] = (pdt + dt)[-10:]
            return
        row: Dict[str, Any] = {
            "fact_id": fid,
            "fact_text": t[:600],
            "holder_scope": "series",
            "known_by": kb,
            "visibility": visibility,
            "first_seen_episode": ep_id,
            "last_seen_episode": ep_id,
            "last_confirmed_episode": ep_id,
            "fact_status": "active",
            "confidence": conf,
            "source_refs": [{"episode_id": ep_id, "kind": kind}],
            "decision_trace": dt,
        }
        old = prev_by_fid.get(fid)
        if old:
            if old.get("superseded_by_fact_id"):
                row["superseded_by_fact_id"] = old.get("superseded_by_fact_id")
                st = old.get("fact_status")
                if st in KNOWLEDGE_FACT_STATUS_ENUM:
                    row["fact_status"] = st
        row.update(meta_row)
        by_id[fid] = row

    for ep_id, d in ep_dirs:
        fn = _load_json(d / ("01_episode_function.json" if layout == "layered" else "episode_function.json")) or {}
        for item in fn.get("what_is_learned") or []:
            ts = str(item)
            kb, tr = _infer_known_by_learned(ts, cast_names)
            conf = "high" if kb else "medium"
            add_fact(
                ts,
                ep_id,
                "character",
                conf,
                "episode_function.what_is_learned",
                known_by=kb,
                decision_trace=tr,
            )
        for item in fn.get("what_is_mislearned") or []:
            add_fact(str(item), ep_id, "audience_only", "low", "episode_function.what_is_mislearned")
        plot = _load_json(d / ("02_plot.json" if layout == "layered" else "plot.json")) or {}
        lc = _logic_check_text(plot)
        if lc and len(_norm(lc)) > 16:
            add_fact(lc[:520], ep_id, "mixed", "low", "plot.logic_check")

        sc = _load_json(d / ("03_script.json" if layout == "layered" else "script.json")) or {}
        if isinstance(sc, dict):
            for ch, detail in _script_character_updates(sc):
                if ch in cast_names:
                    add_fact(
                        f"{ch}：{detail}",
                        ep_id,
                        "character",
                        "high",
                        "script.character_knowledge_updates",
                        known_by=[ch],
                        decision_trace=[
                            "known_by: script.character_knowledge_updates 结构化字段显式角色"
                        ],
                    )

    for e in memory.get("episodes") or []:
        if not isinstance(e, dict):
            continue
        ep_raw = e.get("episode_id")
        if ep_raw is None:
            continue
        ep_id = int(ep_raw)
        for key in ("what_audience_knows_now", "knowledge_delta", "info_boundary_note"):
            v = e.get(key)
            if isinstance(v, str) and len(_norm(v)) > 12:
                add_fact(v[:520], ep_id, "mixed", "low", f"series_memory.{key}")
        # 可选：角色显式字段（高置信度）
        for ck in ("character_knowledge", "who_learned_what"):
            block = e.get(ck)
            if isinstance(block, list):
                for row in block:
                    if not isinstance(row, dict):
                        continue
                    ch = row.get("character") or row.get("name")
                    fact = row.get("fact") or row.get("text")
                    if isinstance(ch, str) and isinstance(fact, str) and ch in cast_names:
                        add_fact(
                            fact.strip()[:600],
                            ep_id,
                            "character",
                            "high",
                            f"series_memory.{ck}",
                            known_by=[ch],
                            decision_trace=[f"known_by: series_memory.{ck} 显式角色字段"],
                        )

    registry["knowledge_fence"] = {
        "schema_note": CARRY_KNOWLEDGE_FENCE_SCHEMA_NOTE,
        "facts": list(by_id.values()),
    }


def migrate_relation_slice(rpm: Dict[str, Any]) -> None:
    if rpm.get("relations"):
        return
    if rpm.get("pairs"):
        rpm["relations"] = list(rpm["pairs"])

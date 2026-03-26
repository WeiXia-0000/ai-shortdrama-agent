"""
production_carry_registry：L3_series/03b_production_carry_registry.json（分层）
或剧根目录 03b_production_carry_registry.json（平铺）。

knowledge_fence.facts[] 使用 visibility（character | audience_only | mixed），
不在 known_by 中混入哨兵。
各行可预留 provenance / last_updated_by / last_updated_at（首版可选落库）。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .creative_constants import (
    KNOWLEDGE_CONFIDENCE_ENUM,
    KNOWLEDGE_FACT_STATUS_ENUM,
    PROMISE_STATUS_ENUM,
)
from .carry_structured_refresh import (
    refresh_knowledge_fence_minimal,
    refresh_promise_lane_structured,
    refresh_relation_pressure_structured,
)
from .genre_rules import bundle_from_registry_series_identity, infer_genre_bundle_for_prompt

SCHEMA_VERSION = "1.0"

# 分层布局下相对 series_dir 的稳定路径
REGISTRY_REL_LAYERED = "L3_series/03b_production_carry_registry.json"
REGISTRY_BASENAME = "03b_production_carry_registry.json"

SLICE_KEYS = (
    "story_thrust",
    "asset_ledger",
    "promise_lane",
    "relation_pressure_map",
    "knowledge_fence",
    "visual_lock_registry",
)

ROW_META_OPTIONAL = ("provenance", "last_updated_by", "last_updated_at")
VISIBILITY_ENUM = frozenset({"character", "audience_only", "mixed"})


def registry_path_from_paths(paths: Dict[str, Any]) -> Path:
    return paths["production_carry_registry"]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _row_meta(
    provenance: str,
    *,
    by: str = "pipeline:carry_registry",
) -> Dict[str, str]:
    return {
        "provenance": provenance,
        "last_updated_by": by,
        "last_updated_at": _utc_now_iso(),
    }


def build_empty_shell(
    *,
    series_slug: str,
    display_title: str,
    genre_key: str = "",
    genre_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    gb = genre_bundle if isinstance(genre_bundle, dict) else {}
    primary = str(gb.get("primary_genre") or genre_key or "")
    setting_tags = gb.get("setting_tags") if isinstance(gb.get("setting_tags"), list) else []
    engine_tags = gb.get("engine_tags") if isinstance(gb.get("engine_tags"), list) else []
    relationship_tags = (
        gb.get("relationship_tags") if isinstance(gb.get("relationship_tags"), list) else []
    )
    series_identity: Dict[str, Any] = {
        "series_slug": series_slug,
        "display_title": display_title,
        "genre_key": primary or "",
        "primary_genre": primary or "",
        "setting_tags": setting_tags,
        "engine_tags": engine_tags,
        "relationship_tags": relationship_tags,
    }
    if isinstance(genre_bundle, dict):
        for k in ("resolved_alias_hits", "primary_resolution_trace", "confidence"):
            if k in genre_bundle and genre_bundle[k] is not None:
                series_identity[k] = genre_bundle[k]

    return {
        "schema_version": SCHEMA_VERSION,
        "series_identity": series_identity,
        "sync_meta": {
            "last_full_refresh_at": None,
            "last_full_refresh_source": None,
            "last_incremental_at": None,
            "last_incremental_source": None,
            "derived_index_stale": False,
        },
        "story_thrust": {"drift_flag": False},
        "asset_ledger": {"items": []},
        "promise_lane": {"promises": []},
        "relation_pressure_map": {"relations": []},
        "knowledge_fence": {"facts": []},
        "visual_lock_registry": {"characters": []},
    }


def validate_registry(obj: Any) -> List[str]:
    errs: List[str] = []
    if not isinstance(obj, dict):
        return ["根对象必须是 JSON 对象"]
    if obj.get("schema_version") != SCHEMA_VERSION:
        errs.append(f"schema_version 应为 {SCHEMA_VERSION!r}")
    for k in ("series_identity", "sync_meta"):
        if k not in obj or not isinstance(obj[k], dict):
            errs.append(f"缺少或类型错误: {k}")
    for sk in SLICE_KEYS:
        if sk not in obj or not isinstance(obj[sk], dict):
            errs.append(f"缺少或类型错误切片: {sk}")
    st = obj.get("story_thrust") or {}
    if "drift_flag" not in st or not isinstance(st.get("drift_flag"), bool):
        errs.append("story_thrust.drift_flag 必填且为 boolean")
    al = obj.get("asset_ledger") or {}
    if not isinstance(al.get("items"), list):
        errs.append("asset_ledger.items 必须为数组")
    pl = obj.get("promise_lane") or {}
    prms = pl.get("promises")
    if prms is None:
        errs.append("promise_lane.promises 缺失")
    elif not isinstance(prms, list):
        errs.append("promise_lane.promises 必须为数组")
    else:
        for i, p in enumerate(prms):
            if not isinstance(p, dict):
                errs.append(f"promise_lane.promises[{i}] 必须为对象")
                continue
            st = p.get("status")
            if st is not None and st not in PROMISE_STATUS_ENUM:
                errs.append(
                    f"promise_lane.promises[{i}].status 非法: {st!r}（允许 {sorted(PROMISE_STATUS_ENUM)}）"
                )
    rpm = obj.get("relation_pressure_map") or {}
    rels = rpm.get("relations")
    if rels is None:
        rels = rpm.get("pairs")
    if not isinstance(rels, list):
        errs.append("relation_pressure_map.relations（或兼容 pairs）必须为数组")
    kf = obj.get("knowledge_fence") or {}
    facts = kf.get("facts")
    if not isinstance(facts, list):
        errs.append("knowledge_fence.facts 必须为数组")
    else:
        for i, f in enumerate(facts):
            if not isinstance(f, dict):
                errs.append(f"knowledge_fence.facts[{i}] 必须为对象")
                continue
            vis = f.get("visibility")
            if vis is not None and vis not in VISIBILITY_ENUM:
                errs.append(
                    f"knowledge_fence.facts[{i}].visibility 必须是 character|audience_only|mixed"
                )
            kb = f.get("known_by")
            if kb is not None and not isinstance(kb, list):
                errs.append(f"knowledge_fence.facts[{i}].known_by 必须为数组")
            fid = f.get("fact_id")
            if fid is not None and not isinstance(fid, str):
                errs.append(f"knowledge_fence.facts[{i}].fact_id 必须为字符串")
            ft = f.get("fact_text")
            if ft is not None and not isinstance(ft, str):
                errs.append(f"knowledge_fence.facts[{i}].fact_text 必须为字符串")
            conf = f.get("confidence")
            if conf is not None and conf not in KNOWLEDGE_CONFIDENCE_ENUM:
                errs.append(
                    f"knowledge_fence.facts[{i}].confidence 非法: {conf!r}（允许 {sorted(KNOWLEDGE_CONFIDENCE_ENUM)}）"
                )
            fst = f.get("fact_status")
            if fst is not None and fst not in KNOWLEDGE_FACT_STATUS_ENUM:
                errs.append(
                    f"knowledge_fence.facts[{i}].fact_status 非法: {fst!r}（允许 {sorted(KNOWLEDGE_FACT_STATUS_ENUM)}）"
                )
            sb = f.get("superseded_by_fact_id")
            if sb is not None and not isinstance(sb, str):
                errs.append(f"knowledge_fence.facts[{i}].superseded_by_fact_id 必须为字符串")
            lce = f.get("last_confirmed_episode")
            if lce is not None and not isinstance(lce, int):
                errs.append(f"knowledge_fence.facts[{i}].last_confirmed_episode 必须为整数")
    vl = obj.get("visual_lock_registry") or {}
    if not isinstance(vl.get("characters"), list):
        errs.append("visual_lock_registry.characters 必须为数组")
    return errs


def load_registry(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    err = validate_registry(data)
    if err:
        raise ValueError("registry 校验失败: " + "; ".join(err))
    return data


def save_registry(path: Path, obj: Dict[str, Any]) -> None:
    err = validate_registry(obj)
    if err:
        raise ValueError("registry 校验失败: " + "; ".join(err))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_registry_file(
    path: Path,
    *,
    series_slug: str,
    display_title: str,
    genre_key: str = "",
    genre_bundle: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """若不存在则写入空壳并返回；若存在则加载校验。"""
    if path.exists():
        return load_registry(path)
    shell = build_empty_shell(
        series_slug=series_slug,
        display_title=display_title,
        genre_key=genre_key,
        genre_bundle=genre_bundle,
    )
    save_registry(path, shell)
    return shell


def _slug(s: str) -> str:
    x = re.sub(r"[^\w\u4e00-\u9fff]+", "_", (s or "").strip())
    return x[:64] or "unnamed"


def _nonblank_str(val: Any, min_len: int = 1) -> bool:
    return isinstance(val, str) and len(val.strip()) >= min_len


def _appearance_lock_minimal(al: Any) -> bool:
    """与 character_bible schema 对齐的最小可锁脸字段。"""
    if not isinstance(al, dict):
        return False
    for k in ("face_shape", "hair", "eyes", "body_type", "default_outfit"):
        if not _nonblank_str(al.get(k), 1):
            return False
    return True


def classify_bible_character_visual_lock(character: Dict[str, Any]) -> str:
    """
    基于当前 bible 实际字段判定 complete / partial（圣经内角色）。
    complete：脸/身三视图提示、负面提示、appearance_lock 五键、consistency_rules 至少一条均有实质内容。
    partial：具备任一主要视觉锁信号但不满足 complete。
    """
    face = character.get("face_triptych_prompt_cn")
    body = character.get("body_triptych_prompt_cn")
    neg = character.get("negative_prompt_cn")
    al = character.get("appearance_lock")
    rules = character.get("consistency_rules")
    rules_ok = isinstance(rules, list) and any(_nonblank_str(x, 2) for x in rules)

    complete_ok = (
        _nonblank_str(face, 20)
        and _nonblank_str(body, 20)
        and _nonblank_str(neg, 3)
        and _appearance_lock_minimal(al)
        and rules_ok
    )
    if complete_ok:
        return "complete"

    legacy = _nonblank_str(
        character.get("seedance_portrait_prompt") or character.get("visual_anchor"), 15
    )
    if (
        legacy
        or _nonblank_str(face, 8)
        or _nonblank_str(body, 8)
        or _appearance_lock_minimal(al)
        or rules_ok
    ):
        return "partial"

    return "partial"


def sync_visual_lock_registry(
    registry: Dict[str, Any],
    character_bible: Dict[str, Any],
    series_memory: Dict[str, Any],
    *,
    layout: str,
    source: str,
) -> None:
    """由 bible + memory 推导 visual_lock_registry 行（衍生）。"""
    meta = _row_meta(source, by=source)
    bible_rel = (
        "L3_series/02_character_bible.json"
        if layout == "layered"
        else "character_bible.json"
    )
    bible_names = {
        c.get("name")
        for c in (character_bible.get("main_characters") or [])
        if isinstance(c, dict) and c.get("name")
    }
    rows: List[Dict[str, Any]] = []
    for c in character_bible.get("main_characters") or []:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        if not name:
            continue
        lock = classify_bible_character_visual_lock(c)
        row: Dict[str, Any] = {
            "cast_id": _slug(str(name)),
            "display_name": str(name),
            "lock_status": lock,
            "bible_pointer": bible_rel,
            "last_patch_at": None,
            "consistency_risk": False,
            "notes": "",
        }
        row.update(meta)
        rows.append(row)

    memory_only: List[str] = []
    for c in series_memory.get("characters") or []:
        if not isinstance(c, dict):
            continue
        n = c.get("name")
        if n and n not in bible_names:
            memory_only.append(str(n))

    for n in memory_only:
        row = {
            "cast_id": _slug(n),
            "display_name": n,
            "lock_status": "missing",
            "bible_pointer": None,
            "last_patch_at": None,
            "consistency_risk": True,
            "notes": "仅见于 series_memory，圣经未收录",
        }
        row.update(meta)
        rows.append(row)

    registry["visual_lock_registry"] = {"characters": rows}


def _parse_episode_id_from_dirname(dirname: str) -> Optional[int]:
    m = re.search(r"第(\d+)集", dirname)
    if not m:
        return None
    return int(m.group(1))


def sync_carry_registry_minimal(
    paths: Dict[str, Any],
    *,
    series_title: str,
    layout: str,
    source: str = "pipeline:episode_batch_tail",
) -> None:
    """接通 visual_lock + promise_lane + relation_pressure 的最小更新路径。"""
    reg_path = registry_path_from_paths(paths)
    slug = _slug(series_title)
    outline_path = paths["series_outline"]

    registry = ensure_registry_file(
        reg_path,
        series_slug=slug,
        display_title=series_title,
        genre_key="",
        genre_bundle={},
    )
    si0 = registry.get("series_identity") or {}
    existing_src = str(si0.get("bundle_source") or "")
    existing_primary = str(
        si0.get("final_primary_genre") or si0.get("primary_genre") or si0.get("genre_key") or ""
    ).strip()
    preserve_genre = existing_primary and existing_src in (
        "chosen_concept",
        "chosen_concept_final",
        "final",
        "series_setup",
    )

    genre_key = existing_primary
    genre_bundle: Dict[str, Any] = {}
    if preserve_genre:
        rb = bundle_from_registry_series_identity(si0)
        genre_bundle = rb if isinstance(rb, dict) else {}
    elif outline_path.exists():
        try:
            ol = json.loads(outline_path.read_text(encoding="utf-8"))
            infer_t = (ol.get("logline") or "") + "\n" + (ol.get("overall_arc") or "")
            genre_bundle = infer_genre_bundle_for_prompt(infer_t)
            genre_key = str(genre_bundle.get("primary_genre") or "")
        except (OSError, json.JSONDecodeError):
            genre_key = genre_key or ""

    registry["series_identity"]["display_title"] = series_title
    registry["series_identity"]["series_slug"] = slug
    if not preserve_genre:
        registry["series_identity"]["genre_key"] = genre_key
        registry["series_identity"]["primary_genre"] = genre_key
        registry["series_identity"]["setting_tags"] = (
            genre_bundle.get("setting_tags") if isinstance(genre_bundle.get("setting_tags"), list) else []
        )
        registry["series_identity"]["engine_tags"] = (
            genre_bundle.get("engine_tags") if isinstance(genre_bundle.get("engine_tags"), list) else []
        )
        registry["series_identity"]["relationship_tags"] = (
            genre_bundle.get("relationship_tags")
            if isinstance(genre_bundle.get("relationship_tags"), list)
            else []
        )
        if genre_key:
            registry["series_identity"]["resolved_alias_hits"] = genre_bundle.get("resolved_alias_hits")
            registry["series_identity"]["primary_resolution_trace"] = genre_bundle.get(
                "primary_resolution_trace"
            )
            registry["series_identity"]["confidence"] = genre_bundle.get("confidence")
        registry["series_identity"]["bundle_source"] = (
            "outline_infer" if genre_key else registry["series_identity"].get("bundle_source")
        )

    bible = json.loads(paths["character_bible"].read_text(encoding="utf-8"))
    mem_path = paths["series_memory"]
    if mem_path.exists():
        memory = json.loads(mem_path.read_text(encoding="utf-8"))
    else:
        memory = {"episodes": [], "characters": []}

    sync_visual_lock_registry(
        registry, bible, memory, layout=layout, source=f"{source}:visual_lock"
    )
    meta_p = _row_meta(f"{source}:promise_lane", by=source)
    refresh_promise_lane_structured(
        registry,
        paths=paths,
        layout=layout,
        source=source,
        meta_row=meta_p,
    )
    meta_r = _row_meta(f"{source}:relation_pressure_map", by=source)
    refresh_relation_pressure_structured(
        registry,
        paths=paths,
        layout=layout,
        bible=bible,
        memory=memory,
        source=source,
        meta_row=meta_r,
    )
    meta_k = _row_meta(f"{source}:knowledge_fence", by=source)
    refresh_knowledge_fence_minimal(
        registry,
        paths=paths,
        layout=layout,
        source=source,
        meta_row=meta_k,
    )

    sm = registry.setdefault("sync_meta", {})
    sm["last_incremental_at"] = _utc_now_iso()
    sm["last_incremental_source"] = source
    sm["derived_index_stale"] = True

    save_registry(reg_path, registry)


def _find_promise_row(
    promises: List[Dict[str, Any]],
    *,
    promise_id: Optional[Any] = None,
    compound_key: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    for p in promises:
        if promise_id is not None and str(p.get("promise_id")) == str(promise_id):
            return p
        if compound_key is not None and str(p.get("compound_key") or "") == str(compound_key):
            return p
    return None


def apply_promise_manual_overrides(
    paths: Dict[str, Any],
    *,
    patch: Dict[str, Any],
) -> None:
    """
    人工纠偏 promise：patch JSON 可含
    - overrides: [{ promise_id | match_compound_key, status?, resolved_episode?, stale_reason?,
        manual_status_lock?, override_reason?, override_source?, superseded_by_promise_id?, same_lineage_as_promise_id? }]
    - supersedes: [{ old_promise_id, new_promise_id, stale_reason?, note? }] 轻量取代标记
    """
    reg_path = registry_path_from_paths(paths)
    registry = load_registry(reg_path)
    pl = registry.setdefault("promise_lane", {})
    promises: List[Dict[str, Any]] = [p for p in (pl.get("promises") or []) if isinstance(p, dict)]
    pl["promises"] = promises
    updated_by = str(patch.get("updated_by") or "op:carry.apply_promise_overrides")
    meta = _row_meta("manual:promise_override", by=updated_by)

    for s in patch.get("supersedes") or []:
        if not isinstance(s, dict):
            continue
        old_id, new_id = s.get("old_promise_id"), s.get("new_promise_id")
        if not old_id or not new_id:
            continue
        old_row = _find_promise_row(promises, promise_id=old_id)
        new_row = _find_promise_row(promises, promise_id=new_id)
        if not old_row:
            continue
        reason = str(s.get("stale_reason") or s.get("note") or "人工标记为被新承诺取代")
        old_row["previous_status"] = old_row.get("status")
        old_row["status"] = "stale"
        old_row["stale_reason"] = reason
        old_row["superseded_by_promise_id"] = str(new_id)
        old_row["override_reason"] = str(s.get("note") or "supersedes_link")
        old_row["override_source"] = str(s.get("override_source") or "patch_json:supersedes")
        old_row["manual_status_lock"] = bool(s.get("manual_status_lock", True))
        old_row.update(meta)
        if new_row:
            new_row.setdefault("supersedes_promise_ids", [])
            if str(old_id) not in [str(x) for x in (new_row.get("supersedes_promise_ids") or [])]:
                new_row["supersedes_promise_ids"] = list(
                    (new_row.get("supersedes_promise_ids") or []) + [str(old_id)]
                )[-8:]

    for o in patch.get("overrides") or []:
        if not isinstance(o, dict):
            continue
        pid = o.get("promise_id")
        ckey = o.get("match_compound_key")
        target = _find_promise_row(promises, promise_id=pid, compound_key=ckey)
        if not target:
            continue
        prev_st = target.get("status")
        st = o.get("status")
        if st in PROMISE_STATUS_ENUM:
            target["status"] = st
        if "resolved_episode" in o:
            target["resolved_episode"] = o.get("resolved_episode")
        if "stale_reason" in o:
            target["stale_reason"] = o.get("stale_reason")
        if o.get("superseded_by_promise_id") is not None:
            target["superseded_by_promise_id"] = str(o.get("superseded_by_promise_id"))
        if o.get("same_lineage_as_promise_id") is not None:
            target["same_lineage_as_promise_id"] = str(o.get("same_lineage_as_promise_id"))
        target["previous_status"] = prev_st
        if o.get("override_reason") is not None:
            target["override_reason"] = str(o.get("override_reason"))
        target["override_source"] = str(o.get("override_source") or "patch_json:overrides")
        target["manual_status_lock"] = bool(o.get("manual_status_lock", True))
        target.update(meta)
    sm = registry.setdefault("sync_meta", {})
    sm["last_incremental_at"] = _utc_now_iso()
    sm["last_incremental_source"] = updated_by
    save_registry(reg_path, registry)


def refresh_registry_slice(
    paths: Dict[str, Any],
    *,
    slice_name: str,
    layout: str,
    series_title: str,
    source: str,
) -> None:
    """仅刷新 promise_lane / relation_pressure_map / knowledge_fence（其它切片保留）。"""
    if slice_name not in ("promise_lane", "relation_pressure_map", "knowledge_fence"):
        raise ValueError(
            "refresh_registry_slice 仅支持 promise_lane | relation_pressure_map | knowledge_fence"
        )
    reg_path = registry_path_from_paths(paths)
    registry = load_registry(reg_path)
    if slice_name == "promise_lane":
        refresh_promise_lane_structured(
            registry,
            paths=paths,
            layout=layout,
            source=source,
            meta_row=_row_meta(source, by=source),
        )
    elif slice_name == "relation_pressure_map":
        mem_path = paths["series_memory"]
        memory = (
            json.loads(mem_path.read_text(encoding="utf-8"))
            if mem_path.exists()
            else {"episodes": [], "characters": []}
        )
        bp = paths["character_bible"]
        bible = (
            json.loads(bp.read_text(encoding="utf-8"))
            if bp.exists()
            else {"main_characters": []}
        )
        refresh_relation_pressure_structured(
            registry,
            paths=paths,
            layout=layout,
            bible=bible,
            memory=memory,
            source=source,
            meta_row=_row_meta(source, by=source),
        )
    else:
        refresh_knowledge_fence_minimal(
            registry,
            paths=paths,
            layout=layout,
            source=source,
            meta_row=_row_meta(source, by=source),
        )
    sm = registry.setdefault("sync_meta", {})
    sm["last_incremental_at"] = _utc_now_iso()
    sm["last_incremental_source"] = source
    sm["derived_index_stale"] = True
    save_registry(reg_path, registry)


def scan_visual_lock_only(
    paths: Dict[str, Any],
    *,
    layout: str,
    series_title: str,
    source: str,
) -> None:
    """仅刷新 visual_lock_registry。"""
    reg_path = registry_path_from_paths(paths)
    registry = load_registry(reg_path)
    bible = json.loads(paths["character_bible"].read_text(encoding="utf-8"))
    mem_path = paths["series_memory"]
    memory = (
        json.loads(mem_path.read_text(encoding="utf-8"))
        if mem_path.exists()
        else {"episodes": [], "characters": []}
    )
    sync_visual_lock_registry(
        registry, bible, memory, layout=layout, source=source
    )
    sm = registry.setdefault("sync_meta", {})
    sm["last_incremental_at"] = _utc_now_iso()
    sm["last_incremental_source"] = source
    sm["derived_index_stale"] = True
    save_registry(reg_path, registry)


def apply_visual_lock_patch(
    paths: Dict[str, Any],
    *,
    layout: str,
    patch: Dict[str, Any],
) -> None:
    """
    patch JSON 可选键：
    - visual_lock_characters: 与 registry 行结构相同的对象数组，按 cast_id 合并覆盖
    - bible_main_characters: 按 name 合并进 character_bible.main_characters
    """
    reg_path = registry_path_from_paths(paths)
    registry = load_registry(reg_path)

    bible_path = paths["character_bible"]
    bible = json.loads(bible_path.read_text(encoding="utf-8"))
    main = bible.setdefault("main_characters", [])
    for upd in patch.get("bible_main_characters") or []:
        if not isinstance(upd, dict) or not upd.get("name"):
            continue
        name = upd["name"]
        found = False
        for i, row in enumerate(main):
            if isinstance(row, dict) and row.get("name") == name:
                merged = {**row, **{k: v for k, v in upd.items() if v is not None}}
                main[i] = merged
                found = True
                break
        if not found:
            main.append(upd)
    bible_path.write_text(
        json.dumps(bible, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    rows = (registry.get("visual_lock_registry") or {}).get("characters") or []
    by_id = {r.get("cast_id"): r for r in rows if isinstance(r, dict) and r.get("cast_id")}
    for upd in patch.get("visual_lock_characters") or []:
        if not isinstance(upd, dict) or not upd.get("cast_id"):
            continue
        cid = upd["cast_id"]
        if cid in by_id:
            by_id[cid] = {**by_id[cid], **upd, **_row_meta("manual:patch", by="op:cast.patch_visual_lock")}
        else:
            by_id[cid] = {**upd, **_row_meta("manual:patch", by="op:cast.patch_visual_lock")}
    registry["visual_lock_registry"] = {"characters": list(by_id.values())}
    save_registry(reg_path, registry)

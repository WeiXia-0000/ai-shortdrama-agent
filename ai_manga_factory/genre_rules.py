from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


PROJECT_ROOT = Path(__file__).resolve().parent
# 兼容包内 genres/ 与仓库根 genres/（后者便于 monorepo 或多包布局）
GENRE_REFERENCE_CANDIDATES = [
    PROJECT_ROOT / "genres" / "genre_reference.json",
    PROJECT_ROOT.parent / "genres" / "genre_reference.json",
]
# 最后一次成功加载的路径（便于排查是否静默退回 stub）
LAST_LOADED_GENRE_REFERENCE_PATH: Optional[Path] = None

# 与 JSON 中 capabilities 字段对齐；未知 genre 或缺字段时兜底
DEFAULT_CAPABILITIES: Dict[str, Any] = {
    "uses_explicit_rules": False,
    "requires_rule_execution_map": False,
    "requires_visible_rule_punishment": False,
    "has_hidden_mechanism": False,
    "prefers_logic_trial": False,
    "prefers_relationship_push": False,
    "prefers_status_hierarchy_conflict": False,
}


def genre_reference_resolve_order() -> list[str]:
    """文档化：题材库文件尝试顺序（先命中先使用）。"""
    return [str(p.resolve()) for p in GENRE_REFERENCE_CANDIDATES]


def _load_genre_reference() -> Dict[str, Any]:
    """
    读取顺序：
    1) <包目录>/genres/genre_reference.json（ai_manga_factory/genres/…）
    2) <包上级>/genres/genre_reference.json（仓库根 genres/…）
    皆不存在时退回内存 stub（等价于仅 general），此时 LAST_LOADED_GENRE_REFERENCE_PATH 为 None。
    """
    global LAST_LOADED_GENRE_REFERENCE_PATH
    for path in GENRE_REFERENCE_CANDIDATES:
        if path.is_file():
            LAST_LOADED_GENRE_REFERENCE_PATH = path
            data = json.loads(path.read_text(encoding="utf-8"))
            # 兼容旧测试/旧调用：允许 ref["general"] 直接读取
            if isinstance(data, dict) and _is_schema_v2(data):
                pmap = data.get("primary_genres") or {}
                for k, v in pmap.items():
                    if k not in data and isinstance(v, dict):
                        data[k] = v
            return data
    LAST_LOADED_GENRE_REFERENCE_PATH = None
    return {
        "schema_version": "2.0",
        "primary_genres": {
            "general": {
                "display_name": "通用短剧",
                "id": "general",
                "aliases": ["通用"],
                "keywords": [],
                "capabilities": dict(DEFAULT_CAPABILITIES),
                "rules_block": "保持逻辑自洽，叙事动作化，结尾留动作钩。",
            }
        },
        "setting_tag_catalog": {},
        "engine_tag_catalog": {},
        "relationship_tag_catalog": {},
        "general_fallback": {"primary_genre": "general"},
    }


def _is_schema_v2(ref: Dict[str, Any]) -> bool:
    sv = str(ref.get("schema_version") or "")
    return sv.startswith("2.") and isinstance(ref.get("primary_genres"), dict)


def _primary_map(ref: Dict[str, Any]) -> Dict[str, Any]:
    if _is_schema_v2(ref):
        return ref.get("primary_genres") or {}
    # 兼容旧版：根对象直接是 primary 映射
    return {k: v for k, v in ref.items() if isinstance(v, dict)}


def _catalog_map(ref: Dict[str, Any], key: str) -> Dict[str, Any]:
    v = ref.get(key)
    return v if isinstance(v, dict) else {}


def _norm_text(s: str) -> str:
    t = str(s or "").lower().strip()
    t = re.sub(r"\s+", " ", t)
    return t


def _safe_list(v: Any) -> List[str]:
    if not isinstance(v, list):
        return []
    out: List[str] = []
    for x in v:
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
    return out


def _entry_hits(text: str, key: str, entry: Dict[str, Any]) -> Tuple[int, List[str], int]:
    score = 0
    hits: List[str] = []
    max_len = 0

    def hit(tok_show: str, w: int) -> None:
        nonlocal score, max_len
        score += w
        hits.append(tok_show)
        max_len = max(max_len, len(tok_show))

    k = str(key or "").strip().lower()
    if k and k in text:
        hit(k, 1)
    display_name = str(entry.get("display_name") or "").strip().lower()
    if display_name and display_name in text:
        hit(display_name, 2)
    for al in _safe_list(entry.get("aliases")):
        tok = al.lower()
        if tok and tok in text:
            hit(al, 3)
    for kw in _safe_list(entry.get("keywords")):
        tok = kw.lower()
        if tok and tok in text:
            hit(kw, 2)
    return score, list(dict.fromkeys(hits)), max_len


def infer_genre_from_text(text: str) -> str:
    """兼容旧接口：返回 primary_genre。"""
    return infer_genre_bundle_from_text(text).get("primary_genre") or "general"


def infer_genre_bundle_from_text(text: str) -> Dict[str, Any]:
    if not isinstance(text, str):
        text = str(text or "")
    t = _norm_text(text)
    ref = _load_genre_reference()
    pmap = _primary_map(ref)

    # 1) 先算“初步候选”：仅用于提供可解释候选集合
    primary_scores: Dict[str, Dict[str, Any]] = {}
    for key, entry in pmap.items():
        if not isinstance(entry, dict):
            continue
        score, hits, hit_len = _entry_hits(t, key, entry)
        if score > 0:
            primary_scores[key] = {"score": score, "hits": hits, "hit_len": hit_len}

    candidates = sorted(
        (
            {"primary": k, **v}
            for k, v in primary_scores.items()
        ),
        key=lambda x: (-int(x.get("score") or 0), int(x.get("hit_len") or 0), x.get("primary")),
    )
    top_primary = candidates[0]["primary"] if candidates else "general"

    # 2) primary 冲突裁决：规则式、可解释、轻量
    # 注意：tag 层仍独立推断；这里只决定最终 primary_genre。
    resolved_primary = top_primary if candidates else "general"
    applied_rules: List[Dict[str, Any]] = []

    def contains_any(terms: List[str]) -> bool:
        return any(term in t for term in terms if isinstance(term, str) and term)

    def term_hits(terms: List[str]) -> int:
        return sum(1 for term in terms if isinstance(term, str) and term and term in t)

    # 1) rule_horror vs horror
    rule_terms = ["规则怪谈", "无限流", "副本", "守则", "告示", "条款", "规则"]
    if "rule_horror" in pmap and "horror" in pmap:
        if contains_any(rule_terms):
            resolved_primary = "rule_horror"
            applied_rules.append(
                {"rule": "rule_horror_vs_horror", "win": "rule_horror", "reason": "命中规则载体/条款词"}
            )
        else:
            # 无规则载体则偏向 horror（如果它有候选命中）
            if "horror" in primary_scores:
                resolved_primary = "horror"
                applied_rules.append(
                    {"rule": "rule_horror_vs_horror", "win": "horror", "reason": "未命中规则载体，回退到恐怖惊悚"}
                )

    # 2) supernatural_urban vs urban
    super_terms = ["修仙", "高武", "灵气复苏", "灵气", "异能", "觉醒", "渡劫"]
    urban_terms = ["商战", "豪门", "职场", "办公室", "合同", "地位", "阶层", "打脸", "逆袭"]
    if "supernatural_urban" in pmap and "urban" in pmap:
        has_super = contains_any(super_terms)
        has_urban = contains_any(urban_terms)
        if has_super and not has_urban:
            resolved_primary = "supernatural_urban"
            applied_rules.append(
                {"rule": "supernatural_urban_vs_urban", "win": "supernatural_urban", "reason": "超自然驱动词强于纯都市权力词"}
            )
        elif has_super and has_urban:
            # 同时命中时：若“灵气复苏/异能/觉醒”这类超自然主卖点出现，仍偏向 supernatural_urban
            strong_super = contains_any(["灵气复苏", "异能", "觉醒"])
            if strong_super:
                win = "supernatural_urban"
                applied_rules.append(
                    {
                        "rule": "supernatural_urban_vs_urban",
                        "win": "supernatural_urban",
                        "reason": "命中灵气复苏/异能/觉醒等超自然主卖点，优先 supernatural_urban",
                    }
                )
            else:
                su = int(primary_scores.get("supernatural_urban", {}).get("score") or 0)
                ur = int(primary_scores.get("urban", {}).get("score") or 0)
                win = "supernatural_urban" if su >= ur else "urban"
                applied_rules.append(
                    {
                        "rule": "supernatural_urban_vs_urban",
                        "win": win,
                        "reason": f"同命中时按初步分数：supernatural_urban={su} / urban={ur}",
                    }
                )
            resolved_primary = win

    # 3) xianxia_fantasy vs supernatural_urban
    xianxia_terms = ["宗门", "仙门", "灵根", "渡劫", "飞升", "古风", "玄幻", "门派", "炼气", "筑基", "元婴"]
    modern_terms = ["都市", "现代", "校园", "职场", "公司", "办公室", "街区", "宴会", "高楼"]
    if "xianxia_fantasy" in pmap and "supernatural_urban" in pmap:
        xh = contains_any(xianxia_terms)
        md = contains_any(modern_terms)
        if xh and not md:
            resolved_primary = "xianxia_fantasy"
            applied_rules.append(
                {"rule": "xianxia_vs_supernatural_urban", "win": "xianxia_fantasy", "reason": "世界整体偏修仙/宗门/古风，非现代语境"}
            )
        elif xh and md:
            # 都市语境明确时优先“修炼嵌入现代生活”
            resolved_primary = "supernatural_urban"
            applied_rules.append(
                {"rule": "xianxia_vs_supernatural_urban", "win": "supernatural_urban", "reason": "现代语境词出现，修炼嵌入都市秩序"}
            )

    # 4) apocalypse vs rebirth_transmigration
    apoc_terms = ["末世", "末日", "丧尸", "尸潮", "极寒", "寒潮", "洪灾", "洪水", "灾变", "变异", "囤货", "生存", "避难"]
    rebirth_terms = ["重生", "回档", "二周目", "前世", "穿越", "穿书", "重活"]
    if "apocalypse" in pmap and "rebirth_transmigration" in pmap:
        ap = term_hits(apoc_terms)
        rb = term_hits(rebirth_terms)
        ap_score = int(primary_scores.get("apocalypse", {}).get("score") or 0)
        rb_score = int(primary_scores.get("rebirth_transmigration", {}).get("score") or 0)
        if ap >= 2 and ap >= rb:
            resolved_primary = "apocalypse"
            applied_rules.append(
                {
                    "rule": "apocalypse_vs_rebirth",
                    "win": "apocalypse",
                    "reason": f"末世环境压强更高：apocalypse_terms={ap} / rebirth_terms={rb}，score={ap_score}-{rb_score}",
                }
            )
        elif rb >= 3 and ap <= 1 and rb > ap:
            resolved_primary = "rebirth_transmigration"
            applied_rules.append(
                {
                    "rule": "apocalypse_vs_rebirth",
                    "win": "rebirth_transmigration",
                    "reason": f"回档/重活主卖点，末世语境弱：rebirth_terms={rb} / apocalypse_terms={ap}",
                }
            )

    # 5) modern_romance vs urban
    romance_terms = ["恋爱", "先婚后爱", "追妻", "甜宠", "误会", "拉扯", "婚约", "情感", "修罗场", "前任", "喜欢", "虐恋", "告白"]
    urban_terms2 = ["商战", "豪门", "职场", "办公室", "合同", "地位", "阶层", "打脸", "逆袭", "权力", "压制"]
    if "modern_romance" in pmap and "urban" in pmap and resolved_primary in ("urban", "modern_romance"):
        rm = term_hits(romance_terms)
        ur = term_hits(urban_terms2)
        rm_score = int(primary_scores.get("modern_romance", {}).get("score") or 0)
        ur_score = int(primary_scores.get("urban", {}).get("score") or 0)
        if rm >= 2 and ur <= 1:
            resolved_primary = "modern_romance"
            applied_rules.append(
                {"rule": "modern_romance_vs_urban", "win": "modern_romance", "reason": f"关系拉扯主卖点：romance_terms={rm} / urban_terms={ur}"}
            )
        elif ur >= 2 and rm <= 1:
            resolved_primary = "urban"
            applied_rules.append(
                {"rule": "modern_romance_vs_urban", "win": "urban", "reason": f"地位/资源压制主卖点：urban_terms={ur} / romance_terms={rm}"}
            )
        else:
            # 不太明确则按分数，但只有当“显性关系/显性都市压制”至少命中一类时才允许抢占
            if rm > 0 or ur > 0:
                win = "modern_romance" if rm_score >= ur_score else "urban"
                if win != resolved_primary and (rm_score > 0 or ur_score > 0):
                    resolved_primary = win
                    applied_rules.append(
                        {"rule": "modern_romance_vs_urban", "win": win, "reason": f"同等不确定时按score：modern={rm_score} / urban={ur_score}"}
                    )

    # 6) system_powerup vs others（一般不抢 primary）
    sys_terms = ["系统", "任务", "签到", "面板", "任务流", "系统文", "抽奖"]
    if "system_powerup" in pmap:
        sys_hit = term_hits(sys_terms)
        sys_score = int(primary_scores.get("system_powerup", {}).get("score") or 0)
        top_other = candidates[1]["primary"] if len(candidates) > 1 else None
        top_other_score = int(primary_scores.get(top_other, {}).get("score") or 0) if top_other else 0
        if sys_hit >= 3 or (sys_score >= top_other_score + 2 and sys_score > 0):
            resolved_primary = "system_powerup"
            applied_rules.append(
                {"rule": "system_powerup_vs_others", "win": "system_powerup", "reason": f"系统任务词占比高：sys_hit={sys_hit}, score={sys_score} / other={top_other_score}"}
            )
        else:
            if resolved_primary == "system_powerup" and candidates:
                # 抢占不成立则让位给最高候选（一般就是 non-system）
                for c in candidates:
                    if c["primary"] != "system_powerup":
                        resolved_primary = c["primary"]
                        applied_rules.append(
                            {"rule": "system_powerup_vs_others", "win": resolved_primary, "reason": "系统任务词不足以抢占 primary"}
                        )
                        break

    # 3) 如果没有候选命中，回退到 general
    if not candidates:
        resolved_primary = "general"
        best_primary_score = 0
        best_primary_len = 0
        alias_hits: List[str] = []
    else:
        best_primary_score = int(primary_scores.get(resolved_primary, {}).get("score") or 0)
        best_primary_len = int(primary_scores.get(resolved_primary, {}).get("hit_len") or 0)
        alias_hits = primary_scores.get(resolved_primary, {}).get("hits") or []

    primary_resolution_trace: Dict[str, Any] = {
        "initial_top_candidates": candidates[:3],
        "decision_rules": applied_rules[:4],
        "final_primary": resolved_primary,
    }

    def pick_tags(catalog_key: str) -> List[str]:
        out: List[Tuple[str, int]] = []
        catalog = _catalog_map(ref, catalog_key)
        for key, entry in catalog.items():
            if not isinstance(entry, dict):
                continue
            s, hits, _ = _entry_hits(t, key, entry)
            if s > 0:
                out.append((key, s))
                alias_hits.extend(hits)
        out.sort(key=lambda x: (-x[1], x[0]))
        return [k for k, _ in out[:4]]

    setting_tags = pick_tags("setting_tag_catalog")
    engine_tags = pick_tags("engine_tag_catalog")
    relationship_tags = pick_tags("relationship_tag_catalog")
    return {
        "primary_genre": resolved_primary,
        "setting_tags": setting_tags,
        "engine_tags": engine_tags,
        "relationship_tags": relationship_tags,
        "resolved_alias_hits": list(dict.fromkeys(alias_hits))[:20],
        "primary_resolution_trace": primary_resolution_trace,
        "confidence": {
            "primary_score": best_primary_score,
            "tag_hits_count": len(setting_tags) + len(engine_tags) + len(relationship_tags),
            "mode": "keyword_rule_v2",
        },
    }


def get_genre_capabilities(genre_key: str) -> Dict[str, Any]:
    """兼容旧接口：读取 primary 题材能力。"""
    return get_primary_genre_capabilities(genre_key)


def get_primary_genre_capabilities(primary_genre: str) -> Dict[str, Any]:
    ref = _load_genre_reference()
    pmap = _primary_map(ref)
    entry = pmap.get(primary_genre) or pmap.get("general") or {}
    raw = entry.get("capabilities")
    if not isinstance(raw, dict):
        raw = {}
    out = dict(DEFAULT_CAPABILITIES)
    for k, v in raw.items():
        if k in DEFAULT_CAPABILITIES and isinstance(v, bool):
            out[k] = v
        elif k in DEFAULT_CAPABILITIES:
            out[k] = bool(v) if v is not None else DEFAULT_CAPABILITIES[k]
    return out


def get_bundle_capabilities(bundle: Dict[str, Any]) -> Dict[str, Any]:
    base = get_primary_genre_capabilities(str(bundle.get("primary_genre") or "general"))
    out = dict(base)
    # 规则可解释合并：primary 为基线，engine/relationship 对特定开关做“增强”。
    boosts_engine = {
        "weird_rule_exploit": {"uses_explicit_rules": True, "prefers_logic_trial": True},
        "survival_trial": {"prefers_logic_trial": True},
        "system_assignment": {"prefers_logic_trial": True},
    }
    boosts_relationship = {
        "romance_push_pull": {"prefers_relationship_push": True},
        "contract_marriage_tension": {"prefers_relationship_push": True},
        "status_hierarchy_conflict": {"prefers_status_hierarchy_conflict": True},
        "public_face_slap": {"prefers_status_hierarchy_conflict": True},
    }
    for tag in _safe_list(bundle.get("engine_tags")):
        b = boosts_engine.get(tag) or {}
        for k, v in b.items():
            if k in out and v is True:
                out[k] = True
    for tag in _safe_list(bundle.get("relationship_tags")):
        b = boosts_relationship.get(tag) or {}
        for k, v in b.items():
            if k in out and v is True:
                out[k] = True
    return out


def capabilities_to_prompt_block(capabilities: Dict[str, Any]) -> str:
    """把能力开关转成固定格式的 prompt 前缀块，供各 agent 遵循。"""
    caps = dict(DEFAULT_CAPABILITIES)
    if isinstance(capabilities, dict):
        for k in DEFAULT_CAPABILITIES:
            if k in capabilities:
                caps[k] = bool(capabilities[k])

    lines = [
        "【题材能力开关】（须与下文创作约束一致；不要与题材规则包矛盾）",
        f"- current_capabilities.uses_explicit_rules: {caps['uses_explicit_rules']}",
        f"- current_capabilities.requires_rule_execution_map: {caps['requires_rule_execution_map']}",
        f"- current_capabilities.requires_visible_rule_punishment: {caps['requires_visible_rule_punishment']}",
        f"- current_capabilities.has_hidden_mechanism: {caps['has_hidden_mechanism']}",
        f"- current_capabilities.prefers_logic_trial: {caps['prefers_logic_trial']}",
        f"- current_capabilities.prefers_relationship_push: {caps['prefers_relationship_push']}",
        f"- current_capabilities.prefers_status_hierarchy_conflict: {caps['prefers_status_hierarchy_conflict']}",
    ]
    return "\n".join(lines) + "\n"


# --- 分 stage / agent 的题材注入 profile（v2.1 厚 reference 落地）---
GENRE_PROFILE_EARLY_IDEATION = "early_ideation"
GENRE_PROFILE_OUTLINE_STRUCTURAL = "outline_structural"
GENRE_PROFILE_OUTLINE_BIAS_HEAVY = "outline_bias_heavy"
GENRE_PROFILE_EPISODE_EXECUTION = "episode_execution"
GENRE_PROFILE_GATE_REVIEW = "gate_review"


def build_genre_bundle_header(bundle: Dict[str, Any]) -> str:
    """统一「题材识别」头，供各 profile 前置。"""
    return (
        f"【题材识别】primary={bundle.get('primary_genre')}"
        f" | setting={','.join(bundle.get('setting_tags') or []) or '-'}"
        f" | engine={','.join(bundle.get('engine_tags') or []) or '-'}"
        f" | relationship={','.join(bundle.get('relationship_tags') or []) or '-'}\n\n"
    )


def collect_outline_bias_lines(bundle: Dict[str, Any], max_items: int = 7) -> List[str]:
    """与 get_bundle_outline_bias_block 同源逻辑，返回去重后的短句列表。"""
    ref = _load_genre_reference()
    pmap = _primary_map(ref)
    primary = str(bundle.get("primary_genre") or "general")
    biases: List[str] = []

    def take_from_catalog(keys: List[str], catalog_key: str) -> None:
        catalog = _catalog_map(ref, catalog_key)
        for k in keys[:3]:
            e = catalog.get(k) or {}
            for b in _safe_list(e.get("outline_bias"))[:3]:
                biases.append(str(b).strip())

    pentry = pmap.get(primary) or pmap.get("general") or {}
    for b in _safe_list(pentry.get("outline_bias"))[:4]:
        biases.append(str(b).strip())
    take_from_catalog(_safe_list(bundle.get("setting_tags")), "setting_tag_catalog")
    take_from_catalog(_safe_list(bundle.get("engine_tags")), "engine_tag_catalog")
    take_from_catalog(_safe_list(bundle.get("relationship_tags")), "relationship_tag_catalog")
    uniq = list(dict.fromkeys([b for b in biases if b]))
    return uniq[:max_items]


def _pentry_for_bundle(bundle: Dict[str, Any]) -> Tuple[Dict[str, Any], str, str]:
    ref = _load_genre_reference()
    pmap = _primary_map(ref)
    primary = str(bundle.get("primary_genre") or "general")
    pentry = pmap.get(primary) or pmap.get("general") or {}
    p_name = str(pentry.get("display_name") or primary)
    return pentry, primary, p_name


def _extract_h2_section(rules_block: str, title: str) -> str:
    """从 rules_block 中抽取 `## 标题` 到下一 `##` 之间的正文。"""
    if not rules_block or not title:
        return ""
    pat = re.compile(
        rf"##\s*{re.escape(title)}\s*\n(.*?)(?=\n##\s|\Z)",
        re.DOTALL,
    )
    m = pat.search(rules_block)
    if not m:
        return ""
    return m.group(1).strip()


def _section_bullets_by_title(pentry: Dict[str, Any], title_substr: str, max_bullets: int = 4) -> List[str]:
    sections = pentry.get("sections") if isinstance(pentry.get("sections"), list) else []
    for s in sections:
        if not isinstance(s, dict):
            continue
        st = str(s.get("title") or "")
        if title_substr in st:
            return _extract_first_bullets_from_content(str(s.get("content") or ""), max_bullets=max_bullets)
    return []


def _collect_section_excerpt_lines(
    pentry: Dict[str, Any],
    *,
    skip_title_contains: Optional[str] = None,
    max_sections: int = 4,
    max_bullets: int = 2,
) -> List[str]:
    """从 sections 抽 2–4 条「标题：要点」短行，控制长度。"""
    sections = pentry.get("sections") if isinstance(pentry.get("sections"), list) else []
    picked: List[Dict[str, Any]] = [s for s in sections if isinstance(s, dict)]
    lines: List[str] = []
    for s in picked:
        if len(lines) >= max_sections:
            break
        st = str(s.get("title") or "").strip()
        if skip_title_contains and skip_title_contains in st:
            continue
        sc = str(s.get("content") or "")
        bullets = _extract_first_bullets_from_content(sc, max_bullets=max_bullets)
        if st and bullets:
            lines.append(f"{st}：{'；'.join(bullets)}")
        elif st and sc.strip():
            lines.append(f"{st}：{_truncate_text(sc, 100, suffix='')}")
    return lines


def _append_tag_prompt_notes(
    lines: List[str],
    bundle: Dict[str, Any],
    ref: Dict[str, Any],
    *,
    setting_n: int,
    engine_n: int,
    rel_n: int,
    note_max: int,
    title_setting: str = "设定层补充",
    title_engine: str = "推进引擎补充",
    title_rel: str = "关系驱动补充",
) -> None:
    def pack(keys: List[str], catalog_key: str, title: str, n: int) -> None:
        catalog = _catalog_map(ref, catalog_key)
        if not keys or n <= 0:
            return
        acc: List[str] = []
        for k in keys[:n]:
            e = catalog.get(k) or {}
            dn = str(e.get("display_name") or k)
            pn = str(e.get("prompt_note") or "").strip()
            if note_max > 0 and len(pn) > note_max:
                pn = pn[:note_max].rstrip() + "…"
            if pn:
                acc.append(f"- {dn}（{k}）：{pn}")
            else:
                acc.append(f"- {dn}（{k}）")
        if acc:
            lines.append(f"【{title}】")
            lines.extend(acc)

    pack(_safe_list(bundle.get("setting_tags")), "setting_tag_catalog", title_setting, setting_n)
    pack(_safe_list(bundle.get("engine_tags")), "engine_tag_catalog", title_engine, engine_n)
    pack(_safe_list(bundle.get("relationship_tags")), "relationship_tag_catalog", title_rel, rel_n)


def _cap_block(s: str, max_chars: int) -> str:
    s = s.strip()
    if max_chars <= 0 or len(s) <= max_chars:
        return s
    return s[:max_chars].rstrip() + "\n（已截断）"


def get_genre_prompt_block_for_profile(
    bundle: Dict[str, Any],
    profile: str,
    *,
    outline_bias_mode: str = "off",
    episode_variant: str = "normal",
) -> str:
    """
    按 profile 生成题材块（不含【题材识别】头；由调用方与 build_genre_bundle_header 组合）。

    profile:
      - early_ideation: 轻量
      - outline_structural: 结构/节奏向
      - outline_bias_heavy: 大纲链加厚
      - episode_execution: 分集执行
      - gate_review: 门神评审锚点

    outline_bias_mode: off | light | heavy（对 outline_structural 有效；outline_bias_heavy 恒为重度内嵌）
    episode_variant: normal | light（略减 tag/失败模式条数）
    """
    ref = _load_genre_reference()
    pentry, primary, p_name = _pentry_for_bundle(bundle)
    ft = pentry.get("frontmatter") if isinstance(pentry.get("frontmatter"), dict) else {}
    rules_full = str(pentry.get("rules_block") or "").strip()
    merged = get_bundle_capabilities(bundle)
    lines: List[str] = [f"【题材 profile】{profile}"]

    if profile == GENRE_PROFILE_EARLY_IDEATION:
        lines.append(f"【主题材概要】{p_name}（{primary}）")
        pr = str(ft.get("pacingRule") or "").strip()
        if pr:
            lines.append("【节奏提示（节选）】")
            lines.append(f"- {_cap_block(pr, 140)}")
        _append_tag_prompt_notes(
            lines, bundle, ref, setting_n=2, engine_n=2, rel_n=2, note_max=90
        )
        lines.append(capabilities_to_prompt_block(merged).strip())
        return _cap_block("\n".join(lines).strip() + "\n", 1400)

    if profile == GENRE_PROFILE_OUTLINE_STRUCTURAL:
        lines.append(f"【当前主题材】{p_name} ({primary})")
        excerpt = _truncate_text(rules_full, 950, suffix="（规则节选已截断）")
        if excerpt:
            lines.append("【主题材规则（节选）】")
            lines.append(excerpt)
        ch = _safe_list(ft.get("chapterTypes"))
        if ch:
            lines.append("【章节场型（chapterTypes）】")
            lines.append("- " + "、".join(ch[:6]))
        pacing = str(ft.get("pacingRule") or "").strip()
        if pacing:
            lines.append("【节奏强约束（pacingRule）】")
            lines.append(f"- {_cap_block(pacing, 420)}")
        pp = str(ft.get("protagonistPressureType") or "").strip()
        if pp:
            lines.append("【主角压力类型】")
            lines.append(f"- {_cap_block(pp, 220)}")
        cf = _safe_list(ft.get("commonFailureModes"))[:4]
        if cf:
            lines.append("【常见失败模式（精选）】")
            lines.extend([f"- {x}" for x in cf])
        taboo_bullets = _section_bullets_by_title(pentry, "禁忌", max_bullets=3)
        if taboo_bullets:
            lines.append("【题材禁忌要点（sections）】")
            lines.extend([f"- {b}" for b in taboo_bullets])
        sec_ex = _collect_section_excerpt_lines(
            pentry, skip_title_contains="禁忌", max_sections=3, max_bullets=2
        )
        if sec_ex:
            lines.append("【关键段落摘录（sections）】")
            lines.extend([f"- {x}" for x in sec_ex])
        _append_tag_prompt_notes(
            lines, bundle, ref, setting_n=3, engine_n=3, rel_n=3, note_max=160
        )
        if outline_bias_mode == "light":
            ob = collect_outline_bias_lines(bundle, max_items=2)
            if ob:
                lines.append("【阶段偏向（轻量）】")
                lines.extend([f"- {x}" for x in ob])
        lines.append(capabilities_to_prompt_block(merged).strip())
        return _cap_block("\n".join(lines).strip() + "\n", 3400)

    if profile == GENRE_PROFILE_OUTLINE_BIAS_HEAVY:
        lines.append(f"【当前主题材】{p_name} ({primary})")
        ob_lines = collect_outline_bias_lines(bundle, max_items=7)
        if ob_lines:
            lines.append("【题材阶段偏向（大纲锚点/分集/复审）】")
            lines.extend([f"- {x}" for x in ob_lines])
        ch = _safe_list(ft.get("chapterTypes"))
        if ch:
            lines.append("【章节场型（chapterTypes）】")
            lines.append("- " + "、".join(ch[:6]))
        pacing = str(ft.get("pacingRule") or "").strip()
        if pacing:
            lines.append("【节奏强约束（pacingRule）】")
            lines.append(f"- {_cap_block(pacing, 380)}")
        sat = _safe_list(ft.get("satisfactionTypes"))[:5]
        if sat:
            lines.append("【爽点类型（satisfactionTypes）】")
            lines.append("- " + "、".join(sat))
        cf = _safe_list(ft.get("commonFailureModes"))[:5]
        if cf:
            lines.append("【常见失败模式】")
            lines.extend([f"- {x}" for x in cf])
        op = str(ft.get("openingRule") or "").strip()
        ed = str(ft.get("endingHookRule") or "").strip()
        if op:
            lines.append("【开场钩子】")
            lines.append(f"- {_cap_block(op, 200)}")
        if ed:
            lines.append("【结尾留钩】")
            lines.append(f"- {_cap_block(ed, 200)}")
        excerpt = _truncate_text(rules_full, 520, suffix="（规则节选已截断）")
        if excerpt:
            lines.append("【主题材规则（节选）】")
            lines.append(excerpt)
        _append_tag_prompt_notes(
            lines, bundle, ref, setting_n=3, engine_n=3, rel_n=3, note_max=140
        )
        lines.append(capabilities_to_prompt_block(merged).strip())
        return _cap_block("\n".join(lines).strip() + "\n", 4000)

    if profile == GENRE_PROFILE_EPISODE_EXECUTION:
        light = episode_variant == "light"
        lines.append(f"【执行向主题材】{p_name} ({primary})")
        ch = _safe_list(ft.get("chapterTypes"))
        if ch:
            lines.append("【章节场型】")
            lines.append("- " + "、".join(ch[:5]))
        pacing = str(ft.get("pacingRule") or "").strip()
        if pacing:
            lines.append("【节奏执行要点】")
            lines.append(f"- {_cap_block(pacing, 320)}")
        pp = str(ft.get("protagonistPressureType") or "").strip()
        if pp:
            lines.append("【主角压力】")
            lines.append(f"- {_cap_block(pp, 200)}")
        sat = _safe_list(ft.get("satisfactionTypes"))[:4]
        if sat:
            lines.append("【本集爽点方向】")
            lines.append("- " + "、".join(sat))
        n_fail = 3 if light else 5
        cf = _safe_list(ft.get("commonFailureModes"))[:n_fail]
        if cf:
            lines.append("【避免踩坑】")
            lines.extend([f"- {x}" for x in cf])
        fw = _safe_list(ft.get("fatigueWords"))[:4]
        if fw:
            lines.append("【慎用词（fatigueWords）】")
            lines.append("- " + "、".join(fw))
        sn, en, rn = (1, 1, 1) if light else (2, 2, 2)
        _append_tag_prompt_notes(
            lines, bundle, ref, setting_n=sn, engine_n=en, rel_n=rn, note_max=110
        )
        lines.append(capabilities_to_prompt_block(merged).strip())
        return _cap_block("\n".join(lines).strip() + "\n", 3000)

    if profile == GENRE_PROFILE_GATE_REVIEW:
        lines.append(f"【评审锚点·主题材】{p_name} ({primary})")
        taboo = _extract_h2_section(rules_full, "题材禁忌")
        if not taboo:
            taboo = "\n".join(f"- {b}" for b in _section_bullets_by_title(pentry, "禁忌", max_bullets=5))
        if taboo.strip():
            lines.append("【题材禁忌（评审对照）】")
            lines.append(_cap_block(taboo, 900))
        pacing = str(ft.get("pacingRule") or "").strip()
        if pacing:
            lines.append("【节奏要求】")
            lines.append(f"- {_cap_block(pacing, 360)}")
        cf = _safe_list(ft.get("commonFailureModes"))[:5]
        if cf:
            lines.append("【失败模式（命中即减分）】")
            lines.extend([f"- {x}" for x in cf])
        sat = _safe_list(ft.get("satisfactionTypes"))[:4]
        if sat:
            lines.append("【爽点兑现检查】")
            lines.append("- " + "、".join(sat))
        _append_tag_prompt_notes(
            lines, bundle, ref, setting_n=2, engine_n=2, rel_n=2, note_max=130,
            title_setting="设定触发", title_engine="引擎触发", title_rel="关系触发",
        )
        lines.append("【评审指令】请判断产物是否具备上述题材气质与执行约束，避免「像别类题材」。")
        lines.append(capabilities_to_prompt_block(merged).strip())
        return _cap_block("\n".join(lines).strip() + "\n", 2800)

    # 未知 profile：回退 structural
    return get_genre_prompt_block_for_profile(
        bundle, GENRE_PROFILE_OUTLINE_STRUCTURAL, outline_bias_mode=outline_bias_mode
    )


def compose_genre_injection(
    bundle: Dict[str, Any],
    *,
    profile: str,
    outline_bias_mode: str = "off",
    episode_variant: str = "normal",
    include_header: bool = True,
) -> str:
    """header + profile 块，供 run_series / gate 统一拼接。"""
    body = get_genre_prompt_block_for_profile(
        bundle,
        profile,
        outline_bias_mode=outline_bias_mode,
        episode_variant=episode_variant,
    )
    if include_header:
        return build_genre_bundle_header(bundle) + body
    return body


# stage / agent 名 → (profile, outline_bias_mode, episode_variant)；供全链路统一映射
GENRE_STAGE_INJECTION: Dict[str, Tuple[str, str, str]] = {
    "market_research": (GENRE_PROFILE_EARLY_IDEATION, "off", "normal"),
    "trend_scout": (GENRE_PROFILE_EARLY_IDEATION, "off", "normal"),
    "concept_judge": (GENRE_PROFILE_EARLY_IDEATION, "off", "normal"),
    "season_mainline": (GENRE_PROFILE_OUTLINE_STRUCTURAL, "light", "normal"),
    "character_growth": (GENRE_PROFILE_OUTLINE_STRUCTURAL, "off", "normal"),
    "world_reveal_pacing": (GENRE_PROFILE_OUTLINE_STRUCTURAL, "off", "normal"),
    "coupling_reconciler": (GENRE_PROFILE_OUTLINE_STRUCTURAL, "off", "normal"),
    "series_spine": (GENRE_PROFILE_OUTLINE_STRUCTURAL, "off", "normal"),
    "anchor_beats": (GENRE_PROFILE_OUTLINE_BIAS_HEAVY, "off", "normal"),
    "episode_outline_expander": (GENRE_PROFILE_OUTLINE_BIAS_HEAVY, "off", "normal"),
    "outline_review": (GENRE_PROFILE_OUTLINE_BIAS_HEAVY, "off", "normal"),
    "character_bible": (GENRE_PROFILE_OUTLINE_STRUCTURAL, "off", "normal"),
    "episode_function": (GENRE_PROFILE_EPISODE_EXECUTION, "off", "normal"),
    "episode_plot": (GENRE_PROFILE_EPISODE_EXECUTION, "off", "normal"),
    "episode_script": (GENRE_PROFILE_EPISODE_EXECUTION, "off", "normal"),
    "episode_storyboard": (GENRE_PROFILE_EPISODE_EXECUTION, "off", "normal"),
    "char_visual_patch": (GENRE_PROFILE_EPISODE_EXECUTION, "off", "light"),
    "episode_memory": (GENRE_PROFILE_EPISODE_EXECUTION, "off", "light"),
    "gate_plot_judge": (GENRE_PROFILE_GATE_REVIEW, "off", "normal"),
    "gate_package_judge": (GENRE_PROFILE_GATE_REVIEW, "off", "normal"),
}


def compose_genre_injection_for_stage(
    bundle: Dict[str, Any],
    stage_name: str,
    *,
    include_header: bool = True,
) -> str:
    """按流水线 stage 名选择 profile，等价于各模块内手写 if/else。"""
    prof, bias_mode, ep_var = GENRE_STAGE_INJECTION.get(
        stage_name, (GENRE_PROFILE_OUTLINE_STRUCTURAL, "off", "normal")
    )
    return compose_genre_injection(
        bundle,
        profile=prof,
        outline_bias_mode=bias_mode,
        episode_variant=ep_var,
        include_header=include_header,
    )


def get_genre_prompt_block_for_stage(bundle: Dict[str, Any], stage_name: str) -> str:
    """仅题材规则块（无【题材识别】头），便于嵌入已有模板。"""
    prof, bias_mode, ep_var = GENRE_STAGE_INJECTION.get(
        stage_name, (GENRE_PROFILE_OUTLINE_STRUCTURAL, "off", "normal")
    )
    return get_genre_prompt_block_for_profile(
        bundle, prof, outline_bias_mode=bias_mode, episode_variant=ep_var
    )


def build_genre_prompt_profile(bundle: Dict[str, Any], stage_name: str) -> str:
    """与 compose_genre_injection_for_stage 相同（含 header），命名贴近「profile 构建器」。"""
    return compose_genre_injection_for_stage(bundle, stage_name, include_header=True)


def get_genre_prompt_block_for_agent(bundle: Dict[str, Any], agent_stage_key: str) -> str:
    """与 stage 映射一致；agent 专用别名（键与 GENRE_STAGE_INJECTION 相同）。"""
    return get_genre_prompt_block_for_stage(bundle, agent_stage_key)


def summarize_genre_bundle_for_debug(bundle: Dict[str, Any], max_len: int = 220) -> str:
    """registry 可选字段：人类可读的 bundle 摘要。"""
    pg = str(bundle.get("primary_genre") or "")
    st = _safe_list(bundle.get("setting_tags"))
    en = _safe_list(bundle.get("engine_tags"))
    rel = _safe_list(bundle.get("relationship_tags"))
    parts = [
        f"primary={pg}",
        f"setting={','.join(st[:4])}" if st else "",
        f"engine={','.join(en[:4])}" if en else "",
        f"rel={','.join(rel[:4])}" if rel else "",
    ]
    s = " | ".join(p for p in parts if p)
    return _cap_block(s, max_len) if s else ""


def bundle_from_registry_series_identity(si: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    从 registry.series_identity 还原用于 prompt 的 bundle（含可选调试字段透传）。
    若无有效 primary 则返回 None。
    """
    if not isinstance(si, dict):
        return None
    primary = str(si.get("final_primary_genre") or si.get("primary_genre") or si.get("genre_key") or "").strip()
    if not primary:
        return None
    out: Dict[str, Any] = {
        "primary_genre": primary,
        "setting_tags": list(si.get("setting_tags") or []) if isinstance(si.get("setting_tags"), list) else [],
        "engine_tags": list(si.get("engine_tags") or []) if isinstance(si.get("engine_tags"), list) else [],
        "relationship_tags": (
            list(si.get("relationship_tags") or [])
            if isinstance(si.get("relationship_tags"), list)
            else []
        ),
    }
    for k in ("resolved_alias_hits", "primary_resolution_trace", "confidence"):
        if k in si and si[k] is not None:
            out[k] = si[k]
    return out


def infer_genre_context_for_prompt(prompt: str) -> Tuple[str, str, Dict[str, Any]]:
    """兼容旧接口：返回 (primary_genre, bundle_prompt_block, merged_capabilities)。"""
    bundle = infer_genre_bundle_for_prompt(prompt)
    g = str(bundle.get("primary_genre") or "general")
    return g, get_genre_bundle_prompt_block(bundle), get_bundle_capabilities(bundle)


def infer_genre_bundle_for_prompt(prompt: str) -> Dict[str, Any]:
    return infer_genre_bundle_from_text(prompt)


def get_genre_rules_block(genre_key: str) -> str:
    # 兼容旧接口：仅 primary 规则块
    ref = _load_genre_reference()
    pmap = _primary_map(ref)
    entry = pmap.get(genre_key) or pmap.get("general") or {}
    display_name = str(entry.get("display_name") or genre_key)
    rules_body = str(entry.get("rules_block") or "").strip()
    return f"【主题材规则：{display_name}】\n{rules_body}\n"


def _truncate_text(s: str, max_chars: int, suffix: str = "（已截断）") -> str:
    if not isinstance(s, str):
        s = str(s or "")
    if max_chars <= 0:
        return s
    if len(s) <= max_chars:
        return s
    # 保留开头高信息密度内容，避免把后段大量“解释性文字”堆进 prompt。
    return s[:max_chars].rstrip() + "\n" + suffix


def _extract_first_bullets_from_content(content: str, max_bullets: int = 2) -> List[str]:
    """
    从 sections[i].content 提取形如 `- xxx` 的前若干条要点（用于控制长度）。
    """
    if not isinstance(content, str):
        content = str(content or "")
    bullets: List[str] = []
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("- "):
            item = line[2:].strip()
            if item:
                bullets.append(item)
        if len(bullets) >= max_bullets:
            break
    return bullets


def _primary_dense_injection(pentry: Dict[str, Any]) -> str:
    """
    从厚 reference 的 frontmatter / sections 抽取“高密度但短”的节奏与失败模式要点。
    目标：让通用 agent 输入里看得到厚内容，但避免无脑全拼接。
    """
    ft = pentry.get("frontmatter") if isinstance(pentry.get("frontmatter"), dict) else {}
    sections = pentry.get("sections") if isinstance(pentry.get("sections"), list) else []

    lines: List[str] = []

    chapter_types = _safe_list(ft.get("chapterTypes"))
    if chapter_types:
        lines.append("【节奏与表达（chapterTypes）】")
        lines.append("- " + "、".join(chapter_types[:6]))

    fatigue_words = _safe_list(ft.get("fatigueWords"))
    if fatigue_words:
        lines.append("【词汇与情绪替换（fatigueWords）】")
        lines.append("- " + "、".join(fatigue_words[:6]))

    pacing_rule = str(ft.get("pacingRule") or "").strip()
    if pacing_rule:
        lines.append("【节奏强约束（pacingRule）】")
        lines.append(f"- {pacing_rule}")

    satisfaction_types = _safe_list(ft.get("satisfactionTypes"))
    if satisfaction_types:
        lines.append("【爽点兑现清单（satisfactionTypes）】")
        lines.append("- " + "、".join(satisfaction_types[:4]))

    opening_rule = str(ft.get("openingRule") or "").strip()
    if opening_rule:
        lines.append("【开场钩子（openingRule）】")
        lines.append(f"- {opening_rule}")

    ending_hook = str(ft.get("endingHookRule") or "").strip()
    if ending_hook:
        lines.append("【结尾留钩（endingHookRule）】")
        lines.append(f"- {ending_hook}")

    protagonist_pressure = str(ft.get("protagonistPressureType") or "").strip()
    if protagonist_pressure:
        lines.append("【主角压力类型】")
        lines.append(f"- {protagonist_pressure}")

    common_failure = _safe_list(ft.get("commonFailureModes"))
    if common_failure:
        lines.append("【常见失败模式（失败模式）】")
        lines.extend([f"- {x}" for x in common_failure[:5]])

    # sections：只取最关键 3 个 sections，并且每个仅抽取 2 条 bullet。
    picked: List[Dict[str, Any]] = [s for s in sections if isinstance(s, dict)]
    if picked:
        lines.append("【关键段落（sections）】")
        for s in picked[:3]:
            st = str(s.get("title") or "").strip()
            sc = str(s.get("content") or "")
            bullets = _extract_first_bullets_from_content(sc, max_bullets=2)
            if st and bullets:
                lines.append(f"- {st}：{'；'.join(bullets)}")
            elif st and sc.strip():
                lines.append(f"- {st}：{_truncate_text(sc, 90, suffix='')}")
            elif sc.strip():
                lines.append(f"- {_truncate_text(sc, 90, suffix='')}")

    dense = "\n".join(lines).strip()
    # 总长度控制：只对 dense 块截断（rules_block 本身不截断，以保留完整主题规则包）。
    return _truncate_text(dense, 1300, suffix="（已截断）")


def get_genre_bundle_prompt_block(bundle: Dict[str, Any]) -> str:
    ref = _load_genre_reference()
    pmap = _primary_map(ref)
    primary = str(bundle.get("primary_genre") or "general")
    pentry = pmap.get(primary) or pmap.get("general") or {}
    p_name = str(pentry.get("display_name") or primary)
    rules = _truncate_text(str(pentry.get("rules_block") or "").strip(), 2400, suffix="（规则包已截断）")
    lines = [f"【当前主题材】{p_name} ({primary})"]
    if rules:
        lines.append("【核心题材规则包】")
        lines.append(f"【主题材规则】{rules}")
        dense = _primary_dense_injection(pentry)
        if dense:
            lines.append(dense)

    def notes_for(tag_keys: List[str], catalog_key: str, title: str) -> None:
        catalog = _catalog_map(ref, catalog_key)
        if not tag_keys:
            return
        note_items: List[str] = []
        for k in tag_keys[:3]:
            e = catalog.get(k) or {}
            dn = str(e.get("display_name") or k)
            pn = str(e.get("prompt_note") or "").strip()
            if pn:
                note_items.append(f"- {dn}（{k}）：{pn}")
            else:
                note_items.append(f"- {dn}（{k}）")
        if note_items:
            lines.append(f"【{title}】")
            lines.extend(note_items)

    notes_for(_safe_list(bundle.get("setting_tags")), "setting_tag_catalog", "设定层补充")
    notes_for(_safe_list(bundle.get("engine_tags")), "engine_tag_catalog", "推进引擎补充")
    notes_for(_safe_list(bundle.get("relationship_tags")), "relationship_tag_catalog", "关系驱动补充")

    merged = get_bundle_capabilities(bundle)
    # 能力开关包：固定格式，供 agent 做“可执行偏好判断”。
    lines.append(capabilities_to_prompt_block(merged).strip())
    return "\n".join(lines).strip() + "\n"


def get_bundle_outline_bias_block(bundle: Dict[str, Any]) -> str:
    """
    outline_bias：面向“阶段/锚点/单集动力”的偏向信息。
    要点：不与 rules_block 重复，尽量短且可解释。
    """
    ref = _load_genre_reference()
    pmap = _primary_map(ref)
    primary = str(bundle.get("primary_genre") or "general")

    biases: List[str] = []

    def take_from_catalog(keys: List[str], catalog_key: str) -> None:
        catalog = _catalog_map(ref, catalog_key)
        for k in keys[:3]:
            e = catalog.get(k) or {}
            for b in _safe_list(e.get("outline_bias"))[:3]:
                biases.append(str(b).strip())

    pentry = pmap.get(primary) or pmap.get("general") or {}
    for b in _safe_list(pentry.get("outline_bias"))[:4]:
        biases.append(str(b).strip())

    take_from_catalog(_safe_list(bundle.get("setting_tags")), "setting_tag_catalog")
    take_from_catalog(_safe_list(bundle.get("engine_tags")), "engine_tag_catalog")
    take_from_catalog(_safe_list(bundle.get("relationship_tags")), "relationship_tag_catalog")

    uniq = list(dict.fromkeys([b for b in biases if b]))
    uniq = uniq[:7]

    if not uniq:
        return ""

    return (
        "【题材阶段偏向（用于主线/锚点/分集大纲/复审）】\n"
        + "\n".join([f"- {x}" for x in uniq])
        + "\n"
    )


def infer_genre_rules_for_prompt(prompt: str) -> Tuple[str, str]:
    """返回 (primary_genre, rules_block) 方便上层注入 prompt。"""
    g, rules_block, _caps = infer_genre_context_for_prompt(prompt)
    return g, rules_block

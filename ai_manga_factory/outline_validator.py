from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


_ABSOLUTE_WORDS = {
    "abstract": [
        "发现",
        "决定",
        "调查",
        "深入了解",
        "意识到",
        "开始怀疑",
        "进一步推进",
        "逐渐明白",
        "察觉",
        "试图弄清",
        "接近真相",
    ],
    "concrete": [
        "当众",
        "逼问",
        "翻脸",
        "截断",
        "抢走",
        "让位",
        "下令",
        "断供",
        "围攻",
        "对质",
        "审判",
        "失控",
        "断裂",
        "跪",
        "宣旨",
        "敬茶",
        "夺权",
        "封门",
        "破防",
        "改口",
    ],
    "late_abstract_drift": [
        "秩序",
        "文明",
        "维度",
        "终极真相",
        "宇宙",
        "永恒",
        "新世界",
        "重建世界",
        "更高层",
        "本源",
        "终极规则",
        "世界意志",
    ],
    "late_person_org": [
        "家族",
        "组织",
        "宗门",
        "公司",
        "项目",
        "婚约",
        "盟友",
        "背叛",
        "资源",
        "股权",
        "证据",
        "名分",
        "庇护所",
        "队伍",
        "合同",
        "席位",
    ],
}


def _is_blank(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, list):
        return len(v) == 0
    return False


def _to_text_for_episode(ep: Dict[str, Any]) -> str:
    parts: List[str] = []
    for k in (
        "one_line",
        "key_turn",
        "cannot_remove_because",
        "dominant_opposition",
        "pressure_arena",
        "status_shift",
        "price_paid",
        "relationship_shift",
        "resource_shift",
        "world_reveal_delta",
        "episode_goal_in_series",
        "visual_or_public_event",
    ):
        v = ep.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v)
    return "\n".join(parts)


def _text_for_event_density(ep: Dict[str, Any]) -> str:
    parts: List[str] = []
    for k in ("one_line", "key_turn", "cannot_remove_because"):
        v = ep.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v)
    return "\n".join(parts)


def _text_for_late_drift(ep: Dict[str, Any]) -> str:
    parts: List[str] = []
    for k in (
        "one_line",
        "key_turn",
        "cannot_remove_because",
        "episode_goal_in_series",
        "visual_or_public_event",
        "world_reveal_delta",
    ):
        v = ep.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v)
    return "\n".join(parts)


def _count_keyword_hits(text: str, words: List[str]) -> int:
    if not text:
        return 0
    c = 0
    for w in words:
        if not w:
            continue
        c += len(re.findall(re.escape(w), text))
    return c


def _episode_sort_key(ep: Dict[str, Any], idx: int) -> Tuple[int, int]:
    eid = ep.get("episode_id")
    if isinstance(eid, int):
        return (eid, idx)
    if isinstance(eid, str) and eid.strip().isdigit():
        return (int(eid.strip()), idx)
    return (idx, idx)


def _episode_phase_token(ep: Dict[str, Any]) -> str | None:
    """
    可选阶段字段（不在 dense contract 强制 schema 内，但若模型/人工补充了，则用于 engine 重复度分组）。
    """
    for k in ("phase", "story_phase", "stage", "arc_phase", "act", "story_stage"):
        v = ep.get(k)
        if v is None:
            continue
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return str(int(v))
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def _scan_engine_repetition_windows(episodes_slice: List[Dict[str, Any]], label_prefix: str) -> Tuple[List[str], List[str]]:
    engine_counts_5: List[str] = []
    engine_counts_6: List[str] = []
    if not episodes_slice:
        return engine_counts_5, engine_counts_6

    for win in range(0, max(0, len(episodes_slice) - 4)):
        slice_eps = episodes_slice[win : win + 5]
        type_counts: Dict[str, int] = {}
        for ep in slice_eps:
            t = str(ep.get("episode_engine_type") or "")
            if not t:
                continue
            type_counts[t] = type_counts.get(t, 0) + 1
        for t, c in type_counts.items():
            if c >= 4:
                a = slice_eps[0].get("episode_id", win)
                b = slice_eps[-1].get("episode_id", win + 4)
                engine_counts_5.append(f"{label_prefix}[{a}-{b}] {t} x{c}")

    for win in range(0, max(0, len(episodes_slice) - 5)):
        slice_eps = episodes_slice[win : win + 6]
        type_counts = {}
        for ep in slice_eps:
            t = str(ep.get("episode_engine_type") or "")
            if not t:
                continue
            type_counts[t] = type_counts.get(t, 0) + 1
        for t, c in type_counts.items():
            if c >= 5:
                a = slice_eps[0].get("episode_id", win)
                b = slice_eps[-1].get("episode_id", win + 5)
                engine_counts_6.append(f"{label_prefix}[{a}-{b}] {t} x{c}")

    return engine_counts_5, engine_counts_6


def _find_missing_runs(episodes: List[Dict[str, Any]], field: str, min_run_len: int) -> List[str]:
    runs: List[str] = []
    run_start: int | None = None
    run_len = 0

    for i, ep in enumerate(episodes):
        if _is_blank(ep.get(field)):
            if run_start is None:
                run_start = i
                run_len = 1
            else:
                run_len += 1
        else:
            if run_start is not None and run_len >= min_run_len:
                runs.append(f"{episodes[run_start].get('episode_id', run_start)}-{episodes[i-1].get('episode_id', i-1)}")
            run_start = None
            run_len = 0

    if run_start is not None and run_len >= min_run_len:
        runs.append(
            f"{episodes[run_start].get('episode_id', run_start)}-{episodes[len(episodes)-1].get('episode_id', len(episodes)-1)}"
        )
    return runs


def validate_dense_outline(series_outline: Dict[str, Any]) -> Dict[str, Any]:
    """
    程序性校验 dense episode contract 的最低质量。
    不调用 LLM，不依赖 embedding/ML。
    """
    if not isinstance(series_outline, dict):
        return {
            "is_pass": False,
            "hard_fail_reasons": ["series_outline 不是对象"],
            "warnings": ["series_outline 类型错误"],
            "stats": {"episode_count": 0},
        }

    episodes = series_outline.get("episode_list")
    if not isinstance(episodes, list):
        return {
            "is_pass": False,
            "hard_fail_reasons": ["series_outline.episode_list 缺失或类型错误"],
            "warnings": [],
            "stats": {"episode_count": 0},
        }

    episodes = [e for e in episodes if isinstance(e, dict)]
    episodes_sorted = sorted(
        list(enumerate(episodes)),
        key=lambda item: _episode_sort_key(item[1], item[0]),
    )
    episodes_sorted = [x[1] for x in episodes_sorted]

    required_fields = [
        "episode_engine_type",
        "episode_goal_in_series",
        "anchor_ids",
        "must_advance",
        "dominant_opposition",
        "pressure_arena",
        "key_turn",
        "status_shift",
        "price_paid",
        "visual_or_public_event",
        "cannot_remove_because",
        "hook",
        "cliffhanger",
    ]

    list_fields = {"anchor_ids", "must_advance"}  # must_payoff/must_set_up handled as "at least one non-empty"
    must_payoff_field = "must_payoff"
    must_set_up_field = "must_set_up"

    missing_required_field_counts: Dict[str, int] = {f: 0 for f in required_fields}
    missing_key_turn_runs: List[str] = []
    missing_status_shift_runs: List[str] = []
    missing_price_paid_runs: List[str] = []

    def missing_field_for_ep(ep: Dict[str, Any], field: str) -> bool:
        v = ep.get(field)
        if field in list_fields:
            return not isinstance(v, list) or len(v) == 0 or all(_is_blank(x) for x in v)
        return _is_blank(v)

    must_payoff_missing_count = 0
    must_set_up_missing_count = 0
    light_shift_triplet_empty_count = 0

    for ep in episodes_sorted:
        for f in required_fields:
            if missing_field_for_ep(ep, f):
                missing_required_field_counts[f] += 1

        mp = ep.get(must_payoff_field)
        ms = ep.get(must_set_up_field)
        if not isinstance(mp, list) or len(mp) == 0 or all(_is_blank(x) for x in mp):
            must_payoff_missing_count += 1
        if not isinstance(ms, list) or len(ms) == 0 or all(_is_blank(x) for x in ms):
            must_set_up_missing_count += 1

        rs = ep.get("relationship_shift")
        rr = ep.get("resource_shift")
        wr = ep.get("world_reveal_delta")
        if _is_blank(rs) and _is_blank(rr) and _is_blank(wr):
            light_shift_triplet_empty_count += 1

    missing_key_turn_runs = _find_missing_runs(episodes_sorted, "key_turn", 3)
    missing_status_shift_runs = _find_missing_runs(episodes_sorted, "status_shift", 3)
    missing_price_paid_runs = _find_missing_runs(episodes_sorted, "price_paid", 3)

    hard_fail_reasons: List[str] = []
    warnings: List[str] = []

    if missing_key_turn_runs:
        hard_fail_reasons.append("连续 3 集以上 key_turn 为空")
    if missing_status_shift_runs:
        hard_fail_reasons.append("连续 3 集以上 status_shift 为空")
    if missing_price_paid_runs:
        hard_fail_reasons.append("连续 3 集以上 price_paid 为空")

    # removability risk
    cannot_remove_missing = 0
    for ep in episodes_sorted:
        if missing_field_for_ep(ep, "cannot_remove_because"):
            cannot_remove_missing += 1
    total = max(1, len(episodes_sorted))
    cannot_remove_ratio = cannot_remove_missing / total
    if cannot_remove_ratio > 0.25:
        hard_fail_reasons.append(f"cannot_remove_because 缺失率过高（ratio={cannot_remove_ratio:.2f}）")
    elif cannot_remove_ratio > 0.15:
        warnings.append(f"cannot_remove_because 缺失率偏高（ratio={cannot_remove_ratio:.2f}）")

    total_eps = max(1, len(episodes_sorted))
    light_shift_triplet_empty_ratio = light_shift_triplet_empty_count / total_eps
    if len(episodes_sorted) >= 8 and light_shift_triplet_empty_ratio >= 0.60:
        warnings.append(
            "relationship_shift/resource_shift/world_reveal_delta 在全剧占比长期偏空（可能整体变薄，建议补关系/资源/世界推进锚点）"
        )

    # engine repetition
    engine_counts_5: List[str] = []
    engine_counts_6: List[str] = []
    engine_repetition_mode = "sliding_global"
    if episodes_sorted:
        tokens = [_episode_phase_token(ep) for ep in episodes_sorted]
        non_null = sum(1 for t in tokens if t is not None)
        coverage = non_null / max(1, len(episodes_sorted))
        use_phase_grouping = len(episodes_sorted) >= 8 and coverage >= 0.70

        if use_phase_grouping:
            engine_repetition_mode = "sliding_by_phase_token"
            groups: Dict[str, List[Dict[str, Any]]] = {}
            order: List[str] = []
            for ep, tok in zip(episodes_sorted, tokens):
                key = tok if tok is not None else "__unknown_phase__"
                if key not in groups:
                    groups[key] = []
                    order.append(key)
                groups[key].append(ep)
            for key in order:
                g_eps = groups[key]
                p5, p6 = _scan_engine_repetition_windows(g_eps, label_prefix=f"phase={key}")
                engine_counts_5.extend(p5)
                engine_counts_6.extend(p6)
        else:
            p5, p6 = _scan_engine_repetition_windows(episodes_sorted, label_prefix="episodes")
            engine_counts_5.extend(p5)
            engine_counts_6.extend(p6)

    engine_repetition_flags: List[str] = []
    if engine_counts_5:
        warnings.append("同一 engine_type 连续窗口重复度偏高（5 连窗）")
        engine_repetition_flags.extend(engine_counts_5[:3])
    if engine_counts_6:
        hard_fail_reasons.append("同一 engine_type 连续窗口重复度过高（6 连窗）")
        engine_repetition_flags.extend(engine_counts_6[:3])

    # low event density risk
    abstract_words = _ABSOLUTE_WORDS["abstract"]
    concrete_words = _ABSOLUTE_WORDS["concrete"]
    total_abstract_hits = 0
    total_concrete_hits = 0
    abstract_hits_per_ep: List[int] = []
    concrete_hits_per_ep: List[int] = []

    for ep in episodes_sorted:
        text = _text_for_event_density(ep)
        a = _count_keyword_hits(text, abstract_words)
        c = _count_keyword_hits(text, concrete_words)
        abstract_hits_per_ep.append(a)
        concrete_hits_per_ep.append(c)
        total_abstract_hits += a
        total_concrete_hits += c

    episode_count = len(episodes_sorted)
    abstract_avg = (total_abstract_hits / episode_count) if episode_count else 0.0
    concrete_avg = (total_concrete_hits / episode_count) if episode_count else 0.0
    low_event_density_flag = False
    low_event_density_notes: List[str] = []

    if episode_count >= 4 and abstract_avg >= 1.8 and concrete_avg <= 0.3:
        low_event_density_flag = True
        low_event_density_notes.append(
            f"abstract_avg={abstract_avg:.2f} concrete_avg={concrete_avg:.2f}（抽象词密度高、具体动作词密度低）"
        )
        # 偏极端则 hard fail
        zero_concrete_ratio = sum(1 for x in concrete_hits_per_ep if x == 0) / episode_count
        if zero_concrete_ratio >= 0.7 and abstract_avg >= 2.6:
            hard_fail_reasons.append("抽象事件词密度过高且几乎无具体事件位移")
        else:
            warnings.append("low_event_density_risk：可能抽象化/后段失控风险")

    # late-stage drift risk
    late_stage_drift_flag = False
    late_stage_drift_notes: List[str] = []
    if episode_count >= 8:  # 小样本不做强判断
        start = int(episode_count * 0.75)
        tail = episodes_sorted[start:]
        tail_abstract_avgs: List[float] = []
        tail_person_avgs: List[float] = []
        for ep in tail:
            text = _text_for_late_drift(ep)
            tail_abstract_avgs.append(float(_count_keyword_hits(text, _ABSOLUTE_WORDS["late_abstract_drift"])))
            tail_person_avgs.append(float(_count_keyword_hits(text, _ABSOLUTE_WORDS["late_person_org"])))
        tail_len = max(1, len(tail))
        tail_abstract_avg = sum(tail_abstract_avgs) / tail_len
        tail_person_avg = sum(tail_person_avgs) / tail_len
        # 注意：人物/组织词常会在 visual/world_reveal 等字段里“顺带出现”，
        # 因此不能只用 person_org_avg 低作为唯一判据；需要同时看 abstract 是否显著压过人物对抗词。
        if tail_abstract_avg >= 1.3 and (
            tail_person_avg <= 0.6 or tail_abstract_avg >= 2.0 * max(0.01, tail_person_avg)
        ):
            late_stage_drift_flag = True
            late_stage_drift_notes.append(
                f"late_tail abstract_avg={tail_abstract_avg:.2f} person_org_avg={tail_person_avg:.2f}"
            )
            if tail_abstract_avg >= 2.0 and (
                tail_person_avg <= 0.2 or tail_abstract_avg >= 3.0 * max(0.01, tail_person_avg)
            ):
                hard_fail_reasons.append("后四分之一漂移风险过高（抽象秩序/文明词高、人物组织冲突词低）")
            else:
                warnings.append("late_stage_drift_risk：可能后段风格抽象化/世界观说明化")

    is_pass = len(hard_fail_reasons) == 0

    return {
        "is_pass": is_pass,
        "hard_fail_reasons": hard_fail_reasons,
        "warnings": warnings,
        "stats": {
            "episode_count": episode_count,
            "missing_required_field_counts": missing_required_field_counts,
            "missing_key_turn_runs": missing_key_turn_runs,
            "missing_status_shift_runs": missing_status_shift_runs,
            "missing_price_paid_runs": missing_price_paid_runs,
            "cannot_remove_because_missing_ratio": cannot_remove_ratio if episodes_sorted else 0.0,
            "engine_repetition_flags": engine_repetition_flags,
            "engine_repetition_mode": engine_repetition_mode,
            "late_stage_drift_flag": late_stage_drift_flag,
            "low_event_density_flag": low_event_density_flag,
            "late_stage_drift_notes": late_stage_drift_notes,
            "low_event_density_notes": low_event_density_notes,
            "must_payoff_missing_count": must_payoff_missing_count,
            "must_set_up_missing_count": must_set_up_missing_count,
            "light_shift_triplet_empty_count": light_shift_triplet_empty_count,
            "light_shift_triplet_empty_ratio": light_shift_triplet_empty_ratio,
        },
    }


def summarize_dense_outline_validation(result: Dict[str, Any]) -> Dict[str, Any] | str:
    if not isinstance(result, dict):
        return "invalid result"
    is_pass = bool(result.get("is_pass"))
    hard = result.get("hard_fail_reasons") or []
    warns = result.get("warnings") or []
    stats = result.get("stats") or {}
    episode_count = stats.get("episode_count")
    summary: List[str] = []
    summary.append(f"DenseOutlineValidator: pass={is_pass} episodes={episode_count}")
    if hard:
        summary.append("HardFail:")
        summary.extend([f"- {x}" for x in hard])
    if warns:
        summary.append("Warnings:")
        summary.extend([f"- {x}" for x in warns])
    notes = []
    if stats.get("late_stage_drift_flag"):
        notes.append("late_stage_drift_flag=true")
    if stats.get("low_event_density_flag"):
        notes.append("low_event_density_flag=true")
    if notes:
        summary.append("Flags: " + ", ".join(notes))
    return "\n".join(summary)


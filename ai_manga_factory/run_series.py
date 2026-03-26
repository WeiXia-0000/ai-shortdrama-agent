import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from .creative_constants import _strict_json_only
from .genre_rules import (
    bundle_from_registry_series_identity,
    compose_genre_injection_for_stage,
    get_bundle_capabilities,
    get_primary_genre_capabilities,
    infer_genre_bundle_for_prompt,
    summarize_genre_bundle_for_debug,
)
from . import series_agents
from .carry_registry import ensure_registry_file, load_registry, save_registry, sync_carry_registry_minimal


APP_NAME = "ai_manga_factory"
PROJECT_ROOT = Path(__file__).resolve().parent


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _dump_json(p: Path, obj: Any) -> None:
    _ensure_dir(p.parent)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_text(p: Path, text: str) -> None:
    _ensure_dir(p.parent)
    p.write_text(text, encoding="utf-8")


def _safe_dir_name(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[\\/:*?\"<>|]+", "_", s)
    return s[:80] if s else "series"


def _sanitize_for_json(s: str) -> str:
    # 去掉控制字符，避免 JSONDecodeError: Invalid control character
    # 关键点：JSON 字符串内部不能出现“真实换行/制表符/回车”，必须是转义的 \\n。
    # 因此这里把 \n/\t/\r 统一替换成空格，尽可能保留可读性同时保证可解析。
    out_chars: List[str] = []
    for ch in s:
        code = ord(ch)
        if ch in ("\n", "\t", "\r"):
            out_chars.append(" ")
        elif code >= 32:
            out_chars.append(ch)
        else:
            # 其他控制字符直接丢弃
            continue
    return "".join(out_chars)


def _extract_json(raw_text: str) -> str:
    t = raw_text.strip() if isinstance(raw_text, str) else str(raw_text)

    if t.startswith("```"):
        parts = t.split("```")
        if len(parts) >= 2:
            t = parts[1].strip()
            if t.lower().startswith("json"):
                t = t[4:].strip()

    if "{" in t and "}" in t:
        candidate = t[t.find("{") : t.rfind("}") + 1]
        candidate = _sanitize_for_json(candidate)
        return candidate
    return _sanitize_for_json(t)


async def _call_agent_once(
    runner: Runner,
    user_id: str,
    session_id: str,
    prompt: str,
) -> str:
    msg = types.Content(role="user", parts=[types.Part(text=prompt)])
    final_text: Optional[str] = None
    async for ev in runner.run_async(user_id=user_id, session_id=session_id, new_message=msg):
        if ev.is_final_response():
            try:
                final_text = ev.content.parts[0].text
            except Exception:
                final_text = str(ev)
    if final_text is None:
        raise RuntimeError("No final response received.")
    return final_text


async def _run_agent_json(
    agent,
    prompt: str,
    session_service: InMemorySessionService,
    user_id: str,
    session_id: str,
    debug_dir: Path,
) -> Dict[str, Any]:
    await session_service.create_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    runner = Runner(app_name=APP_NAME, agent=agent, session_service=session_service)

    raw = await _call_agent_once(runner, user_id=user_id, session_id=session_id, prompt=prompt)

    _ensure_dir(debug_dir)
    _write_text(debug_dir / f"{session_id}.raw.txt", raw)

    extracted = _extract_json(raw)
    try:
        return json.loads(extracted)
    except Exception:
        patched = _strict_json_only(raw)
        patched = _extract_json(patched)
        return json.loads(patched)


def _is_blank(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, (list, dict)):
        return len(v) == 0
    return False


def _validate_required_keys(obj: Dict[str, Any], required: List[str]) -> List[str]:
    issues: List[str] = []
    for k in required:
        if k not in obj:
            issues.append(f"缺少字段: {k}")
            continue
        if _is_blank(obj.get(k)):
            issues.append(f"字段为空: {k}")
    return issues


def _validate_stage_output(
    stage: str,
    obj: Dict[str, Any],
    genre_caps: Optional[Dict[str, Any]] = None,
) -> List[str]:
    if stage == "character_bible":
        issues = _validate_required_keys(obj, ["style_anchor", "main_characters"])
        chars = obj.get("main_characters") or []
        if not isinstance(chars, list) or not chars:
            issues.append("main_characters 不能为空数组")
            return issues
        for c in chars:
            if not isinstance(c, dict):
                issues.append("main_characters 中存在非对象条目")
                continue
            issues.extend(
                _validate_required_keys(
                    c,
                    [
                        "name",
                        "appearance_lock",
                        "face_triptych_prompt_cn",
                        "body_triptych_prompt_cn",
                        "negative_prompt_cn",
                    ],
                )
            )
        return issues
    if stage == "episode_function":
        issues = _validate_required_keys(
            obj,
            [
                "episode_id",
                "episode_goal_in_series",
                "must_advance",
                "must_inherit",
                "future_threads_strengthened",
                "viewer_payoff_design",
            ],
        )
        vpd = obj.get("viewer_payoff_design")
        if not isinstance(vpd, list) or len(vpd) < 2:
            issues.append("viewer_payoff_design 至少需要 2 条对象")
        else:
            for i, item in enumerate(vpd):
                if not isinstance(item, dict):
                    issues.append(f"viewer_payoff_design[{i}] 必须是对象")
                    continue
                for k in ("type", "payoff_target", "description"):
                    if _is_blank(item.get(k)):
                        issues.append(f"viewer_payoff_design[{i}] 缺少或为空: {k}")
        return issues
    if stage == "plot":
        caps = genre_caps if isinstance(genre_caps, dict) else get_primary_genre_capabilities("general")
        req_map = bool(caps.get("requires_rule_execution_map", False))
        use_explicit = bool(caps.get("uses_explicit_rules", False))
        min_rules = 2 if (req_map and use_explicit) else (1 if req_map else 0)

        issues = _validate_required_keys(
            obj, ["episode_id", "title", "acts", "hook", "cliffhanger", "logic_check"]
        )
        if "rule_execution_map" not in obj:
            issues.append("缺少字段: rule_execution_map")
        rem = obj.get("rule_execution_map")
        if not isinstance(rem, list):
            issues.append("rule_execution_map 必须是数组（非规则题材可为 []）")
            return issues
        if req_map:
            if len(rem) < min_rules:
                issues.append(
                    f"rule_execution_map 至少需要 {min_rules} 条可执行绑定（当前题材 requires_rule_execution_map=true）"
                )
        elif len(rem) > 0:
            # 非强制题材：若写了条目则仍校验结构，避免半吊子对象
            pass
        for i, row in enumerate(rem):
            if not isinstance(row, dict):
                issues.append(f"rule_execution_map[{i}] 必须是对象")
                continue
            for k in ("rule_id", "rule_text", "rule_layer", "trigger_beat", "feedback"):
                if _is_blank(row.get(k)):
                    issues.append(f"rule_execution_map[{i}] 缺少或为空: {k}")
        return issues
    if stage == "script":
        issues = _validate_required_keys(obj, ["episode_id", "characters", "scenes"])
        scenes = obj.get("scenes") or []
        if isinstance(scenes, list) and len(scenes) < 4:
            issues.append("script.scenes 过少（建议 >=4）")
        return issues
    if stage == "storyboard":
        issues = _validate_required_keys(obj, ["episode_id", "style", "segments"])
        segs = obj.get("segments") or []
        if isinstance(segs, list) and len(segs) < 6:
            issues.append("storyboard.segments 过少（建议 >=6）")
        return issues
    if stage == "memory":
        return _validate_required_keys(obj, ["episodes", "characters"])
    if stage == "char_visual_patch":
        return _validate_required_keys(obj, ["characters"])
    return []


async def _run_agent_json_with_qc(
    *,
    stage: str,
    agent,
    prompt: str,
    quality_mode: str,
    session_service: InMemorySessionService,
    user_id: str,
    session_id: str,
    debug_dir: Path,
    max_rounds: int = 3,
    genre_caps: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if quality_mode != "quality":
        return await _run_agent_json(
            agent,
            prompt,
            session_service=session_service,
            user_id=user_id,
            session_id=session_id,
            debug_dir=debug_dir,
        )

    current_prompt = prompt
    last_issues: List[str] = []
    for i in range(1, max_rounds + 1):
        sid = f"{session_id}_r{i}"
        out = await _run_agent_json(
            agent,
            current_prompt,
            session_service=session_service,
            user_id=user_id,
            session_id=sid,
            debug_dir=debug_dir,
        )
        issues = _validate_stage_output(stage, out, genre_caps=genre_caps)
        if not issues:
            return out
        last_issues = issues
        feedback = "\n".join([f"- {x}" for x in issues])
        current_prompt = (
            prompt
            + "\n\n【质检反馈】\n上轮输出未通过，请仅修复以下问题并仍只输出一个 JSON 对象：\n"
            + feedback
            + "\n【要求】不得缺字段、不得输出 markdown、不得输出解释文本。"
        )
    raise RuntimeError(f"{stage} 在 quality 模式下重试 {max_rounds} 轮后仍未通过质检: {last_issues}")


def _parse_episode_ids(s: str) -> List[int]:
    s = (s or "").strip()
    if not s:
        return []
    ids: List[int] = []
    parts = re.split(r"\s*,\s*", s)
    for part in parts:
        if "-" in part:
            a, b = part.split("-", 1)
            a_i = int(a.strip())
            b_i = int(b.strip())
            step = 1 if b_i >= a_i else -1
            ids.extend(list(range(a_i, b_i + step, step)))
        else:
            ids.append(int(part.strip()))
    # 去重但保持顺序
    seen = set()
    out: List[int] = []
    for i in ids:
        if i not in seen:
            out.append(i)
            seen.add(i)
    return out


def _inject_genre_prompt_for_stage(
    bundle: Dict[str, Any],
    base_prompt: str,
    stage_name: str,
) -> str:
    """按 stage 选择 genre profile，拼接在 base_prompt 之前。"""
    block = compose_genre_injection_for_stage(bundle, stage_name, include_header=True)
    return (block + "\n" + base_prompt).strip()


def _inject_genre_prompt_from_infer(infer_text: str, base_prompt: str, stage_name: str) -> str:
    bundle = infer_genre_bundle_for_prompt(infer_text)
    return _inject_genre_prompt_for_stage(bundle, base_prompt, stage_name)


def _episode_outline_row(series_outline: Dict[str, Any], ep_id: int) -> Dict[str, Any]:
    for ep in series_outline.get("episode_list") or []:
        if isinstance(ep, dict) and ep.get("episode_id") == ep_id:
            return ep
    return {}


def _unique_episode_dir(episodes_root: Path, series_title: str, ep_id: int) -> Path:
    base = f"{series_title}_第{ep_id:03d}集"
    candidate = episodes_root / base
    if not candidate.exists():
        return candidate
    n = 2
    while True:
        c2 = episodes_root / f"{base}_{n}"
        if not c2.exists():
            return c2
        n += 1


def parse_episode_id_from_dirname(dirname: str) -> Optional[int]:
    """从目录名解析集号（须含「第NNN集」）。"""
    m = re.search(r"第(\d+)集", dirname)
    if not m:
        return None
    return int(m.group(1))


def find_episode_dir_for_id(episodes_root: Path, episode_id: int) -> Tuple[Optional[Path], Optional[str]]:
    """
    在 episodes_root 下查找已存在的、目录名可解析为 episode_id 的集目录。
    不创建新目录；若同集号对应多个目录则返回冲突说明（避免静默落到 _2/_3 新目录）。
    """
    if not episodes_root.is_dir():
        return None, f"分集根目录不存在或不是目录: {episodes_root}"
    matches: List[Path] = []
    for p in sorted(episodes_root.iterdir(), key=lambda x: x.name):
        if not p.is_dir():
            continue
        eid = parse_episode_id_from_dirname(p.name)
        if eid == episode_id:
            matches.append(p)
    if not matches:
        return None, f"未找到第 {episode_id} 集目录（在 {episodes_root} 下）"
    if len(matches) > 1:
        names = [m.name for m in matches]
        return None, f"第 {episode_id} 集存在多个目录（冲突），请合并或删除重复项: {names}"
    return matches[0], None


def _series_root_from_outline_path(outline_path: Path) -> Path:
    """若大纲在 L3_series/ 下，则剧根目录为其上一级。"""
    outline_path = outline_path.resolve()
    if outline_path.parent.name == "L3_series":
        return outline_path.parent.parent
    return outline_path.parent


def _paths_layered(series_dir: Path) -> Dict[str, Any]:
    sd = series_dir.resolve()
    return {
        "layout": "layered",
        "series_dir": sd,
        "series_setup": sd / "L0_setup" / "01_series_setup.json",
        "episode_pitch": sd / "L0_setup" / "02_episode_pitch.json",
        "season_mainline": sd / "L1_season" / "01_season_mainline.json",
        "character_growth": sd / "L1_season" / "02_character_growth.json",
        "world_reveal_pacing": sd / "L1_season" / "03_world_reveal_pacing.json",
        "coupling_map": sd / "L2_spine" / "01_coupling_map.json",
        "series_spine": sd / "L2_spine" / "02_series_spine.json",
        "anchor_beats": sd / "L2_spine" / "03_anchor_beats.json",
        "series_outline": sd / "L3_series" / "01_series_outline.json",
        "outline_review": sd / "L3_series" / "01b_outline_review.json",
        "character_bible": sd / "L3_series" / "02_character_bible.json",
        "series_memory": sd / "L3_series" / "03_series_memory.json",
        "production_carry_registry": sd / "L3_series" / "03b_production_carry_registry.json",
        "episode_batch": sd / "L3_series" / "04_episode_batch.json",
        "series_manifest": sd / "L3_series" / "05_series_manifest.json",
        "episodes_root": sd / "L4_episodes",
    }


def _paths_flat(series_dir: Path) -> Dict[str, Any]:
    sd = series_dir.resolve()
    return {
        "layout": "flat",
        "series_dir": sd,
        "series_setup": sd / "series_setup.json",
        "episode_pitch": sd / "episode_pitch.json",
        "season_mainline": sd / "season_mainline.json",
        "character_growth": sd / "character_growth.json",
        "world_reveal_pacing": sd / "world_reveal_pacing.json",
        "coupling_map": sd / "coupling_map.json",
        "series_spine": sd / "series_spine.json",
        "anchor_beats": sd / "anchor_beats.json",
        "series_outline": sd / "series_outline.json",
        "outline_review": sd / "outline_review.json",
        "character_bible": sd / "character_bible.json",
        "series_memory": sd / "series_memory.json",
        "production_carry_registry": sd / "03b_production_carry_registry.json",
        "episode_batch": sd / "episode_batch.json",
        "series_manifest": sd / "series_manifest.json",
        "episodes_root": sd / "episodes",
    }


def resolve_series_paths(series_dir: Path) -> Dict[str, Any]:
    """
    解析剧目录布局：优先「分层 + 序号文件名」（L0_setup … L4_episodes），
    否则回退到旧版根目录平铺（兼容已有 runs）。
    """
    sd = series_dir.resolve()
    layered_outline = sd / "L3_series" / "01_series_outline.json"
    flat_outline = sd / "series_outline.json"
    if layered_outline.exists():
        return _paths_layered(sd)
    if flat_outline.exists():
        return _paths_flat(sd)
    # 尚无大纲时（极少）：按分层占位，便于与新 series-setup 一致
    return _paths_layered(sd)


def _episode_json_paths(ep_dir: Path, layout: str) -> Dict[str, Path]:
    """单集目录内 JSON 文件名：分层布局用序号前缀；旧版平铺保持原名。"""
    if layout == "layered":
        return {
            "episode_function": ep_dir / "01_episode_function.json",
            "plot": ep_dir / "02_plot.json",
            "script": ep_dir / "03_script.json",
            "storyboard": ep_dir / "04_storyboard.json",
            "creative_scorecard": ep_dir / "05_creative_scorecard.json",
            "package": ep_dir / "06_package.json",
            "gate_artifacts": ep_dir / "07_gate_artifacts.json",
        }
    return {
        "episode_function": ep_dir / "episode_function.json",
        "plot": ep_dir / "plot.json",
        "script": ep_dir / "script.json",
        "storyboard": ep_dir / "storyboard.json",
        "creative_scorecard": ep_dir / "creative_scorecard.json",
        "package": ep_dir / "package.json",
        "gate_artifacts": ep_dir / "gate_artifacts.json",
    }


def _character_bible_name_set(bible: Dict[str, Any]) -> set:
    return {
        c.get("name")
        for c in (bible.get("main_characters") or [])
        if isinstance(c, dict) and c.get("name")
    }


def _memory_chars_missing_bible(series_memory: Dict[str, Any], bible: Dict[str, Any]) -> List[Dict[str, Any]]:
    names = _character_bible_name_set(bible)
    out: List[Dict[str, Any]] = []
    for c in series_memory.get("characters") or []:
        if not isinstance(c, dict):
            continue
        n = c.get("name")
        if not n or n in names:
            continue
        out.append(c)
    return out


def _write_series_manifest(series_dir: Path, series_title: str, paths: Optional[Dict[str, Any]] = None) -> None:
    """剧目录阅读导航：分层文件夹 + 序号文件名 + 依赖关系。"""

    paths = paths or resolve_series_paths(series_dir)
    layout = paths.get("layout", "flat")
    sd: Path = paths["series_dir"]

    # (layer, title, rel_relative_to_series_dir, depends_on_rels, one_line)
    if layout == "layered":
        step_defs: List[Tuple[str, str, str, List[str], str]] = [
            ("L0", "聚合 setup", "L0_setup/01_series_setup.json", [], "入口汇总：市场、概念、评审等"),
            ("L0", "选定概念", "L0_setup/02_episode_pitch.json", ["L0_setup/01_series_setup.json"], "被选中概念卡片"),
            ("L1", "整季主线", "L1_season/01_season_mainline.json", ["L0_setup/02_episode_pitch.json"], "阶段目标与主线方向"),
            ("L1", "人物成长", "L1_season/02_character_growth.json", ["L1_season/01_season_mainline.json"], "主角/配角/团队弧线"),
            ("L1", "世界揭示", "L1_season/03_world_reveal_pacing.json", ["L1_season/01_season_mainline.json"], "认知层与机制揭示节奏"),
            (
                "L2",
                "耦合对齐",
                "L2_spine/01_coupling_map.json",
                ["L1_season/02_character_growth.json", "L1_season/03_world_reveal_pacing.json"],
                "人物线与世界线双向因果",
            ),
            ("L2", "系列骨架", "L2_spine/02_series_spine.json", ["L2_spine/01_coupling_map.json"], "全作 spine"),
            ("L2", "承重锚点", "L2_spine/03_anchor_beats.json", ["L2_spine/02_series_spine.json"], "关键转折点"),
            ("L3", "分集大纲", "L3_series/01_series_outline.json", ["L2_spine/03_anchor_beats.json"], "episode_list + overall_arc"),
            ("L3", "大纲评审", "L3_series/01b_outline_review.json", ["L3_series/01_series_outline.json"], "题材/市场/节奏/转折评分与改写建议"),
            ("L3", "角色圣经", "L3_series/02_character_bible.json", ["L3_series/01_series_outline.json", "L3_series/01b_outline_review.json"], "外观锁与 Seedance 肖像"),
            ("L3", "系列记忆", "L3_series/03_series_memory.json", ["L3_series/01_series_outline.json"], "跨集记忆；batch 更新"),
            (
                "L3",
                "制作承托寄存",
                "L3_series/03b_production_carry_registry.json",
                ["L3_series/02_character_bible.json", "L3_series/03_series_memory.json"],
                "continuity / 承诺 / 关系压力 / 视觉锁等切片（随 batch 增量同步）",
            ),
            ("L3", "批次汇总", "L3_series/04_episode_batch.json", ["L3_series/03_series_memory.json"], "已生成分集 package 列表"),
            ("L3", "阅读导航", "L3_series/05_series_manifest.json", ["L3_series/04_episode_batch.json"], "本文件：顺序与依赖说明"),
        ]
        ep_folder = "L4_episodes/<剧名>_第NNN集/"
        ep_order = [
            "01_episode_function.json",
            "02_plot.json",
            "03_script.json",
            "04_storyboard.json",
            "05_creative_scorecard.json",
            "06_package.json",
        ]
    else:
        step_defs = [
            ("L0", "聚合 setup", "series_setup.json", [], "入口汇总：市场、概念、评审等"),
            ("L0", "选定概念", "episode_pitch.json", ["series_setup.json"], "被选中概念卡片"),
            ("L1", "整季主线", "season_mainline.json", ["episode_pitch.json"], "阶段目标与主线方向"),
            ("L1", "人物成长", "character_growth.json", ["season_mainline.json"], "主角/配角/团队弧线"),
            ("L1", "世界揭示", "world_reveal_pacing.json", ["season_mainline.json"], "认知层与机制揭示节奏"),
            (
                "L2",
                "耦合对齐",
                "coupling_map.json",
                ["character_growth.json", "world_reveal_pacing.json"],
                "人物线与世界线双向因果",
            ),
            ("L2", "系列骨架", "series_spine.json", ["coupling_map.json"], "全作 spine"),
            ("L2", "承重锚点", "anchor_beats.json", ["series_spine.json"], "关键转折点"),
            ("L3", "分集大纲", "series_outline.json", ["anchor_beats.json"], "episode_list + overall_arc"),
            ("L3", "大纲评审", "outline_review.json", ["series_outline.json"], "题材/市场/节奏/转折评分与改写建议"),
            ("L3", "角色圣经", "character_bible.json", ["series_outline.json", "outline_review.json"], "外观锁与 Seedance 肖像"),
            ("L3", "系列记忆", "series_memory.json", ["series_outline.json"], "跨集记忆；batch 更新"),
            (
                "L3",
                "制作承托寄存",
                "03b_production_carry_registry.json",
                ["character_bible.json", "series_memory.json"],
                "continuity 相关切片（随 batch 增量同步）",
            ),
            ("L3", "批次汇总", "episode_batch.json", ["series_memory.json"], "已生成分集 package 列表"),
            ("L3", "阅读导航", "series_manifest.json", ["episode_batch.json"], "本文件：顺序与依赖说明"),
        ]
        ep_folder = "episodes/<剧名>_第NNN集/"
        ep_order = [
            "episode_function.json",
            "plot.json",
            "script.json",
            "storyboard.json",
            "creative_scorecard.json",
            "package.json",
        ]

    batch_path = paths["episode_batch"]

    def ex(rel: str) -> bool:
        # 导航文件在写入前尚不存在，只要批次汇总已生成即可认为「可阅读导航」
        if rel.endswith("series_manifest.json") or "05_series_manifest.json" in rel:
            return batch_path.exists()
        return (sd / rel).exists()

    reading_order: List[Dict[str, Any]] = []
    step = 0
    for layer, title, rel, depends, one_line in step_defs:
        if not ex(rel):
            continue
        step += 1
        reading_order.append(
            {
                "step": step,
                "layer": layer,
                "title": title,
                "file": rel,
                "depends_on": depends,
                "one_line": one_line,
            }
        )

    manifest: Dict[str, Any] = {
        "schema_version": "1.1",
        "layout": layout,
        "series_title": series_title,
        "folders": (
            "L0_setup → L1_season → L2_spine → L3_series → L4_episodes（文件名带序号前缀）"
            if layout == "layered"
            else "旧版：全部在剧根目录 + episodes/ 子目录"
        ),
        "how_to_read": "按文件夹层级 L0→L4 与文件名序号阅读；reading_order 的 step 为建议顺序。depends_on 为上游依赖。",
        "reading_order": reading_order,
        "episode_pipeline": {
            "folder": ep_folder,
            "order": ep_order,
            "one_line": "单集：功能卡(viewer_payoff_design)→plot(rule_execution_map)→[plot_judge]→script→storyboard→[package_judge→creative_scorecard]→memory；括号内在 quality 或 --episode-judge 时启用。",
        },
    }
    _dump_json(paths["series_manifest"], manifest)


async def _patch_character_bible_new_characters(
    *,
    character_bible: Dict[str, Any],
    series_memory: Dict[str, Any],
    series_outline: Dict[str, Any],
    script_out: Dict[str, Any],
    ep_id: int,
    genre_bundle: Dict[str, Any],
    quality_mode: str,
    session_service: InMemorySessionService,
    user_id: str,
    debug_dir: Path,
    genre_caps: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    missing = _memory_chars_missing_bible(series_memory, character_bible)
    if not missing:
        return character_bible

    style_anchor = character_bible.get("style_anchor") or {}
    patch_prompt_base = (
        "以下角色已出现在 series_memory，但尚未出现在 character_bible.main_characters 中。\n"
        "请为每个角色生成与主角色同结构的完整条目（含 appearance_lock、face_triptych_prompt_cn、body_triptych_prompt_cn、negative_prompt_cn、consistency_rules）。\n"
        "要求：两个提示词均只描述角色本体；不得出现他人、互动关系、剧情元素、能量特效；\n"
        "其中 body_triptych_prompt_cn 必须是全身无脸细节强调、标准站立姿势的三视图，且必须写清上装/下装/外套、鞋履、配饰、材质和主色。\n\n"
        f"style_anchor=\n{json.dumps(style_anchor, ensure_ascii=False)}\n\n"
        f"series_logline=\n{series_outline.get('logline', '')}\n\n"
        f"new_characters_from_memory=\n{json.dumps(missing, ensure_ascii=False)}\n\n"
        f"script_for_visual_cues=\n{json.dumps(script_out, ensure_ascii=False)}\n\n"
        f"episode_id={ep_id}\n"
    )
    patch_prompt = _inject_genre_prompt_for_stage(genre_bundle, patch_prompt_base, "char_visual_patch")
    patch_out = await _run_agent_json_with_qc(
        stage="char_visual_patch",
        agent=series_agents.character_visual_patch_agent,
        prompt=patch_prompt,
        quality_mode=quality_mode,
        session_service=session_service,
        user_id=user_id,
        session_id=f"episode_{ep_id}_char_visual_patch",
        debug_dir=debug_dir,
        genre_caps=genre_caps,
    )
    main = character_bible.setdefault("main_characters", [])
    existing = _character_bible_name_set(character_bible)
    for entry in patch_out.get("characters") or []:
        if not isinstance(entry, dict):
            continue
        n = entry.get("name")
        if not n or n in existing:
            continue
        if entry.get("first_appeared_episode") is None:
            entry["first_appeared_episode"] = ep_id
        main.append(entry)
        existing.add(n)
    return character_bible


async def run_series_setup(output_root: Path, args: argparse.Namespace) -> None:
    debug_dir = output_root / "_debug" / f"series_setup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    _ensure_dir(debug_dir)

    user_id = "series_setup_user"
    session_service = InMemorySessionService()

    infer_text = "\n".join([args.theme or "", args.audience_view or "", args.series_title or ""]).strip()
    infer_text = infer_text or (args.series_title or "series")
    setup_bundle = infer_genre_bundle_for_prompt(infer_text)
    setup_genre_key = str(setup_bundle.get("primary_genre") or "general")
    setup_genre_caps = get_bundle_capabilities(setup_bundle)

    # 1) 市场调研
    market_prompt_base = (
        "你是短剧/微短剧编剧顾问。基于输入做市场调研。\n"
        "输出字段：market_report（中文，结构化即可）。\n\n"
        f"输入：\n主题={args.theme}\n受众={args.audience_view}\n质量模式={args.quality_mode}\n"
    )
    market_prompt = _inject_genre_prompt_for_stage(setup_bundle, market_prompt_base, "market_research")
    market_out = await _run_agent_json(
        series_agents.market_research_agent,
        market_prompt,
        session_service=session_service,
        user_id=user_id,
        session_id="series_setup_market",
        debug_dir=debug_dir,
    )

    # 2) 趋势概念（3 个）
    trend_prompt_base = (
        "基于以下 market_report 生成 3 个长篇系列概念（JSON 输出）。\n\n"
        f"market_report=\n{market_out.get('market_report','')}\n"
    )
    trend_prompt = _inject_genre_prompt_for_stage(setup_bundle, trend_prompt_base, "trend_scout")
    trend_out = await _run_agent_json(
        series_agents.trend_scout_series,
        trend_prompt,
        session_service=session_service,
        user_id=user_id,
        session_id="series_setup_trend",
        debug_dir=debug_dir,
    )

    # 3) 概念评审
    judge_prompt_base = (
        "评审以下 3 个系列概念并推荐一个（JSON 输出）。\n\n"
        f"concepts=\n{json.dumps(trend_out.get('concepts', []), ensure_ascii=False)}\n"
    )
    judge_prompt = _inject_genre_prompt_for_stage(setup_bundle, judge_prompt_base, "concept_judge")
    judge_out = await _run_agent_json(
        series_agents.concept_judge_series,
        judge_prompt,
        session_service=session_service,
        user_id=user_id,
        session_id="series_setup_judge",
        debug_dir=debug_dir,
    )

    # 4) 选中概念
    rec_id = judge_out.get("recommended_concept_id")
    chosen_concept = None
    for c in trend_out.get("concepts", []):
        if c.get("id") == rec_id:
            chosen_concept = c
            break
    if not chosen_concept:
        raise RuntimeError("recommended_concept_id 未匹配到概念。")

    # concept bundle：在最终 chosen_concept 确定后，重算一遍题材 bundle
    # 用于后续 season_mainline / anchor_beats / 分集大纲 / 大纲复审等“上游 outline 链”。
    concept_infer_text = json.dumps(chosen_concept, ensure_ascii=False)
    concept_bundle = infer_genre_bundle_for_prompt(concept_infer_text)
    concept_genre_key = str(concept_bundle.get("primary_genre") or "general")
    concept_genre_caps = get_bundle_capabilities(concept_bundle)

    # 5) season_mainline
    mainline_prompt_base = (
        "基于已选概念生成整季主线（只写方向与阶段目标，不写分集细节）。\n\n"
        f"chosen_concept=\n{json.dumps(chosen_concept, ensure_ascii=False)}\n"
    )
    mainline_prompt = _inject_genre_prompt_for_stage(concept_bundle, mainline_prompt_base, "season_mainline")
    season_mainline_out = await _run_agent_json(
        series_agents.season_mainline_agent,
        mainline_prompt,
        session_service=session_service,
        user_id=user_id,
        session_id="series_setup_mainline",
        debug_dir=debug_dir,
    )

    # 6) character_growth
    growth_prompt_base = (
        "基于已选概念和整季主线，生成人物成长线（人物成长优先，规则为催化）。\n\n"
        f"chosen_concept=\n{json.dumps(chosen_concept, ensure_ascii=False)}\n\n"
        f"season_mainline=\n{json.dumps(season_mainline_out, ensure_ascii=False)}\n"
    )
    growth_prompt = _inject_genre_prompt_for_stage(concept_bundle, growth_prompt_base, "character_growth")
    character_growth_out = await _run_agent_json(
        series_agents.character_growth_agent,
        growth_prompt,
        session_service=session_service,
        user_id=user_id,
        session_id="series_setup_character_growth",
        debug_dir=debug_dir,
    )

    # 7) world_reveal_pacing
    reveal_prompt_base = (
        "基于已选概念和整季主线，生成世界观揭示节奏（禁止写具体分集细节）。\n\n"
        f"chosen_concept=\n{json.dumps(chosen_concept, ensure_ascii=False)}\n\n"
        f"season_mainline=\n{json.dumps(season_mainline_out, ensure_ascii=False)}\n"
    )
    reveal_prompt = _inject_genre_prompt_for_stage(concept_bundle, reveal_prompt_base, "world_reveal_pacing")
    world_reveal_out = await _run_agent_json(
        series_agents.world_reveal_pacing_agent,
        reveal_prompt,
        session_service=session_service,
        user_id=user_id,
        session_id="series_setup_world_reveal",
        debug_dir=debug_dir,
    )

    # 8) coupling_reconciler：对齐人物成长线与世界揭示线
    coupling_prompt_base = (
        "对齐人物成长线与世界揭示线，输出双向耦合因果图（不要写分集细节）。\n\n"
        f"season_mainline=\n{json.dumps(season_mainline_out, ensure_ascii=False)}\n\n"
        f"character_growth=\n{json.dumps(character_growth_out, ensure_ascii=False)}\n\n"
        f"world_reveal_pacing=\n{json.dumps(world_reveal_out, ensure_ascii=False)}\n"
    )
    coupling_prompt = _inject_genre_prompt_for_stage(concept_bundle, coupling_prompt_base, "coupling_reconciler")
    coupling_out = await _run_agent_json(
        series_agents.coupling_reconciler_agent,
        coupling_prompt,
        session_service=session_service,
        user_id=user_id,
        session_id="series_setup_coupling",
        debug_dir=debug_dir,
    )

    # 9) series_spine（只立骨架）
    spine_prompt_base = (
        "基于主线+人物成长+世界揭示+耦合图，生成 series_spine（禁止写分集细节）。\n\n"
        f"season_mainline=\n{json.dumps(season_mainline_out, ensure_ascii=False)}\n\n"
        f"character_growth=\n{json.dumps(character_growth_out, ensure_ascii=False)}\n\n"
        f"world_reveal_pacing=\n{json.dumps(world_reveal_out, ensure_ascii=False)}\n\n"
        f"coupling_map=\n{json.dumps(coupling_out, ensure_ascii=False)}\n"
    )
    spine_prompt = _inject_genre_prompt_for_stage(concept_bundle, spine_prompt_base, "series_spine")
    series_spine_out = await _run_agent_json(
        series_agents.series_spine_agent,
        spine_prompt,
        session_service=session_service,
        user_id=user_id,
        session_id="series_setup_spine",
        debug_dir=debug_dir,
    )

    # 10) anchor_beats（关键承重点）
    anchors_prompt_base = (
        "基于 series_spine 输出 anchor_beats（数量不固定，优先人物成长承重）。\n\n"
        f"series_spine=\n{json.dumps(series_spine_out, ensure_ascii=False)}\n"
    )
    anchors_prompt = _inject_genre_prompt_for_stage(concept_bundle, anchors_prompt_base, "anchor_beats")
    anchor_beats_out = await _run_agent_json(
        series_agents.anchor_beats_agent,
        anchors_prompt,
        session_service=session_service,
        user_id=user_id,
        session_id="series_setup_anchor_beats",
        debug_dir=debug_dir,
    )

    # 11) 展开为 series_outline（分集），并用 outline_review_agent 做评分复审
    outline_prompt_base = (
        "将 series_spine + anchor_beats 展开为 series_outline（与现有 JSON 兼容）。\n\n"
        f"chosen_concept=\n{json.dumps(chosen_concept, ensure_ascii=False)}\n\n"
        f"series_spine=\n{json.dumps(series_spine_out, ensure_ascii=False)}\n\n"
        f"anchor_beats=\n{json.dumps(anchor_beats_out, ensure_ascii=False)}\n\n"
        f"coupling_map=\n{json.dumps(coupling_out, ensure_ascii=False)}\n"
    )
    outline_prompt = _inject_genre_prompt_for_stage(concept_bundle, outline_prompt_base, "episode_outline_expander")

    min_outline_score = 8 if args.quality_mode == "quality" else 7
    max_outline_rounds = 3 if args.quality_mode == "quality" else 2
    outline_out: Dict[str, Any] = {}
    outline_review_out: Dict[str, Any] = {}

    for oi in range(1, max_outline_rounds + 1):
        outline_session_id = f"series_setup_outline_expander_r{oi}"
        outline_out = await _run_agent_json(
            series_agents.episode_outline_expander_agent,
            outline_prompt,
            session_service=session_service,
            user_id=user_id,
            session_id=outline_session_id,
            debug_dir=debug_dir,
        )

        review_prompt_base = (
            "你是短剧内容总审片人。请评审下列 series_outline 的市场与题材质量并打分。\n"
            "评估重点：题材匹配（若有 genre_rules）、故事吸引力、当前市场适配、关键转折是否恰当、节奏是否仓促、篇幅是否足以支撑完整短剧。\n\n"
            f"chosen_concept=\n{json.dumps(chosen_concept, ensure_ascii=False)}\n\n"
            f"series_spine=\n{json.dumps(series_spine_out, ensure_ascii=False)}\n\n"
            f"anchor_beats=\n{json.dumps(anchor_beats_out, ensure_ascii=False)}\n\n"
            f"series_outline=\n{json.dumps(outline_out, ensure_ascii=False)}\n\n"
        )
        review_prompt = _inject_genre_prompt_for_stage(concept_bundle, review_prompt_base, "outline_review")
        outline_review_out = await _run_agent_json(
            series_agents.outline_review_agent,
            review_prompt,
            session_service=session_service,
            user_id=user_id,
            session_id=f"series_setup_outline_review_r{oi}",
            debug_dir=debug_dir,
        )
        score = int(outline_review_out.get("overall_score_1to10") or 0)
        hard_fails = outline_review_out.get("hard_fail_reasons") or []
        if score >= min_outline_score and not hard_fails:
            break
        if oi < max_outline_rounds:
            fix_text = "\n".join([f"- {x}" for x in (outline_review_out.get("must_fix") or [])])
            risk_text = "\n".join([f"- {x}" for x in (outline_review_out.get("risks") or [])])
            rewrite_brief = json.dumps(outline_review_out.get("rewrite_brief", {}), ensure_ascii=False)
            outline_prompt = (
                outline_prompt_base
                + "\n【上一轮评审未过，请重写 series_outline】\n"
                + f"score={score}, min_score={min_outline_score}\n"
                + "must_fix:\n"
                + (fix_text or "- 无（请至少修复节奏、转折与市场吸引力）")
                + "\nrisks:\n"
                + (risk_text or "- 无")
                + "\nrewrite_brief:\n"
                + rewrite_brief
            )
            outline_prompt = _inject_genre_prompt_for_stage(
                concept_bundle, outline_prompt, "episode_outline_expander"
            )

    # 12) 角色设定（character_bible）
    cb_prompt_base = (
        "根据 series_outline 抽取主要角色并生成 character_bible（JSON 输出，含 face_triptych_prompt_cn 与 body_triptych_prompt_cn，均 <=800 汉字）。\n\n"
        f"series_outline=\n{json.dumps(outline_out, ensure_ascii=False)}\n"
    )
    cb_prompt = _inject_genre_prompt_for_stage(concept_bundle, cb_prompt_base, "character_bible")
    cb_out = await _run_agent_json_with_qc(
        stage="character_bible",
        agent=series_agents.character_bible_agent,
        prompt=cb_prompt,
        quality_mode=args.quality_mode,
        session_service=session_service,
        user_id=user_id,
        session_id="series_setup_character_bible",
        debug_dir=debug_dir,
        genre_caps=concept_genre_caps,
    )

    series_title = outline_out.get("title") or args.series_title or "series"
    series_dir_name = _safe_dir_name(series_title)
    series_dir = output_root / series_dir_name
    _ensure_dir(series_dir)
    out_paths = _paths_layered(series_dir)
    for sub in ("L0_setup", "L1_season", "L2_spine", "L3_series", "L4_episodes"):
        _ensure_dir(series_dir / sub)

    series_setup_out = {
        "market_report": market_out.get("market_report", ""),
        "concepts": trend_out.get("concepts", []),
        "concept_judge_report": judge_out,
        "season_mainline": season_mainline_out,
        "character_growth": character_growth_out,
        "world_reveal_pacing": world_reveal_out,
        "coupling_map": coupling_out,
        "series_spine": series_spine_out,
        "anchor_beats": anchor_beats_out,
        "series_outline": outline_out,
        "outline_review": outline_review_out,
        "character_bible": cb_out,
    }

    _dump_json(out_paths["series_setup"], series_setup_out)
    _dump_json(out_paths["episode_pitch"], chosen_concept)
    _dump_json(out_paths["season_mainline"], season_mainline_out)
    _dump_json(out_paths["character_growth"], character_growth_out)
    _dump_json(out_paths["world_reveal_pacing"], world_reveal_out)
    _dump_json(out_paths["coupling_map"], coupling_out)
    _dump_json(out_paths["series_spine"], series_spine_out)
    _dump_json(out_paths["anchor_beats"], anchor_beats_out)
    _dump_json(out_paths["series_outline"], outline_out)
    _dump_json(out_paths["outline_review"], outline_review_out)
    _dump_json(out_paths["character_bible"], cb_out)

    # 初始化 memory + episode_batch（此时 L4_episodes 为空）
    series_memory = {"episodes": [], "characters": []}
    _dump_json(out_paths["series_memory"], series_memory)

    episode_batch = {
        "series_outline": outline_out,
        "character_bible": cb_out,
        "episodes": [],
        "series_memory": series_memory,
    }
    _dump_json(out_paths["episode_batch"], episode_batch)

    reg_path = out_paths["production_carry_registry"]
    registry = ensure_registry_file(
        reg_path,
        series_slug=series_dir_name,
        display_title=series_title,
        genre_key=concept_genre_key,
        genre_bundle=concept_bundle,
    )
    si = registry.setdefault("series_identity", {})
    si["genre_key"] = concept_genre_key
    si["primary_genre"] = concept_genre_key
    si["final_primary_genre"] = concept_genre_key
    si["setup_primary_genre"] = setup_genre_key
    si["initial_vs_final_changed"] = bool(setup_genre_key != concept_genre_key)
    si["bundle_source"] = "chosen_concept"
    si["setting_tags"] = list(concept_bundle.get("setting_tags") or [])
    si["engine_tags"] = list(concept_bundle.get("engine_tags") or [])
    si["relationship_tags"] = list(concept_bundle.get("relationship_tags") or [])
    si["resolved_alias_hits"] = concept_bundle.get("resolved_alias_hits")
    si["primary_resolution_trace"] = concept_bundle.get("primary_resolution_trace")
    si["confidence"] = concept_bundle.get("confidence")
    summ = summarize_genre_bundle_for_debug(setup_bundle)
    summ2 = summarize_genre_bundle_for_debug(concept_bundle)
    if summ or summ2:
        si["initial_bundle_summary"] = f"setup: {summ}" + (f" | concept: {summ2}" if summ2 else "")
    save_registry(reg_path, registry)

    _write_series_manifest(series_dir, series_title, paths=out_paths)
    print(f"[series-setup] 输出完成：{series_dir}")


def _episode_judges_enabled(args: argparse.Namespace) -> bool:
    if getattr(args, "no_episode_judge", False):
        return False
    return args.quality_mode == "quality" or getattr(args, "episode_judge", False)


def _judge_retries(args: argparse.Namespace) -> int:
    try:
        return max(0, int(getattr(args, "judge_retries", 2)))
    except (TypeError, ValueError):
        return 2


def _creative_scorecard_placeholder(reason: str) -> Dict[str, Any]:
    return {
        "quality_judge": {"pass": True, "reason": reason, "overall_score_1to10": 0},
        "plot_judge": None,
        "package_judge": None,
    }


def _merge_creative_scorecard(
    plot_judge: Optional[Dict[str, Any]],
    package_judge: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    qj = None
    if isinstance(package_judge, dict):
        qj = package_judge.get("quality_judge")
    if not isinstance(qj, dict):
        qj = {
            "pass": bool((package_judge or {}).get("pass", False)),
            "reason": str((package_judge or {}).get("summary", "") or "package 评审"),
            "overall_score_1to10": int((package_judge or {}).get("overall_score_1to10") or 0),
        }
    return {
        "plot_judge": plot_judge,
        "package_judge": package_judge,
        "quality_judge": {
            "pass": bool(qj.get("pass")),
            "reason": str(qj.get("reason", "")),
            "overall_score_1to10": int(qj.get("overall_score_1to10") or 0),
        },
    }


async def _run_plot_phase_with_optional_judge(
    *,
    ep_id: int,
    plot_prompt_base: str,
    function_out: Dict[str, Any],
    genre_bundle: Dict[str, Any],
    quality_mode: str,
    use_judges: bool,
    judge_retries: int,
    session_service: InMemorySessionService,
    user_id: str,
    debug_dir: Path,
    extra_feedback: str = "",
    genre_caps: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
    """生成 plot；若开启分集 judge，则在 plot 后跑 episode_plot_judge 并重写 plot。"""
    plot_feedback = (extra_feedback or "").strip()
    plot_judge_out: Optional[Dict[str, Any]] = None
    max_plot_rounds = (judge_retries + 1) if use_judges else 1
    plot_out: Dict[str, Any] = {}

    for pi in range(max_plot_rounds):
        plot_prompt = _inject_genre_prompt_for_stage(
            genre_bundle,
            plot_prompt_base + (f"\n\n{plot_feedback}" if plot_feedback else ""),
            "episode_plot",
        )
        plot_out = await _run_agent_json_with_qc(
            stage="plot",
            agent=series_agents.episode_plot_agent,
            prompt=plot_prompt,
            quality_mode=quality_mode,
            session_service=session_service,
            user_id=user_id,
            session_id=f"episode_{ep_id}_plot_p{pi}",
            debug_dir=debug_dir,
            genre_caps=genre_caps,
        )
        if not use_judges:
            return plot_out, None

        pj_prompt_base = (
            "你是分集 plot 层评审。请严格只输出 JSON schema 要求的一个对象。\n"
            "对照 episode_function（含 viewer_payoff_design）与 plot（含 acts、rule_execution_map）。\n\n"
            f"episode_function=\n{json.dumps(function_out, ensure_ascii=False)}\n\n"
            f"plot=\n{json.dumps(plot_out, ensure_ascii=False)}\n"
        )
        pj_prompt = _inject_genre_prompt_for_stage(genre_bundle, pj_prompt_base, "gate_plot_judge")
        plot_judge_out = await _run_agent_json(
            series_agents.episode_plot_judge_agent,
            pj_prompt,
            session_service=session_service,
            user_id=user_id,
            session_id=f"episode_{ep_id}_plot_judge_p{pi}",
            debug_dir=debug_dir,
        )
        if bool(plot_judge_out.get("pass")):
            return plot_out, plot_judge_out

        if pi < max_plot_rounds - 1:
            fixes = plot_judge_out.get("must_fix_for_plot") or []
            issues = plot_judge_out.get("issues") or []
            plot_feedback = (
                "【episode_plot_judge 未通过，请重写 plot JSON】\n"
                + "\n".join([f"- {x}" for x in fixes if x])
                + ("\n\nissues:\n" + "\n".join([f"- {x}" for x in issues if x]) if issues else "")
            )
        else:
            print(
                f"[episode-batch] 警告 ep={ep_id}: plot_judge 在 {max_plot_rounds} 轮后仍未 pass，保留末版 plot。"
            )

    return plot_out, plot_judge_out


async def run_episode_batch(output_root: Path, args: argparse.Namespace) -> None:
    debug_dir = output_root / "_debug" / f"episode_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    _ensure_dir(debug_dir)

    # 新参数：--series-dir 指向 runs/<剧名>/ 目录
    # 兼容旧参数：若没提供 --series-dir，则使用 --series-outline/--character-bible/--series-memory
    if getattr(args, "series_dir", ""):
        series_dir = Path(args.series_dir).resolve()
        paths = resolve_series_paths(series_dir)
        series_outline_path = paths["series_outline"]
        character_bible_path = paths["character_bible"]
        series_memory_path = paths["series_memory"]
    else:
        series_outline_path = Path(args.series_outline).resolve()
        series_dir = _series_root_from_outline_path(series_outline_path)
        paths = resolve_series_paths(series_dir)
        character_bible_path = Path(args.character_bible).resolve() if args.character_bible else paths["character_bible"]
        series_memory_path = Path(args.series_memory).resolve() if args.series_memory else paths["series_memory"]

    layout = str(paths.get("layout", "flat"))

    series_outline = json.loads(series_outline_path.read_text(encoding="utf-8"))
    character_bible = json.loads(character_bible_path.read_text(encoding="utf-8"))

    anchor_beats_path = paths["anchor_beats"]
    if anchor_beats_path.exists():
        anchor_beats = json.loads(anchor_beats_path.read_text(encoding="utf-8"))
    else:
        anchor_beats = {}

    series_title = series_outline.get("title") or series_dir.name
    episodes_root = paths["episodes_root"]
    _ensure_dir(episodes_root)
    if series_memory_path.exists():
        series_memory = json.loads(series_memory_path.read_text(encoding="utf-8"))
    else:
        series_memory = {"episodes": [], "characters": []}

    episode_ids = _parse_episode_ids(args.episodes)
    if not episode_ids:
        raise RuntimeError("episodes 参数为空（请传如 1-10 或 1,2,3）。")

    user_id = "episode_batch_user"
    session_service = InMemorySessionService()

    infer_text = (series_outline.get("logline") or "") + "\n" + (series_outline.get("overall_arc") or "")
    batch_bundle: Optional[Dict[str, Any]] = None
    reg_p = paths.get("production_carry_registry")
    if reg_p is not None and Path(reg_p).is_file():
        try:
            reg_doc = load_registry(Path(reg_p))
            batch_bundle = bundle_from_registry_series_identity(reg_doc.get("series_identity") or {})
        except (ValueError, OSError, json.JSONDecodeError):
            batch_bundle = None
    if not batch_bundle or not str(batch_bundle.get("primary_genre") or "").strip():
        batch_bundle = infer_genre_bundle_for_prompt(infer_text)
    batch_genre_caps = get_bundle_capabilities(batch_bundle)

    # 如果用户希望“续写”，先加载现有 episode_batch.json
    existing_batch_path = paths["episode_batch"]
    if existing_batch_path.exists() and not args.overwrite:
        existing_batch = json.loads(existing_batch_path.read_text(encoding="utf-8"))
        episodes_out: List[Dict[str, Any]] = existing_batch.get("episodes", [])
    else:
        episodes_out = []

    for ep_id in episode_ids:
        ep_dir = _unique_episode_dir(episodes_root, series_title, ep_id)
        _ensure_dir(ep_dir)
        ep_files = _episode_json_paths(ep_dir, layout)

        ep_row = _episode_outline_row(series_outline, ep_id)

        # 0) episode_function：本集在整季中的功能卡（先于 plot）
        function_prompt_base = (
            "生成本集 episode_function 功能卡（JSON 输出）。\n"
            "输入包含：本集在大纲中的条目、完整 series_outline、series_memory、anchor_beats（可为空）。\n\n"
            f"current_episode_outline_row=\n{json.dumps(ep_row, ensure_ascii=False)}\n\n"
            f"series_outline=\n{json.dumps(series_outline, ensure_ascii=False)}\n\n"
            f"series_memory=\n{json.dumps(series_memory, ensure_ascii=False)}\n\n"
            f"anchor_beats=\n{json.dumps(anchor_beats, ensure_ascii=False)}\n\n"
            f"episode_id={ep_id}\n"
        )
        function_prompt = _inject_genre_prompt_for_stage(batch_bundle, function_prompt_base, "episode_function")
        function_out = await _run_agent_json_with_qc(
            stage="episode_function",
            agent=series_agents.episode_function_agent,
            prompt=function_prompt,
            quality_mode=args.quality_mode,
            session_service=session_service,
            user_id=user_id,
            session_id=f"episode_{ep_id}_function",
            debug_dir=debug_dir,
            genre_caps=batch_genre_caps,
        )
        if function_out.get("episode_id") != ep_id:
            function_out["episode_id"] = ep_id
        _dump_json(ep_files["episode_function"], function_out)

        use_judges = _episode_judges_enabled(args)
        jr = _judge_retries(args)
        max_pkg_rounds = (jr + 1) if use_judges else 1

        plot_prompt_base = (
            "生成本集 plot（JSON 输出，字段须含 rule_execution_map 数组；若【题材能力开关】requires_rule_execution_map=false 则允许为空数组，禁止硬造规则）。\n"
            "须落实 episode_function.viewer_payoff_design 与 must_advance/must_inherit。\n\n"
            f"episode_function=\n{json.dumps(function_out, ensure_ascii=False)}\n\n"
            f"series_outline=\n{json.dumps(series_outline, ensure_ascii=False)}\n\n"
            f"series_memory=\n{json.dumps(series_memory, ensure_ascii=False)}\n\n"
            f"episode_id={ep_id}\n"
        )

        script_prompt_base = (
            "生成本集 script（JSON 输出）。\n"
            "须落实 viewer_payoff_design；plot.rule_execution_map 仅当 requires_rule_execution_map=true 或非空时强制对齐。\n"
            "输入包含：episode_function、series_outline、character_bible、series_memory、plot。\n\n"
            f"episode_function=\n{json.dumps(function_out, ensure_ascii=False)}\n\n"
            f"series_outline=\n{json.dumps(series_outline, ensure_ascii=False)}\n\n"
            f"character_bible=\n{json.dumps(character_bible, ensure_ascii=False)}\n\n"
            f"series_memory=\n{json.dumps(series_memory, ensure_ascii=False)}\n\n"
            f"plot=\n{json.dumps({}, ensure_ascii=False)}\n\n"
        )

        storyboard_prompt_base = (
            "生成本集 storyboard（JSON 输出，用于 Seedance）。\n"
            "须落实 viewer_payoff_design 与 script；若 plot.rule_execution_map 非空则画面须对齐其触发与反馈。\n"
            "输入包含：episode_function、plot、series_outline、character_bible、series_memory、script。\n\n"
            f"episode_function=\n{json.dumps(function_out, ensure_ascii=False)}\n\n"
            f"plot=\n{json.dumps({}, ensure_ascii=False)}\n\n"
            f"series_outline=\n{json.dumps(series_outline, ensure_ascii=False)}\n\n"
            f"character_bible=\n{json.dumps(character_bible, ensure_ascii=False)}\n\n"
            f"series_memory=\n{json.dumps(series_memory, ensure_ascii=False)}\n\n"
            f"script=\n{json.dumps({}, ensure_ascii=False)}\n\n"
        )

        def _script_prompt_with(plot_obj: Dict[str, Any], extra: str = "") -> str:
            core = script_prompt_base.replace(
                f"plot=\n{json.dumps({}, ensure_ascii=False)}",
                f"plot=\n{json.dumps(plot_obj, ensure_ascii=False)}",
                1,
            )
            return _inject_genre_prompt_for_stage(
                batch_bundle, core + (f"\n\n{extra}" if extra.strip() else ""), "episode_script"
            )

        def _storyboard_prompt_with(plot_obj: Dict[str, Any], script_obj: Dict[str, Any], extra: str = "") -> str:
            p = storyboard_prompt_base.replace(
                f"plot=\n{json.dumps({}, ensure_ascii=False)}",
                f"plot=\n{json.dumps(plot_obj, ensure_ascii=False)}",
                1,
            )
            p = p.replace(
                f"script=\n{json.dumps({}, ensure_ascii=False)}",
                f"script=\n{json.dumps(script_obj, ensure_ascii=False)}",
                1,
            )
            return _inject_genre_prompt_for_stage(
                batch_bundle, p + (f"\n\n{extra}" if extra.strip() else ""), "episode_storyboard"
            )

        pending_scope: Optional[str] = None
        pkg_feedback = ""
        plot_out: Dict[str, Any] = {}
        plot_judge_out: Optional[Dict[str, Any]] = None
        package_judge_out: Optional[Dict[str, Any]] = None
        script_out: Dict[str, Any] = {}
        storyboard_out: Dict[str, Any] = {}
        creative_scorecard: Dict[str, Any] = _creative_scorecard_placeholder(
            "episode-batch：未开启分集 judge 或跳过后写入占位。"
        )

        for gi in range(max_pkg_rounds):
            if gi == 0 or pending_scope == "plot":
                plot_extra = pkg_feedback if pending_scope == "plot" else ""
                plot_out, plot_judge_out = await _run_plot_phase_with_optional_judge(
                    ep_id=ep_id,
                    plot_prompt_base=plot_prompt_base,
                    function_out=function_out,
                    genre_bundle=batch_bundle,
                    quality_mode=args.quality_mode,
                    use_judges=use_judges,
                    judge_retries=jr,
                    session_service=session_service,
                    user_id=user_id,
                    debug_dir=debug_dir,
                    extra_feedback=plot_extra,
                    genre_caps=batch_genre_caps,
                )
                _dump_json(ep_files["plot"], plot_out)

                script_x = pkg_feedback if pending_scope == "plot" else ""
                script_out = await _run_agent_json_with_qc(
                    stage="script",
                    agent=series_agents.episode_script_agent,
                    prompt=_script_prompt_with(plot_out, script_x),
                    quality_mode=args.quality_mode,
                    session_service=session_service,
                    user_id=user_id,
                    session_id=f"episode_{ep_id}_script_g{gi}",
                    debug_dir=debug_dir,
                    genre_caps=batch_genre_caps,
                )
                _dump_json(ep_files["script"], script_out)

                storyboard_out = await _run_agent_json_with_qc(
                    stage="storyboard",
                    agent=series_agents.episode_storyboard_agent,
                    prompt=_storyboard_prompt_with(plot_out, script_out, ""),
                    quality_mode=args.quality_mode,
                    session_service=session_service,
                    user_id=user_id,
                    session_id=f"episode_{ep_id}_storyboard_g{gi}",
                    debug_dir=debug_dir,
                    genre_caps=batch_genre_caps,
                )
                _dump_json(ep_files["storyboard"], storyboard_out)

            elif pending_scope == "script":
                script_out = await _run_agent_json_with_qc(
                    stage="script",
                    agent=series_agents.episode_script_agent,
                    prompt=_script_prompt_with(plot_out, f"【package_judge 返修】\n{pkg_feedback}"),
                    quality_mode=args.quality_mode,
                    session_service=session_service,
                    user_id=user_id,
                    session_id=f"episode_{ep_id}_script_g{gi}",
                    debug_dir=debug_dir,
                    genre_caps=batch_genre_caps,
                )
                _dump_json(ep_files["script"], script_out)
                storyboard_out = await _run_agent_json_with_qc(
                    stage="storyboard",
                    agent=series_agents.episode_storyboard_agent,
                    prompt=_storyboard_prompt_with(plot_out, script_out, ""),
                    quality_mode=args.quality_mode,
                    session_service=session_service,
                    user_id=user_id,
                    session_id=f"episode_{ep_id}_storyboard_g{gi}",
                    debug_dir=debug_dir,
                    genre_caps=batch_genre_caps,
                )
                _dump_json(ep_files["storyboard"], storyboard_out)

            elif pending_scope == "storyboard":
                storyboard_out = await _run_agent_json_with_qc(
                    stage="storyboard",
                    agent=series_agents.episode_storyboard_agent,
                    prompt=_storyboard_prompt_with(
                        plot_out, script_out, f"【package_judge 返修】\n{pkg_feedback}"
                    ),
                    quality_mode=args.quality_mode,
                    session_service=session_service,
                    user_id=user_id,
                    session_id=f"episode_{ep_id}_storyboard_g{gi}",
                    debug_dir=debug_dir,
                    genre_caps=batch_genre_caps,
                )
                _dump_json(ep_files["storyboard"], storyboard_out)

            if not use_judges:
                creative_scorecard = _creative_scorecard_placeholder(
                    "fast 模式且未加 --episode-judge：跳过分集 plot/package judge。"
                )
                break

            pkg_prompt_base = (
                "你是分集整包评审（memory 之前最后一道内容门）。请只输出 JSON。\n"
                "对照 episode_function（含 viewer_payoff_design）、plot（含 rule_execution_map）、script、storyboard。\n\n"
                f"episode_function=\n{json.dumps(function_out, ensure_ascii=False)}\n\n"
                f"plot=\n{json.dumps(plot_out, ensure_ascii=False)}\n\n"
                f"script=\n{json.dumps(script_out, ensure_ascii=False)}\n\n"
                f"storyboard=\n{json.dumps(storyboard_out, ensure_ascii=False)}\n"
            )
            pkg_prompt = _inject_genre_prompt_for_stage(batch_bundle, pkg_prompt_base, "gate_package_judge")
            package_judge_out = await _run_agent_json(
                series_agents.episode_package_judge_agent,
                pkg_prompt,
                session_service=session_service,
                user_id=user_id,
                session_id=f"episode_{ep_id}_package_judge_g{gi}",
                debug_dir=debug_dir,
            )
            creative_scorecard = _merge_creative_scorecard(plot_judge_out, package_judge_out)
            _dump_json(ep_files["creative_scorecard"], creative_scorecard)

            if bool(package_judge_out.get("pass")):
                break

            if gi < max_pkg_rounds - 1:
                pending_scope = str(package_judge_out.get("rewrite_scope") or "storyboard").strip().lower()
                if pending_scope not in ("storyboard", "script", "plot"):
                    pending_scope = "storyboard"
                fixes = package_judge_out.get("must_fix") or []
                iss = package_judge_out.get("issues") or []
                pkg_feedback = "\n".join([f"- {x}" for x in fixes if x])
                if iss:
                    pkg_feedback += "\nissues:\n" + "\n".join([f"- {x}" for x in iss if x])
            else:
                print(
                    f"[episode-batch] 警告 ep={ep_id}: package_judge 在 {max_pkg_rounds} 轮后仍未 pass，保留末版。"
                )

        if not use_judges:
            _dump_json(ep_files["creative_scorecard"], creative_scorecard)

        # 5) update series_memory
        memory_prompt_base = (
            "更新 series_memory（JSON 输出）。\n"
            "输入包含：old_series_memory、episode_id、episode_function、plot、script、storyboard。\n\n"
            f"old_series_memory=\n{json.dumps(series_memory, ensure_ascii=False)}\n\n"
            f"episode_id={ep_id}\n\n"
            f"episode_function=\n{json.dumps(function_out, ensure_ascii=False)}\n\n"
            f"plot=\n{json.dumps(plot_out, ensure_ascii=False)}\n\n"
            f"script=\n{json.dumps(script_out, ensure_ascii=False)}\n\n"
            f"storyboard=\n{json.dumps(storyboard_out, ensure_ascii=False)}\n\n"
        )
        memory_prompt = _inject_genre_prompt_for_stage(batch_bundle, memory_prompt_base, "episode_memory")
        memory_out = await _run_agent_json_with_qc(
            stage="memory",
            agent=series_agents.episode_memory_agent,
            prompt=memory_prompt,
            quality_mode=args.quality_mode,
            session_service=session_service,
            user_id=user_id,
            session_id=f"episode_{ep_id}_memory",
            debug_dir=debug_dir,
            genre_caps=batch_genre_caps,
        )
        if not isinstance(memory_out, dict) or "episodes" not in memory_out or "characters" not in memory_out:
            raise RuntimeError("episode_memory_agent 输出缺少 episodes/characters 字段。")
        series_memory = memory_out
        _dump_json(series_memory_path, series_memory)

        # 5b) 将 series_memory 中尚未写入 character_bible 的新角色补全为与主角同级的 Seedance 肖像条目，并写回磁盘
        character_bible = await _patch_character_bible_new_characters(
            character_bible=character_bible,
            series_memory=series_memory,
            series_outline=series_outline,
            script_out=script_out,
            ep_id=ep_id,
            genre_bundle=batch_bundle,
            quality_mode=args.quality_mode,
            session_service=session_service,
            user_id=user_id,
            debug_dir=debug_dir,
            genre_caps=batch_genre_caps,
        )
        _dump_json(character_bible_path, character_bible)

        # 6) per-episode package.json（结构与 episode_batch.json 中 episodes[i] 一致）
        episode_pkg = {
            "episode_id": ep_id,
            "episode_function": function_out,
            "plot": plot_out,
            "script": script_out,
            "storyboard": storyboard_out,
            "creative_scorecard": creative_scorecard,
        }
        _dump_json(ep_files["package"], episode_pkg)

        # 支持续写/重复生成：同一集号以最新生成结果为准
        episodes_out = [e for e in episodes_out if e.get("episode_id") != ep_id]
        episodes_out.append(episode_pkg)
        print(f"[episode-batch] 生成完成：{ep_dir}")

    # 写回 episode_batch.json
    episode_batch_out = {
        "series_outline": series_outline,
        "character_bible": character_bible,
        "episodes": episodes_out,
        "series_memory": series_memory,
    }
    _dump_json(paths["episode_batch"], episode_batch_out)
    try:
        sync_carry_registry_minimal(paths, series_title=series_title, layout=layout)
    except Exception as exc:
        print(f"[episode-batch] production_carry_registry 同步未完全成功: {exc}")
    _write_series_manifest(series_dir, series_title, paths=paths)
    print(f"[episode-batch] 已更新：{paths['episode_batch']}")


async def main_async() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "op":
        from .studio_operations import run_cli

        run_cli(sys.argv[2:])
        return

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=["series-setup", "episode-batch"])
    parser.add_argument("--series-title", default="")

    parser.add_argument("--theme", default="")
    parser.add_argument("--audience-view", default="")
    parser.add_argument("--quality-mode", default="fast", choices=["fast", "quality"])

    # episode-batch 新入口：直接给剧名目录
    parser.add_argument("--series-dir", default="")

    # 兼容旧入口（不再推荐）：直接给 series_outline/character_bible/series_memory 文件路径
    parser.add_argument("--series-outline", default="")
    parser.add_argument("--character-bible", default="")
    parser.add_argument("--episodes", default="")
    parser.add_argument("--series-memory", default="")
    parser.add_argument("--overwrite", action="store_true")

    # 分集双层 judge：默认在 quality-mode quality 时启用；fast 可加 --episode-judge
    parser.add_argument(
        "--no-episode-judge",
        action="store_true",
        help="关闭 episode_plot_judge / episode_package_judge（仍保留字段校验与 viewer_payoff / rule_map）。",
    )
    parser.add_argument(
        "--episode-judge",
        action="store_true",
        help="在 fast 模式下仍运行分集 plot/package judge（耗 API）。",
    )
    parser.add_argument(
        "--judge-retries",
        type=int,
        default=2,
        help="plot_judge 与 package_judge 各自最多重试轮数（默认 2，即最多 3 次生成尝试）。",
    )

    args = parser.parse_args()
    # 输出目录固定在仓库内的 runs/，不需要用户手动提供路径
    output_root = PROJECT_ROOT / "runs"

    if args.mode == "series-setup":
        await run_series_setup(output_root=output_root, args=args)
    else:
        if not getattr(args, "series_dir", "") and (not args.series_outline or not args.character_bible):
            raise RuntimeError("episode-batch 模式必须提供 --series-dir（推荐），或提供 --series-outline + --character-bible。")
        await run_episode_batch(output_root=output_root, args=args)


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()


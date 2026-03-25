"""
独立执行分集 plot / package gate，复用 episode_plot_judge_agent、episode_package_judge_agent。
不写 creative_scorecard（避免与 ownership 扩展冲突）；结果以 JSON 返回供 op CLI。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from google.adk.sessions import InMemorySessionService

from . import series_agents
from .gate_artifacts import append_gate_entry, gate_artifact_path
from .run_series import (
    find_episode_dir_for_id,
    resolve_series_paths,
    _episode_json_paths,
    _maybe_inject_genre_rules,
    _run_agent_json,
)


def _infer_text_from_outline(outline: Dict[str, Any]) -> str:
    return (outline.get("logline") or "") + "\n" + (outline.get("overall_arc") or "")


def _default_debug_dir(series_dir: Path) -> Path:
    d = series_dir / "_debug" / f"gate_ops_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def plan_plot_gate(series_dir: Path, episode_id: int) -> Dict[str, Any]:
    paths = resolve_series_paths(series_dir.resolve())
    if not paths["series_outline"].exists():
        return {
            "ok": False,
            "operation": "gate.run_plot_gate",
            "error": f"缺少大纲: {paths['series_outline']}",
        }
    ep_dir, err = find_episode_dir_for_id(paths["episodes_root"], episode_id)
    if err:
        return {"ok": False, "operation": "gate.run_plot_gate", "error": err}
    layout = str(paths.get("layout", "flat"))
    ep_files = _episode_json_paths(ep_dir, layout)
    return {
        "ok": True,
        "dry_run": True,
        "operation": "gate.run_plot_gate",
        "episode_id": episode_id,
        "episode_dir": str(ep_dir),
        "would_read": [str(ep_files["episode_function"]), str(ep_files["plot"])],
        "would_write": [str(gate_artifact_path(ep_dir, layout))],
        "would_call": "episode_plot_judge_agent",
    }


def plan_package_gate(series_dir: Path, episode_id: int) -> Dict[str, Any]:
    paths = resolve_series_paths(series_dir.resolve())
    if not paths["series_outline"].exists():
        return {
            "ok": False,
            "operation": "gate.run_package_gate",
            "error": f"缺少大纲: {paths['series_outline']}",
        }
    ep_dir, err = find_episode_dir_for_id(paths["episodes_root"], episode_id)
    if err:
        return {"ok": False, "operation": "gate.run_package_gate", "error": err}
    layout = str(paths.get("layout", "flat"))
    ep_files = _episode_json_paths(ep_dir, layout)
    pkg = ep_files["package"]
    if pkg.exists():
        source = "06_package.json" if layout == "layered" else "package.json"
        would_read = [str(pkg)]
    else:
        source = "01–04 分文件"
        would_read = [
            str(ep_files["episode_function"]),
            str(ep_files["plot"]),
            str(ep_files["script"]),
            str(ep_files["storyboard"]),
        ]
    return {
        "ok": True,
        "dry_run": True,
        "operation": "gate.run_package_gate",
        "episode_id": episode_id,
        "episode_dir": str(ep_dir),
        "input_mode": source,
        "would_read": would_read,
        "would_write": [str(gate_artifact_path(ep_dir, layout))],
        "would_call": "episode_package_judge_agent",
    }


def _load_plot_inputs(ep_files: Dict[str, Path]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[str]]:
    ef, pl = ep_files["episode_function"], ep_files["plot"]
    if not ef.is_file():
        return None, None, f"缺少 episode_function: {ef}"
    if not pl.is_file():
        return None, None, f"缺少 plot: {pl}"
    try:
        return (
            json.loads(ef.read_text(encoding="utf-8")),
            json.loads(pl.read_text(encoding="utf-8")),
            None,
        )
    except json.JSONDecodeError as e:
        return None, None, f"JSON 解析失败: {e}"


def _load_package_inputs(
    ep_files: Dict[str, Path],
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[str]]:
    pkg_path = ep_files["package"]
    if pkg_path.is_file():
        try:
            pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            return None, None, None, None, f"package JSON 解析失败: {e}"
        fo = pkg.get("episode_function")
        po = pkg.get("plot")
        so = pkg.get("script")
        sbo = pkg.get("storyboard")
        if isinstance(fo, dict) and isinstance(po, dict) and isinstance(so, dict) and isinstance(sbo, dict):
            return fo, po, so, sbo, None
        return (
            None,
            None,
            None,
            None,
            "package 内缺少 episode_function/plot/script/storyboard 四对象字段",
        )

    missing = []
    for key in ("episode_function", "plot", "script", "storyboard"):
        if not ep_files[key].is_file():
            missing.append(str(ep_files[key]))
    if missing:
        return None, None, None, None, "缺少文件: " + "; ".join(missing)
    try:
        return (
            json.loads(ep_files["episode_function"].read_text(encoding="utf-8")),
            json.loads(ep_files["plot"].read_text(encoding="utf-8")),
            json.loads(ep_files["script"].read_text(encoding="utf-8")),
            json.loads(ep_files["storyboard"].read_text(encoding="utf-8")),
            None,
        )
    except json.JSONDecodeError as e:
        return None, None, None, None, str(e)


async def run_plot_gate_standalone(
    series_dir: Path,
    episode_id: int,
    *,
    debug_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    plan = plan_plot_gate(series_dir, episode_id)
    if not plan.get("ok"):
        return plan
    paths = resolve_series_paths(series_dir.resolve())
    outline = json.loads(paths["series_outline"].read_text(encoding="utf-8"))
    infer_text = _infer_text_from_outline(outline)
    ep_dir = Path(plan["episode_dir"])
    layout = str(paths.get("layout", "flat"))
    ep_files = _episode_json_paths(ep_dir, layout)
    function_out, plot_out, err = _load_plot_inputs(ep_files)
    if err:
        return {"ok": False, "operation": "gate.run_plot_gate", "error": err}

    ddir = debug_dir or _default_debug_dir(series_dir.resolve())
    pj_prompt_base = (
        "你是分集 plot 层评审。请严格只输出 JSON schema 要求的一个对象。\n"
        "对照 episode_function（含 viewer_payoff_design）与 plot（含 acts、rule_execution_map）。\n\n"
        f"episode_function=\n{json.dumps(function_out, ensure_ascii=False)}\n\n"
        f"plot=\n{json.dumps(plot_out, ensure_ascii=False)}\n"
    )
    pj_prompt = _maybe_inject_genre_rules(infer_text, pj_prompt_base)
    session_service = InMemorySessionService()
    plot_judge_out = await _run_agent_json(
        series_agents.episode_plot_judge_agent,
        pj_prompt,
        session_service=session_service,
        user_id="gate_op_user",
        session_id=f"gate_plot_ep{episode_id}",
        debug_dir=ddir,
    )
    gate_path = None
    gate_artifact_error = None
    try:
        gate_path = append_gate_entry(
            episodes_root=paths["episodes_root"],
            ep_dir=ep_dir,
            layout=layout,
            episode_id=episode_id,
            gate_type="plot_gate",
            gate_result=plot_judge_out if isinstance(plot_judge_out, dict) else {},
            generator="episode_plot_judge_agent",
            source_inputs={
                "episode_function": str(ep_files["episode_function"]),
                "plot": str(ep_files["plot"]),
            },
        )
    except (OSError, ValueError, PermissionError, TypeError, KeyError) as e:
        gate_artifact_error = str(e)
    return {
        "ok": True,
        "operation": "gate.run_plot_gate",
        "episode_id": episode_id,
        "episode_dir": str(ep_dir),
        "debug_dir": str(ddir),
        "gate_result": plot_judge_out,
        "gate_artifact_path": str(gate_path) if gate_path else None,
        "gate_artifact_error": gate_artifact_error,
    }


async def run_package_gate_standalone(
    series_dir: Path,
    episode_id: int,
    *,
    debug_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    plan = plan_package_gate(series_dir, episode_id)
    if not plan.get("ok"):
        return plan
    paths = resolve_series_paths(series_dir.resolve())
    outline = json.loads(paths["series_outline"].read_text(encoding="utf-8"))
    infer_text = _infer_text_from_outline(outline)
    ep_dir = Path(plan["episode_dir"])
    layout = str(paths.get("layout", "flat"))
    ep_files = _episode_json_paths(ep_dir, layout)
    fo, po, so, sbo, err = _load_package_inputs(ep_files)
    if err:
        return {"ok": False, "operation": "gate.run_package_gate", "error": err}

    ddir = debug_dir or _default_debug_dir(series_dir.resolve())
    pkg_prompt_base = (
        "你是分集整包评审（memory 之前最后一道内容门）。请只输出 JSON。\n"
        "对照 episode_function（含 viewer_payoff_design）、plot（含 rule_execution_map）、script、storyboard。\n\n"
        f"episode_function=\n{json.dumps(fo, ensure_ascii=False)}\n\n"
        f"plot=\n{json.dumps(po, ensure_ascii=False)}\n\n"
        f"script=\n{json.dumps(so, ensure_ascii=False)}\n\n"
        f"storyboard=\n{json.dumps(sbo, ensure_ascii=False)}\n"
    )
    pkg_prompt = _maybe_inject_genre_rules(infer_text, pkg_prompt_base)
    session_service = InMemorySessionService()
    package_judge_out = await _run_agent_json(
        series_agents.episode_package_judge_agent,
        pkg_prompt,
        session_service=session_service,
        user_id="gate_op_user",
        session_id=f"gate_package_ep{episode_id}",
        debug_dir=ddir,
    )
    si: Dict[str, str] = {}
    pkg_path = ep_files["package"]
    if pkg_path.is_file():
        si["package"] = str(pkg_path)
    else:
        si["episode_function"] = str(ep_files["episode_function"])
        si["plot"] = str(ep_files["plot"])
        si["script"] = str(ep_files["script"])
        si["storyboard"] = str(ep_files["storyboard"])
    gate_path = None
    gate_artifact_error = None
    try:
        gate_path = append_gate_entry(
            episodes_root=paths["episodes_root"],
            ep_dir=ep_dir,
            layout=layout,
            episode_id=episode_id,
            gate_type="package_gate",
            gate_result=package_judge_out if isinstance(package_judge_out, dict) else {},
            generator="episode_package_judge_agent",
            source_inputs=si,
        )
    except (OSError, ValueError, PermissionError, TypeError, KeyError) as e:
        gate_artifact_error = str(e)
    return {
        "ok": True,
        "operation": "gate.run_package_gate",
        "episode_id": episode_id,
        "episode_dir": str(ep_dir),
        "debug_dir": str(ddir),
        "gate_result": package_judge_out,
        "gate_artifact_path": str(gate_path) if gate_path else None,
        "gate_artifact_error": gate_artifact_error,
    }

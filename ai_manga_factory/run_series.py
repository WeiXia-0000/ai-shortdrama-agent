import argparse
import asyncio
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from .agent import _strict_json_only
from .genre_rules import infer_genre_rules_for_prompt
from . import series_agents


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


def _maybe_inject_genre_rules(infer_text: str, base_prompt: str) -> str:
    _, rules_block = infer_genre_rules_for_prompt(infer_text)
    return (rules_block + "\n\n" + base_prompt).strip()


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


async def run_series_setup(output_root: Path, args: argparse.Namespace) -> None:
    debug_dir = output_root / "_debug" / f"series_setup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    _ensure_dir(debug_dir)

    user_id = "series_setup_user"
    session_service = InMemorySessionService()

    infer_text = "\n".join([args.theme or "", args.audience_view or "", args.series_title or ""]).strip()
    infer_text = infer_text or (args.series_title or "series")

    # 1) 市场调研
    market_prompt_base = (
        "你是短剧/微短剧编剧顾问。基于输入做市场调研。\n"
        "输出字段：market_report（中文，结构化即可）。\n\n"
        f"输入：\n主题={args.theme}\n受众={args.audience_view}\n质量模式={args.quality_mode}\n"
    )
    market_prompt = _maybe_inject_genre_rules(infer_text, market_prompt_base)
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
    trend_prompt = _maybe_inject_genre_rules(infer_text, trend_prompt_base)
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
    judge_prompt = _maybe_inject_genre_rules(infer_text, judge_prompt_base)
    judge_out = await _run_agent_json(
        series_agents.concept_judge_series,
        judge_prompt,
        session_service=session_service,
        user_id=user_id,
        session_id="series_setup_judge",
        debug_dir=debug_dir,
    )

    # 4) 系列大纲（series_outline）
    rec_id = judge_out.get("recommended_concept_id")
    chosen_concept = None
    for c in trend_out.get("concepts", []):
        if c.get("id") == rec_id:
            chosen_concept = c
            break
    if not chosen_concept:
        raise RuntimeError("recommended_concept_id 未匹配到概念。")

    planner_prompt_base = (
        "把你评审推荐的概念扩展成 series_outline（JSON 输出，结构与 series_outline.json 兼容）。\n\n"
        f"chosen_concept=\n{json.dumps(chosen_concept, ensure_ascii=False)}\n"
    )
    planner_prompt = _maybe_inject_genre_rules(infer_text, planner_prompt_base)
    outline_out = await _run_agent_json(
        series_agents.series_planner_agent,
        planner_prompt,
        session_service=session_service,
        user_id=user_id,
        session_id="series_setup_outline",
        debug_dir=debug_dir,
    )

    # 5) 角色设定（character_bible）
    cb_prompt_base = (
        "根据 series_outline 抽取主要角色并生成 character_bible（JSON 输出，portrait_prompt_cn <=800 汉字）。\n\n"
        f"series_outline=\n{json.dumps(outline_out, ensure_ascii=False)}\n"
    )
    cb_prompt = _maybe_inject_genre_rules(infer_text, cb_prompt_base)
    cb_out = await _run_agent_json(
        series_agents.character_bible_agent,
        cb_prompt,
        session_service=session_service,
        user_id=user_id,
        session_id="series_setup_character_bible",
        debug_dir=debug_dir,
    )

    series_title = outline_out.get("title") or args.series_title or "series"
    series_dir_name = _safe_dir_name(series_title)
    series_dir = output_root / series_dir_name
    _ensure_dir(series_dir)

    series_setup_out = {
        "market_report": market_out.get("market_report", ""),
        "concepts": trend_out.get("concepts", []),
        "concept_judge_report": judge_out,
        "series_outline": outline_out,
        "character_bible": cb_out,
    }

    _dump_json(series_dir / "series_setup.json", series_setup_out)
    _dump_json(series_dir / "series_outline.json", outline_out)
    _dump_json(series_dir / "character_bible.json", cb_out)
    _dump_json(series_dir / "episode_pitch.json", chosen_concept)

    # 初始化 memory + episode_batch（此时 episodes 为空）
    series_memory = {"episodes": [], "characters": []}
    _dump_json(series_dir / "series_memory.json", series_memory)

    episode_batch = {
        "series_outline": outline_out,
        "character_bible": cb_out,
        "episodes": [],
        "series_memory": series_memory,
    }
    _dump_json(series_dir / "episode_batch.json", episode_batch)

    print(f"[series-setup] 输出完成：{series_dir}")


async def run_episode_batch(output_root: Path, args: argparse.Namespace) -> None:
    debug_dir = output_root / "_debug" / f"episode_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    _ensure_dir(debug_dir)

    series_outline_path = Path(args.series_outline)
    character_bible_path = Path(args.character_bible)
    series_dir = series_outline_path.parent

    series_outline = json.loads(series_outline_path.read_text(encoding="utf-8"))
    character_bible = json.loads(character_bible_path.read_text(encoding="utf-8"))

    series_title = series_outline.get("title") or series_dir.name
    episodes_root = series_dir / "episodes"
    _ensure_dir(episodes_root)

    series_memory_path = Path(args.series_memory) if args.series_memory else (series_dir / "series_memory.json")
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

    # 如果用户希望“续写”，先加载现有 episode_batch.json
    existing_batch_path = series_dir / "episode_batch.json"
    if existing_batch_path.exists() and not args.overwrite:
        existing_batch = json.loads(existing_batch_path.read_text(encoding="utf-8"))
        episodes_out: List[Dict[str, Any]] = existing_batch.get("episodes", [])
    else:
        episodes_out = []

    for ep_id in episode_ids:
        ep_dir = _unique_episode_dir(episodes_root, series_title, ep_id)
        _ensure_dir(ep_dir)

        # 1) plot
        plot_prompt_base = (
            "生成本集 plot（JSON 输出）。\n"
            "输入包含：series_outline、series_memory、episode_id。\n\n"
            f"series_outline=\n{json.dumps(series_outline, ensure_ascii=False)}\n\n"
            f"series_memory=\n{json.dumps(series_memory, ensure_ascii=False)}\n\n"
            f"episode_id={ep_id}\n"
        )
        plot_prompt = _maybe_inject_genre_rules(infer_text, plot_prompt_base)
        plot_out = await _run_agent_json(
            series_agents.episode_plot_agent,
            plot_prompt,
            session_service=session_service,
            user_id=user_id,
            session_id=f"episode_{ep_id}_plot",
            debug_dir=debug_dir,
        )
        _dump_json(ep_dir / "plot.json", plot_out)

        # 2) script
        script_prompt_base = (
            "生成本集 script（JSON 输出）。\n"
            "输入包含：series_outline、character_bible、series_memory、plot。\n\n"
            f"series_outline=\n{json.dumps(series_outline, ensure_ascii=False)}\n\n"
            f"character_bible=\n{json.dumps(character_bible, ensure_ascii=False)}\n\n"
            f"series_memory=\n{json.dumps(series_memory, ensure_ascii=False)}\n\n"
            f"plot=\n{json.dumps(plot_out, ensure_ascii=False)}\n\n"
        )
        script_prompt = _maybe_inject_genre_rules(infer_text, script_prompt_base)
        script_out = await _run_agent_json(
            series_agents.episode_script_agent,
            script_prompt,
            session_service=session_service,
            user_id=user_id,
            session_id=f"episode_{ep_id}_script",
            debug_dir=debug_dir,
        )
        _dump_json(ep_dir / "script.json", script_out)

        # 3) storyboard
        storyboard_prompt_base = (
            "生成本集 storyboard（JSON 输出，用于 Seedance）。\n"
            "输入包含：series_outline、character_bible、series_memory、script。\n\n"
            f"series_outline=\n{json.dumps(series_outline, ensure_ascii=False)}\n\n"
            f"character_bible=\n{json.dumps(character_bible, ensure_ascii=False)}\n\n"
            f"series_memory=\n{json.dumps(series_memory, ensure_ascii=False)}\n\n"
            f"script=\n{json.dumps(script_out, ensure_ascii=False)}\n\n"
        )
        storyboard_prompt = _maybe_inject_genre_rules(infer_text, storyboard_prompt_base)
        storyboard_out = await _run_agent_json(
            series_agents.episode_storyboard_agent,
            storyboard_prompt,
            session_service=session_service,
            user_id=user_id,
            session_id=f"episode_{ep_id}_storyboard",
            debug_dir=debug_dir,
        )
        _dump_json(ep_dir / "storyboard.json", storyboard_out)

        # 4) creative_scorecard（和你现有示例保持一致：目前给快评占位）
        creative_scorecard = {
            "quality_judge": {
                "pass": True,
                "reason": "episode-batch (fast) 模式下生成，尚未经过自动 QC。",
            }
        }
        _dump_json(ep_dir / "creative_scorecard.json", creative_scorecard)

        # 5) update series_memory
        memory_prompt_base = (
            "更新 series_memory（JSON 输出）。\n"
            "输入包含：old_series_memory、episode_id、plot、script、storyboard。\n\n"
            f"old_series_memory=\n{json.dumps(series_memory, ensure_ascii=False)}\n\n"
            f"episode_id={ep_id}\n\n"
            f"plot=\n{json.dumps(plot_out, ensure_ascii=False)}\n\n"
            f"script=\n{json.dumps(script_out, ensure_ascii=False)}\n\n"
            f"storyboard=\n{json.dumps(storyboard_out, ensure_ascii=False)}\n\n"
        )
        memory_prompt = _maybe_inject_genre_rules(infer_text, memory_prompt_base)
        memory_out = await _run_agent_json(
            series_agents.episode_memory_agent,
            memory_prompt,
            session_service=session_service,
            user_id=user_id,
            session_id=f"episode_{ep_id}_memory",
            debug_dir=debug_dir,
        )
        if not isinstance(memory_out, dict) or "episodes" not in memory_out or "characters" not in memory_out:
            raise RuntimeError("episode_memory_agent 输出缺少 episodes/characters 字段。")
        series_memory = memory_out
        _dump_json(series_memory_path, series_memory)

        # 6) per-episode package.json（结构与 episode_batch.json 中 episodes[i] 一致）
        episode_pkg = {
            "episode_id": ep_id,
            "plot": plot_out,
            "script": script_out,
            "storyboard": storyboard_out,
            "creative_scorecard": creative_scorecard,
        }
        _dump_json(ep_dir / "package.json", episode_pkg)

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
    _dump_json(series_dir / "episode_batch.json", episode_batch_out)
    print(f"[episode-batch] 已更新：{series_dir / 'episode_batch.json'}")


async def main_async() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=["series-setup", "episode-batch"])
    parser.add_argument("--series-title", default="")

    parser.add_argument("--theme", default="")
    parser.add_argument("--audience-view", default="")
    parser.add_argument("--quality-mode", default="fast", choices=["fast", "quality"])

    parser.add_argument("--series-outline", default="")
    parser.add_argument("--character-bible", default="")
    parser.add_argument("--episodes", default="")
    parser.add_argument("--series-memory", default="")
    parser.add_argument("--overwrite", action="store_true")

    args = parser.parse_args()
    # 输出目录固定在仓库内的 runs/，不需要用户手动提供路径
    output_root = PROJECT_ROOT / "runs"

    if args.mode == "series-setup":
        await run_series_setup(output_root=output_root, args=args)
    else:
        if not args.series_outline or not args.character_bible:
            raise RuntimeError("episode-batch 模式必须提供 --series-outline 和 --character-bible。")
        await run_episode_batch(output_root=output_root, args=args)


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()


import asyncio
import json
import os
import re
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
load_dotenv()  # load .env into os.environ

from ai_manga_factory.agent import root_agent

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types


APP_NAME = "ai_manga_factory"


# ----------------------------
# Utils: filesystem + json extraction
# ----------------------------
def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if isinstance(text, str) else str(text), encoding="utf-8")


def _dump_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def _extract_json(text: str) -> str:
    """Extract the first JSON object from model output (handles ```json fences)."""
    if not isinstance(text, str):
        text = str(text)
    t = text.strip()

    # Remove markdown fences if present
    if t.startswith("```"):
        parts = t.split("```")
        if len(parts) >= 2:
            t = parts[1].strip()
            if t.lower().startswith("json"):
                t = t[4:].strip()

    # Extract {...}
    if "{" in t and "}" in t:
        return t[t.find("{") : t.rfind("}") + 1]
    return t


# ----------------------------
# QC: hard validation rules
# ----------------------------
def validate_package(pkg: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Factory QC (hard checks). Empty list => pass.
    """
    issues: List[Dict[str, str]] = []

    # required top-level artifacts + type check
    required = {
        "episode_pitch": dict,
        "script": dict,
        "storyboard": dict,
        "creative_scorecard": dict,
    }

    for k, t in required.items():
        if k not in pkg:
            issues.append({"code": "MISSING_KEY", "target": k, "hint": f"必须补齐顶层字段 {k}。"})
            continue
        if not isinstance(pkg[k], t):
            issues.append({
                "code": "TYPE_INVALID",
                "target": k,
                "hint": f"{k} 必须是 JSON 对象（object），不能是 {type(pkg[k]).__name__}。"
            })
            continue
        if pkg[k] == {}:
            issues.append({
                "code": "EMPTY_OBJECT",
                "target": k,
                "hint": f"{k} 不能为空对象，必须包含必要字段。"
            })

    # If basic structure fails, stop early (avoid cascading errors)
    if issues:
        return issues

    # --- script checks ---
    script = pkg["script"]
    scenes = script.get("scenes", [])
    if not isinstance(scenes, list) or len(scenes) < 6:
        issues.append({"code": "SCENES_TOO_FEW", "target": "script.scenes", "hint": "script 至少 6 个 scene。"})
    else:
        for s in scenes:
            if not isinstance(s, dict):
                issues.append({"code": "SCENE_TYPE_INVALID", "target": "script.scenes[]", "hint": "scene 必须是对象。"})
                continue
            sid = s.get("scene_id", "unknown")
            dialogue = s.get("dialogue", [])
            if not isinstance(dialogue, list) or len(dialogue) < 6:
                issues.append({
                    "code": "DIALOGUE_TOO_FEW",
                    "target": f"script.scenes(scene_id={sid}).dialogue",
                    "hint": "该 scene 对白至少 6 句（中文短句，信息密度高）。"
                })

    # --- storyboard checks ---
    storyboard = pkg["storyboard"]
    shots = storyboard.get("shots", [])
    if not isinstance(shots, list) or len(shots) < 16:
        issues.append({"code": "SHOTS_TOO_FEW", "target": "storyboard.shots", "hint": "storyboard 至少 16 个 shot。"})
    else:
        for sh in shots:
            if not isinstance(sh, dict):
                issues.append({"code": "SHOT_TYPE_INVALID", "target": "storyboard.shots[]", "hint": "shot 必须是对象。"})
                continue
            shot_id = sh.get("shot_id", "unknown")
            visual = sh.get("visual", "")
            if not isinstance(visual, str) or len(visual.strip()) < 25:
                issues.append({
                    "code": "VISUAL_TOO_THIN",
                    "target": f"storyboard.shots(shot_id={shot_id}).visual",
                    "hint": "visual 至少 25 汉字，写清主体+动作+环境+关键道具/线索。"
                })

    # --- creative_scorecard minimal ---
    score = pkg["creative_scorecard"]
    # 你可以先只要求有 score_breakdown，避免太苛刻
    if "score_breakdown" not in score:
        issues.append({
            "code": "SCORECARD_MISSING",
            "target": "creative_scorecard.score_breakdown",
            "hint": "creative_scorecard 必须包含 score_breakdown。"
        })

    return issues


def build_feedback(issues: List[Dict[str, str]]) -> str:
    lines = [f"- [{i['code']}] {i['target']}: {i['hint']}" for i in issues]

    # 给一个“必须按此骨架填”的模板（非常关键）
    skeleton = {
        "episode_pitch": {
            "title": "string",
            "logline": "string",
            "hook_first_line": "string",
            "twist": "string",
            "why_people_watch": ["string"],
            "content_warnings": ["string"],
            "china_context_checks": {
                "no_western_templates": True,
                "setting": "如：城中村/地铁/外卖/直播/物业群/医院挂号/出租屋",
            },
        },
        "script": {
            "characters": [{"name": "string", "role": "string"}],
            "scenes": [
                {
                    "scene_id": 1,
                    "location": "string",
                    "time": "string",
                    "beats": ["string"],
                    "dialogue": [{"speaker": "string", "line": "string"}],
                }
            ],
        },
        "storyboard": {
            "shots": [
                {
                    "shot_id": 1,
                    "scene_id": 1,
                    "camera": "近景/中景/远景/跟拍/俯拍等",
                    "visual": ">=25汉字：主体+动作+环境+关键道具/线索",
                    "audio": "对白/环境音/音效提示",
                    "on_screen_text": "可选",
                }
            ]
        },
        "creative_scorecard": {
            "score_breakdown": {
                "hook": 0,
                "pacing": 0,
                "china_resonance": 0,
                "twist_payoff": 0,
                "clarity": 0
            },
            "critic_report": {"issues": ["string"], "top_fix": "string"},
            "rewrite_report": {"changed": ["string"], "why": "string"}
        }
    }

    return (
        "上轮输出未通过工厂验收，请严格逐条修复（不要发散重写）：\n"
        + "\n".join(lines)
        + "\n\n必须按以下 JSON 骨架输出完整 package（四个顶层字段都必须是 object 且非空；script/storyboard 不能是空字符串）：\n"
        + json.dumps(skeleton, ensure_ascii=False, indent=2)
        + "\n\n硬性要求：只输出一个 JSON 对象；不要 markdown；不要 ```；不要任何额外文字。"
    )


# ----------------------------
# Runner call + rate-limit backoff
# ----------------------------
def _parse_retry_seconds(err_text: str) -> float:
    """
    Try to parse 'Please retry in XXs' from error. fallback to 60s.
    """
    m = re.search(r"Please retry in ([0-9.]+)s", err_text)
    if m:
        return float(m.group(1))
    m2 = re.search(r"retryDelay['\"]?:\s*['\"]?(\d+)s", err_text)
    if m2:
        return float(m2.group(1))
    return 60.0


async def call_root_once(runner: Runner, user_id: str, session_id: str, prompt: str) -> str:
    """Run one turn and return final response text."""
    msg = types.Content(role="user", parts=[types.Part(text=prompt)])

    final_text = None
    async for ev in runner.run_async(user_id=user_id, session_id=session_id, new_message=msg):
        if ev.is_final_response():
            try:
                final_text = ev.content.parts[0].text
            except Exception:
                final_text = str(ev)

    if final_text is None:
        raise RuntimeError("No final_response event received from runner.")
    return final_text


async def call_root_once_with_backoff(
    runner: Runner,
    user_id: str,
    session_id: str,
    prompt: str,
    round_dir: Path,
    max_retries: int = 5,
) -> str:
    """
    Retry on 429 RESOURCE_EXHAUSTED with sleep, to avoid batch crash.
    """
    for attempt in range(1, max_retries + 1):
        try:
            return await call_root_once(runner, user_id, session_id, prompt)
        except Exception as e:
            s = str(e)
            # ADK wraps 429 as _ResourceExhaustedError, but we keep it generic:
            if "RESOURCE_EXHAUSTED" in s or "Error code: 429" in s or "429" in s:
                sleep_s = _parse_retry_seconds(s)
                sleep_s = min(sleep_s + 2.0, 180.0)  # small buffer + cap
                _write_text(round_dir / "error.txt", s)
                print(f"[RATE LIMIT] 429 hit. Sleeping {sleep_s:.1f}s then retry ({attempt}/{max_retries})...")
                await asyncio.sleep(sleep_s)
                continue
            # non-429: rethrow
            _write_text(round_dir / "error.txt", s)
            raise
    raise RuntimeError(f"Exceeded max_retries={max_retries} for rate limit.")


# ----------------------------
# Job: supervised loop with per-round artifacts
# ----------------------------
async def run_supervised_job(
    job_prompt: str,
    job_dir: Path,
    max_rounds: int = 3,
) -> Dict[str, Any]:
    """
    Supervisor loop:
    - run root agent
    - parse JSON
    - validate
    - if fail: feed back fix-list and retry
    Produces per-round logs on disk.
    """
    session_service = InMemorySessionService()
    user_id = "batch_user"
    session_id = f"batch_session_{job_dir.name}"

    await session_service.create_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    runner = Runner(app_name=APP_NAME, agent=root_agent, session_service=session_service)

    prompt = job_prompt
    job_meta: Dict[str, Any] = {
        "app_name": APP_NAME,
        "user_id": user_id,
        "session_id": session_id,
        "max_rounds": max_rounds,
        "started_at": datetime.now().isoformat(),
        "rounds": [],
    }
    _dump_json(job_dir / "job_meta.json", job_meta)

    last_pkg: Dict[str, Any] = {}
    last_raw: str = ""

    for r in range(1, max_rounds + 1):
        round_dir = job_dir / f"round_{r:02d}"
        round_dir.mkdir(parents=True, exist_ok=True)

        _write_text(round_dir / "prompt.txt", prompt)

        raw = await call_root_once_with_backoff(
            runner=runner, user_id=user_id, session_id=session_id, prompt=prompt, round_dir=round_dir
        )
        last_raw = raw
        _write_text(round_dir / "raw_response.txt", raw)

        extracted = _extract_json(raw)
        _write_text(round_dir / "extracted_json.txt", extracted)

        round_record: Dict[str, Any] = {"round": r}

        # parse json
        try:
            pkg = json.loads(extracted)
            last_pkg = pkg
            _dump_json(round_dir / "parsed.json", pkg)
        except Exception as e:
            round_record["passed"] = False
            round_record["parse_error"] = {"type": type(e).__name__, "message": str(e)}
            # feedback for next round
            prompt = (
                "你的输出不是可解析的 JSON。请只输出一个 JSON 对象："
                "不要 markdown，不要 ```，不要任何额外文字。"
                "再次输出完整 package（episode_pitch/script/storyboard/creative_scorecard）。"
            )
            _write_text(round_dir / "supervisor_feedback.txt", prompt)
            job_meta["rounds"].append(round_record)
            _dump_json(job_dir / "job_meta.json", job_meta)
            continue

        # validate
        issues = validate_package(pkg)
        _dump_json(round_dir / "qc_issues.json", issues)

        print(f"[QC] job={job_dir.name} round={r} issues={len(issues)}")
        for it in issues[:8]:
            print(" ", it)

        if not issues:
            round_record["passed"] = True
            job_meta["rounds"].append(round_record)
            job_meta["finished_at"] = datetime.now().isoformat()
            _dump_json(job_dir / "job_meta.json", job_meta)

            # final outputs
            final_dir = job_dir / "final"
            final_dir.mkdir(parents=True, exist_ok=True)
            _dump_json(final_dir / "package.json", pkg)
            for k, fn in [
                ("episode_pitch", "episode_pitch.json"),
                ("script", "script.json"),
                ("storyboard", "storyboard.json"),
                ("creative_scorecard", "creative_scorecard.json"),
            ]:
                if isinstance(pkg.get(k), (dict, list)):
                    _dump_json(final_dir / fn, pkg[k])

            pkg["supervisor_meta"] = {"passed": True, "rounds": r}
            return pkg

        # fail -> build feedback and retry
        feedback = build_feedback(issues)
        _write_text(round_dir / "supervisor_feedback.txt", feedback)
        prompt = feedback

        round_record["passed"] = False
        round_record["issues_count"] = len(issues)
        job_meta["rounds"].append(round_record)
        _dump_json(job_dir / "job_meta.json", job_meta)

    # failed after max rounds
    job_meta["finished_at"] = datetime.now().isoformat()
    _dump_json(job_dir / "job_meta.json", job_meta)
    return {
        "supervisor_meta": {"passed": False, "rounds": max_rounds},
        "last_raw": last_raw,
        "last_pkg": last_pkg,
        "job_dir": str(job_dir),
    }


# ----------------------------
# Main batch entry
# ----------------------------
async def main():
    # Batch prompts
    prompts = [
        "你是导演，请召集编剧室，按 trend_scout→plot→dialogue→storyboard→critic→rewrite→critic复评 流程完成。题材必须是中国现实生活语境，禁止欧美模板（特工组织/FBI/古堡/教堂驱魔等）。输出完整 package（episode_pitch/script/storyboard/creative_scorecard），只输出 JSON。",
        "偏都市悬疑：老小区/物业群/城中村/地铁/外卖/直播。必须钩子开场+结尾反转回扣伏笔。输出完整 package（episode_pitch/script/storyboard/creative_scorecard），只输出 JSON。",
    ]

    runs_root = Path(__file__).resolve().parent / "runs" / datetime.now().strftime("%Y%m%d_%H%M%S")
    runs_root.mkdir(parents=True, exist_ok=True)

    for idx, p in enumerate(prompts, start=1):
        job_dir = runs_root / f"job_{idx:02d}"
        job_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n=== Job {idx}/{len(prompts)} ===")
        pkg = await run_supervised_job(p, job_dir=job_dir, max_rounds=3)

        print("Saved:", job_dir)
        print("Supervisor:", pkg.get("supervisor_meta"))

        # Optional throttle between jobs (helps avoid 429 on free tier)
        await asyncio.sleep(2)

    print("\nAll done. Runs root:", runs_root)


if __name__ == "__main__":
    asyncio.run(main())
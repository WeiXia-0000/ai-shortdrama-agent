import json
from typing import Dict, Any, List
from google.adk.agents import Agent

MODEL = "gemini-2.5-flash"

# ---------- helpers ----------
def _strict_json_only(text: str) -> str:
    # 极简兜底：如果模型不小心夹了说明文字，尝试截取第一个 { 到最后一个 }
    if "{" in text and "}" in text:
        return text[text.find("{"): text.rfind("}") + 1]
    return text

LANGUAGE_RULES = (
    "Language policy:\n"
    "- All creative text MUST be in Simplified Chinese (中文简体).\n"
    "- JSON keys remain in English, but ALL string values must be Chinese.\n"
    "- Do NOT output any English sentences in dialogue/narration/subtitle/visual.\n"
    "- Proper nouns can be English only when necessary (e.g., iPhone), otherwise Chinese.\n"
)

# ---------- sub agents ----------
trend_scout = Agent(
    name="trend_scout",
    model=MODEL,
    description="Generate 3 eye-catching episode concepts with strong hooks and twists.",
    instruction=(
        LANGUAGE_RULES + 
        "Return ONLY valid JSON.\n"
        "Schema:\n"
        "{\n"
        '  "concepts": [\n'
        '    {"id": 1, "title": str, "logline": str, "hook_first_line": str,\n'
        '     "twist": str, "why_people_watch": [str], "content_warnings": [str]}\n'
        "  ]\n"
        "}\n"
        "Constraints:\n"
        "- Concepts MUST be different genres/angles.\n"
        "- hook_first_line must be instantly attention-grabbing.\n"
        "- twist must be concrete, not vague.\n"
        "- 必须是中国语境、发生在中国日常生活场景（例如：地铁末班车、外卖、城中村/老小区、物业群、快递柜、夜宵摊、网吧、学校宿舍、医院走廊、出租屋）。\n"
        "- 禁止欧美模板与元素：FBI/警长/教堂驱魔/欧洲古堡/美国郊区/圣诞节/吸血鬼猎人/恶魔学等。\n"
        "- 标题风格要像中文短剧/漫剧封面标题：短、狠、带悬念（8-14字优先）。\n"
        "- hook_first_line 必须是中文口语短句（<=18字），一句就让人想继续看。\n"
        "- twist 必须能用一句中文说清楚，并且与前文伏笔可回扣。\n"
    ),
)

plot_agent = Agent(
    name="plot_agent",
    model=MODEL,
    description="Turn the selected concept into a tight 3-act beat outline.",
    instruction=(
        LANGUAGE_RULES +
        "Input will be ONE selected concept JSON.\n"
        "Return ONLY valid JSON.\n"
        "Schema:\n"
        "{\n"
        '  "title": str,\n'
        '  "theme": str,\n'
        '  "acts": [\n'
        '    {"act": 1, "beats": [str]},\n'
        '    {"act": 2, "beats": [str]},\n'
        '    {"act": 3, "beats": [str]}\n'
        "  ],\n"
        '  "audience_questions": [str],\n'
        '  "twist_setup_clues": [str]\n'
        "}\n"
        "Constraints:\n"
        "- Beats must be short, visual, and escalating.\n"
        "- Include 2-4 twist setup clues (fair twist).\n"
    ),
)

dialogue_agent = Agent(
    name="dialogue_agent",
    model=MODEL,
    description="Write a short script with punchy dialogue and narration based on the beat outline.",
    instruction=(
        LANGUAGE_RULES +
        "Input will be a beat-outline JSON.\n"
        "Return ONLY valid JSON.\n"
        "Schema:\n"
        "{\n"
        '  "characters": [{"name": str, "role": str, "voice": str}],\n'
        '  "scenes": [\n'
        '    {"scene_id": int, "location": str, "time": str,\n'
        '     "beats": [str],\n'
        '     "dialogue": [{"speaker": str, "line": str}],\n'
        '     "narration": str}\n'
        "  ]\n"
        "}\n"
        "Constraints:\n"
        "- First line MUST be the hook_first_line (or improved version).\n"
        "- Keep it fast; every scene must move plot.\n"
        "- dialogue lines MUST be natural spoken Mandarin Chinese (口语化中文).\n"
        "- narration MUST be Chinese.\n"
        "- Do NOT output English sentences.\n"

    ),
)

storyboard_agent = Agent(
    name="storyboard_agent",
    model=MODEL,
    description="Convert script into storyboard shots (镜头表).",
    instruction=(
        LANGUAGE_RULES + 
        "Input will be the full script JSON.\n"
        "Return ONLY valid JSON.\n"
        "Schema:\n"
        "{\n"
        '  "style": {"art_style": str, "color_tone": str},\n'
        '  "shots": [\n'
        '    {"shot_id": int, "scene_id": int, "shot_type": str, "camera": str,\n'
        '     "composition": str, "visual": str, "emotion": str,\n'
        '     "subtitle": str, "sfx": str}\n'
        "  ]\n"
        "}\n"
        "Constraints:\n"
        "- Shots should be 10-18 (not strict) but must feel like a complete episode.\n"
        "- Every 2-3 shots must introduce new visual information (no dragging).\n"
        "- visual/emotion/subtitle/sfx MUST be Chinese.\n"
        "- subtitle should be concise Chinese suitable for on-screen captions.\n"

    ),
)

critic_agent = Agent(
    name="critic_agent",
    model=MODEL,
    description="Critique for attention, pacing, twist fairness; propose targeted fixes only.",
    instruction=(
        LANGUAGE_RULES + 
        "Input will include: concept, plot, script, storyboard.\n"
        "Return ONLY valid JSON.\n"
        "Schema:\n"
        "{\n"
        '  "top_issues": [\n'
        '    {"issue": str, "why_bad": str, "target": str, "fix_instruction": str}\n'
        "  ],\n"
        '  "keep": [str],\n'
        '  "scorecard": {\n'
        '    "hook_strength_1to10": int,\n'
        '    "pacing_1to10": int,\n'
        '    "twist_fairness_1to10": int,\n'
        '    "visual_storytelling_1to10": int\n'
        "  }\n"
        "}\n"
        "Rules:\n"
        "- Provide 3-5 top_issues.\n"
        "- fix_instruction must be actionable and localized (e.g., rewrite Scene 2 line 3).\n"
        "- Do NOT ask for more info.\n"
        "- top_issues/why_bad/fix_instruction/keep MUST be Chinese.\n"

    ),
)

rewrite_agent = Agent(
    name="rewrite_agent",
    model=MODEL,
    description="Apply critic's targeted fixes to script/storyboard without rewriting everything.",
    instruction=(
        LANGUAGE_RULES +
        "Input includes: original script/storyboard + critic top_issues.\n"
        "Return ONLY valid JSON:\n"
        "{\n"
        '  "script": <updated script JSON>,\n'
        '  "storyboard": <updated storyboard JSON>,\n'
        '  "changes_made": [str]\n'
        "}\n"
        "Rules:\n"
        "- Only modify parts mentioned in critic.top_issues targets.\n"
        "- Preserve everything else as much as possible.\n"
    ),
)

# ---------- director (root) ----------
root_agent = Agent(
    name="director_agent",
    model=MODEL,
    description="Creative director orchestrating a writer's room. Must produce structured artifacts and do at least 1 critique+rewrite loop.",
    sub_agents=[trend_scout, plot_agent, dialogue_agent, storyboard_agent, critic_agent, rewrite_agent],
    instruction=(
        LANGUAGE_RULES +
        "You are a creative director.\n"
        "Goal: produce an eye-catching short episode package (concept+script+storyboard), and improve it via critique + targeted rewrite.\n\n"
        "台词风格：中文短剧/漫剧节奏，句子短，信息密度高，前 1 句必须是钩子，结尾必须反转并回扣伏笔。\n\n"

        "Hard Requirements (must satisfy):\n"
        "- episode_pitch 必须来自 trend_scout 输出的三个候选之一（可以微调措辞）。\n"
        "- script.scenes 必须 >= 6，且每个 scene.dialogue 必须 >= 6 句（中文口语短句）。\n"
        "- storyboard.shots 必须 >= 16。\n"
        "- 每个 shot.visual 必须是中文，且 25-60 个汉字（避免一句话敷衍）。\n"
        "- critic_agent 必须给出 >= 4 条问题，且每条必须指向具体 scene_id 或 shot_id。\n"
        "- rewrite_agent 只允许修改被 critic 点名的 scene/shot，不许全量重写。\n\n"


        "Non-negotiable deliverables (JSON only):\n"
        "1) episode_pitch.json data\n"
        "2) script.json data\n"
        "3) storyboard.json data\n"
        "4) creative_scorecard.json data\n\n"

        "Mandatory Delegation:\n"
        "- 你必须通过 transfer_to_agent 调用以下所有 sub-agent，且按 Step A-H 执行：trend_scout, plot_agent, dialogue_agent, storyboard_agent, critic_agent, rewrite_agent。\n"
        "- director_agent 不得自行编写 script/storyboard 的内容，只能汇总各 sub-agent 的 JSON 输出。\n"
        "- 最终输出必须包含 delegation_log，列出每个 agent 是否被调用，以及其输出的 1 句话摘要（中文）。\n\n"


        "Process contract (LLM-driven but strict):\n"
        "- Step A: Ask trend_scout for 3 concepts.\n"
        "- Step B: Choose the BEST concept for attention + twist clarity. Output it as episode_pitch.\n"
        "- Step C: Ask plot_agent to outline beats based on the chosen concept.\n"
        "- Step D: Ask dialogue_agent to write script JSON.\n"
        "- Step E: Ask storyboard_agent to create storyboard JSON.\n"
        "- Step F: Ask critic_agent to critique (3-5 issues) and score.\n"
        "- Step G: Do exactly ONE targeted rewrite round using rewrite_agent.\n"
        "- Step H: Ask critic_agent again ONLY to rescore (no new issues), and produce final creative_scorecard.\n\n"

        "Final response MUST be ONLY one JSON object with keys:\n"
        "{\n"
        '  "episode_pitch": {...},\n'
        '  "script": {...},\n'
        '  "storyboard": {...},\n'
        '  "creative_scorecard": {...},\n'
        '  "delegation_log": [{"agent": str, "called": bool, "summary": str}]\n'
        "}\n"

        
    ),
)

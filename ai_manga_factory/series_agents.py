import json
from typing import Dict, Any, List

from google.adk.agents import Agent

from .agent import MODEL, LANGUAGE_RULES


def _json_only_instruction(schema_hint: str, constraints: List[str]) -> str:
    return (
        LANGUAGE_RULES
        + "Return ONLY valid JSON.\n"
        + schema_hint
        + "\nConstraints:\n"
        + "".join([f"- {c}\n" for c in constraints])
    )


# ================== series-setup 专职 agents ==================

market_research_agent = Agent(
    name="market_research_agent",
    model=MODEL,
    description="做短剧/微短剧市场调研，输出中文 market_report。",
    instruction=_json_only_instruction(
        schema_hint='{ "market_report": str }\n',
        constraints=[
            "只输出 JSON 对象，不要 markdown，不要 ```。",
            "market_report 必须是中文，且尽量覆盖热门题材、爽点钩子套路与创作建议。",
        ],
    ),
)

trend_scout_series = Agent(
    name="trend_scout_series",
    model=MODEL,
    description="基于 market_report 生成 3 个长篇系列概念。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "concepts": [\n    {\n      "id": int,\n      "title": str,\n      "logline": str,\n      "total_episodes": int,\n      "hook_premise": str,\n      "main_arc": str,\n      "why_people_watch": [str],\n      "content_warnings": [str]\n    }\n  ]\n}\n',
        constraints=[
            "3 个概念必须题材/视角/情绪价值明显不同。",
            "尽量贴近当下短剧常见爆点（系统+求生/规则/规则验证/反杀/反转），但不得生抄。",
            "hook_premise 与 main_arc 要能支撑长期铺垫，避免只写开头。",
            "数字合理：total_episodes 建议在 30-70 范围内。",
        ],
    ),
)

concept_judge_series = Agent(
    name="concept_judge_series",
    model=MODEL,
    description="评审 3 个系列概念并推荐一个。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "audience_view": str,\n  "evaluations": [\n    {\n      "concept_id": int,\n      "market_fit_score_1to10": int,\n      "audience_hook_score_1to10": int,\n      "long_run_potential_score_1to10": int,\n      "logic_score_1to10": int,\n      "commercial_score_1to10": int,\n      "strengths": [str],\n      "risks": [str],\n      "why_target_audience_may_watch": str,\n      "why_target_audience_may_skip": str,\n      "fix_suggestions": [str]\n    }\n  ],\n  "recommended_concept_id": int\n}\n',
        constraints=[
            "recommended_concept_id 必须是 evaluations 中存在的 concept_id。",
            "所有字段必须填写，不得为空。",
        ],
    ),
)

series_planner_agent = Agent(
    name="series_planner_agent",
    model=MODEL,
    description="把选中概念扩展成 series_outline（与现有 JSON 兼容）。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "title": str,\n  "total_episodes": int,\n  "logline": str,\n  "main_characters": [\n    { "name": str, "role": str, "arc_hint": str }\n  ],\n  "overall_arc": str,\n  "episode_list": [\n    { "episode_id": int, "title": str, "one_line": str, "hook": str, "cliffhanger": str }\n  ]\n}\n',
        constraints=[
            "episode_list 的 episode_id 必须从 1 连续到 total_episodes，不得缺失或跳号。",
            "每一集必须有 title/one_line/hook/cliffhanger 四个字段且不为空。",
            "overall_arc 必须是分阶段升级结构，并保证每阶段都能形成可持续爽点。",
            "禁止出现明显‘机械凑集数’：如果某集无法带来新增看点，应合并逻辑而非硬写重复内容。",
        ],
    ),
)

character_bible_agent = Agent(
    name="character_bible_agent_series",
    model=MODEL,
    description="从 series_outline 抽取主要角色并输出 character_bible。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "style_anchor": { "visual_style": str, "era_or_world": str, "camera_feel": str },\n  "main_characters": [\n    {\n      "name": str,\n      "gender": str,\n      "age_range": str,\n      "role": str,\n      "core_personality": [str],\n      "appearance_lock": {\n        "face_shape": str,\n        "hair": str,\n        "eyes": str,\n        "body_type": str,\n        "signature_features": [str],\n        "default_outfit": str,\n        "color_palette": [str]\n      },\n      "portrait_prompt_cn": str,\n      "negative_prompt_cn": str,\n      "consistency_rules": [str]\n    }\n  ]\n}\n',
        constraints=[
            "portrait_prompt_cn 必须是面向 Seedance 的中文详细肖像提示词，<=800 汉字。",
            "negative_prompt_cn 建议 <=150 汉字，用于明确不要出现的元素/风格。",
            "appearance_lock 必须可复用以锁脸：不要只写‘帅/酷’，要写可观察的五官与穿搭要素。",
        ],
    ),
)


# ================== episode-batch 专职 agents ==================

episode_plot_agent = Agent(
    name="episode_plot_agent",
    model=MODEL,
    description="根据 series_outline + series_memory 生成某一集 plot（节拍）。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "episode_id": int,\n  "title": str,\n  "theme": str,\n  "acts": [\n    { "act": 1, "beats": [str] },\n    { "act": 2, "beats": [str] },\n    { "act": 3, "beats": [str] }\n  ],\n  "hook": str,\n  "cliffhanger": str,\n  "twist_setup_clues": [str]\n}\n',
        constraints=[
            "严格输出合法 JSON（一个且仅一个 JSON 对象）；不允许额外自然语言。",
            "episode_id 必须与输入一致。",
            "beats 必须承接 series_memory.episodes 最近几集的 open_threads：至少 1-2 个 beats 要推进/回扣未解决线索。",
            "每一幕内部必须至少包含一个‘即时爽点’（反转/翻身/反杀/规则利用/付出换取）。",
            "act1 前 1-2 个 beats 必须完成大世界观/规则开场。",
            "act3 最后 1-2 个 beats 必须与本集 cliffhanger 对齐，为下一集抛出高张力问题。",
            "道具与设定必须逻辑自洽：禁止无来源天降（如普通办公室突然出现军用防毒面具）。",
        ],
    ),
)

episode_script_agent = Agent(
    name="episode_script_agent",
    model=MODEL,
    description="根据 plot + character_bible + series_memory 生成 script。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "episode_id": int,\n  "characters": [{"name": str, "role": str, "voice": str}],\n  "scenes": [\n    { "scene_id": int, "location": str, "time": str,\n      "beats": [str],\n      "dialogue": [{"speaker": str, "line": str}],\n      "narration": str }\n  ]\n}\n',
        constraints=[
            "严格遵循 input 里已存在的角色名：在 characters 里出现的 name 必须与 character_bible 或 series_memory 角色一致。",
            "dialogue 必须是口语化中文短句；narration 必须是中文且有情绪/画面感。",
            "如果出现群众/人群/观众反应，speaker 必须用‘群众/观众’，并在 narration 描写现场反应（不要只讲主角）。",
            "规则/系统类题材：禁止理工报告腔的‘解析完成/依据/指标’句式；要通过主角直觉/小动作/生活类比体验规则恐怖。",
            "整集必须有真实的‘违反规则→惩罚兑现’场面（可以是死亡/异变/重伤），并且用旁白+对话+环境细节呈现。",
        ],
    ),
)

episode_storyboard_agent = Agent(
    name="episode_storyboard_agent",
    model=MODEL,
    description="根据 script 生成 storyboard segments（每段可直接用于 Seedance）。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "episode_id": int,\n  "style": {"art_style": str, "color_tone": str},\n  "segments": [\n    {\n      "segment_id": int,\n      "scene_id": int,\n      "duration_seconds_min": int,\n      "duration_seconds_max": int,\n      "location": str,\n      "time_of_day": str,\n      "characters_in_frame": [str],\n      "dialogue_lines": [{"speaker": str, "line": str}],\n      "narration": str | null,\n      "emotion_tone": str,\n      "performance_notes": str,\n      "camera_plan": str,\n      "environment_details": str,\n      "sound_design": str,\n      "visual_description": str,\n      "subtitle_display": str,\n      "seedance_video_prompt": str\n    }\n  ]\n}\n',
        constraints=[
            "每个 segment 对应 3-8 秒视频；duration_seconds_min/max 要落在该范围内。",
            "visual_description 必须写明主体/动作/环境/关键道具，中文且有画面感。",
            "seedance_video_prompt 必须为中文且自包含，使用固定栏目模板，并尽量 <=800 汉字。",
            "seedance_video_prompt 必须严格包含以下栏目（顺序固定；缺失任一栏目都算不合格）：",
            "1)【场景地点】2)【时间】3)【角色】4)【角色外观锁定】5)【情绪语气】6)【表演动作】7)【镜头调度】8)【环境细节】9)【对白】10)【旁白】11)【字幕】12)【音效/环境音】13)【时长】14)【风格】。",
            "如果 narration 为 null，则在 seedance_video_prompt 中把【旁白】写成“无”；如果 dialogue_lines 为空，则【对白】写成“无”。",
            "seedance_video_prompt 的【角色外观锁定】必须把需要锁脸的命名角色外观要点写出（优先复用 character_bible.appearance_lock）。",
            "【对白】必须逐条覆盖 dialogue_lines（按顺序拼接）；【字幕】必须与屏幕字幕一致（可与【对白】相同，但必须有具体句子）。",
            "需要锁脸的主角/重要配角：必须在【角色外观锁定】复用 character_bible.appearance_lock 信息。",
            "如果 script/narration 有群众/人群/观众反应：必须在 characters_in_frame 加入‘群众/观众’，并在【角色】或【环境细节】写清群众做什么。",
        ],
    ),
)

episode_memory_agent = Agent(
    name="episode_memory_agent",
    model=MODEL,
    description="维护 series_memory：更新 episodes summary/open_threads 与 characters 登场状态。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "episodes": [\n    {"episode_id": int, "summary": str, "open_threads": [str]}\n  ],\n  "characters": [\n    {"name": str, "first_episode": int, "last_appeared_episode": int,\n     "status": "alive|dead|missing", "appearance_hint": str}\n  ]\n}\n',
        constraints=[
            "必须保留旧 series_memory 的 episodes/characters，只在其基础上更新 last_appeared_episode/status 并追加新条目。",
            "episodes 至少包含本集 episode_id：summary 3-5 句，open_threads 列出未解决悬念/线索。",
            "characters 只收录‘有名字的角色’，不收录‘群众/观众/人群’这类群像词。",
            "新角色：first_episode/last_appeared_episode 都设为本集 id，并给 appearance_hint（年龄/性别/穿着/气质）。",
        ],
    ),
)


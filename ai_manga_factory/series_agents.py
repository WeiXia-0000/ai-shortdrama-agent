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

season_mainline_agent = Agent(
    name="season_mainline_agent",
    model=MODEL,
    description="定义整季主线，只给方向不细化到具体集细节。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "title": str,\n  "core_theme": str,\n  "mainline_statement": str,\n  "phase_count": int,\n  "phase_goals": [\n    { "phase": int, "goal": str, "escalation": str }\n  ],\n  "main_conflicts": [str]\n}\n',
        constraints=[
            "只定义整季方向与阶段目标，不允许写“第X集去哪里/第X集出现什么规则/第X集靠什么道具活下来”。",
            "phase_goals 必须体现从被动到主动、从局部生存到系统性反制的升级轨迹。",
            "语言以高层策略为主，不输出具体地点、具体道具、具体规则条文。",
        ],
    ),
)

character_growth_agent = Agent(
    name="character_growth_agent",
    model=MODEL,
    description="定义角色成长与关系演化，人物成长优先。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "protagonist_arc": {\n    "initial_state": str,\n    "milestones": [\n      { "stage": int, "change": str, "decision_shift": str }\n    ],\n    "final_state": str\n  },\n  "supporting_arcs": [\n    { "name": str, "initial_role": str, "growth_turning_point": str, "importance_upgrade": str }\n  ],\n  "team_dynamics": [\n    { "stage": int, "relationship_change": str, "cause": str, "impact": str }\n  ],\n  "world_dependency_points": [\n    {\n      "stage": int,\n      "required_world_trigger": str,\n      "why_character_can_only_change_after_this": str\n    }\n  ],\n      "core_blind_spots": [str]\n}\n',
        constraints=[
            "人物成长必须是主驱动力，规则/机制只作为压力与催化，不得喧宾夺主。",
            "must: 核心成长节点必须伴随可持续后果：失去某物、关系受损、认知偏差加深、行动空间收缩四者至少其一。",
            "must: 每个里程碑必须写清“人物如何变化”与“下一次决策怎么被影响”。",
            "must: 团队关系至少出现一次明显分裂或重组，并给出可追溯原因。",
            "should: 角色成长应由具体事件或误判代价触发，而不是抽象地‘想通了’或‘变成熟了’。",
            "should: 支持角色的权重提升，必须通过功能性表现兑现（提供观察、判断、牺牲、纠错或关键选择），而不是只在描述中说其重要。",
            "avoid: 避免角色成长只表现为更冷静、更聪明、更强大，而没有同步失去或受限。",
            "avoid: 避免团队关系变化像突然翻脸或突然和解，必须让前面已有摩擦、依赖或误解做铺垫。",
        ],
    ),
)

world_reveal_pacing_agent = Agent(
    name="world_reveal_pacing_agent",
    model=MODEL,
    description="定义世界观揭示节奏，不写具体分集事件清单。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "reveal_layers": [\n    { "layer": int, "what_is_revealed": str, "why_now": str, "uncertainty_left": str }\n  ],\n  "mechanism_progression": [\n    { "stage": int, "new_understanding": str, "old_assumption_broken": str }\n  ],\n  "character_consequence_points": [\n    {\n      "stage": int,\n      "reveal": str,\n      "which_character_must_change": str,\n      "how_their_decision_logic_changes": str\n    }\n  ],\n  "late_game_truth_direction": str\n}\n',
        constraints=[
            "必须包含“规则并非随机”与“存在幕后机制”两个关键揭示层。",
            "must: 只定义揭示节奏和认知升级，不允许写具体集号地点与具体道具细节。",
            "must: 每层揭示都要保留不确定性，给后续阶段留下可生长空间。",
            "must: 每一层关键揭示都必须能够改变至少一个核心角色的判断方式、选择逻辑或关系立场。",
            "should: 揭示应优先通过代价、误判、冲突后果或异常现象逼出来，而不是单靠资料说明、口头说明或旁白总结。",
            "should: 前期揭示应更多打破旧理解，中后期揭示再逐步提供新框架，不要过早解释完整真相。",
            "avoid: 避免世界观揭示只是单纯增加设定名词，而没有改变角色行动。",
            "avoid: 避免过早给出完整幕后答案，导致后续只能平铺执行。",
        ],
    ),
)

coupling_reconciler_agent = Agent(
    name="coupling_reconciler_agent",
    model=MODEL,
    description="对齐人物成长线与世界揭示线，形成双向因果耦合。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "world_to_character": [\n    { "stage": int, "world_change_or_reveal": str, "trigger_event_type": str, "character_change": str }\n  ],\n  "character_to_world": [\n    { "stage": int, "character_change": str, "decision_shift": str, "world_reveal_push": str }\n  ],\n  "reconciled_growth_path": [\n    {\n      "stage": int,\n      "world_shift": str,\n      "character_shift": str,\n      "relationship_shift": str,\n      "why_this_stage_now_holds": str\n    }\n  ],\n  "non_negotiable_coupling_rules": [str],\n  "point_of_no_return": {\n    "stage": int,\n    "what_is_lost": str,\n    "why_return_is_impossible": str\n  },\n  "coupling_checks": [\n    { "check_id": int, "possible_gap": str, "fix_rule": str }\n  ],\n  "coupling_summary": str\n}\n',
        constraints=[
            "must: 必须形成双向链路：世界观/规则认知变化 → 事件类型变化 → 人物改变；以及人物改变 → 决策变化 → 世界揭示推进。",
            "must: 如果发现人物线与世界线平行不相交，必须在 coupling_checks 中明确指出裂缝并给出修正规则。",
            "must: 必须在 coupling_summary 中指出全剧至少一个“不可逆转点（Point of No Return）”，确保主角无法退回旧的安全认知或旧的关系结构。",
            "should: 人物获得新认知后，优先带来更复杂的规则悖论、道德困境或关系压力，而不是直接降低难度。",
            "should: 每次重大世界观揭示，最好同时改变至少一项：人物信念、团队关系、行动方法。",
            "avoid: 避免出现‘因为主角更聪明了所以更轻松通关’的线性升级逻辑。",
            "avoid: 避免世界揭示只服务于设定推进，而不改变任何人物状态。",
            "输出只做因果对齐，不写具体分集细节。",
        ],
    ),
)

series_spine_agent = Agent(
    name="series_spine_agent",
    model=MODEL,
    description="基于耦合结果生成整部作品骨架（spine），延迟细化。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "title": str,\n  "logline": str,\n  "mainline_arc": str,\n  "phases": [\n    {\n      "phase": int,\n      "objective": str,\n      "character_upgrade": str,\n      "world_upgrade": str,\n      "risk_level": str\n    }\n  ],\n  "phase_to_phase_bridges": [str],\n  "phase_end_state_changes": [\n    {\n      "phase": int,\n      "persistent_assets_gained": [str],\n      "persistent_costs_created": [str],\n      "beliefs_updated": [str],\n      "relationships_rewritten": [str]\n    }\n  ],\n  "non_negotiable_growth_rules": [str]\n}\n',
        constraints=[
            "must: 只给骨架，不允许写具体“第几集发生什么”。",
            "must: 每个 phase 必须同时体现人物升级和世界认知升级，不能只写其中一条线。",
            "must: non_negotiable_growth_rules 必须能约束后续分集不能乱写，例如：先有认知变化，再有策略升级；先有代价，再有方法论沉淀。",
            "should: 每个阶段结束时，应形成可持续的状态变化，例如：新的资产、长期代价、错误信念被修正、关系被改写中的至少两类。",
            "should: phase_to_phase_bridges 应说明上一阶段的后果如何逼出下一阶段，而不是只写‘危机升级了’。",
            "avoid: 避免把阶段写成单纯地点切换或难度升级。",
            "avoid: 避免上游过早细化具体规则、具体道具、具体场景解法。",
        ],
    ),
)

anchor_beats_agent = Agent(
    name="anchor_beats_agent",
    model=MODEL,
    description="锁定全作关键承重点（数量动态，不固定）。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "beat_count": int,\n  "anchors": [\n    {\n      "anchor_id": int,\n      "anchor_name": str,\n      "phase": int,\n      "what_happens": str,\n      "why_it_must_exist": str,\n      "belief_before": str,\n      "belief_after": str,\n      "character_state_before": str,\n      "character_state_after": str,\n      "relationship_change": str,\n      "cost_paid_here": str,\n      "must_be_true_conditions": [str],\n      "long_term_outputs": [str],\n      "character_growth_priority": str\n    }\n  ]\n}\n',
        constraints=[
            "must: anchor 数量不固定，但建议 6-12 个，必须与篇幅匹配。",
            "must: anchors 不是分集大纲，不允许写完整 episode 列表。",
            "must: 每个 anchor 必须优先体现人物成长承重意义，再描述规则/机制层面的变化。",
            "must: must_be_true_conditions 与 long_term_outputs 必须可供后续分集展开直接引用。",
            "must: 每个 anchor 至少明确一种长期输出：新资产、新代价、新误解、可回收伏笔中的一种。",
            "should: 关键 anchors 中，至少过半应包含一次直觉解法失效、误判代价或伪解法陷阱。",
            "should: long_term_outputs 最好包含可延后回收的细节，而不是只写抽象影响。",
            "should: 人物状态在 anchor 前后必须有可描述的差异，例如 belief shift、决策方式变化、关系位移。",
            "avoid: 避免 anchor 只是一个大事件发生了，但人物和长期状态没有变化。",
            "avoid: 避免每个 anchor 都强行做同一种‘复杂悖论’，导致节奏僵硬。",
        ],
    ),
)

episode_outline_expander_agent = Agent(
    name="episode_outline_expander_agent",
    model=MODEL,
    description="从 spine + anchors 展开到 series_outline（分集列表）。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "title": str,\n  "total_episodes": int,\n  "logline": str,\n  "main_characters": [\n    { "name": str, "role": str, "arc_hint": str }\n  ],\n  "overall_arc": str,\n  "episode_list": [\n    { "episode_id": int, "title": str, "one_line": str, "hook": str, "cliffhanger": str }\n  ]\n}\n',
        constraints=[
            "must: episode_list 必须由 anchors 驱动展开：分集内容是 anchor 之间的桥接，不是从零平铺。",
            "must: episode_id 必须从 1 连续到 total_episodes。",
            "must: 每一集必须至少服务于一个：角色成长推进 / 世界揭示推进 / anchor 条件回收。",
            "must: 若某一集删去后不影响任何角色成长、世界揭示或 anchor 回收，则该集应被压缩、合并或删除。",
            "should: bridge 集应优先承担‘沉淀后果’和‘埋设下阶段条件’的功能，而不是只做过渡走位。",
            "should: 分集展开时要体现前一阶段留下的资产、代价或误解如何影响下一集，而不是只继承 open_threads。",
            "avoid: 避免机械凑集数；桥接不足时，应压缩冗余而非复制模板剧情。",
            "avoid: 避免出现大量‘地点变化了、规则变化了、但人物和主线没有变化’的填充集。",
        ],
    ),
)

outline_review_agent = Agent(
    name="outline_review_agent",
    model=MODEL,
    description="从题材匹配、市场吸引力、转折节奏与篇幅承载力评审 series_outline，并给出分数与返修建议。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "overall_score_1to10": int,\n  "pass": bool,\n  "dimension_scores": {\n    "genre_fit_1to10": int,\n    "market_hook_1to10": int,\n    "turning_points_1to10": int,\n    "pacing_balance_1to10": int,\n    "length_support_1to10": int,\n    "closure_and_aftertaste_1to10": int\n  },\n  "hard_fail_reasons": [str],\n  "strengths": [str],\n  "risks": [str],\n  "must_fix": [str],\n  "rewrite_brief": {\n    "target_overall_score_1to10": int,\n    "must_keep": [str],\n    "must_change": [str],\n    "episode_level_adjustments": [str]\n  }\n}\n',
        constraints=[
            "只输出 JSON 对象。",
            "必须结合输入的 genre_rules（若有）判断题材符合度，不得泛泛而谈。",
            "必须评估故事吸引力、当下市场匹配度、关键转折恰当性、节奏是否仓促、篇幅是否能支撑完整短剧。",
            "overall_score_1to10 取 1-10 整数；pass 仅当 overall_score_1to10 >= 8 且 hard_fail_reasons 为空时可为 true。",
            "must_fix 至少给 3 条可执行建议；rewrite_brief 必须具体到可改写的分集层动作。",
        ],
    ),
)

character_bible_agent = Agent(
    name="character_bible_agent_series",
    model=MODEL,
    description="从 series_outline 抽取主要角色并输出 character_bible。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "style_anchor": { "visual_style": str, "era_or_world": str, "camera_feel": str },\n  "main_characters": [\n    {\n      "name": str,\n      "gender": str,\n      "age_range": str,\n      "role": str,\n      "core_personality": [str],\n      "appearance_lock": {\n        "face_shape": str,\n        "hair": str,\n        "eyes": str,\n        "body_type": str,\n        "signature_features": [str],\n        "default_outfit": str,\n        "color_palette": [str]\n      },\n      "face_triptych_prompt_cn": str,\n      "body_triptych_prompt_cn": str,\n      "negative_prompt_cn": str,\n      "consistency_rules": [str]\n    }\n  ]\n}\n',
        constraints=[
            "face_triptych_prompt_cn 必须是面向 Seedance 的中文提示词，生成“脸部三视图（正面/左侧/右侧）”，<=800 汉字。",
            "body_triptych_prompt_cn 必须是面向 Seedance 的中文提示词，生成“全身三视图（正面/左侧/右侧）”，且人物为标准站立姿势、无脸部细节强调，<=800 汉字。",
            "body_triptych_prompt_cn 必须清楚描述服装着装（上装/下装/外套）、鞋履、配饰、材质与主色，并与 appearance_lock.default_outfit / color_palette 一致。",
            "negative_prompt_cn 建议 <=150 汉字，用于明确不要出现的元素/风格。",
            "appearance_lock 必须可复用以锁脸：不要只写‘帅/酷’，要写可观察的五官与穿搭要素。",
            "两个提示词只能描述该角色本体形象，不得出现其他人物、互动关系、场景叙事、能量特效、道具剧情等额外元素。",
        ],
    ),
)


# ================== episode-batch 专职 agents ==================

character_visual_patch_agent = Agent(
    name="character_visual_patch_agent",
    model=MODEL,
    description="为 series_memory 中尚未写入 character_bible 的新登场角色补全与主角同级的 Seedance 肖像与外观锁定。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "characters": [\n    {\n      "name": str,\n      "gender": str,\n      "age_range": str,\n      "role": str,\n      "core_personality": [str],\n      "appearance_lock": {\n        "face_shape": str,\n        "hair": str,\n        "eyes": str,\n        "body_type": str,\n        "signature_features": [str],\n        "default_outfit": str,\n        "color_palette": [str]\n      },\n      "face_triptych_prompt_cn": str,\n      "body_triptych_prompt_cn": str,\n      "negative_prompt_cn": str,\n      "consistency_rules": [str],\n      "first_appeared_episode": int\n    }\n  ]\n}\n',
        constraints=[
            "只输出 JSON 对象；characters 仅包含本次需要补全的新角色，不得重复已有 character_bible 中已存在同名条目。",
            "face_triptych_prompt_cn 必须为中文、可直接投喂 Seedance，用于脸部三视图（正面/左侧/右侧），<=800 汉字。",
            "body_triptych_prompt_cn 必须为中文、可直接投喂 Seedance，用于全身三视图（正面/左侧/右侧），标准站立姿势，<=800 汉字。",
            "body_triptych_prompt_cn 必须包含完整着装信息：上装/下装/外套（如有）、鞋履、配饰、材质与主色，且与 appearance_lock.default_outfit / color_palette 一致。",
            "negative_prompt_cn 建议 <=150 汉字。",
            "appearance_lock 必须与 face_triptych_prompt_cn / body_triptych_prompt_cn 一致且可复用锁脸。",
            "提示词只能描述角色本体，不得包含他人、互动动作、剧情事件、场景叙事、能量/特效/新增设定。",
            "first_appeared_episode 必须与输入中该角色的登场集数一致。",
            "风格须与输入的 style_anchor 一致，不得另起无关画风。",
        ],
    ),
)

episode_function_agent = Agent(
    name="episode_function_agent",
    model=MODEL,
    description="生成本集在整季中的功能卡：承接 anchor、必须推进/继承项、持久变化与线索强化。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "episode_id": int,\n  "linked_anchor_ids": [int],\n  "episode_goal_in_series": str,\n  "must_advance": [str],\n  "must_inherit": [str],\n  "what_changes_persistently": [str],\n  "what_is_learned": [str],\n  "what_is_mislearned": [str],\n  "what_is_gained": [str],\n  "what_is_lost": [str],\n  "future_threads_strengthened": [str]\n}\n',
        constraints=[
            "严格输出合法 JSON（一个且仅一个 JSON 对象）；不允许额外自然语言。",
            "episode_id 必须与输入一致。",
            "must: episode_goal_in_series 必须回答本集删掉会坏什么、本集在整季里负责什么。",
            "must: linked_anchor_ids 必须引用输入中 anchor_beats.anchors 里存在的 anchor_id；若无可用 anchor 可写空数组但须在 episode_goal_in_series 说明原因。",
            "must: must_advance 至少 2 条，必须明确推进角色成长、世界揭示或 anchor 条件回收中的至少两类。",
            "must: must_inherit 至少 1 条，必须从 series_memory 或上集遗留中承接可验证线索/状态。",
            "must: what_changes_persistently 至少 1 条，写清本集结束后会留下来的东西。",
            "should: what_is_mislearned 可写主角或团队的错误认知，为后续反噬埋伏笔。",
            "avoid: 不要写具体分镜台词，不要替代 plot 的节拍细节。",
        ],
    ),
)

episode_plot_agent = Agent(
    name="episode_plot_agent",
    model=MODEL,
    description="根据 episode_function + series_outline + series_memory 生成某一集 plot（节拍）。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "episode_id": int,\n  "title": str,\n  "theme": str,\n  "acts": [\n    { "act": 1, "beats": [str] },\n    { "act": 2, "beats": [str] },\n    { "act": 3, "beats": [str] }\n  ],\n  "hook": str,\n  "cliffhanger": str,\n  "twist_setup_clues": [str],\n  "buried_clues": [str],\n  "logic_check": {\n    "why_this_episode_matters_in_series": str,\n    "what_from_previous_episodes_is_actually_used": [str],\n    "what_new_longterm_change_is_created": [str],\n    "what_would_break_if_this_episode_were_removed": str\n  }\n}\n',
        constraints=[
            "严格输出合法 JSON（一个且仅一个 JSON 对象）；不允许额外自然语言。",
            "episode_id 必须与输入一致。",
            "must: 必须落实输入中的 episode_function：must_advance、must_inherit、linked_anchor_ids 所指向的承重点，不得另起一套与功能卡无关的主线。",
            "must: beats 必须承接 series_memory.episodes 最近几集的 open_threads：至少 1-2 个 beats 要推进/回扣未解决线索。",
            "must: 每一幕内部必须至少包含一个‘即时兑现’：反转、规则利用、代价换收益、关系位移、误判惩罚中的至少一种。",
            "must: 核心破局方式不得依赖未铺垫、低代价、单步即解的直觉动作。",
            "must: act3 最后 1-2 个 beats 必须与本集 cliffhanger 对齐，为下一集抛出高张力问题。",
            "must: 道具与设定必须逻辑自洽：禁止无来源天降（如普通办公室突然出现军用防毒面具）。",
            "should: 解法优先基于规则灰区、判定漏洞、环境约束、错误理解被纠正后的窄缝，而不是单纯躲避、遮挡、逃跑。",
            "should: 场景危机最好与环境固有物理特性绑定（如能见度、重力、隔音、材质、空间结构）。",
            "should: 每一集结束后最好沉淀至少一种长期变化：资产、代价、误解、伏笔中的一种。",
            "avoid: 避免用‘刚好发现一个关键道具’来替代真正的困局设计。",
            "avoid: 避免角色刚获得新认知就立刻轻松压制局面。",
        ],
    ),
)

episode_script_agent = Agent(
    name="episode_script_agent",
    model=MODEL,
    description="根据 episode_function + plot + character_bible + series_memory 生成 script。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "episode_id": int,\n  "characters": [{"name": str, "role": str, "voice": str}],\n  "scenes": [\n    { "scene_id": int, "location": str, "time": str,\n      "beats": [str],\n      "dialogue": [{"speaker": str, "line": str}],\n      "narration": str }\n  ]\n}\n',
        constraints=[
            "严格遵循 input 里已存在的角色名：在 characters 里出现的 name 必须与 character_bible 或 series_memory 角色一致。",
            "must: 必须体现 episode_function 中的 must_advance、what_is_learned/what_is_mislearned、what_changes_persistently，不得写成与功能卡无关的平行故事。",
            "must: dialogue 必须是口语化中文短句；narration 必须是中文且有情绪/画面感。",
            "must: 不允许角色直接口头完整解释‘破局逻辑’或‘规则原理’；必须通过试错动作、代价、环境反馈和现场反噬侧面呈现。",
            "must: 整集必须有真实的‘违反规则→惩罚兑现’场面（可以是死亡/异变/重伤），并且用旁白+对话+环境细节呈现。",
            "must: 如果出现群众/人群/观众反应，speaker 必须用‘群众/观众’，并在 narration 描写现场惨状或恐慌（不要只讲主角）。",
            "should: 关键情报优先通过行为、观察、停顿、争执、误判后果来显露，而不是靠一人长篇说明。",
            "should: 角色对白应体现其当前 belief state 和误判状态，不要让所有人都像全知编剧。",
            "should: 规则/系统类题材要通过主角直觉、小动作、生活类比体验规则恐怖，避免理工报告腔。",
            "avoid: 避免角色在危机中说出明显属于作者视角的总结性台词。",
            "avoid: 避免把 buried clues 写得像明显答案提示。",
        ],
    ),
)

episode_storyboard_agent = Agent(
    name="episode_storyboard_agent",
    model=MODEL,
    description="根据 episode_function + script 生成分镜（每段可直接用于 Seedance）。",
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
            "must: 分镜须服务于 episode_function 中的本集目标与持久变化，不得只复述 script 而无推进感。",
            "must: seedance_video_prompt 不得引入 script 中未出现的关键剧情信息、关键规则机制或关键解法解释。",
            "should: 分镜应优先强化人物状态变化、环境压迫感和规则后果的可视化，而不是额外补设定。",
            "avoid: 避免在 prompt 中偷偷解释上游没有写清的逻辑。",
        ],
    ),
)

episode_memory_agent = Agent(
    name="episode_memory_agent",
    model=MODEL,
    description="维护 series_memory：结合 episode_function 更新摘要、线索与角色状态。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "episodes": [\n    { "episode_id": int, "summary": str, "open_threads": [str] }\n  ],\n  "characters": [\n    {\n      "name": str,\n      "first_episode": int,\n      "last_appeared_episode": int,\n      "status": "alive|dead|missing",\n      "appearance_hint": str\n    }\n  ],\n  "persistent_assets": [str],\n  "persistent_costs": [str],\n  "current_beliefs_true": [str],\n  "current_beliefs_false": [str],\n  "relationship_shifts": [str],\n  "planted_clues": [str],\n  "rule_knowledge_progression": [str]\n}\n',
        constraints=[
            "必须保留旧 series_memory 的 episodes/characters，只在其基础上更新 last_appeared_episode/status 并追加新条目。",
            "must: 更新时必须回扣输入中的 episode_function：what_changes_persistently、future_threads_strengthened、what_is_mislearned 等应体现在 open_threads 或 persistent 字段中。",
            "must: episodes 至少包含本集 episode_id：summary 3-5 句，open_threads 列出未解决悬念/线索。",
            "must: 除了 open_threads，还应尽量总结本集留下的长期影响：新资产、新代价、新误解、关系变化中的至少一种。",
            "must: characters 只收录‘有名字的角色’，不收录‘群众/观众/人群’这类群像词。",
            "must: 新角色：first_episode/last_appeared_episode 都设为本集 id，并给 appearance_hint（年龄/性别/穿着/气质）。",
            "should: 对核心角色，应更新其当前状态变化，而不仅仅是 alive/dead/missing。",
            "avoid: 避免 summary 只写‘发生了什么’，不写‘改变了什么’。",
        ],
    ),
)


import json
from typing import Dict, Any, List

from google.adk.agents import Agent

from .creative_constants import MODEL, LANGUAGE_RULES


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
            "必须遵守用户 prompt 中的【题材能力开关】uses_explicit_rules。",
            "must（通用结构）: 人物成长必须是主驱动力；外部系统、规则条文、社会秩序、关系结构、资源与身份压力等只作为压力与催化，不得喧宾夺主。",
            "genre enhancement: 若 uses_explicit_rules=true，可进一步写清规则/机制/执行成本如何逼出人物成长与决策变化。",
            "genre enhancement: 若 uses_explicit_rules=false，优先体现社会秩序、关系失衡、资源约束、身份压力或情感错位如何逼出人物成长。",
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
    description="定义世界观/情境认知的揭示节奏，不写具体分集事件清单。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "reveal_layers": [\n    { "layer": int, "what_is_revealed": str, "why_now": str, "uncertainty_left": str }\n  ],\n  "mechanism_progression": [\n    { "stage": int, "new_understanding": str, "old_assumption_broken": str }\n  ],\n  "character_consequence_points": [\n    {\n      "stage": int,\n      "reveal": str,\n      "which_character_must_change": str,\n      "how_their_decision_logic_changes": str\n    }\n  ],\n  "late_game_truth_direction": str\n}\n',
        constraints=[
            "必须遵守用户 prompt 中的【题材能力开关】has_hidden_mechanism。",
            "must: 通用表达：至少体现“表层理解被推翻/更深一层运行逻辑（可为利益结构、关系真相、隐藏因果、系统性压制等）正在逼近”；不要用单一题材模板硬套所有剧。",
            "must: 若 has_hidden_mechanism=true，鼓励深层机制、认知升级、幕后结构或系统性反转；可包含规则类世界观，但不强迫每剧都是条文规则。",
            "must: 若 has_hidden_mechanism=false，禁止硬写完整幕后规则系统或超自然条文体系；揭示侧重社会关系、资源结构、情感与立场真相等可落地逻辑。",
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
            "必须遵守用户 prompt 中的【题材能力开关】uses_explicit_rules（及 prefers_relationship_push / prefers_status_hierarchy_conflict 若适用）。",
            "must（通用结构）: 必须形成双向链路：对世界运行逻辑、关系真相、秩序结构或规则系统的认知变化 → 事件类型变化 → 人物改变；以及人物改变 → 决策变化 → 更深层真相或结构被揭开（世界揭示推进）。",
            "genre enhancement: 若 uses_explicit_rules=true，“运行逻辑/认知变化”可具体体现为规则认知、机制陷阱、执行成本、隐藏条文等。",
            "genre enhancement: 若 uses_explicit_rules=false，优先体现为关系真相、利益结构、身份秩序、社会压力或情感结构；可结合 prefers_relationship_push / prefers_status_hierarchy_conflict 强化关系或阶层博弈侧。",
            "must: 如果发现人物线与世界线平行不相交，必须在 coupling_checks 中明确指出裂缝并给出修正规则。",
            "must: 必须在 coupling_summary 中指出全剧至少一个“不可逆转点（Point of No Return）”，确保主角无法退回旧的安全认知或旧的关系结构。",
            "should: 人物获得新认知后，优先带来更复杂的张力升级（可为规则悖论、道德困境、关系或秩序压力），而不是直接降低难度。",
            "should: 每次重大“世界一侧”的揭示，最好同时改变至少一项：人物信念、团队关系、行动方法。",
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
            "必须遵守用户 prompt 中的【题材能力开关】uses_explicit_rules、prefers_relationship_push、prefers_status_hierarchy_conflict。",
            "must: anchor 数量不固定，但建议 6-12 个，必须与篇幅匹配。",
            "must: anchors 不是分集大纲，不允许写完整 episode 列表。",
            "must: 每个 anchor 必须优先体现人物成长承重意义，再描述外部结构带来的变化（规则/秩序/关系等随题材具体化）。",
            "must: must_be_true_conditions 与 long_term_outputs 必须可供后续分集展开直接引用。",
            "must: 每个 anchor 至少明确一种长期输出：新资产、新代价、新误解、可回收伏笔中的一种。",
            "must（通用结构）: 关键 anchors 中至少过半须包含一次「低成本直觉路径失效」或「错误判断带来代价」——角色不能靠低成本、低理解、无代价的方式轻易过关，错误路径须暴露成本。",
            "genre enhancement: 若 uses_explicit_rules=true，上述失败/代价可优先体现为规则误读、伪解法陷阱、错误验证、表层生路失效等。",
            "genre enhancement: 若 uses_explicit_rules=false，可优先体现为关系误判、身份判断错误、资源押注错误、情绪决策失误、站队判断失误等。",
            "genre enhancement: 若 prefers_relationship_push=true，可优先用情感错位、底线误判、立场误读等承载上述代价。",
            "genre enhancement: 若 prefers_status_hierarchy_conflict=true，可优先用押错人、站错队、身份/阶层判断失误等承载上述代价。",
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
    description="生成本集在整季中的功能卡：承接 anchor、必须推进/继承项、持久变化、观众爽点设计与线索强化。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "episode_id": int,\n  "linked_anchor_ids": [int],\n  "episode_goal_in_series": str,\n  "must_advance": [str],\n  "must_inherit": [str],\n  "what_changes_persistently": [str],\n  "what_is_learned": [str],\n  "what_is_mislearned": [str],\n  "what_is_gained": [str],\n  "what_is_lost": [str],\n  "future_threads_strengthened": [str],\n  "viewer_payoff_design": [\n    {\n      "type": str,\n      "setup_source": str,\n      "payoff_target": str,\n      "description": str\n    }\n  ]\n}\n',
        constraints=[
            "严格输出合法 JSON（一个且仅一个 JSON 对象）；不允许额外自然语言。",
            "episode_id 必须与输入一致。",
            "must: episode_goal_in_series 必须回答本集删掉会坏什么、本集在整季里负责什么。",
            "must: linked_anchor_ids 必须引用输入中 anchor_beats.anchors 里存在的 anchor_id；若无可用 anchor 可写空数组但须在 episode_goal_in_series 说明原因。",
            "must: must_advance 至少 2 条，必须明确推进角色成长、世界揭示或 anchor 条件回收中的至少两类。",
            "must: must_inherit 至少 1 条，必须从 series_memory 或上集遗留中承接可验证线索/状态。",
            "must: what_changes_persistently 至少 1 条，写清本集结束后会留下来的东西。",
            "must: viewer_payoff_design 至少 2 条；每条须含 type（如 rule_exploit/shock/reversal/emotional_hit）、payoff_target（如 early_hook/act2_or_act3/closing）、description（中文，可执行）。",
            "should: setup_source 可指向 must_inherit/must_advance 等，说明爽点承接来源；无则写空字符串。",
            "should: what_is_mislearned 可写主角或团队的错误认知，为后续反噬埋伏笔。",
            "avoid: 不要写具体分镜台词，不要替代 plot 的节拍细节；viewer_payoff_design 只定义观众层目标，不写具体台词。",
        ],
    ),
)

episode_plot_agent = Agent(
    name="episode_plot_agent",
    model=MODEL,
    description="根据 episode_function + series_outline + series_memory 生成 plot（节拍）；若题材启用显式规则机制则生成可用的 rule_execution_map。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "episode_id": int,\n  "title": str,\n  "theme": str,\n  "acts": [\n    { "act": 1, "beats": [str] },\n    { "act": 2, "beats": [str] },\n    { "act": 3, "beats": [str] }\n  ],\n  "hook": str,\n  "cliffhanger": str,\n  "twist_setup_clues": [str],\n  "buried_clues": [str],\n  "rule_execution_map": [\n    {\n      "rule_id": str,\n      "rule_text": str,\n      "rule_layer": str,\n      "trigger_beat": str,\n      "feedback": str,\n      "verified_in_episode": bool\n    }\n  ],\n  "logic_check": {\n    "why_this_episode_matters_in_series": str,\n    "what_from_previous_episodes_is_actually_used": [str],\n    "what_new_longterm_change_is_created": [str],\n    "what_would_break_if_this_episode_were_removed": str\n  }\n}\n',
        constraints=[
            "严格输出合法 JSON（一个且仅一个 JSON 对象）；不允许额外自然语言。",
            "必须遵守用户 prompt 中的【题材能力开关】uses_explicit_rules 与 requires_rule_execution_map。",
            "episode_id 必须与输入一致。",
            "must: 必须落实输入中的 episode_function：must_advance、must_inherit、linked_anchor_ids、viewer_payoff_design；节拍须让观众爽点设计在对应幕次兑现。",
            "must: 若 requires_rule_execution_map=true：rule_execution_map 至少 1 条；若同时 uses_explicit_rules=true 则至少 2 条。每条含 rule_id、rule_text、rule_layer、trigger_beat（须能在 acts.beats 语义上对位）、feedback（可拍后果）、verified_in_episode=true。",
            "must: 若 requires_rule_execution_map=false：rule_execution_map 必须为 []；禁止为凑字段编造条文规则；重点写人物推进、关系位移、冲突升级、长期变化与爽点兑现。",
            "must: beats 必须承接 series_memory.episodes 最近几集的 open_threads：至少 1-2 个 beats 要推进/回扣未解决线索。",
            "must: 每一幕内部必须至少包含一个‘即时兑现’：反转、（仅显式规则题材）规则利用、代价换收益、关系位移、误判惩罚中的至少一种。",
            "must: 核心破局方式不得依赖未铺垫、低代价、单步即解的直觉动作。",
            "must: act3 最后 1-2 个 beats 必须与本集 cliffhanger 对齐，为下一集抛出高张力问题。",
            "must: 道具与设定必须逻辑自洽：禁止无来源天降（如普通办公室突然出现军用防毒面具）。",
            "should: 若 uses_explicit_rules=true：解法优先规则灰区、判定漏洞、误读纠正后的窄缝；否则优先关系张力、资源/秩序约束、社会压力、情感误判与环境限制中的窄缝，而不是单纯躲避、遮挡、逃跑。",
            "should: 场景危机最好与环境或社会情境的固有约束绑定（物理空间、时间压力、权力结构、舆论场等）。",
            "should: 每一集结束后最好沉淀至少一种长期变化：资产、代价、误解、伏笔中的一种。",
            "avoid: 若 requires_rule_execution_map=true：避免 rule_execution_map 与 beats 脱节；避免规则只作背景板。",
            "avoid: 避免用‘刚好发现一个关键道具’来替代真正的困局设计。",
            "avoid: 避免角色刚获得新认知就立刻轻松压制局面。",
        ],
    ),
)

episode_script_agent = Agent(
    name="episode_script_agent",
    model=MODEL,
    description="根据 episode_function + plot + character_bible + series_memory 生成 script；若 plot 含有效 rule_execution_map 或题材要求显式规则则落实其触发与反馈。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "episode_id": int,\n  "characters": [{"name": str, "role": str, "voice": str}],\n  "scenes": [\n    { "scene_id": int, "location": str, "time": str,\n      "beats": [str],\n      "dialogue": [{"speaker": str, "line": str}],\n      "narration": str }\n  ]\n}\n',
        constraints=[
            "必须遵守用户 prompt 中的【题材能力开关】requires_rule_execution_map、requires_visible_rule_punishment、uses_explicit_rules。",
            "严格遵循 input 里已存在的角色名：在 characters 里出现的 name 必须与 character_bible 或 series_memory 角色一致。",
            "must: 必须落实 episode_function.viewer_payoff_design：每条爽点须在对应幕次/节奏有可观察的场面与后果，不得只写旁白概括。",
            "must: 若 requires_rule_execution_map=true 且 plot.rule_execution_map 非空：每条须在具体场次中有触发或试探，反馈与 plot 一致，不得改写成无关新规则。",
            "must: 若 requires_rule_execution_map=false：不得为凑规则写伪条文；不强制落实空 rule_execution_map。",
            "must: 必须体现 episode_function 中的 must_advance、what_is_learned/what_is_mislearned、what_changes_persistently，不得写成与功能卡无关的平行故事。",
            "must: dialogue 必须是口语化中文短句；narration 必须是中文且有情绪/画面感。",
            "must: 若 requires_visible_rule_punishment=true：整集须有显式规则被触发/违反后的可感后果（惩罚、异变、重伤、公开处刑式反馈等），用旁白+对话+环境细节呈现。",
            "must: 若 requires_visible_rule_punishment=false：须有‘核心机制/关系/秩序被触发后的后果兑现’（如关系破裂、资源失守、站队变化、误会升级、名誉损失、身份暴露、情感错位、社会性惩罚等），禁止硬写条文式规则惩罚。",
            "must: 若 uses_explicit_rules=true：不允许角色直接口头完整解释破局逻辑或规则原理；须通过试错动作、代价、环境反馈和现场反噬侧面呈现。",
            "must: 若 uses_explicit_rules=false：不允许角色用作者视角长篇解释整场戏的运作逻辑；优先通过动作、现场反馈、关系变化呈现。",
            "must: 如果出现群众/人群/观众反应，speaker 必须用‘群众/观众’，并在 narration 描写现场反应（不要只讲主角）。",
            "should: 关键情报优先通过行为、观察、停顿、争执、误判后果来显露，而不是靠一人长篇说明。",
            "should: 角色对白应体现其当前 belief state 和误判状态，不要让所有人都像全知编剧。",
            "should: 仅当 uses_explicit_rules=true：可通过直觉、小动作、生活类比呈现规则压迫，避免理工报告腔。",
            "avoid: 避免角色在危机中说出明显属于作者视角的总结性台词。",
            "avoid: 避免把 buried clues 写得像明显答案提示。",
        ],
    ),
)

episode_storyboard_agent = Agent(
    name="episode_storyboard_agent",
    model=MODEL,
    description="根据 episode_function（含 viewer_payoff_design）+ plot + script 生成分镜；若 rule_execution_map 非空或题材要求显式规则则画面须对齐规则后果。",
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
            "must: 分镜须服务于 episode_function 中的本集目标、viewer_payoff_design 与持久变化，不得只复述 script 而无推进感。",
            "must: 遵守【题材能力开关】requires_rule_execution_map。若 plot.rule_execution_map 非空：须在画面层兑现其中触发与反馈（可拍、可见）。若为空且 requires_rule_execution_map=false：改为强化关系/冲突后果、爽点与 episode_function 目标的视觉兑现，勿硬画条文规则。",
            "must: seedance_video_prompt 不得引入 script 中未出现的关键剧情信息、关键规则机制或关键解法解释。",
            "should: 分镜应优先强化人物状态变化、环境压迫感和规则后果的可视化，而不是额外补设定。",
            "avoid: 避免在 prompt 中偷偷解释上游没有写清的逻辑。",
        ],
    ),
)


episode_plot_judge_agent = Agent(
    name="episode_plot_judge_agent",
    model=MODEL,
    description="在 plot 生成后审逻辑、爽点兑现；在显式规则题材下另审 rule_execution_map 是否可执行。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "pass": bool,\n  "overall_score_1to10": int,\n  "plot_logic_ok": bool,\n  "viewer_payoff_delivered": bool,\n  "rules_not_decorative": bool,\n  "issues": [str],\n  "must_fix_for_plot": [str],\n  "summary": str\n}\n',
        constraints=[
            "只输出一个 JSON 对象。",
            "必须遵守用户 prompt 中的【题材能力开关】requires_rule_execution_map 与 uses_explicit_rules。",
            "必须对照输入的 episode_function（含 viewer_payoff_design）与 plot（含 acts、rule_execution_map、logic_check）。",
            "pass 仅当 overall_score_1to10>=8 且 hard 逻辑问题已排除：plot_logic_ok、viewer_payoff_delivered 均为 true；rules_not_decorative 按下列规则判定；issues 中无致命矛盾。",
            "若 requires_rule_execution_map=true：rule_execution_map 不得为空；若条目与 beats 脱节或规则仅为背景板，则 rules_not_decorative=false。",
            "若 requires_rule_execution_map=false：rule_execution_map 允许为空，此时 rules_not_decorative=true；若非空则仍须检查条目是否与 beats 对齐，否则 rules_not_decorative=false。",
            "若 viewer_payoff_design 中的爽点在节拍中未落地，viewer_payoff_delivered=false。",
            "must_fix_for_plot 须为中文、可执行，供下一轮重写 plot 使用；至少 0 条（通过时），不通过时至少 2 条。",
        ],
    ),
)


episode_package_judge_agent = Agent(
    name="episode_package_judge_agent",
    model=MODEL,
    description="在 storyboard 之后审整包：功能卡兑现、叙事落地、Seedance 可拍性与 prompt 质量。",
    instruction=_json_only_instruction(
        schema_hint='{\n  "pass": bool,\n  "overall_score_1to10": int,\n  "function_delivered": bool,\n  "narrative_not_hollow": bool,\n  "seedance_prompts_usable": bool,\n  "rules_and_clues_landed": bool,\n  "issues": [str],\n  "must_fix": [str],\n  "rewrite_scope": str,\n  "quality_judge": { "pass": bool, "reason": str, "overall_score_1to10": int }\n}\n',
        constraints=[
            "只输出一个 JSON 对象。",
            "输入包含整集：episode_function、plot、script、storyboard；须检查是否空谈、分镜是否可拍、seedance_video_prompt 是否只是复述而无画面执行。",
            "rewrite_scope 必须是以下之一：storyboard | script | plot ；storyboard=仅重分镜；script=剧本+分镜需重做；plot=从节拍起重做（下游全重跑）。",
            "quality_judge.pass 必须与顶层 pass 一致；quality_judge.reason 用 1-3 句中文概括；overall_score_1to10 与顶层一致。",
            "pass 仅当 overall_score_1to10>=8 且 function_delivered、narrative_not_hollow、seedance_prompts_usable、rules_and_clues_landed 均为 true。",
            "rules_and_clues_landed 判定：若【题材能力开关】requires_rule_execution_map=true，须检查 plot.rule_execution_map 与分镜是否落地；若为 false，则改为检查功能卡爽点、主线推进与关键线索/关系后果是否在 script+storyboard 中有可拍落地，不得因无规则表判失败。",
            "must_fix 为中文可执行项；不通过时至少 2 条。",
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


"""Shared model id, language policy, JSON extraction, and carry / gate schema constants."""

MODEL = "gemini-2.5-flash"

# --- production_carry_registry 深化版本（promise / relation / knowledge_fence）---
CARRY_PROMISE_SCHEMA_NOTE = "1.2"
CARRY_RELATION_SCHEMA_NOTE = "1.1"
CARRY_KNOWLEDGE_FENCE_SCHEMA_NOTE = "1.1"

PROMISE_STATUS_ENUM = frozenset({"open", "paid_off", "broken", "stale"})

RELATION_CURRENT_STATE_ENUM = frozenset(
    {
        "unknown",
        "aligned",
        "strained",
        "fractured",
        "dependent",
        "concealed_tension",
        "hostile",
        "unstable_alliance",
        "protector_dynamic",
    }
)

# 允许写入 relation 行的 pressure_tags（小写 snake）
PRESSURE_TAGS_VOCAB = frozenset(
    {
        "mistrust",
        "leverage",
        "debt",
        "dependence",
        "concealment",
        "betrayal_risk",
        "status_gap",
        "emotional_pull",
        "fear_link",
        "obligation",
        "split_loyalty",
        "co_presence",
    }
)

# 开放承诺超过 N 集未在任何结构化字段中出现 → stale
STALE_PROMISE_EPISODE_WINDOW = 5

# knowledge_fence 最小置信度词表（刷新用）
KNOWLEDGE_CONFIDENCE_ENUM = frozenset({"low", "medium", "high"})

# facts 生命周期（轻量；默认 active）
KNOWLEDGE_FACT_STATUS_ENUM = frozenset({"active", "superseded", "stale"})

# gate 失败趋势标签（规则式，供 query / dashboard）
GATE_FAILURE_TREND_LABEL_ENUM = frozenset(
    {
        "no_runs",
        "stable_pass",
        "first_failure",
        "repeated_same_failure",
        "shifted_failure_type",
        "recovered_after_failure",
        "intermittent_failures",
    }
)

# gate 编排提示（规则式）
RERUN_HINT_ENUM = frozenset(
    {
        "rerun_plot_only",
        "rerun_script_and_storyboard",
        "rerun_package_only",
        "rerun_episode_function_and_plot",
        "manual_review_first",
        "none",
    }
)

# 单集 gate 沉淀文件
GATE_ARTIFACT_SCHEMA_VERSION = "1.2"
GATE_ARTIFACT_FILENAME_LAYERED = "07_gate_artifacts.json"
GATE_ARTIFACT_FILENAME_FLAT = "gate_artifacts.json"


def _strict_json_only(text: str) -> str:
    """If the model wrapped JSON in prose, take the first `{` through the last `}`."""
    if "{" in text and "}" in text:
        return text[text.find("{") : text.rfind("}") + 1]
    return text


LANGUAGE_RULES = (
    "Language policy:\n"
    "- All creative text MUST be in Simplified Chinese (简体中文).\n"
    "- JSON keys remain in English, but ALL string values must be Chinese.\n"
    "- Do NOT output any English sentences in dialogue/narration/subtitle/visual.\n"
    "- Proper nouns can be English only when necessary (e.g., iPhone), otherwise Chinese.\n"
)

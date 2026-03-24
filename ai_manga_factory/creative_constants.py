"""Shared model id, language policy, and JSON extraction used by series_agents / run_series."""

MODEL = "gemini-2.5-flash"


def _strict_json_only(text: str) -> str:
    """If the model wrapped JSON in prose, take the first `{` through the last `}`."""
    if "{" in text and "}" in text:
        return text[text.find("{") : text.rfind("}") + 1]
    return text


LANGUAGE_RULES = (
    "Language policy:\n"
    "- All creative text MUST be in Simplified Chinese (中文简体).\n"
    "- JSON keys remain in English, but ALL string values must be Chinese.\n"
    "- Do NOT output any English sentences in dialogue/narration/subtitle/visual.\n"
    "- Proper nouns can be English only when necessary (e.g., iPhone), otherwise Chinese.\n"
)

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


PROJECT_ROOT = Path(__file__).resolve().parent
# 兼容包内 genres/ 与仓库根 genres/（后者便于 monorepo 或多包布局）
GENRE_REFERENCE_CANDIDATES = [
    PROJECT_ROOT / "genres" / "genre_reference.json",
    PROJECT_ROOT.parent / "genres" / "genre_reference.json",
]
# 最后一次成功加载的路径（便于排查是否静默退回 stub）
LAST_LOADED_GENRE_REFERENCE_PATH: Optional[Path] = None

# 与 JSON 中 capabilities 字段对齐；未知 genre 或缺字段时兜底
DEFAULT_CAPABILITIES: Dict[str, Any] = {
    "uses_explicit_rules": False,
    "requires_rule_execution_map": False,
    "requires_visible_rule_punishment": False,
    "has_hidden_mechanism": False,
    "prefers_logic_trial": False,
    "prefers_relationship_push": False,
    "prefers_status_hierarchy_conflict": False,
}


def genre_reference_resolve_order() -> list[str]:
    """文档化：题材库文件尝试顺序（先命中先使用）。"""
    return [str(p.resolve()) for p in GENRE_REFERENCE_CANDIDATES]


def _load_genre_reference() -> Dict[str, Any]:
    """
    读取顺序：
    1) <包目录>/genres/genre_reference.json（ai_manga_factory/genres/…）
    2) <包上级>/genres/genre_reference.json（仓库根 genres/…）
    皆不存在时退回内存 stub（等价于仅 general），此时 LAST_LOADED_GENRE_REFERENCE_PATH 为 None。
    """
    global LAST_LOADED_GENRE_REFERENCE_PATH
    for path in GENRE_REFERENCE_CANDIDATES:
        if path.is_file():
            LAST_LOADED_GENRE_REFERENCE_PATH = path
            return json.loads(path.read_text(encoding="utf-8"))
    LAST_LOADED_GENRE_REFERENCE_PATH = None
    return {
        "general": {
            "display_name": "通用",
            "id": "general",
            "keywords": [],
            "capabilities": dict(DEFAULT_CAPABILITIES),
            "rules_block": "【题材规则包：通用】\n- 保持逻辑自洽，禁止道具天降。\n- 叙事尽量口语化、有画面、少报告腔。\n",
        }
    }


def infer_genre_from_text(text: str) -> str:
    """基于 keywords 的粗粒度推断 genre key。"""
    if not isinstance(text, str):
        text = str(text or "")
    t = text.strip()
    if not t:
        return "general"

    ref = _load_genre_reference()
    best_key = "general"
    best_score = 0

    for key, entry in ref.items():
        keywords = entry.get("keywords", [])
        if not isinstance(keywords, list):
            continue
        score = sum(1 for kw in keywords if isinstance(kw, str) and kw and kw in t)
        if score > best_score:
            best_key = key
            best_score = score

    return best_key


def get_genre_capabilities(genre_key: str) -> Dict[str, Any]:
    """读取某题材的 capabilities，与 DEFAULT_CAPABILITIES 合并，保证布尔字段齐全。"""
    ref = _load_genre_reference()
    entry = ref.get(genre_key) or ref.get("general") or {}
    raw = entry.get("capabilities")
    if not isinstance(raw, dict):
        raw = {}
    out = dict(DEFAULT_CAPABILITIES)
    for k, v in raw.items():
        if k in DEFAULT_CAPABILITIES and isinstance(v, bool):
            out[k] = v
        elif k in DEFAULT_CAPABILITIES:
            out[k] = bool(v) if v is not None else DEFAULT_CAPABILITIES[k]
    return out


def capabilities_to_prompt_block(capabilities: Dict[str, Any]) -> str:
    """把能力开关转成固定格式的 prompt 前缀块，供各 agent 遵循。"""
    caps = dict(DEFAULT_CAPABILITIES)
    if isinstance(capabilities, dict):
        for k in DEFAULT_CAPABILITIES:
            if k in capabilities:
                caps[k] = bool(capabilities[k])

    lines = [
        "【题材能力开关】（须与下文创作约束一致；不要与题材规则包矛盾）",
        f"- current_capabilities.uses_explicit_rules: {caps['uses_explicit_rules']}",
        f"- current_capabilities.requires_rule_execution_map: {caps['requires_rule_execution_map']}",
        f"- current_capabilities.requires_visible_rule_punishment: {caps['requires_visible_rule_punishment']}",
        f"- current_capabilities.has_hidden_mechanism: {caps['has_hidden_mechanism']}",
        f"- current_capabilities.prefers_logic_trial: {caps['prefers_logic_trial']}",
        f"- current_capabilities.prefers_relationship_push: {caps['prefers_relationship_push']}",
        f"- current_capabilities.prefers_status_hierarchy_conflict: {caps['prefers_status_hierarchy_conflict']}",
    ]
    return "\n".join(lines) + "\n"


def infer_genre_context_for_prompt(prompt: str) -> Tuple[str, str, Dict[str, Any]]:
    """返回 (genre_key, rules_block, capabilities)。"""
    g = infer_genre_from_text(prompt)
    return g, get_genre_rules_block(g), get_genre_capabilities(g)


def get_genre_rules_block(genre_key: str) -> str:
    ref = _load_genre_reference()
    entry = ref.get(genre_key) or ref.get("general") or {}
    display_name = entry.get("display_name") or genre_key
    rules_body = entry.get("rules_block") or ""
    if not isinstance(rules_body, str):
        rules_body = ""

    frontmatter = entry.get("frontmatter")
    if not isinstance(frontmatter, dict):
        frontmatter = {}

    # 为避免“漏掉官网某些字段”，这里把除 auditDimensions 之外的 frontmatter 全量转成注入文本。
    # 注意：rules_block（md 正文）已经包含绝大多数禁忌/语言铁律/数值规则。
    meta_lines = []
    for k in sorted(frontmatter.keys()):
        if k == "auditDimensions":
            continue
        v = frontmatter.get(k)
        if v is None:
            continue
        if isinstance(v, bool):
            meta_lines.append(f"【{k}】" + ("启用" if v else "不强制"))
        elif isinstance(v, str):
            vv = v.strip()
            if vv:
                meta_lines.append(f"【{k}】{vv}")
        elif isinstance(v, list):
            # 列表太长就截断，避免 prompt 过长
            items = [str(x) for x in v if x is not None]
            if not items:
                continue
            if k == "fatigueWords":
                items = items[:60]
                meta_lines.append("【fatigueWords（尽量避免）】" + "、".join(items))
            else:
                items = items[:30]
                meta_lines.append(f"【{k}】" + "、".join(items))
        else:
            # 兜底：把复杂类型转字符串
            meta_lines.append(f"【{k}】{str(v).strip()}")

    meta_block = "\n".join(meta_lines).strip()
    if meta_block:
        meta_block = "\n" + meta_block + "\n"

    rules_body = rules_body.strip()
    return f"【题材规则包：{display_name}】{meta_block}{rules_body}\n"


def infer_genre_rules_for_prompt(prompt: str) -> Tuple[str, str]:
    """返回 (genre_key, rules_block) 方便上层注入 prompt。内部复用 infer_genre_context_for_prompt。"""
    g, rules_block, _caps = infer_genre_context_for_prompt(prompt)
    return g, rules_block

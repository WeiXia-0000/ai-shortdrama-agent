from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Tuple


PROJECT_ROOT = Path(__file__).resolve().parent
GENRE_REFERENCE_PATH = PROJECT_ROOT / "genres" / "genre_reference.json"


def _load_genre_reference() -> Dict[str, Any]:
    if not GENRE_REFERENCE_PATH.exists():
        return {
            "general": {
                "display_name": "通用",
                "id": "general",
                "keywords": [],
                "rules_block": "【题材规则包：通用】\n- 保持逻辑自洽，禁止道具天降。\n- 叙事尽量口语化、有画面、少报告腔。\n",
            }
        }
    return json.loads(GENRE_REFERENCE_PATH.read_text(encoding="utf-8"))


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
    """返回 (genre_key, rules_block) 方便上层注入 prompt。"""
    g = infer_genre_from_text(prompt)
    return g, get_genre_rules_block(g)


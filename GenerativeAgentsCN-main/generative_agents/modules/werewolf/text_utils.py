# 文件作用：纯文本处理工具：清洗 LLM 输出、模糊匹配候选项、拼接姓名列表。

import re
from typing import Iterable, Sequence


def clean_text(value: str, max_chars: int) -> str:
    """压缩空白、剥离前缀冒号、截断到 max_chars。"""
    text = re.sub(r"\s+", " ", str(value)).strip()
    text = re.sub(r"^.+?[：:]\s*", "", text) if len(text) < max_chars + 20 else text
    if len(text) > max_chars:
        text = text[:max_chars].rstrip("，。；、 ") + "。"
    return text or "我还需要再观察一下。"


def match_choice(value: str, choices: Sequence[str], fallback: str) -> str:
    """把 LLM 自由文本对齐到候选项之一；失败返回 fallback。"""
    text = str(value).strip()
    if text in choices:
        return text
    for choice in choices:
        if choice in text:
            return choice
    normalized = re.sub(r"\s+", "", text)
    for choice in choices:
        if re.sub(r"\s+", "", choice) == normalized:
            return choice
    return fallback


def join_names(names: Iterable[str]) -> str:
    return "、".join([name for name in names if name])

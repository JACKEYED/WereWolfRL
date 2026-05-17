# 文件作用：把 ReplayBuffer 转成 verl 训练管线可消费的 parquet 数据集。
#
# 设计要点：
#   - verl 的 GRPO 训练消费"每行 = 一个 (prompt, response, advantage, old_logprobs)"的 parquet
#   - 我们的 RLCollector 已经按 group 算好 advantage（同身份同座位 8 局），直接拍平到行
#   - 只保留 Qwen 那一座位的 step（有 logprobs），过滤掉 11 个 API 对手的 step
#   - GRPO 的 token-level loss 需要 old_logprobs / tokens 序列，我们从 last_call 抓到的就是
#
# 输出 schema（每行）：
#   prompt: str                  完整 system+user prompt
#   response: str                Qwen 实际输出的文本（已 strip think 标签）
#   tokens: list[str]            response 的 token 切分（vLLM 给的）
#   old_logprobs: list[float]    rollout 时 vLLM 给出的 per-token logprob
#   advantage: float             同 group 归一化后的 advantage
#   reward_episode: float        本局终奖（赢/输 ±1，再乘权重）
#   role: str                    Qwen 在这一局扮演的身份（werewolf/seer/...）
#   decision_type: str           speech / vote / skill / choice
#   cycle: int                   第几轮训练 cycle
#   group_idx: int               group 内第几局（0..group_size-1）

import os
from typing import Optional, Tuple

from modules.rl.buffer import ReplayBuffer


def buffer_to_parquet(
    buffer: ReplayBuffer,
    output_path: str,
    *,
    normalize_advantage: bool = True,
    drop_zero_advantage: bool = True,
    min_response_length: int = 1,
) -> Tuple[str, int, dict]:
    """把一个 ReplayBuffer 序列化成 verl 训练用 parquet。

    Args:
      buffer: collector 跑完一 cycle 的输出
      output_path: parquet 落盘路径
      normalize_advantage: group 内 (R - mean) / std 标准化
      drop_zero_advantage: 丢掉 advantage=0 的 step（如同组全平 → 无学习信号）
      min_response_length: 过滤掉 response 太短的样本（保险）

    Returns:
      (output_path, 行数, 统计 dict)
    """
    try:
        import pandas as pd
    except ImportError as e:
        raise RuntimeError(
            "需要 pandas + pyarrow 才能写 parquet。pip install pandas pyarrow"
        ) from e

    rows = []
    n_total = 0
    n_no_logprob = 0
    n_zero_adv = 0
    n_short = 0

    for item in buffer.iter_steps_with_advantage(normalize=normalize_advantage):
        n_total += 1
        step = item["step"]
        adv = item["advantage"]

        # 必须是 Qwen 的 step（有 logprob）
        logprobs = step.get("logprobs")
        tokens = step.get("tokens")
        if not logprobs or not tokens:
            n_no_logprob += 1
            continue

        # 跳过 zero advantage（同 group 全平，无学习信号）
        if drop_zero_advantage and abs(adv) < 1e-9:
            n_zero_adv += 1
            continue

        response = str(step.get("action", ""))
        if len(response) < min_response_length:
            n_short += 1
            continue

        rows.append({
            "prompt": step.get("prompt") or "",
            "response": response,
            "tokens": list(tokens),
            "old_logprobs": list(logprobs),
            "advantage": float(adv),
            "reward_episode": float(step.get("reward_episode", 0.0)),
            "reward_step": float(step.get("reward_step", 0.0)),
            "role": item["role"],
            "decision_type": str(step.get("decision_type", "")),
            "cycle": int(item["cycle"]),
            "group_idx": int(item["group_idx"]),
        })

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_parquet(output_path, index=False)

    stats = {
        "rows_written": len(rows),
        "rows_total": n_total,
        "dropped_no_logprob": n_no_logprob,
        "dropped_zero_advantage": n_zero_adv,
        "dropped_short_response": n_short,
        "advantage_mean": float(df["advantage"].mean()) if len(df) else 0.0,
        "advantage_std": float(df["advantage"].std()) if len(df) > 1 else 0.0,
    }
    return output_path, len(rows), stats


def verify_parquet(path: str) -> dict:
    """读回 parquet 做完整性 sanity check。"""
    import pandas as pd

    df = pd.read_parquet(path)
    required = {"prompt", "response", "tokens", "old_logprobs", "advantage"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"parquet 缺字段：{missing}")

    # 每条 tokens 长度 == old_logprobs 长度
    bad_pairs = 0
    for _, row in df.iterrows():
        if len(row["tokens"]) != len(row["old_logprobs"]):
            bad_pairs += 1
    if bad_pairs:
        raise ValueError(f"{bad_pairs} 行 tokens/old_logprobs 长度不一致")

    return {
        "rows": len(df),
        "advantage_mean": float(df["advantage"].mean()),
        "advantage_std": float(df["advantage"].std()) if len(df) > 1 else 0.0,
        "by_role": df.groupby("role").size().to_dict() if len(df) else {},
        "by_decision_type": df.groupby("decision_type").size().to_dict() if len(df) else {},
    }

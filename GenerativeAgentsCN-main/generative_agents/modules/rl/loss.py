# 文件作用：GRPO 损失的纯函数实现 + token-level mask 工具。
# 与 trl.GRPOTrainer 的核心数学等价；独立实现是为了让单元测试不依赖 trl + GPU。
# 真实训练会优先用 trl.GRPOTrainer，但其内部 loss 与这里一致。

from typing import Optional


def grpo_token_loss(
    new_logprobs,           # Tensor[T] 当前 policy 对 action tokens 的 logprob
    old_logprobs,           # Tensor[T] rollout 时 policy 的 logprob（detach）
    ref_logprobs,           # Tensor[T] reference model 的 logprob（detach）
    advantage: float,       # 标量：本 traj 的 group advantage
    clip_eps: float = 0.2,
    beta_kl: float = 0.04,
    mask=None,              # Tensor[T] 0/1 token mask（None 表示全部计算）
):
    """计算单条 trajectory（已扁平化 token）的 GRPO loss。

    数学：
      ratio       = exp(new_lp - old_lp)
      surrogate   = min(ratio * adv, clip(ratio, 1-eps, 1+eps) * adv)
      kl_to_ref   = new_lp - ref_lp                 # 单边近似（标准 GRPO 用对称 KL；trl 默认这个）
      loss_per_t  = -(surrogate - beta * kl_to_ref)
      loss        = mean(loss_per_t * mask)

    返回标量 tensor。需要 torch；非训练环境用 fakerunner.fake_grpo_loss 做规模测试。
    """
    import torch  # 局部导入，让 buffer/config 在没 torch 时也能跑

    new_logprobs = new_logprobs.float()
    old_logprobs = old_logprobs.float().detach()
    ref_logprobs = ref_logprobs.float().detach()

    ratio = torch.exp(new_logprobs - old_logprobs)
    surr1 = ratio * advantage
    surr2 = torch.clamp(ratio, 1.0 - clip_eps, 1.0 + clip_eps) * advantage
    surrogate = torch.min(surr1, surr2)

    kl = new_logprobs - ref_logprobs

    per_token = -(surrogate - beta_kl * kl)
    if mask is not None:
        per_token = per_token * mask
        denom = mask.sum().clamp(min=1.0)
        return per_token.sum() / denom
    return per_token.mean()


# ----- 不依赖 torch 的"纯 Python 镜像"，用于单元测试公式正确性 -----
def grpo_token_loss_py(
    new_logprobs, old_logprobs, ref_logprobs,
    advantage: float,
    clip_eps: float = 0.2,
    beta_kl: float = 0.04,
    mask: Optional[list] = None,
) -> float:
    """纯 Python 版 GRPO token loss，便于单测验数学，无需 torch。"""
    import math

    T = len(new_logprobs)
    assert len(old_logprobs) == T == len(ref_logprobs)
    losses = []
    weights = []
    for t in range(T):
        ratio = math.exp(new_logprobs[t] - old_logprobs[t])
        surr1 = ratio * advantage
        surr2 = max(min(ratio, 1.0 + clip_eps), 1.0 - clip_eps) * advantage
        surrogate = min(surr1, surr2)
        kl = new_logprobs[t] - ref_logprobs[t]
        loss = -(surrogate - beta_kl * kl)
        w = 1.0 if mask is None else float(mask[t])
        losses.append(loss * w)
        weights.append(w)
    total_w = sum(weights) or 1.0
    return sum(losses) / total_w

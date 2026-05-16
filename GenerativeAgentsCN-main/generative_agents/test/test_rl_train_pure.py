# 文件作用：RL 训练管线纯模块测试（不依赖 torch / transformers / vLLM）。
# 跑法：cd generative_agents && python -m pytest test/test_rl_train_pure.py -v

import math
import os
import tempfile

import pytest

from modules.rl.buffer import (
    GroupRecord, ReplayBuffer,
    compute_total_reward_for_qwen, extract_qwen_steps,
)
from modules.rl.config import RLConfig
from modules.rl.loss import grpo_token_loss_py


# =========================================================================
# RLConfig
# =========================================================================
class TestRLConfig:
    def test_defaults_sane(self):
        cfg = RLConfig()
        assert cfg.group_size >= 2
        assert cfg.groups_per_role >= 1
        assert len(cfg.roles) == 6
        assert "werewolf" in cfg.roles
        assert cfg.scene_mode == "game"
        assert 0 < cfg.beta_kl < 1
        assert 0 < cfg.clip_eps < 1


# =========================================================================
# GroupRecord & advantage
# =========================================================================
class TestGroupRecord:
    def _make(self, rewards):
        return GroupRecord(role="werewolf", seat="陈砚秋",
                           rewards=rewards,
                           qwen_steps_per_game=[[{"action": "x"}] for _ in rewards])

    def test_size(self):
        assert self._make([1, 2, 3]).size == 3

    def test_advantage_normalize(self):
        g = self._make([1.0, 2.0, 3.0])
        advs = g.advantages(normalize=True)
        # 均值 2，标准差 sqrt(2/3) ≈ 0.8165
        assert abs(sum(advs)) < 1e-6
        assert advs[0] < 0 < advs[2]

    def test_advantage_no_normalize(self):
        g = self._make([1.0, 2.0, 3.0])
        advs = g.advantages(normalize=False)
        assert advs == [-1.0, 0.0, 1.0]

    def test_advantage_zero_variance(self):
        g = self._make([1.0, 1.0, 1.0])
        advs = g.advantages(normalize=True)
        assert advs == [0.0, 0.0, 0.0]

    def test_empty_rewards(self):
        g = GroupRecord(role="r", seat="s", rewards=[], qwen_steps_per_game=[])
        assert g.advantages() == []


# =========================================================================
# ReplayBuffer
# =========================================================================
class TestReplayBuffer:
    def _group(self, role="werewolf", rewards=(1.0, 2.0, 3.0)):
        return GroupRecord(role=role, seat="s",
                           rewards=list(rewards),
                           qwen_steps_per_game=[
                               [{"action": f"a{i}", "reward_step": 0, "reward_episode": 0, "obs": {}}]
                               for i, _ in enumerate(rewards)
                           ])

    def test_push_and_len(self):
        buf = ReplayBuffer()
        buf.push(self._group())
        buf.push(self._group())
        assert len(buf) == 2

    def test_iter_steps_with_advantage(self):
        buf = ReplayBuffer()
        buf.push(self._group(rewards=[0.0, 4.0]))
        items = list(buf.iter_steps_with_advantage(normalize=False))
        assert len(items) == 2
        # 一个 reward 在 mean 之下 → advantage 负；另一个正
        advs = sorted(i["advantage"] for i in items)
        assert advs[0] < 0 < advs[1]

    def test_stats(self):
        buf = ReplayBuffer()
        buf.push(self._group("werewolf", [1.0, 1.0]))     # zero variance
        buf.push(self._group("seer", [0.5, 1.5, 2.5]))
        s = buf.stats()
        assert s["groups"] == 2
        assert s["zero_variance_groups"] == 1
        assert "werewolf" in s["rewards_by_role"]
        assert "seer" in s["rewards_by_role"]

    def test_save_load_roundtrip(self):
        buf = ReplayBuffer()
        buf.push(self._group())
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "b.json")
            buf.save(path)
            loaded = ReplayBuffer.load(path)
            assert len(loaded) == 1
            assert loaded.groups[0].role == "werewolf"
            assert loaded.groups[0].rewards == [1.0, 2.0, 3.0]


# =========================================================================
# 抽取 Qwen steps & 累计 reward
# =========================================================================
class TestExtractQwenSteps:
    def test_from_dict(self):
        td = {"steps": [
            {"agent": "陈砚秋", "action": "x"},
            {"agent": "苏蘅", "action": "y"},
            {"agent": "陈砚秋", "action": "z"},
        ]}
        out = extract_qwen_steps(td, "陈砚秋")
        assert len(out) == 2
        assert all(s["agent"] == "陈砚秋" for s in out)


class TestComputeTotalReward:
    def test_step_plus_win_bonus(self):
        steps = [
            {"reward_step": 0.1, "reward_episode": 0.0, "obs": {}},
            {"reward_step": 0.2, "reward_episode": 1.0, "obs": {}},
        ]
        r = compute_total_reward_for_qwen(steps, win_bonus_weight=5.0)
        # 0.1 + 0.2 + 5*1.0 = 5.3
        assert abs(r - 5.3) < 1e-6

    def test_shaping_weights_applied(self):
        steps = [{"reward_step": 0, "reward_episode": 0,
                  "obs": {"format_ok": True, "mentions_player": False}}]
        r = compute_total_reward_for_qwen(
            steps, win_bonus_weight=0,
            shaping_weights={"format_ok": 0.05, "mentions_player": 0.05},
        )
        # 只有 format_ok 是 True → +0.05
        assert abs(r - 0.05) < 1e-6


# =========================================================================
# GRPO loss 数学（纯 Python 镜像）
# =========================================================================
class TestGRPOLossPy:
    def test_zero_kl_no_clip(self):
        # new == old，ratio=1，surrogate=adv，kl=0；loss = -adv
        T = 3
        new = [0.0] * T
        old = [0.0] * T
        ref = [0.0] * T
        loss = grpo_token_loss_py(new, old, ref, advantage=2.0, beta_kl=0.0)
        assert abs(loss - (-2.0)) < 1e-9

    def test_kl_penalty_when_diverged(self):
        # new != ref → kl > 0 → loss 增大
        new = [-1.0, -1.0]
        old = [-1.0, -1.0]
        ref = [-2.0, -2.0]
        loss = grpo_token_loss_py(new, old, ref, advantage=0.0, beta_kl=0.1)
        # surrogate=0；kl = (-1) - (-2) = 1；loss = beta * kl = 0.1
        assert abs(loss - 0.1) < 1e-6

    def test_clipping_when_ratio_large(self):
        # new >> old → ratio 远大于 1+eps → 被 clip
        new = [1.0]
        old = [0.0]
        ref = [0.0]
        adv = 1.0
        # ratio = e^1 ≈ 2.718；eps=0.2 → clipped at 1.2
        # surr2 = 1.2 * 1.0 = 1.2；surr1 = 2.718 * 1.0 = 2.718
        # min(surr1, surr2) = 1.2；loss = -1.2 + 0 = -1.2
        loss = grpo_token_loss_py(new, old, ref, advantage=adv, beta_kl=0.0, clip_eps=0.2)
        assert abs(loss - (-1.2)) < 1e-6

    def test_negative_advantage_inverts(self):
        # adv < 0 时 min(surr1, surr2) 取的是更大的那个（绝对值更大的负数）
        # 公式仍是 -surrogate → loss > 0，鼓励降低这条 trajectory 的概率
        loss = grpo_token_loss_py([0.0], [0.0], [0.0], advantage=-1.0, beta_kl=0.0)
        assert loss > 0

    def test_mask_zeros_token(self):
        new = [0.0, 1.0]
        old = [0.0, 0.0]
        ref = [0.0, 0.0]
        masked = grpo_token_loss_py(new, old, ref, advantage=1.0, beta_kl=0.0, mask=[1, 0])
        # 只计第一个 token：ratio=1, surr=1, loss=-1
        assert abs(masked - (-1.0)) < 1e-6

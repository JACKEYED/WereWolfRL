# 文件作用：verl 集成的纯模块测试。
# 不依赖 verl / vLLM / torch；只测 buffer → parquet 转换 + verl_trainer 配置生成。
# 跑法：cd generative_agents && python -m pytest test/test_rl_verl.py -v

import os
import tempfile

import pytest

# 这两个依赖在 requirements-rl.txt 里；test 时如果没装就 skip
pandas = pytest.importorskip("pandas")
pyarrow = pytest.importorskip("pyarrow")

from modules.rl.buffer import GroupRecord, ReplayBuffer
from modules.rl.verl_dataset import buffer_to_parquet, verify_parquet


def _mk_qwen_step(action="刀 苏蘅，他白天信息太多", with_logprobs=True, reward_episode=0.0):
    base = {
        "step_id": 0,
        "agent": "陈砚秋",
        "phase": "第1天 夜晚",
        "day": 1,
        "decision_type": "skill",
        "obs": {"my_role": "werewolf"},
        "candidates": ["苏蘅", "周文卿"],
        "action": action,
        "reward_step": 0.1,
        "reward_episode": reward_episode,
        "prompt": "你是狼人 ……（完整 prompt）",
        "logprobs": [-0.5, -0.3, -1.2, -0.8, -0.4, -0.6, -0.9] if with_logprobs else None,
        "tokens": ["刀", " ", "苏蘅", "，", "他", "白天", "信息"] if with_logprobs else None,
    }
    return base


def _mk_api_step(action="我倾向于投陈砚秋"):
    """对手座位（非 Qwen）的 step，没有 logprobs → 应当被 parquet 过滤。"""
    step = _mk_qwen_step(action=action, with_logprobs=False)
    step["agent"] = "苏蘅"
    return step


def _mk_group(rewards, steps_per_game):
    return GroupRecord(
        role="werewolf", seat="陈砚秋",
        rewards=list(rewards),
        qwen_steps_per_game=list(steps_per_game),
        cycle=0,
    )


# =========================================================================
# buffer_to_parquet
# =========================================================================
class TestBufferToParquet:
    def test_basic_roundtrip(self):
        buf = ReplayBuffer()
        buf.push(_mk_group(
            rewards=[1.0, 2.0, 3.0],
            steps_per_game=[[_mk_qwen_step()] for _ in range(3)],
        ))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.parquet")
            out_path, n, stats = buffer_to_parquet(buf, path)
            assert out_path == path
            assert n == 3
            assert stats["rows_written"] == 3
            df = pandas.read_parquet(path)
            assert list(df.columns) >= [
                "prompt", "response", "tokens", "old_logprobs",
                "advantage", "reward_episode", "role", "decision_type",
            ]

    def test_filters_steps_without_logprobs(self):
        """API 对手 step（无 logprobs）应该被过滤。"""
        buf = ReplayBuffer()
        # 每局 1 个 Qwen step + 1 个 API step
        buf.push(_mk_group(
            rewards=[1.0, 2.0],
            steps_per_game=[
                [_mk_qwen_step(), _mk_api_step()],
                [_mk_qwen_step(), _mk_api_step()],
            ],
        ))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.parquet")
            _, n, stats = buffer_to_parquet(buf, path)
            assert n == 2  # 只留 Qwen step
            assert stats["dropped_no_logprob"] == 2

    def test_filters_zero_advantage(self):
        """同 group 全部 reward 相同 → advantage=0 → 默认丢弃。"""
        buf = ReplayBuffer()
        buf.push(_mk_group(
            rewards=[1.0, 1.0, 1.0],
            steps_per_game=[[_mk_qwen_step()] for _ in range(3)],
        ))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.parquet")
            _, n, stats = buffer_to_parquet(buf, path)
            assert n == 0
            assert stats["dropped_zero_advantage"] == 3

    def test_advantage_normalized(self):
        buf = ReplayBuffer()
        buf.push(_mk_group(
            rewards=[1.0, 2.0, 3.0],
            steps_per_game=[[_mk_qwen_step()] for _ in range(3)],
        ))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.parquet")
            buffer_to_parquet(buf, path, normalize_advantage=True)
            df = pandas.read_parquet(path)
            # 三条 advantage 应该零均
            assert abs(df["advantage"].mean()) < 1e-6

    def test_filters_short_response(self):
        buf = ReplayBuffer()
        empty_step = _mk_qwen_step(action="")
        buf.push(_mk_group(
            rewards=[1.0, 2.0, 3.0],
            steps_per_game=[[empty_step] for _ in range(3)],
        ))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.parquet")
            _, n, stats = buffer_to_parquet(buf, path, min_response_length=1)
            assert n == 0
            assert stats["dropped_short_response"] == 3


# =========================================================================
# verify_parquet
# =========================================================================
class TestVerifyParquet:
    def test_passes_for_valid(self):
        buf = ReplayBuffer()
        buf.push(_mk_group(
            rewards=[1.0, 2.0, 3.0],
            steps_per_game=[[_mk_qwen_step()] for _ in range(3)],
        ))
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.parquet")
            buffer_to_parquet(buf, path)
            stats = verify_parquet(path)
            assert stats["rows"] == 3
            assert "werewolf" in stats["by_role"]

    def test_detects_token_logprob_mismatch(self):
        """构造一条 tokens / old_logprobs 长度对不上的 parquet，应当报 ValueError。"""
        bad = pandas.DataFrame([{
            "prompt": "p",
            "response": "r",
            "tokens": ["a", "b", "c"],
            "old_logprobs": [-0.5, -0.3],  # 少一个
            "advantage": 1.0,
            "reward_episode": 0.0,
            "reward_step": 0.0,
            "role": "werewolf",
            "decision_type": "skill",
            "cycle": 0,
            "group_idx": 0,
        }])
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bad.parquet")
            bad.to_parquet(path, index=False)
            with pytest.raises(ValueError, match="长度不一致"):
                verify_parquet(path)


# =========================================================================
# VerlGRPOAdapter 配置生成
# =========================================================================
class TestVerlConfigBuild:
    def test_builds_cycle_config(self):
        yaml = pytest.importorskip("yaml")
        from modules.rl.config import RLConfig
        from modules.rl.verl_trainer import VerlGRPOAdapter

        # 现成模板
        template_path = os.path.join("configs", "verl_grpo.yaml")
        if not os.path.exists(template_path):
            pytest.skip("configs/verl_grpo.yaml 不存在（被移动了？）")

        cfg = RLConfig(
            base_model="Qwen/Qwen2.5-7B-Instruct",
            learning_rate=3e-6,
            beta_kl=0.05,
            clip_eps=0.15,
            lora_rank=32,
            lora_alpha=64,
            epochs_per_buffer=2,
            output_dir="results/rl_test",
            wandb_project="test-proj",
        )
        adapter = VerlGRPOAdapter(cfg, base_config_path=template_path)
        result = adapter._build_cycle_config("/tmp/sample.parquet", cycle=5)

        assert result["data"]["train_files"] == ["/tmp/sample.parquet"]
        assert result["actor_rollout_ref"]["model"]["path"] == "Qwen/Qwen2.5-7B-Instruct"
        assert result["actor_rollout_ref"]["actor"]["optim"]["lr"] == 3e-6
        assert result["actor_rollout_ref"]["actor"]["lora_rank"] == 32
        assert result["actor_rollout_ref"]["actor"]["lora_alpha"] == 64
        assert result["grpo"]["kl_coef"] == 0.05
        assert result["grpo"]["clip_ratio"] == 0.15
        assert result["trainer"]["total_epochs"] == 2
        assert "cycle_005" in result["trainer"]["default_local_dir"]
        assert result["trainer"]["project_name"] == "test-proj"

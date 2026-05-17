"""
完整一轮 GRPO 训练 Demo：不跳过任何步骤。

用法:
    1. 启动 vLLM（Qwen 座位推理 + 获取 logprobs）:
       vllm serve Qwen/Qwen2.5-7B-Instruct --port 8001 \
           --enable-lora --enable-lora-hot-swap --max-lora-rank 64

    2. 确保 data/config.json 配置了 DeepSeek API（其他 11 个座位用）

    3. 运行:
       cd generative_agents
       python ../demo/end_to_end_demo.py

需要:
    - vLLM 服务在 127.0.0.1:8001
    - data/config.json 里配置了有效的 LLM API
    - verl 已安装: pip install verl
    - GPU (至少 1×A100 80G 用于 verl 训练)
"""

# TODO 待测试
import os
import sys

_PROJ_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SRC_DIR = os.path.join(_PROJ_DIR, "GenerativeAgentsCN-main", "generative_agents")
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)
os.chdir(_SRC_DIR)

from modules.rl.config import RLConfig
from modules.rl.collector import RLCollector
from modules.rl.verl_dataset import buffer_to_parquet, verify_parquet
from modules.rl.verl_trainer import VerlGRPOAdapter, hot_swap_lora_to_vllm


# =============================================================================
# 配置
# =============================================================================

def build_config() -> RLConfig:
    return RLConfig(
        # ── Phase A: 采集 ──
        group_size=8,               # 每组 8 局并行（同身份同座位）
        groups_per_role=20,          # 每个身份 20 组
        roles=["werewolf", "seer", "witch", "hunter", "guard", "villager"],
        collection_workers=8,
        scene_mode="game",           # RL 训练用 game 模式（纯狼人杀）
        seed_base=42,

        # ── Phase C: verl 训练 ──
        epochs_per_buffer=4,
        learning_rate=5e-6,
        beta_kl=0.04,
        clip_eps=0.2,
        lora_rank=64,
        lora_alpha=128,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        max_prompt_length=4096,
        max_completion_length=512,

        # ── 模型 ──
        base_model="Qwen/Qwen2.5-7B-Instruct",
        vllm_endpoint="http://127.0.0.1:8001/v1",
        qwen_seat_provider="vllm",
        opponent_provider="openai",
        use_llm=True,               # ★ 真实 LLM 调用

        # ── Reward ──
        reward_episode=5.0,          # 终奖权重
        reward_format=0.05,          # JSON 格式加分
        reward_mention=0.05,         # 提到玩家名加分
        reward_cite=0.05,            # 引用事件加分

        # ── 循环 ──
        num_cycles=1,
        output_dir="results/rl_demo",
        wandb_project="",
    )


# =============================================================================
# 主流程
# =============================================================================

def main():
    cfg = build_config()
    total_games = cfg.group_size * cfg.groups_per_role * len(cfg.roles)
    print(f"完整一轮 GRPO 训练 Demo")
    print(f"  身份: {cfg.roles}")
    print(f"  每组 {cfg.group_size} 局 × {cfg.groups_per_role} 组 × {len(cfg.roles)} 身份"
          f" = {total_games} 局")
    print(f"  Qwen 座位: vLLM @ {cfg.vllm_endpoint}")
    print(f"  对手座位: API ({cfg.opponent_provider})")
    print()

    # =========================================================================
    # Phase A: 采集
    # =========================================================================
    print("=" * 60)
    print("Phase A: 并行采集游戏数据")
    print("=" * 60)

    collector = RLCollector(cfg)
    buf = collector.collect_cycle(cycle=0)

    stats = buf.stats()
    print(f"  采集完毕:")
    print(f"    groups: {stats['groups']}, steps: {stats['total_steps']}")
    print(f"    reward mean: {stats['reward_mean']:.3f}, "
          f"min: {stats['reward_min']:.3f}, max: {stats['reward_max']:.3f}")
    print(f"    零方差 groups: {stats['zero_variance_groups']}")

    # 保存 buffer
    os.makedirs(os.path.join(cfg.output_dir, "buffers"), exist_ok=True)
    buf.save(os.path.join(cfg.output_dir, "buffers", "cycle_000.json"))

    # =========================================================================
    # Phase B: Buffer → Parquet
    # =========================================================================
    print("\n" + "=" * 60)
    print("Phase B: Buffer → Parquet")
    print("=" * 60)

    os.makedirs(os.path.join(cfg.output_dir, "parquets"), exist_ok=True)
    parquet_path = os.path.join(cfg.output_dir, "parquets", "cycle_000.parquet")

    _, n_rows, conv_stats = buffer_to_parquet(buf, parquet_path)
    print(f"  转换完毕: {n_rows} 行 → {parquet_path}")
    print(f"  过滤: 无logprob={conv_stats['dropped_no_logprob']}, "
          f"零优势={conv_stats['dropped_zero_advantage']}, "
          f"短响应={conv_stats['dropped_short_response']}")

    if n_rows == 0:
        print("  ERROR: parquet 为空，检查 vLLM 是否正常返回 logprobs")
        return 1

    verify_stats = verify_parquet(parquet_path)
    print(f"  校验通过: rows={verify_stats['rows']}, "
          f"adv_mean={verify_stats['advantage_mean']:.4f}, "
          f"by_role={verify_stats['by_role']}")

    # =========================================================================
    # Phase C: verl GRPO 训练
    # =========================================================================
    print("\n" + "=" * 60)
    print("Phase C: verl GRPO 训练")
    print("=" * 60)

    yaml_template = os.path.join("configs", "verl_grpo.yaml")
    if not os.path.exists(yaml_template):
        print(f"  ERROR: {yaml_template} 不存在")
        return 1

    adapter = VerlGRPOAdapter(cfg, base_config_path=yaml_template)
    result = adapter.train_one_cycle(parquet_path, cycle=0, dry=False)

    lora_path = result["lora_path"]
    print(f"  训练完毕: LoRA → {lora_path}")

    # =========================================================================
    # Phase D: vLLM Hot-Swap
    # =========================================================================
    print("\n" + "=" * 60)
    print("Phase D: vLLM LoRA 热切换")
    print("=" * 60)

    hot_swap_lora_to_vllm(lora_path, cfg.vllm_endpoint, adapter_name="current")
    print(f"  完成: 新 LoRA 已加载到 vLLM")

    # =========================================================================
    print("\n" + "=" * 60)
    print("一轮完整训练完成")
    print(f"  Parquet:  {os.path.abspath(parquet_path)}")
    print(f"  LoRA:     {os.path.abspath(lora_path)}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())

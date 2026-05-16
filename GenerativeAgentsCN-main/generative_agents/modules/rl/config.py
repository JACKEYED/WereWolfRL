# 文件作用：GRPO 训练的超参数集中定义，方便从 YAML / CLI 注入。

from dataclasses import dataclass, field
from typing import List


@dataclass
class RLConfig:
    # ─── 采集（Phase A） ─────────────────────────────────────────
    group_size: int = 8                   # 每个 group 起 N 局并行（同身份同座位）
    groups_per_role: int = 20             # 每个身份采几个 group
    roles: List[str] = field(default_factory=lambda: [
        "werewolf", "seer", "witch", "hunter", "guard", "villager"
    ])
    # 训练 Qwen 扮演的座位：每个 group 随机抽一个；空表示全 12 座位都参与
    seat_pool: List[str] = field(default_factory=list)
    collection_workers: int = 8           # 同时跑多少局（≥group_size 才能一波采完一个 group）
    scene_mode: str = "game"              # v1 训练用 game 模式
    seed_base: int = 0                    # cycle k 的 game seed = seed_base + cycle*10000 + idx

    # ─── 训练（Phase B） ─────────────────────────────────────────
    epochs_per_buffer: int = 4            # 同一 buffer 训几个 epoch
    learning_rate: float = 5e-6
    beta_kl: float = 0.04                 # KL ref penalty
    clip_eps: float = 0.2                 # GRPO ratio clip
    advantage_norm: bool = True           # group 内 (R - mean) / std
    max_prompt_length: int = 4096
    max_completion_length: int = 512
    lora_rank: int = 64
    lora_alpha: int = 128
    lora_dropout: float = 0.05
    target_modules: List[str] = field(default_factory=lambda: [
        "q_proj", "k_proj", "v_proj", "o_proj",
    ])

    # ─── 模型 ───────────────────────────────────────────────────
    base_model: str = "Qwen/Qwen2.5-7B-Instruct"
    vllm_endpoint: str = "http://127.0.0.1:8001/v1"  # 在哪儿 serve Qwen（actor）
    qwen_seat_provider: str = "vllm"      # Qwen 那一座位的 LLM provider
    opponent_provider: str = "openai"     # 其他 11 座的 provider（DeepSeek 等）
    use_llm: bool = True                  # dry-run 时设 False，所有 agent 走 fallback

    # ─── Reward shaping ─────────────────────────────────────────
    reward_format: float = 0.05           # 输出能解析为合规 JSON 加分
    reward_mention: float = 0.05          # 提到至少一个在场玩家名加分
    reward_cite: float = 0.05             # 引用 public_log 里的具体事件加分
    reward_episode: float = 5.0           # 局末胜负权重（×5 让 sparse 信号强势）

    # ─── 训练循环 ───────────────────────────────────────────────
    num_cycles: int = 30
    eval_games: int = 30
    eval_every: int = 1
    output_dir: str = "results/rl"
    wandb_project: str = "jiangnan-werewolf-grpo"
    wandb_run_name: str = ""

    def __post_init__(self):
        if self.collection_workers < self.group_size:
            # 不够 worker 一波采完一组：会顺次跑，慢但能跑
            pass

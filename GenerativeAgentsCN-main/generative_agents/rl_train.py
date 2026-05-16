# 文件作用：RL 训练 CLI 入口。
# 用法：
#   # 1. 先 host 一个 vLLM（actor）：
#   vllm serve Qwen/Qwen2.5-7B-Instruct --port 8001
#
#   # 2. 跑 dry-run（无需 GPU、不真训，仅走通 collect→pack→metric 链路；适合本地调通）
#   python rl_train.py --dry --cycles 1 --groups-per-role 1 --group-size 2
#
#   # 3. 真训（需 torch + transformers + peft + trl + 实际 vLLM endpoint）
#   python rl_train.py --cycles 30 --groups-per-role 20 --group-size 8

import argparse
import json
import os
import sys
from datetime import datetime

try:
    from dotenv import find_dotenv, load_dotenv
except ImportError:
    # dotenv 可选；缺失时跳过 .env 加载
    def find_dotenv(): return ""
    def load_dotenv(*a, **k): return False


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(find_dotenv())

    parser = argparse.ArgumentParser(description="GRPO 训练入口（v1 纯狼人杀）")
    parser.add_argument("--dry", action="store_true", help="dry-run：跑数据流但不更新模型")
    parser.add_argument("--cycles", type=int, default=30)
    parser.add_argument("--group-size", type=int, default=8)
    parser.add_argument("--groups-per-role", type=int, default=20)
    parser.add_argument("--collection-workers", type=int, default=8)
    parser.add_argument("--epochs-per-buffer", type=int, default=4)
    parser.add_argument("--lr", type=float, default=5e-6)
    parser.add_argument("--beta-kl", type=float, default=0.04)
    parser.add_argument("--clip-eps", type=float, default=0.2)
    parser.add_argument("--base-model", type=str, default="Qwen/Qwen2.5-7B-Instruct")
    parser.add_argument("--vllm-endpoint", type=str, default="http://127.0.0.1:8001/v1")
    parser.add_argument("--output-dir", type=str, default="results/rl")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--wandb-project", type=str, default="")
    parser.add_argument(
        "--roles", type=str, default="werewolf,seer,witch,hunter,guard,villager",
        help="逗号分隔；每个 role 都会被 groups_per_role 次采集",
    )
    args = parser.parse_args()

    from modules.rl.config import RLConfig
    from modules.rl.collector import RLCollector
    from modules.rl.trainer import GRPOTrainer

    cfg = RLConfig(
        group_size=args.group_size,
        groups_per_role=args.groups_per_role,
        roles=[r.strip() for r in args.roles.split(",") if r.strip()],
        collection_workers=args.collection_workers,
        epochs_per_buffer=args.epochs_per_buffer,
        learning_rate=args.lr,
        beta_kl=args.beta_kl,
        clip_eps=args.clip_eps,
        base_model=args.base_model,
        vllm_endpoint=args.vllm_endpoint,
        output_dir=args.output_dir,
        num_cycles=args.cycles,
        seed_base=args.seed,
        wandb_project=args.wandb_project,
        scene_mode="game",       # v1 强制 game 模式
        use_llm=not args.dry,    # dry 模式所有 agent 走 fallback，不调任何 LLM
    )

    print(f"[rl_train] mode={'dry' if args.dry else 'real'} | "
          f"cycles={cfg.num_cycles} | group={cfg.group_size} × {cfg.groups_per_role}/role × {len(cfg.roles)} roles")
    print(f"[rl_train] 每 cycle 约采集 {cfg.group_size * cfg.groups_per_role * len(cfg.roles)} 局")

    collector = RLCollector(cfg)
    trainer = GRPOTrainer(cfg, mode="dry" if args.dry else "real")

    # wandb 可选
    wandb = None
    if cfg.wandb_project and not args.dry:
        try:
            import wandb as _wb
            wandb = _wb.init(
                project=cfg.wandb_project,
                name=cfg.wandb_run_name or f"grpo-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
                config=cfg.__dict__,
            )
        except ImportError:
            print("[rl_train] 未装 wandb，跳过 wandb 日志")

    for cycle in range(cfg.num_cycles):
        print(f"\n========== Cycle {cycle} / {cfg.num_cycles - 1} ==========")
        # Phase A: collect
        print(f"[cycle {cycle}] Phase A 采集中…")
        buf = collector.collect_cycle(cycle)
        trainer.save_buffer(buf, cycle)
        stats = buf.stats()
        print(f"[cycle {cycle}] 采集完毕：{stats['groups']} groups, "
              f"reward_mean={stats.get('reward_mean', 0):.3f}, "
              f"zero_var={stats.get('zero_variance_groups', 0)}")

        # Phase B: train
        print(f"[cycle {cycle}] Phase B {'dry-run' if args.dry else '训练中'}…")
        metrics = trainer.train_on_buffer(buf, cycle)
        trainer.save_metrics(metrics, cycle)
        print(f"[cycle {cycle}] 完毕：samples={metrics['samples']}, "
              f"with_logprobs={metrics.get('samples_with_logprobs', 0)}")

        if wandb is not None:
            wandb.log({**{f"cycle/{k}": v for k, v in stats.items() if isinstance(v, (int, float))},
                       "cycle": cycle})

    print("\n[rl_train] 全部 cycle 完成。")
    if not args.dry:
        print(f"LoRA 权重在：{os.path.join(cfg.output_dir, 'cycle_*/')}")
    print(f"Buffer + metrics 在：{cfg.output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

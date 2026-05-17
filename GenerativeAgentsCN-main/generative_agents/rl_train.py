# 文件作用：RL 训练主入口。每 cycle 闭环：
#   1. RLCollector 并行起 N 局，收 trajectory（Phase A）
#   2. ReplayBuffer → parquet（Phase B）
#   3. VerlGRPOAdapter 调 verl 跑 GRPO 训练，输出新 LoRA（Phase C）
#   4. hot_swap_lora_to_vllm 把新 LoRA 推到 vLLM serving 端（Phase D）
#   5. 进入下一 cycle，新一轮 rollout 用更新后的 Qwen
#
# 用法：
#   # 1. 启 vLLM（带 LoRA hot-swap）：
#   vllm serve Qwen/Qwen2.5-7B-Instruct --port 8001 \
#       --enable-lora --enable-lora-hot-swap --max-lora-rank 64
#
#   # 2. dry-run（无 GPU、不真训，只走 collect → parquet → verl_dry）
#   python rl_train.py --dry --cycles 1 --groups-per-role 1 --group-size 2
#
#   # 3. 真训
#   pip install -r requirements-rl.txt
#   python rl_train.py --cycles 30 --groups-per-role 20 --group-size 8

import argparse
import os
import sys
from datetime import datetime

try:
    from dotenv import find_dotenv, load_dotenv
except ImportError:
    def find_dotenv(): return ""
    def load_dotenv(*a, **k): return False


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    load_dotenv(find_dotenv())

    parser = argparse.ArgumentParser(description="GRPO 训练入口（v1 纯狼人杀 + verl backend）")
    parser.add_argument("--dry", action="store_true",
                        help="dry-run：只跑 collect→parquet 链路，不真调 verl/vLLM")
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
        help="逗号分隔",
    )
    parser.add_argument(
        "--verl-config", type=str, default="configs/verl_grpo.yaml",
        help="verl 训练配置模板",
    )
    parser.add_argument(
        "--skip-hot-swap", action="store_true",
        help="不要在训练完后推 LoRA 到 vLLM（用于离线 batch 训练）",
    )
    args = parser.parse_args()

    from modules.rl.config import RLConfig
    from modules.rl.collector import RLCollector
    from modules.rl.verl_dataset import buffer_to_parquet, verify_parquet
    from modules.rl.verl_trainer import VerlGRPOAdapter, hot_swap_lora_to_vllm

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
        use_llm=not args.dry,    # dry 走 fallback 不调 LLM
    )

    print(f"[rl_train] mode={'dry' if args.dry else 'real(verl)'} | "
          f"cycles={cfg.num_cycles} | group={cfg.group_size} × {cfg.groups_per_role}/role × {len(cfg.roles)} roles",
          flush=True)
    print(f"[rl_train] 每 cycle 约采集 {cfg.group_size * cfg.groups_per_role * len(cfg.roles)} 局", flush=True)
    if not args.dry:
        print(f"[rl_train] verl 配置：{args.verl_config}", flush=True)
        print(f"[rl_train] vLLM endpoint：{args.vllm_endpoint}", flush=True)

    collector = RLCollector(cfg)
    adapter = VerlGRPOAdapter(cfg, base_config_path=args.verl_config) if not args.dry else None

    # wandb
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
            print("[rl_train] 未装 wandb，跳过", flush=True)

    parquet_dir = os.path.join(cfg.output_dir, "parquets")
    buffer_dir = os.path.join(cfg.output_dir, "buffers")
    os.makedirs(parquet_dir, exist_ok=True)
    os.makedirs(buffer_dir, exist_ok=True)

    for cycle in range(cfg.num_cycles):
        print(f"\n========== Cycle {cycle} / {cfg.num_cycles - 1} ==========", flush=True)

        # ─── Phase A：采集 ──────────────────────────────
        print(f"[cycle {cycle}] Phase A：采集 {cfg.group_size * cfg.groups_per_role * len(cfg.roles)} 局…", flush=True)
        buf = collector.collect_cycle(cycle)
        buf.save(os.path.join(buffer_dir, f"cycle_{cycle:03d}.json"))
        stats = buf.stats()
        print(f"[cycle {cycle}]   采集完毕：{stats['groups']} groups, "
              f"reward_mean={stats.get('reward_mean', 0):.3f}, "
              f"zero_var_groups={stats.get('zero_variance_groups', 0)}", flush=True)

        # ─── Phase B：转 parquet ──────────────────────
        parquet_path = os.path.join(parquet_dir, f"cycle_{cycle:03d}.parquet")
        try:
            _, n_rows, conv_stats = buffer_to_parquet(buf, parquet_path)
            print(f"[cycle {cycle}] Phase B：写 parquet {n_rows} 行 → {parquet_path}", flush=True)
            print(f"[cycle {cycle}]   过滤统计：{conv_stats}", flush=True)
        except Exception as exc:
            print(f"[cycle {cycle}] ❌ parquet 转换失败：{exc}", flush=True)
            continue

        if n_rows == 0:
            print(f"[cycle {cycle}] ⚠ parquet 0 行（可能 dry 或 Qwen 全部用 fallback），跳过训练", flush=True)
            if wandb:
                wandb.log({"cycle": cycle, **{f"buffer/{k}": v for k, v in stats.items() if isinstance(v, (int, float))}})
            continue

        verify_stats = verify_parquet(parquet_path)
        print(f"[cycle {cycle}]   parquet 校验：{verify_stats}", flush=True)

        # ─── Phase C：verl 训练 ──────────────────────
        if args.dry:
            print(f"[cycle {cycle}] Phase C：dry-run（跳过 verl）", flush=True)
            lora_path = None
        else:
            print(f"[cycle {cycle}] Phase C：调 verl 训练（{cfg.epochs_per_buffer} epochs）…", flush=True)
            result = adapter.train_one_cycle(parquet_path, cycle, dry=False)
            lora_path = result["lora_path"]
            print(f"[cycle {cycle}]   verl 训练完毕，LoRA → {lora_path}", flush=True)

        # ─── Phase D：vLLM hot-swap ──────────────────
        if lora_path and not args.skip_hot_swap:
            try:
                hot_swap_lora_to_vllm(lora_path, cfg.vllm_endpoint, adapter_name="current")
                print(f"[cycle {cycle}] Phase D：LoRA 已推到 vLLM（next cycle 用新权重 rollout）", flush=True)
            except Exception as exc:
                print(f"[cycle {cycle}] ⚠ vLLM hot-swap 失败：{exc}。下一 cycle 仍用旧权重", flush=True)

        # ─── wandb 日志 ──────────────────────────────
        if wandb:
            wandb.log({
                "cycle": cycle,
                **{f"buffer/{k}": v for k, v in stats.items() if isinstance(v, (int, float))},
                **{f"parquet/{k}": v for k, v in verify_stats.items() if isinstance(v, (int, float))},
            })

    print("\n[rl_train] 全部 cycle 完成。", flush=True)
    print(f"  Buffers:  {buffer_dir}", flush=True)
    print(f"  Parquets: {parquet_dir}", flush=True)
    if not args.dry:
        print(f"  LoRA 权重: {os.path.join(cfg.output_dir, 'verl_ckpt')}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

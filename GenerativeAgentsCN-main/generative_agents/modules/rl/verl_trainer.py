# 文件作用：包装 verl 的 GRPO 训练入口，让我们的"采集 → parquet → 训练 → 推 LoRA"循环能调它。
#
# 实现策略（hybrid）：
#   - 优先：subprocess 调 verl 标准入口 `python -m verl.trainer.main_ppo`，传配置 yaml
#   - 备选：dry-run 模式只 dump 配置不真训，CI 友好
#
# 为什么用 subprocess 而不是 import verl Python API：
#   1. verl 的训练循环深度依赖 Ray + FSDP 初始化，主进程 import 会污染 asyncio
#   2. verl 训练完会写 LoRA 到磁盘，下一 cycle 直接从磁盘读，进程隔离更稳
#   3. verl 不同版本 Python API 变化大，subprocess + yaml 接口稳定
#
# 配置 yaml 模板见：configs/verl_grpo.yaml

import json
import os
import subprocess
import sys
from typing import Dict, Optional

import yaml

from modules.rl.config import RLConfig


class VerlGRPOAdapter:
    """协调 verl 训练：每 cycle 从 parquet 读数据，调 verl，输出新 LoRA。"""

    def __init__(self, cfg: RLConfig, base_config_path: str = "configs/verl_grpo.yaml"):
        self.cfg = cfg
        self.base_config_path = base_config_path
        if not os.path.exists(base_config_path):
            raise FileNotFoundError(
                f"verl 配置模板找不到：{base_config_path}。"
                "请确保 configs/verl_grpo.yaml 存在。"
            )

    # =====================================================================
    # 配置生成：把 RLConfig + parquet 路径 + cycle 序号 拼成本次 cycle 的 yaml
    # =====================================================================
    def _build_cycle_config(self, parquet_path: str, cycle: int) -> Dict:
        """读模板 + 覆盖 cycle-specific 字段。"""
        with open(self.base_config_path, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        # 数据
        cfg.setdefault("data", {})
        cfg["data"]["train_files"] = [parquet_path]
        cfg["data"]["train_batch_size"] = cfg["data"].get("train_batch_size", 16)

        # 模型 / LoRA
        cfg.setdefault("actor_rollout_ref", {}).setdefault("model", {})
        cfg["actor_rollout_ref"]["model"]["path"] = self.cfg.base_model
        cfg["actor_rollout_ref"].setdefault("actor", {})
        cfg["actor_rollout_ref"]["actor"]["optim"] = {"lr": self.cfg.learning_rate}
        cfg["actor_rollout_ref"]["actor"]["use_lora"] = True
        cfg["actor_rollout_ref"]["actor"]["lora_rank"] = self.cfg.lora_rank
        cfg["actor_rollout_ref"]["actor"]["lora_alpha"] = self.cfg.lora_alpha
        cfg["actor_rollout_ref"]["actor"]["target_modules"] = list(self.cfg.target_modules)

        # GRPO 超参
        cfg.setdefault("algorithm", "grpo")
        cfg.setdefault("grpo", {})
        cfg["grpo"]["kl_coef"] = self.cfg.beta_kl
        cfg["grpo"]["clip_ratio"] = self.cfg.clip_eps

        # 训练循环
        cfg.setdefault("trainer", {})
        cfg["trainer"]["total_epochs"] = self.cfg.epochs_per_buffer
        cfg["trainer"]["total_training_steps"] = -1  # 由 epochs 决定
        cycle_output = os.path.join(self.cfg.output_dir, "verl_ckpt", f"cycle_{cycle:03d}")
        cfg["trainer"]["default_local_dir"] = cycle_output
        # 加载上一 cycle 的 LoRA 作为本次起点（增量训练）
        if cycle > 0:
            prev_lora = os.path.join(
                self.cfg.output_dir, "verl_ckpt", f"cycle_{cycle - 1:03d}", "actor"
            )
            if os.path.isdir(prev_lora):
                cfg["actor_rollout_ref"]["actor"]["resume_from"] = prev_lora

        # wandb
        if self.cfg.wandb_project:
            cfg["trainer"]["logger"] = ["console", "wandb"]
            cfg["trainer"]["project_name"] = self.cfg.wandb_project
            cfg["trainer"]["experiment_name"] = (
                self.cfg.wandb_run_name or f"grpo-cycle-{cycle:03d}"
            )

        # 长度约束
        cfg["data"]["max_prompt_length"] = self.cfg.max_prompt_length
        cfg["data"]["max_response_length"] = self.cfg.max_completion_length

        return cfg

    # =====================================================================
    # 主入口：一 cycle 训练
    # =====================================================================
    def train_one_cycle(self, parquet_path: str, cycle: int, dry: bool = False) -> Dict:
        """跑一 cycle 的 verl 训练。

        Returns: 含 lora_path 等元数据的 dict。
        """
        cycle_config = self._build_cycle_config(parquet_path, cycle)
        cycle_config_path = os.path.join(
            self.cfg.output_dir, "verl_runs", f"cycle_{cycle:03d}.yaml"
        )
        os.makedirs(os.path.dirname(cycle_config_path), exist_ok=True)
        with open(cycle_config_path, "w", encoding="utf-8") as f:
            yaml.dump(cycle_config, f, allow_unicode=True)

        lora_dir = cycle_config["trainer"]["default_local_dir"]

        if dry:
            return {
                "mode": "dry",
                "config_path": cycle_config_path,
                "would_write_lora_to": lora_dir,
                "cycle": cycle,
            }

        # 调 verl 自带 entrypoint
        cmd = [
            sys.executable, "-m", "verl.trainer.main_ppo",
            f"--config-path={os.path.dirname(os.path.abspath(cycle_config_path))}",
            f"--config-name={os.path.basename(cycle_config_path).replace('.yaml', '')}",
        ]
        env = os.environ.copy()
        # 让 verl 输出尽量啰嗦，便于诊断
        env.setdefault("VERL_LOGGING_LEVEL", "INFO")

        print(f"[verl] cycle {cycle}: 启动 verl 训练，config={cycle_config_path}", flush=True)
        result = subprocess.run(cmd, env=env)
        if result.returncode != 0:
            raise RuntimeError(
                f"verl 训练失败，returncode={result.returncode}。"
                f"查看上面的 verl 输出 + 检查 config：{cycle_config_path}"
            )

        return {
            "mode": "real",
            "config_path": cycle_config_path,
            "lora_path": lora_dir,
            "cycle": cycle,
        }


# =========================================================================
# vLLM hot-swap：把新 LoRA 推到正在 serve Qwen 的 vLLM 实例
# =========================================================================
def hot_swap_lora_to_vllm(
    lora_path: str,
    vllm_endpoint: str,
    adapter_name: str = "current",
    timeout: float = 30.0,
) -> bool:
    """通过 vLLM 的 /v1/load_lora_adapter 接口热加载新 LoRA。

    要求 vLLM 启动时带 `--enable-lora` 并设置环境变量 `VLLM_ALLOW_RUNTIME_LORA_UPDATING=1`。

    Returns: True 表示加载成功。
    """
    try:
        import requests
    except ImportError as e:
        raise RuntimeError("需要 requests 库做 vLLM 控制") from e

    base = vllm_endpoint.rstrip("/")
    # 先卸载同名旧的（vLLM 不允许重复名）
    try:
        requests.post(
            f"{base}/v1/unload_lora_adapter",
            json={"lora_name": adapter_name},
            timeout=timeout,
        )
    except Exception:
        pass

    resp = requests.post(
        f"{base}/v1/load_lora_adapter",
        json={"lora_name": adapter_name, "lora_path": os.path.abspath(lora_path)},
        timeout=timeout,
    )
    if resp.status_code >= 400:
        raise RuntimeError(
            f"vLLM hot-swap 失败 status={resp.status_code} body={resp.text[:500]}"
        )
    return True

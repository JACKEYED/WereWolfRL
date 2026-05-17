# 文件作用：⚠ DEPRECATED ——遗留的 trl-based GRPO trainer，**真训练已切到 verl**。
# 保留本文件只为以下场景：
#   1. CI / pytest 跑 dry-run（buffer→loss 数学验证），不引入 verl 依赖
#   2. 没有 verl 的环境下手动 debug 单条样本的 loss 数值
# 真实训练入口请用：modules.rl.verl_trainer.VerlGRPOAdapter
# 主流程 rl_train.py 默认走 verl，不再 import 本文件。
#
# ───────────────────────────────────────────────────────────
# 以下为原 trl-based 实现（保留用于参考 + dry-run）。

import json
import os
from typing import List, Optional

from modules.rl.buffer import ReplayBuffer
from modules.rl.config import RLConfig


class GRPOTrainer:
    """协调 GRPO 训练。
    - mode='dry'：不加载模型，遍历 buffer 计算 advantage 和 metric，只走数据流（CI 友好）
    - mode='real'：调 trl.GRPOTrainer 真训
    """

    def __init__(self, cfg: RLConfig, mode: str = "dry"):
        self.cfg = cfg
        if mode not in ("dry", "real"):
            raise ValueError("mode 必须是 'dry' 或 'real'")
        self.mode = mode
        self._real = None
        if mode == "real":
            self._real = self._init_real()

    # =====================================================================
    # 真实训练入口
    # =====================================================================
    def _init_real(self):
        """加载 base + LoRA + reference；构造 trl.GRPOTrainer。"""
        try:
            import torch  # noqa: F401
            from transformers import AutoTokenizer, AutoModelForCausalLM
            from peft import LoraConfig, get_peft_model
            from trl import GRPOConfig, GRPOTrainer as TrlGRPO
        except ImportError as exc:
            raise RuntimeError(
                "real 模式需要安装 torch / transformers / peft / trl，"
                "请 pip install -r requirements-rl.txt"
            ) from exc

        tokenizer = AutoTokenizer.from_pretrained(self.cfg.base_model, trust_remote_code=True)
        policy = AutoModelForCausalLM.from_pretrained(
            self.cfg.base_model, torch_dtype="auto", device_map="auto",
            trust_remote_code=True,
        )
        lora_cfg = LoraConfig(
            r=self.cfg.lora_rank,
            lora_alpha=self.cfg.lora_alpha,
            lora_dropout=self.cfg.lora_dropout,
            target_modules=self.cfg.target_modules,
            task_type="CAUSAL_LM",
        )
        policy = get_peft_model(policy, lora_cfg)
        ref = AutoModelForCausalLM.from_pretrained(
            self.cfg.base_model, torch_dtype="auto", device_map="auto",
            trust_remote_code=True,
        )
        ref.eval()
        # trl 的 GRPOConfig
        args = GRPOConfig(
            output_dir=self.cfg.output_dir,
            learning_rate=self.cfg.learning_rate,
            num_train_epochs=self.cfg.epochs_per_buffer,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=1,
            beta=self.cfg.beta_kl,
            num_generations=self.cfg.group_size,
            max_prompt_length=self.cfg.max_prompt_length,
            max_completion_length=self.cfg.max_completion_length,
            logging_steps=10,
            save_steps=200,
            report_to=["wandb"] if self.cfg.wandb_project else [],
        )
        trainer = TrlGRPO(
            model=policy,
            ref_model=ref,
            args=args,
            tokenizer=tokenizer,
            # reward 已经在 buffer 里算好了——通过 trainer.train_step 自定义注入
            reward_funcs=[lambda completions, **k: [0.0] * len(completions)],
        )
        return {"trainer": trainer, "tokenizer": tokenizer}

    # =====================================================================
    # buffer → 训练样本
    # =====================================================================
    def _make_train_samples(self, buf: ReplayBuffer) -> List[dict]:
        """把 buffer 里每个 Qwen step 转换成训练样本（dict 形式，trainer 端再 tokenize）。"""
        samples = []
        for item in buf.iter_steps_with_advantage(normalize=self.cfg.advantage_norm):
            step = item["step"]
            samples.append({
                "prompt": step.get("prompt") or "",
                "completion": str(step.get("action")),
                "old_logprobs": step.get("logprobs"),
                "advantage": item["advantage"],
                "role": item["role"],
                "decision_type": step.get("decision_type"),
            })
        return samples

    # =====================================================================
    # 主入口：消费一个 cycle 的 buffer
    # =====================================================================
    def train_on_buffer(self, buf: ReplayBuffer, cycle: int) -> dict:
        """在 buffer 上跑 epochs_per_buffer 轮 GRPO 更新。返回 metrics。"""
        samples = self._make_train_samples(buf)
        metrics = {
            "cycle": cycle,
            "samples": len(samples),
            "groups": len(buf),
            **buf.stats(),
        }
        valid_samples = [s for s in samples if s.get("old_logprobs")]
        metrics["samples_with_logprobs"] = len(valid_samples)

        if self.mode == "dry":
            metrics["mode"] = "dry"
            return metrics

        # ─── real 模式 ───
        # 关键：trl.GRPOTrainer 默认期望它自己生成 rollout；我们已经在 collector 里生成好了，
        # 所以走"离线 GRPO"路径——把 (prompt, completion, old_lp, advantage) 直接塞到 trainer。
        # trl 0.x 提供 trainer._inner_training_loop 可手动喂 batch；
        # 实践中通常 subclass 或者用 trainer.compute_loss 单独算。
        # 这里给出最朴素的写法：逐样本 forward + backward。
        import torch
        trainer = self._real["trainer"]
        tokenizer = self._real["tokenizer"]
        policy = trainer.model
        ref = trainer.ref_model
        optimizer = trainer.optimizer if trainer.optimizer is not None else torch.optim.AdamW(
            policy.parameters(), lr=self.cfg.learning_rate
        )

        from modules.rl.loss import grpo_token_loss

        for epoch in range(self.cfg.epochs_per_buffer):
            for sample in valid_samples:
                prompt_ids = tokenizer(sample["prompt"], return_tensors="pt").input_ids.to(policy.device)
                compl_ids = tokenizer(sample["completion"], return_tensors="pt", add_special_tokens=False).input_ids.to(policy.device)
                # 拼成 [prompt | completion] 喂模型，取 completion 段的 logprob
                full_ids = torch.cat([prompt_ids, compl_ids], dim=1)
                with torch.no_grad():
                    ref_logits = ref(full_ids).logits
                logits = policy(full_ids).logits

                # 取 completion 部分的 token logprobs
                T_p = prompt_ids.size(1)
                T_c = compl_ids.size(1)
                # logits 在位置 i 预测 token i+1
                lp_new = torch.log_softmax(logits[0, T_p - 1: T_p + T_c - 1], dim=-1)
                lp_ref = torch.log_softmax(ref_logits[0, T_p - 1: T_p + T_c - 1], dim=-1)
                gather_idx = compl_ids[0].unsqueeze(-1)
                new_lp_per_tok = lp_new.gather(-1, gather_idx).squeeze(-1)
                ref_lp_per_tok = lp_ref.gather(-1, gather_idx).squeeze(-1)
                old_lp_per_tok = torch.tensor(
                    sample["old_logprobs"][: T_c], device=policy.device, dtype=new_lp_per_tok.dtype
                )

                loss = grpo_token_loss(
                    new_lp_per_tok, old_lp_per_tok, ref_lp_per_tok,
                    advantage=sample["advantage"],
                    clip_eps=self.cfg.clip_eps, beta_kl=self.cfg.beta_kl,
                )
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
            metrics[f"epoch_{epoch}_done"] = True

        # 保存 LoRA
        out_dir = os.path.join(self.cfg.output_dir, f"cycle_{cycle:03d}")
        os.makedirs(out_dir, exist_ok=True)
        policy.save_pretrained(out_dir)
        metrics["lora_saved_to"] = out_dir
        metrics["mode"] = "real"
        return metrics

    # =====================================================================
    # 落盘 buffer + metrics
    # =====================================================================
    def save_buffer(self, buf: ReplayBuffer, cycle: int) -> str:
        path = os.path.join(self.cfg.output_dir, "buffers", f"cycle_{cycle:03d}.json")
        buf.save(path)
        return path

    def save_metrics(self, metrics: dict, cycle: int) -> str:
        path = os.path.join(self.cfg.output_dir, "metrics", f"cycle_{cycle:03d}.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)
        return path

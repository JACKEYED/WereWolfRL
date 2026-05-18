# 文件作用：RL 训练 job 注册表 + 后台 worker 线程 + 事件总线。
# 与 api/sessions.py 的对局会话注册表是平级设计，但有几点不同：
#   - 同时只允许 1 个 active job（GPU 资源唯一）
#   - 每个 job 内部跑 N cycle 闭环：collect → parquet → verl → hot-swap
#   - 每个阶段切换发 WS 事件，前端实时可视化
#   - 支持 dry 模式（不真训，sleep + 假 metric，纯演示 UI 用）

import asyncio
import os
import threading
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


# 训练 job 的状态机
JOB_STATES = (
    "pending",      # 已创建未启动
    "running",      # 后台线程在跑
    "completed",    # 全部 cycle 跑完
    "failed",       # 异常退出
    "stopped",      # 用户主动停
)

# 每个 cycle 内的阶段
CYCLE_PHASES = (
    "idle",         # 还没开始本 cycle
    "collecting",   # Phase A：起 N 局并行采集
    "packaging",    # Phase B：buffer → parquet
    "training",     # Phase C：verl 训练
    "hotswapping",  # Phase D：推 LoRA 到 vLLM
)


@dataclass
class CycleMetric:
    """单 cycle 训练指标，用于前端画图。"""
    cycle: int
    reward_mean: float = 0.0
    reward_min: float = 0.0
    reward_max: float = 0.0
    zero_variance_groups: int = 0
    total_steps: int = 0
    parquet_rows: int = 0
    elapsed_sec: float = 0.0
    # 真训才有的：
    loss: Optional[float] = None
    kl: Optional[float] = None
    lora_path: Optional[str] = None


@dataclass
class TrainingJob:
    id: str
    created_at: str
    state: str = "pending"
    current_phase: str = "idle"
    current_cycle: int = 0
    total_cycles: int = 0
    cfg_dict: Dict[str, Any] = field(default_factory=dict)
    dry: bool = False
    cycle_metrics: List[CycleMetric] = field(default_factory=list)
    log: List[str] = field(default_factory=list)
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    # 不参与序列化（运行时控制 + WS subscribe）
    _stop_flag: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    subscribers: List["asyncio.Queue[dict]"] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "id": self.id,
            "created_at": self.created_at,
            "state": self.state,
            "current_phase": self.current_phase,
            "current_cycle": self.current_cycle,
            "total_cycles": self.total_cycles,
            "cfg": self.cfg_dict,
            "dry": self.dry,
            "cycle_metrics": [asdict(m) for m in self.cycle_metrics],
            "log": list(self.log[-200:]),
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }
        return d

    def summary(self) -> dict:
        """小巧版本，列表页用。"""
        last = self.cycle_metrics[-1] if self.cycle_metrics else None
        return {
            "id": self.id,
            "state": self.state,
            "current_phase": self.current_phase,
            "current_cycle": self.current_cycle,
            "total_cycles": self.total_cycles,
            "dry": self.dry,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "last_reward_mean": last.reward_mean if last else None,
        }


class TrainingRegistry:
    """同进程同时只允许 1 个 active job（避免 GPU 抢资源）。"""

    def __init__(self):
        self._jobs: Dict[str, TrainingJob] = {}
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def current_active(self) -> Optional[TrainingJob]:
        with self._lock:
            for j in self._jobs.values():
                if j.state == "running":
                    return j
        return None

    def create(self, cfg_dict: dict, total_cycles: int, dry: bool) -> TrainingJob:
        if self.current_active():
            raise RuntimeError("已有训练 job 在运行，停掉后再开新的")
        job_id = uuid.uuid4().hex[:12]
        job = TrainingJob(
            id=job_id,
            created_at=datetime.now().isoformat(timespec="seconds"),
            total_cycles=total_cycles,
            cfg_dict=dict(cfg_dict),
            dry=dry,
        )
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get(self, job_id: str) -> Optional[TrainingJob]:
        with self._lock:
            return self._jobs.get(job_id)

    def list_all(self) -> List[TrainingJob]:
        with self._lock:
            return list(self._jobs.values())

    def remove(self, job_id: str) -> bool:
        with self._lock:
            return self._jobs.pop(job_id, None) is not None

    def stop(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job:
            return False
        job._stop_flag.set()
        return True

    # ─── 事件派发 ─────────────────────────────────────────
    def emit(self, job: TrainingJob, event: dict) -> None:
        """线程安全把事件 push 给所有订阅者。"""
        event = dict(event)
        event.setdefault("ts", datetime.now().strftime("%H:%M:%S"))
        # 文本日志一并追加（便于前端从 status 接口拉历史）
        if event.get("type") in ("log", "phase", "cycle_done", "error"):
            with job._lock:
                job.log.append(f"[{event['ts']}] {event.get('msg', event.get('type'))}")
                if len(job.log) > 500:
                    job.log = job.log[-500:]
        if not self._loop:
            return
        for q in list(job.subscribers):
            try:
                self._loop.call_soon_threadsafe(q.put_nowait, event)
            except Exception:
                pass

    def subscribe(self, job: TrainingJob) -> "asyncio.Queue[dict]":
        q: asyncio.Queue = asyncio.Queue()
        job.subscribers.append(q)
        return q

    def unsubscribe(self, job: TrainingJob, q) -> None:
        try:
            job.subscribers.remove(q)
        except ValueError:
            pass


# ─── 全局单例 ──────────────────────────────────────────────
registry = TrainingRegistry()


# =========================================================================
# 后台 worker：跑一整个 job 的所有 cycle
# =========================================================================
def run_training_job(job: TrainingJob) -> None:
    """在后台线程里跑。会改 job 状态、emit 事件。"""
    job.state = "running"
    job.started_at = datetime.now().isoformat(timespec="seconds")
    registry.emit(job, {
        "type": "job_start", "msg": f"训练 job {job.id} 启动",
        "total_cycles": job.total_cycles, "dry": job.dry,
    })

    try:
        if job.dry:
            _run_dry_loop(job)
        else:
            _run_real_loop(job)
        if job._stop_flag.is_set():
            job.state = "stopped"
            registry.emit(job, {"type": "job_stop", "msg": "用户停止"})
        else:
            job.state = "completed"
            registry.emit(job, {"type": "job_done", "msg": f"全部 {job.total_cycles} cycle 完成"})
    except Exception as exc:
        job.state = "failed"
        job.error = f"{exc}\n{traceback.format_exc()}"
        registry.emit(job, {"type": "error", "msg": f"训练失败：{exc}"})
    finally:
        job.finished_at = datetime.now().isoformat(timespec="seconds")


def _emit_phase(job: TrainingJob, phase: str, msg: str = "") -> None:
    job.current_phase = phase
    registry.emit(job, {
        "type": "phase", "phase": phase, "cycle": job.current_cycle, "msg": msg or phase,
    })


def _run_dry_loop(job: TrainingJob) -> None:
    """模拟训练：每 cycle sleep + 生成假 metric，让前端 UI 能动起来。"""
    import math
    import random

    rng = random.Random(0)
    for cycle in range(job.total_cycles):
        if job._stop_flag.is_set():
            return
        job.current_cycle = cycle
        t0 = time.time()
        for phase, sleep_s in [
            ("collecting", 1.2),
            ("packaging", 0.3),
            ("training", 0.8),
            ("hotswapping", 0.2),
        ]:
            if job._stop_flag.is_set():
                return
            _emit_phase(job, phase, f"cycle {cycle} {phase}…")
            # 拆分 sleep 让停止信号能尽快响应
            for _ in range(int(sleep_s * 10)):
                if job._stop_flag.is_set():
                    return
                time.sleep(0.1)
        # 模拟一个"reward 随 cycle 逐步上升"的曲线 + 噪声
        base = -0.4 + 0.04 * cycle
        noise = (rng.random() - 0.5) * 0.3
        reward_mean = base + noise
        metric = CycleMetric(
            cycle=cycle,
            reward_mean=reward_mean,
            reward_min=reward_mean - 0.5,
            reward_max=reward_mean + 0.8,
            zero_variance_groups=max(0, 6 - cycle // 3),
            total_steps=rng.randint(800, 1400),
            parquet_rows=rng.randint(400, 900),
            elapsed_sec=time.time() - t0,
            loss=max(0.05, 1.0 - 0.02 * cycle + (rng.random() - 0.5) * 0.1),
            kl=max(0.0, 0.05 + (rng.random() - 0.5) * 0.03),
            lora_path=f"results/rl/verl_ckpt/cycle_{cycle:03d}/actor",
        )
        job.cycle_metrics.append(metric)
        registry.emit(job, {
            "type": "cycle_done", "cycle": cycle, "metric": asdict(metric),
            "msg": f"cycle {cycle} 完成，reward_mean={reward_mean:.3f}",
        })


def _run_real_loop(job: TrainingJob) -> None:
    """真训：调 collector + verl_dataset + verl_trainer。要求依赖齐全。"""
    from modules.rl.config import RLConfig
    from modules.rl.collector import RLCollector
    from modules.rl.verl_dataset import buffer_to_parquet, verify_parquet
    from modules.rl.verl_trainer import VerlGRPOAdapter, hot_swap_lora_to_vllm

    cfg = RLConfig(**job.cfg_dict)
    collector = RLCollector(cfg)
    adapter = VerlGRPOAdapter(cfg)
    parquet_dir = os.path.join(cfg.output_dir, "parquets")
    buffer_dir = os.path.join(cfg.output_dir, "buffers")
    os.makedirs(parquet_dir, exist_ok=True)
    os.makedirs(buffer_dir, exist_ok=True)

    for cycle in range(job.total_cycles):
        if job._stop_flag.is_set():
            return
        job.current_cycle = cycle
        t0 = time.time()

        # Phase A
        _emit_phase(job, "collecting", f"cycle {cycle} 采集 {cfg.group_size * cfg.groups_per_role * len(cfg.roles)} 局")
        buf = collector.collect_cycle(cycle)
        buf.save(os.path.join(buffer_dir, f"cycle_{cycle:03d}.json"))
        stats = buf.stats()

        # Phase B
        _emit_phase(job, "packaging", f"cycle {cycle} 写 parquet")
        parquet_path = os.path.join(parquet_dir, f"cycle_{cycle:03d}.parquet")
        _, n_rows, _ = buffer_to_parquet(buf, parquet_path)
        if n_rows == 0:
            registry.emit(job, {
                "type": "log", "msg": f"cycle {cycle} parquet 0 行，跳过训练",
            })
            metric = CycleMetric(
                cycle=cycle,
                reward_mean=stats.get("reward_mean", 0.0),
                reward_min=stats.get("reward_min", 0.0),
                reward_max=stats.get("reward_max", 0.0),
                zero_variance_groups=stats.get("zero_variance_groups", 0),
                total_steps=stats.get("total_steps", 0),
                parquet_rows=0,
                elapsed_sec=time.time() - t0,
            )
            job.cycle_metrics.append(metric)
            registry.emit(job, {"type": "cycle_done", "cycle": cycle, "metric": asdict(metric)})
            continue

        # Phase C
        _emit_phase(job, "training", f"cycle {cycle} 调 verl 训练 {cfg.epochs_per_buffer} epochs")
        result = adapter.train_one_cycle(parquet_path, cycle, dry=False)
        lora_path = result.get("lora_path")

        # Phase D
        if lora_path:
            _emit_phase(job, "hotswapping", f"cycle {cycle} 推 LoRA 到 vLLM")
            try:
                hot_swap_lora_to_vllm(lora_path, cfg.vllm_endpoint, adapter_name="current")
            except Exception as exc:
                registry.emit(job, {"type": "log", "msg": f"hot-swap 失败：{exc}（继续）"})

        metric = CycleMetric(
            cycle=cycle,
            reward_mean=stats.get("reward_mean", 0.0),
            reward_min=stats.get("reward_min", 0.0),
            reward_max=stats.get("reward_max", 0.0),
            zero_variance_groups=stats.get("zero_variance_groups", 0),
            total_steps=stats.get("total_steps", 0),
            parquet_rows=n_rows,
            elapsed_sec=time.time() - t0,
            lora_path=lora_path,
        )
        job.cycle_metrics.append(metric)
        registry.emit(job, {
            "type": "cycle_done", "cycle": cycle, "metric": asdict(metric),
            "msg": f"cycle {cycle} 完成，reward_mean={metric.reward_mean:.3f}",
        })

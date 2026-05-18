# 文件作用：RL 训练 job 的 REST + WebSocket 路由。
# 挂到主 FastAPI app 上的写法见 api/server.py 末尾。
#
# 接口：
#   POST   /api/rl/jobs                创建并启动训练 job
#   GET    /api/rl/jobs                列所有 job
#   GET    /api/rl/jobs/{id}/status    完整状态（含 cycle_metrics + log）
#   POST   /api/rl/jobs/{id}/stop      请求停止
#   DELETE /api/rl/jobs/{id}           删除 job 记录（必须先 stop / completed）
#   WS     /ws/rl/jobs/{id}            订阅事件流

from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from api.rl_sessions import registry, run_training_job


router = APIRouter(prefix="/api/rl", tags=["rl"])
ws_router = APIRouter(tags=["rl"])

# 后台线程池：训练 job 起在这里
_executor = ThreadPoolExecutor(max_workers=1)


# ─── 请求 / 响应模型 ──────────────────────────────────────
class NewTrainingRequest(BaseModel):
    cycles: int = 30
    group_size: int = 8
    groups_per_role: int = 20
    collection_workers: int = 8
    epochs_per_buffer: int = 4
    lr: float = 5e-6
    beta_kl: float = 0.04
    clip_eps: float = 0.2
    base_model: str = "Qwen/Qwen2.5-7B-Instruct"
    vllm_endpoint: str = "http://127.0.0.1:8001/v1"
    output_dir: str = "results/rl"
    seed: int = 0
    wandb_project: str = ""
    roles: List[str] = [
        "werewolf", "seer", "witch", "hunter", "guard", "villager",
    ]
    dry: bool = False  # True = 不真训，模拟 metric 给前端演示


class JobSummary(BaseModel):
    id: str
    state: str
    current_phase: str
    current_cycle: int
    total_cycles: int
    dry: bool
    created_at: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    last_reward_mean: Optional[float] = None


# ─── REST ────────────────────────────────────────────────
@router.post("/jobs", response_model=JobSummary)
def create_job(req: NewTrainingRequest):
    cfg_dict = {
        "group_size": req.group_size,
        "groups_per_role": req.groups_per_role,
        "roles": list(req.roles),
        "collection_workers": req.collection_workers,
        "epochs_per_buffer": req.epochs_per_buffer,
        "learning_rate": req.lr,
        "beta_kl": req.beta_kl,
        "clip_eps": req.clip_eps,
        "base_model": req.base_model,
        "vllm_endpoint": req.vllm_endpoint,
        "output_dir": req.output_dir,
        "num_cycles": req.cycles,
        "seed_base": req.seed,
        "wandb_project": req.wandb_project,
        "scene_mode": "game",
        "use_llm": not req.dry,
    }
    try:
        job = registry.create(cfg_dict, total_cycles=req.cycles, dry=req.dry)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    _executor.submit(run_training_job, job)
    return JobSummary(**job.summary())


@router.get("/jobs", response_model=List[JobSummary])
def list_jobs():
    return [JobSummary(**j.summary()) for j in registry.list_all()]


@router.get("/jobs/{job_id}/status")
def job_status(job_id: str):
    job = registry.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    return job.to_dict()


@router.post("/jobs/{job_id}/stop", response_model=JobSummary)
def stop_job(job_id: str):
    ok = registry.stop(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    job = registry.get(job_id)
    return JobSummary(**job.summary())


@router.delete("/jobs/{job_id}")
def delete_job(job_id: str):
    job = registry.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"job {job_id} not found")
    if job.state == "running":
        raise HTTPException(status_code=409, detail="job 还在运行，先 stop")
    registry.remove(job_id)
    return {"ok": True}


# ─── WS ──────────────────────────────────────────────────
@ws_router.websocket("/ws/rl/jobs/{job_id}")
async def ws_rl_job(websocket: WebSocket, job_id: str):
    job = registry.get(job_id)
    if not job:
        await websocket.close(code=4004, reason=f"job {job_id} not found")
        return

    await websocket.accept()
    q = registry.subscribe(job)
    try:
        # 先把已有 status 推一次让前端 hydrate
        await websocket.send_json({"type": "snapshot", "job": job.to_dict()})
        while True:
            event = await q.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        registry.unsubscribe(job, q)

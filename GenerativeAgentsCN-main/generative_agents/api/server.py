# 文件作用：FastAPI 应用入口。
# 启动：cd generative_agents && uvicorn api.server:app --reload --port 8000
# 主要路由：
#   POST   /api/games                  新建一局
#   GET    /api/games                  列出所有对局
#   GET    /api/games/{id}/state       查当前完整状态
#   POST   /api/games/{id}/setup       初始化身份（move 到家、首条记录）
#   POST   /api/games/{id}/step        推进一个阶段（night/day/social）
#   POST   /api/games/{id}/run         一口气跑完整局（阻塞，长任务）
#   GET    /api/games/{id}/agent/{n}   读取某 Agent 的私密记忆
#   GET    /api/games/{id}/report      下载 Markdown 报告
#   WS     /ws/games/{id}              订阅实时事件流

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from typing import List, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from api.sessions import registry
from modules import utils
from modules.werewolf.director import (
    DEFAULT_WEREWOLF_PLAYERS,
    WerewolfDirector,
    build_werewolf_config,
    load_agent_base,
)


app = FastAPI(
    title="江南古镇狼人杀 API",
    description="把 WerewolfDirector 包装成可控的 REST + WebSocket 服务。",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 把当前 asyncio loop 注入 registry，跨线程事件转发用得到
@app.on_event("startup")
async def _on_startup():
    registry.set_event_loop(asyncio.get_running_loop())


# 阻塞型 director.run() 用线程池跑，免得拽住 asyncio loop
_executor = ThreadPoolExecutor(max_workers=2)


# ==================== 请求/响应模型 ====================
class NewGameRequest(BaseModel):
    name: Optional[str] = None
    seed: Optional[int] = None
    players: Optional[List[str]] = None
    use_llm: bool = True
    write_memory: bool = False  # API 默认关向量记忆，避免一局十几次 embedding
    scene_mode: str = "social"   # social = 江南叙事完整版；game = v1 纯狼人杀 RL 训练版


class GameSummary(BaseModel):
    id: str
    name: str
    created_at: str
    day: int
    winner: Optional[str]
    finished: bool
    scene_mode: str = "social"


# ==================== 工具 ====================
def _summarize(sess) -> GameSummary:
    d = sess.director
    return GameSummary(
        id=sess.id,
        name=sess.name,
        created_at=sess.created_at,
        day=getattr(d, "day", 0),
        winner=getattr(d, "winner", None),
        finished=sess.finished,
        scene_mode=getattr(d, "scene_mode", "social"),
    )


def _require(game_id: str):
    sess = registry.get(game_id)
    if not sess:
        raise HTTPException(status_code=404, detail=f"game {game_id} not found")
    return sess


# ==================== 路由 ====================
@app.post("/api/games", response_model=GameSummary)
def create_game(req: NewGameRequest):
    """创建对局。注意：此请求会同步执行：
      1. 加载 853KB maze.json + 建空间索引（~1-2s）
      2. 读 12 份 agent.json，建 12 个 Agent 对象（~1-2s）
      3. reset_game() 给 12 个 Agent 创建 LLM 客户端（首次 `import openai` ~1-2s）
      总计 4-10 秒，请耐心等待。
    """
    import time
    from datetime import datetime as _dt

    t_start = time.perf_counter()
    name = req.name if req.name else f"api-{_dt.now().strftime('%Y%m%d-%H%M%S')}"

    players = req.players or DEFAULT_WEREWOLF_PLAYERS
    if len(players) != 12:
        raise HTTPException(status_code=400, detail="必须 12 名玩家")

    checkpoints_folder = os.path.join("results", "checkpoints", name)
    if os.path.exists(checkpoints_folder):
        raise HTTPException(status_code=409, detail=f"对局 {name} 已存在")

    config = build_werewolf_config("20240213-18:00", 10, players, load_agent_base())
    if not req.write_memory:
        config["agent_base"]["associate"] = {"disabled": True}
    t_config = time.perf_counter()
    print(f"[create_game] {name}: 配置就绪 {(t_config - t_start) * 1000:.0f}ms")

    director = WerewolfDirector(
        name,
        "frontend/static",
        checkpoints_folder,
        config,
        seed=req.seed,
        use_llm=req.use_llm,
        write_memory=req.write_memory,
        scene_mode=req.scene_mode,
    )
    t_init = time.perf_counter()
    print(
        f"[create_game] {name}: WerewolfDirector 初始化完毕 "
        f"{(t_init - t_config) * 1000:.0f}ms (含 maze + 12 agents + reset_game)"
    )

    sess = registry.create(name, director)
    print(
        f"[create_game] {name}: 总耗时 {(time.perf_counter() - t_start) * 1000:.0f}ms"
    )
    return _summarize(sess)


@app.get("/api/games", response_model=List[GameSummary])
def list_games():
    return [_summarize(s) for s in registry.list_all()]


@app.get("/api/games/{game_id}/state")
def get_state(game_id: str):
    sess = _require(game_id)
    return sess.director.state_dict(getattr(sess.director, "_last_phase", "init"))


@app.post("/api/games/{game_id}/setup", response_model=GameSummary)
def setup(game_id: str):
    sess = _require(game_id)
    sess.director.setup()
    return _summarize(sess)


class StepRequest(BaseModel):
    phase: str  # 'social-pre' | 'night' | 'day' | 'social-post'


@app.post("/api/games/{game_id}/step", response_model=GameSummary)
def step(game_id: str, req: StepRequest):
    """推进一个阶段。
    - social-pre / social-post：仅 scene_mode='social' 模式可用（game 模式跳过这两阶段）
    - night / day：两个模式都可用，phase label 按 mode 自适应
    """
    sess = _require(game_id)
    director = sess.director
    mode = getattr(director, "scene_mode", "social")

    if req.phase == "social-pre":
        if mode == "game":
            raise HTTPException(
                status_code=400,
                detail="game 模式跳过开场社交，请直接调用 night",
            )
        label = director.phase_label(0, "evening_pre")
        director.free_social_window(label, rounds=3)
        director.end_of_phase(label)
    elif req.phase == "night":
        director.day += 1
        label = director.phase_label(director.day, "night")
        director.night_phase(director.day)
        director.end_of_phase(label)
        director.check_win("子时结算" if mode == "social" else "夜晚结算")
        if director.winner:
            sess.finished = True
    elif req.phase == "day":
        label = director.phase_label(director.day, "day_council")
        director.day_phase(director.day)
        director.end_of_phase(label)
        director.check_win("辰时议会" if mode == "social" else "白天议会")
        if director.winner:
            sess.finished = True
    elif req.phase == "social-post":
        if mode == "game":
            raise HTTPException(
                status_code=400,
                detail="game 模式跳过申时余韵，请直接调用下一轮 night",
            )
        label = director.phase_label(director.day, "evening_post")
        director.free_social_window(label, rounds=2)
        director.end_of_phase(label)
    else:
        raise HTTPException(status_code=400, detail=f"未知 phase: {req.phase}")

    return _summarize(sess)


@app.post("/api/games/{game_id}/run", response_model=GameSummary)
async def run_to_completion(game_id: str):
    """一口气跑完一局。会阻塞数十秒到数分钟，建议配合 WebSocket 看进度。"""
    sess = _require(game_id)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(_executor, sess.director.run)
    sess.finished = True
    return _summarize(sess)


@app.get("/api/games/{game_id}/agent/{name}")
def get_agent_private(game_id: str, name: str):
    sess = _require(game_id)
    director = sess.director
    if name not in director.players:
        raise HTTPException(status_code=404, detail=f"agent {name} not found")
    player = director.players[name]
    bs = director.belief_of(name) if hasattr(director, "belief_of") else None
    trajectory = []
    if hasattr(director, "trajectories"):
        trajectory = [
            s.to_dict() for s in director.trajectories.all_for(name)
        ][-30:]
    return {
        "name": name,
        "role": player.role,
        "role_name": player.role_name,
        "camp": player.camp,
        "alive": player.alive,
        "death_reason": player.death_reason,
        "private_log": director.private_log.get(name, []),
        "seer_checks": director.seer_checks.get(name, {}) if player.role == "seer" else None,
        "belief": bs.to_dict() if bs else None,
        "trajectory_tail": trajectory,
    }


@app.get("/api/games/{game_id}/trajectories")
def get_trajectories(game_id: str):
    """完整 trajectory JSON。RL 训练流水线主要消费这个端点。"""
    sess = _require(game_id)
    director = sess.director
    if not hasattr(director, "trajectories"):
        return {"steps": [], "count": 0}
    return director.trajectories.to_dict()


@app.get("/api/games/{game_id}/report", response_class=PlainTextResponse)
def get_report(game_id: str):
    sess = _require(game_id)
    path = os.path.join(sess.director.checkpoints_folder, "werewolf_report.md")
    if not os.path.exists(path):
        sess.director.write_report()
    return FileResponse(path, media_type="text/markdown")


@app.delete("/api/games/{game_id}")
def delete_game(game_id: str):
    if not registry.remove(game_id):
        raise HTTPException(status_code=404, detail=f"game {game_id} not found")
    return {"ok": True}


# ==================== WebSocket ====================
@app.websocket("/ws/games/{game_id}")
async def ws_live(websocket: WebSocket, game_id: str):
    sess = registry.get(game_id)
    if not sess:
        await websocket.close(code=4004, reason=f"game {game_id} not found")
        return

    await websocket.accept()
    queue = registry.subscribe(sess)
    try:
        # 先发一条 snapshot 让前端 hydrate
        await websocket.send_json(
            {
                "type": "snapshot",
                "summary": _summarize(sess).model_dump(),
            }
        )
        while True:
            event = await queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        pass
    finally:
        registry.unsubscribe(sess, queue)

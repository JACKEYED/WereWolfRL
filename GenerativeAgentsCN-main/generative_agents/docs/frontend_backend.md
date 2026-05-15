# 前后端架构与运行说明

本项目自 v0.2 起拆成 **Python 后端**（含规则引擎和 FastAPI 服务）+ **React 前端**（控制台 UI）。
旧的 Flask 回放页面（`replay.py` / `frontend/templates/`）暂时保留，可与新前端并存。

## 目录速览

```
generative_agents/
├── modules/
│   ├── werewolf/             # 模块化后的规则引擎（路 1 重构）
│   │   ├── locations.py      # 8 个江南地点常量
│   │   ├── rules.py          # ROLE_DECK + 同守同救 + 胜负判定（纯函数）
│   │   ├── player.py         # WerewolfPlayer + role_brief + fallback_speech
│   │   ├── text_utils.py     # clean_text / match_choice / join_names
│   │   ├── recorder.py       # 日志 / 对话 / 检查点 / 报告
│   │   ├── llm_io.py         # ask_text / ask_choice / build_agent_prompt
│   │   ├── phases/           # night.py + day.py + social.py
│   │   └── director.py       # WerewolfDirector 状态壳（~410 行）
│   ├── gossip.py             # NPC 流言模块（保守扭曲）
│   ├── memory/               # 既有 Generative Agents 记忆系统
│   └── ...
├── api/
│   ├── server.py             # FastAPI 入口
│   └── sessions.py           # 内存会话注册表 + 事件总线
├── web/                      # React + Vite + TS 前端
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── api.ts            # REST + WebSocket 客户端
│       ├── types.ts          # 与 server.py 对齐的 TS 类型
│       ├── styles.css
│       └── components/
│           ├── MapPanel.tsx       # 8 地点占位（Phaser 接入预留）
│           ├── TimelinePanel.tsx  # 公开/暗记/私聊/移动 实时流
│           └── AgentPanel.tsx     # 角色芯片 + 私密视角
├── start.py                  # 原 CLI 入口（一口气跑完一局）
├── replay.py                 # 旧 Flask 回放（待退役）
└── test/
    └── test_werewolf_pure.py # 43 个纯模块单元测试
```

## 安装依赖

### 后端

```bash
cd D:\code\bytedance\GenerativeAgentsCN-main\generative_agents
pip install -r requirements.txt
pip install fastapi uvicorn[standard]  # 路 2 新增
```

> `requirements.txt` 已包含 pydantic、flask 等；FastAPI 没在里面，需要补装。

### 前端

```bash
cd web
npm install
```

## 运行

打开两个终端：

**终端 A：启后端**

```bash
cd generative_agents
uvicorn api.server:app --reload --port 8000
```

浏览器访问 `http://127.0.0.1:8000/docs` 可以看到自动生成的 OpenAPI 文档（FastAPI 内置）。

**终端 B：启前端**

```bash
cd generative_agents/web
npm run dev
```

浏览器访问 `http://127.0.0.1:5173`。Vite 配置已把 `/api` 和 `/ws` 代理到 `127.0.0.1:8000`，跨域问题自动消失。

## REST 接口一览

| 方法 | 路径 | 用途 |
|------|------|------|
| POST | `/api/games` | 新建一局（body: `{name?, seed?, use_llm?, write_memory?}`） |
| GET  | `/api/games` | 列出所有进行中的对局 |
| POST | `/api/games/{id}/setup` | 发身份牌 + 角色 move 到家 |
| POST | `/api/games/{id}/step` | 推进一阶段（body: `{phase: "social-pre"\|"night"\|"day"\|"social-post"}`） |
| POST | `/api/games/{id}/run` | 一口气跑完整局（阻塞，建议配合 WebSocket） |
| GET  | `/api/games/{id}/state` | 取当前完整 state |
| GET  | `/api/games/{id}/agent/{name}` | 取某 Agent 的私密视角 |
| GET  | `/api/games/{id}/report` | 下载 Markdown 复盘报告 |
| DELETE | `/api/games/{id}` | 删除内存中的对局 |
| WS   | `/ws/games/{id}` | 订阅实时事件流 |

### WebSocket 事件格式

```json
// 首条 snapshot
{ "type": "snapshot", "summary": { "id": "...", "name": "...", "day": 0, "winner": null, "finished": false } }

// 后续 record
{ "type": "record", "scope": "public", "phase": "第1日子时", "text": "...", "actors": [...], "location": "...", "day": 1 }
```

## 已知限制 & 后续工作

1. **单进程单局**：`modules/game.py` 用全局单例，同进程同时只能跑一局。未来要并行需要重构 game singleton。
2. **Phaser 地图未接入**：`MapPanel.tsx` 当前是 8 地点的占位网格。等瓦片美术就绪后，可把 Phaser 实例嵌入该组件。
3. **无人机模式（自动 step）未做**：当前必须手动点"子时→辰时→申时"。可加一个"自动推进"按钮。
4. **多用户隔离**：内存会话注册表无鉴权，任何人能看任何 game 的私密 log。给生产环境部署前需要加 token。
5. **`run` 阻塞**：`/api/games/{id}/run` 跑完整局会阻塞数十秒到数分钟。前端已用 WebSocket 看进度，但建议用 `step` 一段一段推。

## 与原 CLI 的关系

`start.py` 还能用，跑一局完整流程并写检查点。FastAPI 服务并不取代它，而是把同一份 `WerewolfDirector` 暴露成可控的 API。
两者不会冲突——只要不同时跑（因为单例）。

## 与旧 Flask 回放（`replay.py`）的关系

`replay.py` + `frontend/templates/` 提供基于 Phaser 的"录像回放"功能，**只读历史 checkpoint**。
新前端是**实时控制台**，定位互补。建议在 Phaser 接入新前端后再下线旧回放。

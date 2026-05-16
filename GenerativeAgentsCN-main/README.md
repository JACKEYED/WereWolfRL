<!-- 文件作用：项目总说明。面向开发者介绍江南古镇版 12 人狼人杀的目标、安装、运行、架构、测试和协作流程。 -->

# 江南古镇狼人杀（Generative Agents 中文版）

一个基于 Generative Agents 小镇思想改造的 **12 人狼人杀真实社交模拟项目**。

目标不是一个简单的文字版狼人杀，而是让多个 AI Agent 在民国江南古镇的地图中移动、观察、私聊、形成记忆，并基于这些经历参与白天发言、质疑、辩论、投票和夜晚技能决策。本项目最终用于训练**本地 Qwen-7B Agent** 与固定 API 对手对弈的强化学习实验。

## 核心特性

- **双场景模式（scene_mode）**：
  - `social`（默认）：完整江南古镇叙事，含开场社交、辩论质疑、申时余韵、NPC 流言——**演示 / 回放 / 可观赏性**
  - `game`（v1）：纯狼人杀，跳过开场社交和申时余韵，辩论缩到 2 轮，中性现代汉语 prompt，禁用流言——**RL 训练专用，去掉对训练有噪声的叙事冗余**
- **12 人标准板**：4 狼人、预言家、女巫、猎人、守卫、4 村民；遵守同守同救、女巫一夜一药、猎人被毒禁枪等标准规则。
- **江南古镇空间模拟**（social 模式）：8 个地点（镇中广场、听雨茶馆、同德医馆、观星楼、更夫房、后山染坊、码头夜市、归云客栈）+ 乱葬岗。
- **时辰阶段制**（social 模式）：卯/辰/申/戌/子 六段制，神职夜行动绑定专属地点。
- **现代中性命名**（game 模式）：广场 / 茶馆 / 制药室 / 神职房 / 值夜房 / 狼人议事室 / 市场 / 客栈 / 墓地；阶段标签"第N天 夜晚/白天/破晓"。
- **非正式社交**：Agent 会在黄昏（申时）私聊，局部对话只对在场的人形成记忆。
- **NPC 流言系统**：4 个 NPC（医馆小哑巴、染坊老染工、观星楼老仆、巡街更夫）按"保守扭曲"规则在清晨广场散播线索（保留时间地点，隐去姓名）。
- **公开议会**：幸存玩家在镇中广场依次发言、质疑、辩论、投票，含平票辩解 + 二轮全场投票。
- **独立记忆**：每个 Agent 只知道自己身份、公开信息、自己参与过的私聊和自己的技能结果。
- **回放与控制台两种界面**：
  - **CLI + Flask 回放**（既有）：跑完一局后浏览器看录像
  - **FastAPI + React 控制台**（新增）：浏览器实时操控、订阅事件、单步推进
- **支持 OpenAI 兼容 API**：DeepSeek、OpenAI、Ollama、硅基流动、OpenRouter 等。

## 默认角色（民国江南 12 人）

| # | 姓名 | 年龄 | 民国职业 |
|---|------|---:|------|
| 1 | 陈砚秋 | 38 | 私塾先生 |
| 2 | 苏蘅 | 25 | 茶馆雅间清客 |
| 3 | 林宛娘 | 31 | 同德医馆郎中 |
| 4 | 周文卿 | 42 | 钱庄帐房 |
| 5 | 孟雨棠 | 22 | 染坊织娘 |
| 6 | 沈鹤年 | 50 | 退役镖师 / 更夫 |
| 7 | 阿福 | 19 | 客栈跑堂 |
| 8 | 温知微 | 29 | 戏班正旦 |
| 9 | 白潜舟 | 35 | 乌篷船夫 |
| 10 | 徐慎之 | 27 | 外乡药商 |
| 11 | 柳青禾 | 33 | 杂货铺女当家 |
| 12 | 吴掌柜 | 45 | 听雨茶馆掌柜 |

身份（狼 / 神 / 民）随机分配，与人物职业解耦。

默认身份牌：

| 阵营 | 身份 | 数量 |
|---|---|---:|
| 狼人阵营 | 狼人 | 4 |
| 好人阵营 | 预言家 | 1 |
| 好人阵营 | 女巫 | 1 |
| 好人阵营 | 猎人 | 1 |
| 好人阵营 | 守卫 | 1 |
| 好人阵营 | 村民 | 4 |

## 项目结构

```text
GenerativeAgentsCN-main/
├── README.md                              # 本文件
├── LICENSE
├── requirements.txt                       # Python 依赖
├── docs/
│   ├── technical.md                       # 技术架构文档
│   ├── werewolf.md                        # 狼人杀玩法和运行说明
│   └── ollama.md                          # Ollama 配置说明
└── generative_agents/
    ├── start.py                           # CLI 入口：一局完整流程
    ├── compress.py                        # 把 checkpoint 压缩成回放数据
    ├── replay.py                          # 启动旧 Flask 回放服务
    ├── data/config.json                   # LLM 和 embedding 配置
    │
    ├── modules/
    │   ├── werewolf/                      # ★ 路 1 重构后的规则引擎包
    │   │   ├── __init__.py                # 包入口（仅暴露纯模块）
    │   │   ├── locations.py               # 8 江南地点常量 + 显示名映射
    │   │   ├── rules.py                   # ROLE_DECK / 同守同救 / 胜负判定（纯函数）
    │   │   ├── player.py                  # WerewolfPlayer + 开局简报 + 兜底发言
    │   │   ├── text_utils.py              # clean_text / match_choice / join_names
    │   │   ├── recorder.py                # 日志、对话、检查点、Markdown 报告
    │   │   ├── llm_io.py                  # ask_text / ask_choice + prompt 构造
    │   │   ├── phases/
    │   │   │   ├── night.py               # 子时（狼/守/预/女/猎）+ 流言派发
    │   │   │   ├── day.py                 # 辰时议会 + 平票二轮
    │   │   │   └── social.py              # 申时自由活动 + 私聊小组
    │   │   └── director.py                # WerewolfDirector 状态壳 + 主循环
    │   ├── gossip.py                      # NPC 流言模块（保守扭曲）
    │   ├── agent.py                       # Agent 运行时状态
    │   ├── game.py                        # 小镇 Game 容器（全局单例）
    │   ├── maze.py                        # 地图 / 寻路
    │   ├── memory/                        # 事件 / 动作 / 空间 / 向量记忆
    │   ├── storage/                       # LlamaIndex 向量索引
    │   ├── model/llm_model.py             # LLM API 封装
    │   └── utils/                         # 日志 / 时间 / 参数
    │
    ├── api/                               # ★ 路 2 FastAPI 后端
    │   ├── __init__.py
    │   ├── server.py                      # REST + WebSocket 路由
    │   └── sessions.py                    # 内存会话 + 事件总线
    │
    ├── web/                               # ★ 路 2 React + Vite + TS 前端
    │   ├── package.json
    │   ├── vite.config.ts
    │   ├── tsconfig.json
    │   ├── index.html
    │   └── src/
    │       ├── main.tsx
    │       ├── App.tsx                    # 三栏布局 + 顶部控制
    │       ├── api.ts                     # REST + WebSocket 客户端
    │       ├── types.ts                   # 与 server.py 对齐的 TS 类型
    │       ├── styles.css
    │       └── components/
    │           ├── MapPanel.tsx           # 8 地点占位（Phaser 接入预留）
    │           ├── TimelinePanel.tsx      # 事件实时流
    │           └── AgentPanel.tsx         # 角色芯片 + 私密视角
    │
    ├── frontend/                          # 旧 Flask 回放（保留兼容）
    │   ├── templates/                     # Phaser 回放页面
    │   └── static/assets/village/
    │       ├── maze.json                  # 江南古镇瓦片地址（路 0 已迁移）
    │       └── agents/<名字>/             # 12 民国 persona 文件夹
    │
    └── test/
        └── test_werewolf_pure.py          # 43 个纯模块单元测试
```

## 环境要求

- Python 3.12（或 3.13）
- Node.js 18+（**仅前端需要**）
- 可访问你选择的大模型 API
- Windows / macOS / Linux

### 安装 Python 依赖

```bash
cd D:\code\bytedance\GenerativeAgentsCN-main
pip install -r requirements.txt
# 路 2 新增依赖（FastAPI 服务）
pip install fastapi "uvicorn[standard]"
```

### 安装前端依赖（可选，只在用 React 控制台时需要）

```bash
cd generative_agents/web
npm install
```

## API 配置

```text
generative_agents/data/config.json
```

### 使用 DeepSeek

推荐先用 DeepSeek 的非工具调用普通聊天模式。本项目已经改成本地解析 JSON，不再发送 `tool_choice`。

```json
{
  "agent": {
    "percept": { "mode": "box", "vision_r": 8, "att_bandwidth": 8 },
    "schedule": { "max_try": 5, "diversity": 5 },
    "think": {
      "llm": {
        "provider": "openai",
        "model": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "api_key": "你的 DeepSeek API Key"
      },
      "interval": 1000,
      "poignancy_max": 150
    },
    "chat_iter": 4,
    "associate": {
      "embedding": {
        "provider": "ollama",
        "model": "qwen3-embedding:0.6b-q8_0",
        "base_url": "http://127.0.0.1:11434",
        "api_key": ""
      },
      "retention": 8
    }
  }
}
```

推荐先用 `--no-memory` 跑通主流程（只需配置 LLM，不需配置 embedding）：

```bash
python start.py --name ww-demo --no-memory
```

### 使用 Ollama

参考 [`docs/ollama.md`](docs/ollama.md)。

## 一键启动（最快路径）

项目根目录提供了 `run.sh`，**仅负责启动，不管装依赖**。请先按上文"环境要求"和"运行方式 B"装好 Python / Node 依赖。

```bash
cd D:\code\bytedance\GenerativeAgentsCN-main
bash run.sh up           # 同时启后端 :8000 和前端 :5173；Ctrl+C 一并停
```

其他子命令：

```bash
bash run.sh test         # 跑 43 个纯模块 pytest
bash run.sh smoke        # 跑一局 CLI 烟雾测试（不调 LLM）
bash run.sh backend      # 仅启后端
bash run.sh frontend     # 仅启前端
bash run.sh help         # 显示帮助
```

> Windows 用户在 Git Bash / WSL 中执行。`./run.sh up` 也行（已设置可执行权限）。

如果想分开看两个进程的日志、或者要自定义端口，跳到下面"运行方式 A / B"自己拼。

## 运行方式 A：CLI 一口气跑完

进入运行目录：

```bash
cd generative_agents
```

跑完整一局：

```bash
python start.py --name ww-demo
```

快速烟雾测试（不调 LLM、不写向量记忆）：

```bash
python start.py --name ww-smoke --no-llm --no-memory
```

固定随机种子复现：

```bash
python start.py --name ww-seed-7 --seed 7
```

跑完后生成回放：

```bash
python compress.py --name ww-demo
python replay.py
# 浏览器打开 http://127.0.0.1:5000/?name=ww-demo
```

## 运行方式 B：FastAPI + React 控制台（实时）

打开两个终端。

**终端 A —— 后端：**

```bash
cd generative_agents
uvicorn api.server:app --reload --port 8000
```

- REST API：`http://127.0.0.1:8000`
- 自动生成的 OpenAPI 文档：`http://127.0.0.1:8000/docs`
- WebSocket：`ws://127.0.0.1:8000/ws/games/{id}`

**终端 B —— 前端：**

```bash
cd generative_agents/web
npm run dev
# 浏览器打开 http://127.0.0.1:5173
```

Vite dev server 会把 `/api` 和 `/ws` 自动代理到 `127.0.0.1:8000`，无跨域配置负担。

### 控制台操作

1. 点右上"新开一局（不调 LLM）"——后端创建对局，分配身份，把所有 Agent move 到家
2. 点"申时·开场"——3 轮黄昏自由活动
3. 点"子时·夜"——夜晚（狼/守/预/女/猎）+ 死亡结算 + NPC 流言
4. 点"辰时·议会"——白天发言/质疑/投票
5. 点"申时·余韵"——2 轮黄昏私聊
6. 重复 3-5 直到决出胜负

事件通过 WebSocket 实时推送，时间线滚动、地图占用、角色面板自动更新。

详细架构与接口规范见 [`docs/frontend_backend.md`](generative_agents/docs/frontend_backend.md)。

## 输出文件

原始模拟数据：

```text
generative_agents/results/checkpoints/<局名>/
├── simulate-*.json       # 每个阶段的完整状态
├── conversation.json     # 公开发言 + 私聊 + 狼人夜谈
├── werewolf_state.json   # 最新狼人杀状态
└── werewolf_report.md    # Markdown 复盘报告
```

压缩回放数据：

```text
generative_agents/results/compressed/<局名>/
├── movement.json         # 网页回放使用
└── simulation.md         # 按时间线整理的文字记录
```

## 自定义身份

写一个身份 JSON，例如 `roles.json`：

```json
{
  "陈砚秋": "seer",
  "苏蘅": "werewolf",
  "林宛娘": "witch",
  "周文卿": "villager",
  "孟雨棠": "werewolf",
  "沈鹤年": "guard",
  "阿福": "villager",
  "温知微": "werewolf",
  "白潜舟": "hunter",
  "徐慎之": "werewolf",
  "柳青禾": "villager",
  "吴掌柜": "villager"
}
```

```bash
python start.py --name ww-fixed --role-map roles.json
```

可用身份键：`werewolf | seer | witch | hunter | guard | villager`

## 常用参数（start.py）

| 参数 | 作用 |
|---|---|
| `--name` | 本局游戏名称（存档和回放名）。 |
| `--seed` | 固定随机种子，方便复现实验。 |
| `--players` | 自定义 12 名玩家，使用英文逗号分隔。 |
| `--role-map` | 指定身份分配 JSON。 |
| `--no-llm` | 不调大模型，使用规则兜底，适合流程测试。 |
| `--no-memory` | 关闭向量长期记忆，只使用局内上下文。 |
| `--scene` | `game`（默认，纯狼人杀 RL 训练版）/ `social`（江南叙事完整版） |
| `--verbose` | 日志等级：`debug` / `info` / `warn` / `error`。 |
| `--log` | 把日志写入文件。 |

## 记忆说明

默认情况下，Agent 有两类记忆：

- **局内上下文**：身份、公开信息、私聊、技能结果、投票和死亡信息。
- **向量长期记忆**：把 Agent 亲身经历过的事件写入 LlamaIndex，通过 embedding 语义检索。

`--no-memory` 后：

- 仍保留局内上下文
- 不写向量数据库
- 不进行 embedding 检索
- Agent 不会变成全知

每个 Agent 只知道自己应该知道的信息，不会自动知道完整身份表。

## RL 训练基础设施（路 3）

### Belief / Reward / Trajectory 三件套

每个 Agent 维护**对其他 11 名玩家身份的概率分布**（`belief_state`），LLM 在每个阶段末重新评估这个分布。决策点（发言 / 投票 / 技能）被记成 `(obs, action, reward)` 三元组，写入 `trajectories.json`，可被 SFT / DPO / GRPO 流水线直接消费。

```
generative_agents/modules/werewolf/
├── beliefs.py       # BeliefState + 初始先验 + 锁定 + 归一化
├── llm_judge.py     # 中颗粒度 belief 更新（每阶段末，每听众一次 LLM 调用）
├── reward.py        # 狼/神/民 三阵营的 step + episode reward
└── trajectory.py    # TrajectoryRecorder（决策点收集 + 局末回填）
```

### Belief 更新流程

```
阶段开始 ──▶ 决策点 ──▶ 决策点 ──▶ 阶段末
   │           │           │           │
   prior     trajectory  trajectory   end_of_phase
   belief     step       step          │
                                       ├─ LLM judge × N 听众 → posterior belief
                                       ├─ step reward = belief shift
                                       └─ 回填到本阶段 trajectory steps
```

### 三档颗粒度

| 颗粒度 | 触发 | 一局调用 | 成本 |
|---|---|---:|---:|
| 细 | 每条发言 → 每听众一次 | ~1500 | $1 |
| **中**（当前实现）| **每阶段末 → 每存活听众一次** | **~200** | **$0.15** |
| 粗 | 每天末 → 每听众一次 | ~70 | $0.05 |

### Reward 设计

| 决策 | 狼人 | 好人阵营 |
|---|---|---|
| 自由发言 | 别人对自己 `P(werewolf)` 下降 → 正 reward | 别人对真狼的 `P(werewolf)` 上升 → 正 reward |
| 投票 | 投同伴 -1，投好人 +0.5 | 投狼 +1，投同阵营 -0.3 |
| 夜间技能 | 刀好人 +0.7，刀同伴 -2 | 预言家查狼 +1；女巫毒狼 +1、毒好人 -1.5；守对 +1 |
| 局末加奖 | 阵营赢 +1，输 -1 | 同左 |

### 训练数据格式

每局结束后写到 `results/checkpoints/<局名>/trajectories.json`：

```json
{
  "steps": [
    {
      "step_id": 17,
      "agent": "陈砚秋",
      "phase": "第2日辰时议会",
      "day": 2,
      "decision_type": "speech",
      "obs": {
        "my_role": "seer",
        "my_belief": { "holder": "陈砚秋", "beliefs": {...}, "locked": {...} },
        "public_log_tail": [...],
        "private_log_tail": [...],
        "alive": [...]
      },
      "candidates": null,
      "action": "我倾向于先听阿福解释昨夜在码头夜市的去向……",
      "reward_step": 0.18,
      "reward_episode": 1.0
    }
  ],
  "count": 312
}
```

### API 端点

```
GET /api/games/{id}/agent/{name}        # 该 Agent 的 belief + 最近 30 步 trajectory
GET /api/games/{id}/trajectories        # 完整轨迹 JSON（RL 流水线用）
```

### 前端展示

AgentPanel 现在多两栏：
- **心里的怀疑表**：6×11 概率矩阵，最高概率高亮、锁定行斜体
- **最近 12 个决策点**：每步动作 + step reward（红色负，绿色正）

## 测试

跑纯模块单元测试（不依赖 LLM / Phaser / 任何外部服务）：

```bash
cd generative_agents
python -m pytest test/ -v
```

**当前 130 个测试用例**全过：
- 43 个 路 1 重构（locations / text_utils / rules / player）
- 36 个 路 3 RL 三件套（beliefs / reward / trajectory）
- 18 个 v1 scene_mode（双套显示名 / 双 prompt 套 / phase_label 派发 / behavior rules）
- 15 个并行多 game（ActiveGameContext / GameRegistry / 8 线程隔离压力测试）
- 18 个 GRPO 训练管线（RLConfig / GroupRecord / ReplayBuffer / 累计 reward / GRPO loss 数学）

跑一局烟雾测试（要装好依赖）：

```bash
python start.py --name smoke --no-llm --no-memory
```

## 架构亮点（路 1 + 路 2 重构）

**路 1：werewolf.py 模块化**

| 项 | 重构前 | 重构后 |
|---|---:|---:|
| 最大单文件行数 | **1240** | **410**（director.py） |
| 文件数 | 1 | 12 |
| God Class | ✅ WerewolfDirector | ❌ 已拆 |
| pytest 覆盖 | 0 | 43 ✅ |

**路 2：FastAPI + React 控制台**

| 能力 | CLI 模式 | 控制台模式 |
|---|---|---|
| 看一局怎么打的 | 跑完看 replay | 实时 WebSocket 滚动 |
| 单步调试某夜晚 | 改代码加 breakpoint | 前端按一阶段一推 |
| 暴露给训练流水线 | 改 start.py | curl `/api/games/{id}/step` |
| 多前端复用 | 不支持 | OpenAPI 自动生成 |

## 已知限制

1. **同进程不能并行多局**：`modules/game.py` 仍是全局单例。多局并行需要后续重构。
2. **MapPanel 是占位**：Phaser 还没嵌入 React，等瓦片美术。
3. **无鉴权**：内存会话表无 token，生产部署前需加。
4. **`/api/.../run` 阻塞**：长任务跑完才返回，建议改用 `/step` 分段推。
5. **`--seed` 不完全可复现**：LLM `temperature > 0` 时同 seed 两次结果可能不同。
6. **Belief 更新依赖 LLM**：路 3 的 belief 评判走 LLM，`--no-llm` 模式下不更新，trajectory 的 step_reward 会偏弱。

## GitHub 协作建议

首次上传：

```bash
cd D:\code\bytedance\GenerativeAgentsCN-main
git init
git branch -M main
git add .
git commit -m "init 江南古镇 12 人狼人杀（含模块化重构和前后端）"
git remote add origin https://github.com/你的用户名/你的仓库名.git
git push -u origin main
```

日常开发：

```bash
git pull --rebase origin main
git checkout -b feature/你的功能名
git add .
git commit -m "说明这次修改"
git push origin feature/你的功能名
```

然后在 GitHub 上创建 Pull Request。

## 安全注意

不要把真实 API Key 提交到 GitHub，尤其不要提交：

```text
sk-xxxxxxxx
```

如果 Key 已经暴露，立刻去服务商控制台删除或重置。

## 更多文档

- [`docs/technical.md`](docs/technical.md) —— 技术架构和扩展点
- [`docs/werewolf.md`](docs/werewolf.md) —— 狼人杀玩法和自定义配置
- [`docs/ollama.md`](docs/ollama.md) —— Ollama 本地模型配置
- [`generative_agents/docs/frontend_backend.md`](generative_agents/docs/frontend_backend.md) —— 前后端接口与运行细节

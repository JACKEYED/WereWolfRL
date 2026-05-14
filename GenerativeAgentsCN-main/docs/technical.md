<!-- 文件作用：说明斯坦福小镇版狼人杀的工程架构、数据流、核心模块和扩展点。 -->

# 技术文档

本文档说明“斯坦福小镇版狼人杀”的工程结构、运行链路和主要扩展点。

## 项目目标

本项目把 Stanford Generative Agents 式小镇环境改造成一局空间化狼人杀。Agent 会在小镇地图中移动、进行公开或私密对话、写入记忆，并根据身份目标完成夜晚技能、白天发言、辩论与投票。

## 核心运行流程

1. `python start.py --name <局名>` 启动一局完整狼人杀。
   `start.py` 读取 `data/config.json` 中的大模型和记忆配置，加载默认 12 名玩家。
   `modules.werewolf.WerewolfDirector` 创建小镇 `Game`，分配身份，驱动整局游戏。
   每个阶段都会写出 checkpoint 到 `results/checkpoints/<局名>/`。
2. `python compress.py --name <局名>` 将 checkpoint 转换成网页回放数据。
3. `python replay.py` 启动 Flask 服务，通过 `http://127.0.0.1:5000/?name=<局名>` 回放。
简单地说：
start.py    = 生成一局游戏
compress.py = 整理成回放文件
replay.py   = 打开网页回放服务

## 游戏导演

`generative_agents/modules/werewolf.py` 是本项目最核心的文件，负责：

- 身份牌：4 狼、预言家、女巫、猎人、守卫、4 村民。
- 地点：村庄广场、狼人房间、神职房间、女巫房间、酒吧、咖啡馆、市场等。
- 夜晚：狼人协商击杀、守卫守护、预言家查验、女巫救/毒、猎人等待。
- 白天：集合、顺序发言、质疑辩论、投票、平票辩解和二轮投票。
- 非正式社交：按小组移动到不同地点并产生局部私聊记忆。
- 胜负：狼人全灭则好人胜；狼人数量不少于好人数量则狼人胜。

`SAFETY_DAY_LIMIT` 是内部安全上限，只用于防止异常情况下无限循环，不是用户玩法参数。

## Agent 与记忆

`modules/agent.py` 现在是轻量角色运行时，不再保留旧日常生活模拟的复杂日程引擎。它主要负责：

- 保存人设、当前状态、坐标、动作。
- 持有 LLM 客户端。
- 持有空间记忆和向量记忆。
- 为 checkpoint 提供可序列化状态。

记忆相关文件在 `modules/memory/`：

- `event.py`：事件数据结构。
- `action.py`：持续动作和结束时间。
- `spatial.py`：地点树和居住地记忆。
- `associate.py`：基于 LlamaIndex 的向量记忆。
- `__init__.py`：提供 `NullAssociate`，用于 `--no-memory` 快速测试。

## LLM 调用

`modules/model/llm_model.py` 封装大模型调用。

配置位置：

```text
generative_agents/data/config.json
```

`llm` 配置控制 Agent 决策和发言。`embedding` 配置控制向量记忆。若暂时不想配置 embedding，可使用：

```bash
python start.py --name ww-demo --no-memory
```
```text
存入memory长期记忆说明：
--no-memory 只是关闭“向量长期记忆”。

每个 Agent 仍然只会拿到它该知道的信息：
自己的身份
自己阵营该知道的信息，比如狼人知道狼队友
公开信息，比如白天发言、投票、死亡公告
自己参与过的私聊
自己的技能结果，比如预言家查验结果、女巫用药记录、守卫守护记录

它不会知道：
其他人的真实身份
其他地点发生的私聊
狼人夜晚讨论，除非自己是狼人
预言家查验结果，除非自己是预言家
女巫/守卫夜间选择，除非自己本人就是该角色
系统完整身份表
--no-memory 的区别只是：这些信息不会再被写进向量数据库做长期语义检索。
```


`--no-llm` 会使用规则兜底发言和选择，适合测试流程，但不适合正式体验。

## 地图与回放

地图资源位于：

```text
generative_agents/frontend/static/assets/village/
```

关键数据：

- `maze.json`：后端寻路、地点索引、碰撞信息。
- `tilemap/tilemap.json`：前端 Phaser 地图。
- `agents/<姓名>/agent.json`：角色人设、初始坐标、居住地和空间树。

回放链路：

- `compress.py` 读取 checkpoint 和 `conversation.json`。
- 生成 `results/compressed/<局名>/movement.json` 和 `simulation.md`。
- `replay.py` 读取 `movement.json` 并渲染 `frontend/templates/index.html`。
- `main_script.html` 用 Phaser 展示地图、角色移动和对话。

## 数据目录

```text
results/checkpoints/<局名>/
```

保存原始模拟阶段数据：

- `simulate-*.json`
- `conversation.json`
- `werewolf_state.json`
- `werewolf_report.md`

```text
results/compressed/<局名>/
```

保存回放数据：

- `movement.json`
- `simulation.md`

## 扩展建议

- 新增角色：从 `ROLE_DECK`、`ROLE_NAMES`、`ROLE_GOALS` 和夜晚行动函数入手。
- 新增地点：在 `LOCATIONS` 和 `SOCIAL_SPOTS` 中加入已有地图地址。
- 改发言风格：调整 `build_agent_prompt()` 中的身份目标、公开时间线、私密记忆和输出约束。
- 改胜负条件：修改 `check_win()`。
- 接入其他模型：修改 `data/config.json`，优先使用 OpenAI 兼容 API。

<!-- 文件作用：项目总说明，面向开发者和队友介绍斯坦福小镇版狼人杀的目标、安装、配置、运行、回放、目录结构和协作流程。 -->

# 斯坦福小镇版狼人杀

这是一个基于 Generative Agents 小镇思想改造的 **12 人狼人杀真实社交模拟项目**。

项目目标不是做一个简单的文字版狼人杀，而是让多个 AI Agent 在小镇地图中移动、观察、私聊、形成记忆，并基于这些经历参与白天发言、质疑、辩论、投票和夜晚技能决策。

## 核心特性

- 12 人标准局：4 狼人、预言家、女巫、猎人、守卫、4 村民。
- 小镇空间模拟：广场、酒吧、咖啡馆、药店、学院、宿舍公共休息室等真实地点。
- 非正式社交：Agent 会在白天/黄昏阶段私聊，局部对话会影响后续推理。
- 公开议会：幸存玩家在广场集合，依次发言、质疑、辩论、投票。
- 夜晚行动：狼人会面、预言家查验、女巫救/毒、守卫守护、猎人死亡触发。
- 独立记忆：每个 Agent 只知道自己身份、公开信息、自己参与过的私聊和自己的技能结果。
- 可回放：模拟完成后可生成地图回放数据，并在浏览器中观看角色移动和对话。
- 支持 OpenAI 兼容 API：可接入 DeepSeek、OpenAI、Ollama、硅基流动、OpenRouter 等服务。

## 默认角色

默认 12 名玩家：

```text
亚当, 阿比盖尔, 伊莎贝拉, 亚瑟, 简, 汤姆, 山姆, 詹妮弗, 弗朗西斯科, 拉吉夫, 拉托亚, 山本百合子
```

默认身份牌数量：

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
├─ README.md                         # 项目总说明
├─ requirements.txt                  # Python 依赖
├─ docs/
│  ├─ technical.md                   # 技术架构文档
│  ├─ werewolf.md                    # 狼人杀玩法和运行说明
│  └─ ollama.md                      # Ollama 配置说明
└─ generative_agents/
   ├─ start.py                       # 一局狼人杀主入口
   ├─ compress.py                    # 将 checkpoint 压缩成回放数据
   ├─ replay.py                      # 启动网页回放服务
   ├─ data/config.json               # LLM 和 embedding 配置
   ├─ modules/
   │  ├─ werewolf.py                 # 狼人杀导演、规则和阶段控制
   │  ├─ agent.py                    # Agent 运行时状态
   │  ├─ game.py                     # 小镇 Game 容器
   │  ├─ maze.py                     # 地图、地点和寻路
   │  ├─ model/llm_model.py          # LLM API 封装
   │  ├─ memory/                     # 事件、动作、空间和向量记忆
   │  ├─ storage/                    # LlamaIndex 向量索引
   │  └─ utils/                      # 日志、时间、参数工具
   └─ frontend/
      ├─ templates/                  # Flask + Phaser 回放页面
      └─ static/assets/village/      # 地图、角色贴图、人设 JSON
```

## 环境要求

建议环境：

- Python 3.12
- Windows / macOS / Linux
- 可访问你选择的大模型 API

安装依赖：

```bash
cd D:\code\bytedance\GenerativeAgentsCN-main
pip install -r requirements.txt
```

## API 配置

配置文件：

```text
generative_agents/data/config.json
```

### 使用 DeepSeek

推荐先用 DeepSeek 的非工具调用普通聊天模式，本项目已经改成本地解析 JSON，不再发送 `tool_choice`。

示例：

```json
{
  "agent": {
    "percept": {
      "mode": "box",
      "vision_r": 8,
      "att_bandwidth": 8
    },
    "schedule": {
      "max_try": 5,
      "diversity": 5
    },
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

推荐先使用 `--no-memory` 跑通主流程，这样只需要配置 LLM，不需要配置 embedding：

```bash
python start.py --name ww-demo --no-memory
```

### 使用 Ollama

如果使用本地 Ollama，可参考：

```text
docs/ollama.md
```

## 运行一局狼人杀

进入运行目录：

```bash
cd D:\code\bytedance\GenerativeAgentsCN-main\generative_agents
```

运行完整一局：

```bash
python start.py --name ww-demo
```

如果不传 `--name`，程序会自动生成本局名称：

```bash
python start.py
```

快速测试，不调用 LLM、不启用向量记忆：

```bash
python start.py --name ww-smoke --no-llm --no-memory
```

固定随机种子：

```bash
python start.py --name ww-seed-7 --seed 7
```

## 生成回放

模拟完成后，先压缩数据：

```bash
python compress.py --name ww-demo
```

然后启动回放服务：

```bash
python replay.py
```

浏览器打开：

```text
http://127.0.0.1:5000/?name=ww-demo
```

## 输出文件

原始模拟数据：

```text
generative_agents/results/checkpoints/<局名>/
```

包括：

- `simulate-*.json`：每个阶段的完整状态。
- `conversation.json`：公开发言、私聊、狼人夜谈等对话。
- `werewolf_state.json`：最新狼人杀状态。
- `werewolf_report.md`：文字复盘报告。

压缩回放数据：

```text
generative_agents/results/compressed/<局名>/
```

包括：

- `movement.json`：网页回放使用的移动数据。
- `simulation.md`：按时间线整理的文字记录。

## 自定义身份

可以写一个身份 JSON，例如 `roles.json`：

```json
{
  "亚当": "seer",
  "阿比盖尔": "werewolf",
  "伊莎贝拉": "witch",
  "亚瑟": "villager",
  "简": "guard",
  "汤姆": "werewolf",
  "山姆": "hunter",
  "詹妮弗": "villager",
  "弗朗西斯科": "werewolf",
  "拉吉夫": "villager",
  "拉托亚": "werewolf",
  "山本百合子": "villager"
}
```

运行：

```bash
python start.py --name ww-fixed --role-map roles.json
```

可用身份键：

```text
werewolf, seer, witch, hunter, guard, villager
```

## 常用参数

| 参数 | 作用 |
|---|---|
| `--name` | 本局游戏名称，也就是存档和回放名称。 |
| `--seed` | 固定随机种子，方便复现实验。 |
| `--players` | 自定义 12 名玩家，使用英文逗号分隔。 |
| `--role-map` | 指定身份分配 JSON。 |
| `--no-llm` | 不调用大模型，使用规则兜底，适合流程测试。 |
| `--no-memory` | 关闭向量长期记忆，只使用局内上下文，适合先跑通 API。 |
| `--verbose` | 日志等级，如 `debug`、`info`、`warn`。 |
| `--log` | 把日志写入文件。 |

## 记忆说明

默认情况下，Agent 有两类记忆：

- 局内上下文：身份、公开信息、私聊、技能结果、投票和死亡信息。
- 向量长期记忆：把 Agent 亲身经历过的事件写入 LlamaIndex，通过 embedding 语义检索。

使用 `--no-memory` 后：

- 仍然保留局内上下文。
- 不写入向量数据库。
- 不进行 embedding 检索。
- 不会让 Agent 变成全知。

每个 Agent 只知道自己应该知道的信息，不会自动知道完整身份表。

## GitHub 协作建议

首次上传：

```bash
cd D:\code\bytedance\GenerativeAgentsCN-main
git init
git branch -M main
git add .
git commit -m "init stanford town werewolf"
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

然后在 GitHub 上创建 Pull Request，由队友 Review 后合并。

## 安全注意

不要把真实 API Key 提交到 GitHub。

尤其不要提交：

```text
sk-xxxxxxxx
```

如果 Key 已经暴露，建议立刻去服务商控制台删除或重置。

## 更多文档

- `docs/technical.md`：技术架构和扩展点。
- `docs/werewolf.md`：狼人杀玩法和自定义配置。
- `docs/ollama.md`：Ollama 本地模型配置。

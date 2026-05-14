<!-- 文件作用：项目总说明，介绍斯坦福小镇版狼人杀的玩法、安装、运行、回放和配置入口。 -->

# 斯坦福小镇版狼人杀

这是一个把 Generative Agents 小镇改造成 12 人狼人杀社会推理环境的项目。玩家不是简单按座次发言，而是在小镇地图中移动、观察、私聊、形成记忆，然后再进入白天议会和夜晚技能阶段。

## 玩法

固定 12 人局：

- 4 狼人
- 1 预言家
- 1 女巫
- 1 猎人
- 1 守卫
- 4 村民

空间化流程：

- 白天：所有幸存玩家在约翰逊公园集合，依次发言、质疑、辩论、投票。
- 夜晚：狼人进入玫瑰酒吧的狼人房间商量击杀；预言家和守卫在神职房间行动；女巫在药店房间决定救人或毒人；猎人等待死亡触发。
- 平时：玩家会在酒吧、咖啡馆、市场、公园、宿舍公共休息室等地点产生非正式对话，这些局部信息会进入后续推理。

默认玩家：

```text
亚当, 阿比盖尔, 伊莎贝拉, 亚瑟, 简, 汤姆, 山姆, 詹妮弗, 弗朗西斯科, 拉吉夫, 拉托亚, 山本百合子
```

## 安装

建议使用 Python 3.12。

```bash
pip install -r requirements.txt
```

配置大模型 API：

编辑 `generative_agents/data/config.json`。默认使用 Ollama 的 OpenAI 兼容接口；如果使用其他 OpenAI 兼容服务，把 `provider` 设为 `openai`，并填写 `model`、`base_url`、`api_key`。

Ollama 安装和模型下载可参考 `docs/ollama.md`。

工程结构和扩展点可参考 `docs/technical.md`。

## 运行

```bash
cd generative_agents
python start.py --name ww-demo
```

快速结构测试，不调用 LLM：

```bash
python start.py --name ww-smoke --no-llm --no-memory
```

固定随机种子：

```bash
python start.py --name ww-seed-7 --seed 7
```

如果不传 `--name`，程序会自动生成本局名称并在结束时打印出来。狼人杀会从开局自动跑到胜负结算，开局时间和回放步长只是内部回放标尺，不需要手动指定。

## 回放

生成回放数据：

```bash
python compress.py --name ww-demo
```

启动回放服务：

```bash
python replay.py
```

浏览器打开：

```text
http://127.0.0.1:5000/?name=ww-demo
```

## 输出

运行后会生成：

- `generative_agents/results/checkpoints/<name>/simulate-*.json`
- `generative_agents/results/checkpoints/<name>/conversation.json`
- `generative_agents/results/checkpoints/<name>/werewolf_state.json`
- `generative_agents/results/checkpoints/<name>/werewolf_report.md`

压缩后会生成：

- `generative_agents/results/compressed/<name>/movement.json`
- `generative_agents/results/compressed/<name>/simulation.md`

## 自定义身份

可以传入固定身份 JSON：

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

```bash
python start.py --name ww-fixed --role-map roles.json
```

可用身份键：`werewolf`、`seer`、`witch`、`hunter`、`guard`、`villager`。

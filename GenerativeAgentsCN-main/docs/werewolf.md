<!-- 文件作用：说明空间化狼人杀模式的角色配置、运行命令、输出文件和自定义身份方式。 -->

# 真实社交狼人杀模拟

这个模式把原本的小镇生活系统改造成一个 12 人狼人杀社会推理环境。Agent 不只是轮流发言，而是会在地图中移动、观察、私聊、形成记忆，再把这些记忆带入白天发言、辩论、投票和夜晚技能决策。

## 角色配置

默认 12 人身份：

- 4 狼人
- 1 预言家
- 1 女巫
- 1 猎人
- 1 守卫
- 4 村民

默认玩家：

```text
亚当, 阿比盖尔, 伊莎贝拉, 亚瑟, 简, 汤姆, 山姆, 詹妮弗, 弗朗西斯科, 拉吉夫, 拉托亚, 山本百合子
```

## 运行

在 `generative_agents` 目录运行：

```bash
python start.py --name ww-demo
```

如果只想做不调用 LLM、不写入向量记忆的快速结构测试：

```bash
python start.py --name ww-smoke --no-llm --no-memory
```

生成回放数据：

```bash
python compress.py --name ww-demo
python replay.py
```

回放地址示例：

```text
http://127.0.0.1:5000/?name=ww-demo
```

## 输出

运行后会生成：

- `results/checkpoints/<name>/simulate-*.json`：可被回放压缩器读取的阶段检查点
- `results/checkpoints/<name>/conversation.json`：公开发言、狼队夜谈、私聊对话
- `results/checkpoints/<name>/werewolf_state.json`：最新狼人杀完整状态
- `results/checkpoints/<name>/werewolf_report.md`：含身份、公开线、私密记忆摘要的复盘报告

执行 `compress.py` 后会生成：

- `results/compressed/<name>/movement.json`
- `results/compressed/<name>/simulation.md`

## 空间设计

- 白天议会：约翰逊公园的公园花园，所有幸存玩家集合、顺序发言、质疑、辩论、投票。
- 狼人房间：玫瑰酒吧吧台后面，狼人进行私密夜谈并决定击杀目标。
- 神职房间：奥克山学院图书馆，预言家查验，守卫选择守护。
- 女巫房间：柳树市场和药店的药店柜台后面，女巫决定救人或毒人。
- 非正式社交：酒吧、咖啡馆、公园、市场、学院宿舍公共休息室、艺术家共居空间公共休息室。

## 自定义玩家和身份

自定义 12 名玩家：

```bash
python start.py --name ww-custom --players "亚当,阿比盖尔,伊莎贝拉,亚瑟,简,汤姆,山姆,詹妮弗,弗朗西斯科,拉吉夫,拉托亚,山本百合子"
```

固定身份可以传入 JSON：

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

然后：

```bash
python start.py --name ww-fixed --role-map roles.json
```

可用身份键：`werewolf`、`seer`、`witch`、`hunter`、`guard`、`villager`。

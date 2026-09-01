
这些参数可以分成 4 类：感知、日程兼容、LLM、记忆。

"percept": {
  "mode": "box",
  "vision_r": 8,
  "att_bandwidth": 8
}
percept：感知范围配置。
现在狼人杀主要由导演系统控制流程，这块保留给小镇 Agent 感知兼容。

mode: 感知模式。box 表示以角色为中心的方形范围。
vision_r: 视野半径。8 表示向上下左右各扩展 8 格。
att_bandwidth: 注意力带宽。表示最多关注多少个事件。
"schedule": {
  "max_try": 5,
  "diversity": 5
}
schedule：旧日常小镇的日程参数。
现在狼人杀项目基本不使用，只为兼容 Agent 状态保留。

max_try: 生成日程最多尝试次数。
diversity: 日程多样性要求。
"think": {
  "llm": {
    "provider": "openai",
    "model": "deepseek-v4-flash",
    "base_url": "https://api.deepseek.com",
    "api_key_env": "DEEPSEEK_API_KEY",
    "api_key": ""
  },
  "interval": 1000,
  "poignancy_max": 150
}
think.llm：最重要，控制 AI Agent 调用哪个大模型。

provider: 模型供应商类型。
ollama：本地 Ollama。
openai：OpenAI 兼容 API，比如 DeepSeek、OpenAI、硅基流动、OpenRouter。
model: 模型名称。DeepSeek 可填类似 deepseek-v4-flash。
base_url: API 地址。DeepSeek 是 https://api.deepseek.com。
api_key_env: 保存 API Key 的环境变量名。真实 Key 不应写入此文件。
api_key: 仅为兼容本地服务保留；远程 API 应保持为空。
其他两个：

interval: 旧小镇思考间隔，狼人杀里基本不重要。
poignancy_max: 旧记忆反思阈值，狼人杀里基本不重要。
"chat_iter": 4
chat_iter：旧小镇自由聊天最多轮数。
现在狼人杀的对话由 WerewolfDirector 控制，这个参数基本不重要。

"associate": {
  "embedding": {
    "provider": "ollama",
    "model": "qwen3-embedding:0.6b-q8_0",
    "base_url": "http://127.0.0.1:11434",
    "api_key": ""
  },
  "retention": 8
}
associate：向量记忆配置。

embedding.provider: embedding 模型来源。
embedding.model: embedding 模型名。
embedding.base_url: embedding API 地址。
embedding.api_key: embedding API Key。
retention: 检索最近多少条记忆。

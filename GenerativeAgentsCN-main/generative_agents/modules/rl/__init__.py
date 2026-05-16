# 文件作用：RL 训练子系统。仅在跑训练时被引入；零侵入主游戏代码。
#
# 设计：
#   - buffer.py     ReplayBuffer + GroupRecord：批量采集 trajectory
#   - collector.py  起 N 并行 Game，每 group 同身份同座位
#   - loss.py       GRPO loss 纯函数（可独立单测）
#   - trainer.py    包 trl 的 GRPOTrainer，加载 Qwen + LoRA + ref
#   - config.py     RLConfig 超参数

from .config import RLConfig
from .buffer import GroupRecord, ReplayBuffer

__all__ = ["RLConfig", "GroupRecord", "ReplayBuffer"]

# 文件作用：狼人杀阶段模块的包入口，按时段拆分（night / day / social）。

from modules.werewolf.phases import day, night, social

__all__ = ["night", "day", "social"]

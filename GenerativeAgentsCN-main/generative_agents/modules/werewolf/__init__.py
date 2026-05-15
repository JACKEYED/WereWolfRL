# 文件作用：werewolf 包入口。只暴露纯数据/纯函数模块，使其在 pydantic 等可选依赖缺失时也可用。
# 需要 WerewolfDirector / build_werewolf_config 等运行时入口，请显式 import 子模块：
#   from modules.werewolf.director import WerewolfDirector, build_werewolf_config, load_agent_base

from modules.werewolf.locations import (
    LOCATIONS,
    LOCATION_DISPLAY,
    ROLE_LOCATIONS,
    SOCIAL_SPOTS,
    SOCIAL_SPOT_KEYS,
    shichen,
    location_display_from_address,
)

__all__ = [
    "LOCATIONS",
    "LOCATION_DISPLAY",
    "ROLE_LOCATIONS",
    "SOCIAL_SPOTS",
    "SOCIAL_SPOT_KEYS",
    "shichen",
    "location_display_from_address",
]

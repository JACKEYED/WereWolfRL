# 文件作用：江南古镇 NPC 流言系统。把夜里真实发生的事件用保守扭曲方式播散给清晨在镇上的玩家。
# 保守扭曲：保留时间和地点，隐去当事人姓名，不主动错认性别或身份。

from typing import List, Tuple

# TODO 流言是否可以交由模型生成

class GossipMill:
    NPCS = {
        "clinic_attendant": "同德医馆小哑巴",
        "dyehouse_dyer": "后山染坊老染工",
        "stargazer_keeper": "观星楼守院老仆",
        "street_watchman": "巡街更夫",
    }

    def __init__(self, rng):
        self.rng = rng

    def spin(self, events: dict, day: int) -> List[Tuple[str, str]]:
        """根据夜间事件生成 (NPC 称谓, 模糊化叙述) 列表。

        events 字段：
          - witch_visited_clinic: 女巫今夜是否到医馆熬药（解药或毒药任一）
          - wolves_met: 狼队是否在染坊会面
          - seer_active: 预言家是否登观星楼
          - guard_active: 守卫是否提灯出更
        """
        lines: List[Tuple[str, str]] = []

        if events.get("witch_visited_clinic"):
            line = self.rng.choice([
                "昨夜三更，药柜后头似乎有人取过东西，灯影晃了两下就熄了。",
                "昨儿后半夜，医馆来人取了药，脚步极轻，没敢正眼看我。",
                "昨夜药铺门虚掩了一会儿，掌灯的人没出声，取了药便走。",
            ])
            lines.append((self.NPCS["clinic_attendant"], line))

        if events.get("wolves_met"):
            line = self.rng.choice([
                "昨儿后山染缸边好几个人影晃，话压得低，听不真切。",
                "夜半听见染坊后头有人小声商量，像是在算计什么。",
                "昨夜染坊那头不太对劲，有人聚着不亮灯。",
            ])
            lines.append((self.NPCS["dyehouse_dyer"], line))

        if events.get("seer_active"):
            line = self.rng.choice([
                "先生昨夜又登了观星楼，对着星图皱眉头到丑时。",
                "昨夜观星楼上灯亮了大半宿，先生似乎在排卦。",
                "夜里听见观星楼有人翻书页，叹了好几口气。",
            ])
            lines.append((self.NPCS["stargazer_keeper"], line))

        if events.get("guard_active"):
            line = self.rng.choice([
                "昨夜我提灯巡到镇东，远远见个身影候在某户门外，没敢上前。",
                "夜里巡街时，有人静静守在一户人家屋檐下，像是怕惊扰里头的人。",
                "昨夜三更打更经过一处院子，门口立着个人影，提着盏小灯。",
            ])
            lines.append((self.NPCS["street_watchman"], line))

        return lines

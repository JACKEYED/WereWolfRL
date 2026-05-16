# 文件作用：scene_mode（v1 game / 默认 social）相关的纯模块单元测试。
# 跑法：cd generative_agents && python -m pytest test/test_scene_mode.py -v

from modules.werewolf.locations import (
    LOCATIONS,
    LOCATION_DISPLAY,
    LOCATION_DISPLAY_GAME,
    location_display_from_address,
)
from modules.prompt import social, game
from modules.prompt.dispatcher import get_task, phase_label


# =========================================================================
# locations: 双套显示名
# =========================================================================
class TestLocationDisplayDual:
    def test_both_tables_cover_all_keys(self):
        assert set(LOCATION_DISPLAY.keys()) == set(LOCATIONS.keys())
        assert set(LOCATION_DISPLAY_GAME.keys()) == set(LOCATIONS.keys())

    def test_game_names_are_neutral(self):
        """game 模式不含任何 江南/民国 风字眼"""
        forbidden = ["染坊", "茶馆掌柜", "镇外", "乱葬岗", "观星", "更夫房", "归云", "听雨"]
        for key, name in LOCATION_DISPLAY_GAME.items():
            for f in forbidden:
                assert f not in name, f"game 地点名 '{name}' 还含古风字 '{f}'"

    def test_social_names_keep_jiangnan(self):
        """social 模式保留江南叙事"""
        assert LOCATION_DISPLAY["dyehouse"] == "后山染坊"
        assert LOCATION_DISPLAY["stargazer"] == "观星楼"

    def test_dispatch_by_mode(self):
        addr = LOCATIONS["dyehouse"]
        assert location_display_from_address(addr, mode="social") == "后山染坊"
        assert location_display_from_address(addr, mode="game") == "狼人议事室"

    def test_default_mode_is_social(self):
        addr = LOCATIONS["teahouse"]
        assert location_display_from_address(addr) == "听雨茶馆"


# =========================================================================
# prompt: 双套 OPENING / TASKS / phase_label
# =========================================================================
class TestPromptModes:
    def test_openings_differ(self):
        assert social.OPENING != game.OPENING

    def test_social_opening_mentions_jiangnan(self):
        assert "江南" in social.OPENING or "民国" in social.OPENING

    def test_game_opening_no_jiangnan(self):
        for f in ["江南", "民国", "古镇", "镇上"]:
            assert f not in game.OPENING, f"game opening 不该含 '{f}'"

    def test_both_have_same_task_keys(self):
        assert set(social.TASKS.keys()) == set(game.TASKS.keys())

    def test_get_task_dispatches(self):
        s = get_task("social", "day_speech")
        g = get_task("game", "day_speech")
        assert s != g
        # social 留余地"自然"，game 明确"立场"
        assert "立场" in g or "表态" in g or "指认" in g

    def test_get_task_templated_with_kwargs(self):
        s = get_task("social", "werewolf_speech", target="苏蘅", other_wolves="周文卿、阿福")
        g = get_task("game", "werewolf_speech", target="苏蘅", other_wolves="周文卿、阿福")
        assert "苏蘅" in s and "苏蘅" in g
        assert "周文卿" in s and "周文卿" in g

    def test_get_task_unknown_key_falls_back_empty(self):
        assert get_task("game", "nonexistent_key") == ""

    def test_vote_task_revote(self):
        first = get_task("game", "vote", revote=False)
        second = get_task("game", "vote", revote=True)
        assert "第二轮" in second or "二轮" in second
        assert first != second


# =========================================================================
# phase_label: 时辰 vs 现代汉语
# =========================================================================
class TestPhaseLabelByMode:
    def test_social_uses_shichen(self):
        assert phase_label("social", 1, "night") == "第1日子时"
        assert phase_label("social", 2, "day_council") == "第2日辰时议会"

    def test_game_uses_modern_chinese(self):
        assert phase_label("game", 1, "night") == "第1天 夜晚"
        assert phase_label("game", 2, "day_council") == "第2天 白天"
        assert phase_label("game", 3, "dawn") == "第3天 破晓"

    def test_game_label_no_shichen_chars(self):
        for slot in ["night", "dawn", "day_council"]:
            label = phase_label("game", 1, slot)
            for f in ["子时", "辰时", "卯时", "申时", "日"]:
                if f == "日":
                    # 不该出现 "第N日"（古风）
                    assert "第1日" not in label
                else:
                    assert f not in label, f"game 标签 '{label}' 不该含 '{f}'"


# =========================================================================
# behavior rules
# =========================================================================
class TestBehaviorRules:
    def test_game_rules_emphasize_brevity(self):
        # game 模式行为规则应强调"简洁、直接、有依据"
        assert "简洁" in game.BEHAVIOR_RULES or "直接" in game.BEHAVIOR_RULES

    def test_social_rules_allow_natural_speech(self):
        # social 不强制简洁，可以发挥
        assert len(social.BEHAVIOR_RULES) > 0

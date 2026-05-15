# 文件作用：werewolf 包内纯模块的单元测试（不依赖 pydantic / dotenv / LLM / Phaser）。
# 跑法：cd generative_agents && python -m pytest test/test_werewolf_pure.py -v

import random

import pytest

from modules.werewolf.locations import (
    LOCATIONS,
    LOCATION_DISPLAY,
    ROLE_LOCATIONS,
    SOCIAL_SPOTS,
    location_display_from_address,
    shichen,
)
from modules.werewolf.text_utils import clean_text, join_names, match_choice
from modules.werewolf import rules
from modules.werewolf.player import WerewolfPlayer, fallback_speech, role_brief


# =========================================================================
# locations
# =========================================================================
class TestLocations:
    def test_all_locations_have_display(self):
        assert set(LOCATIONS.keys()) == set(LOCATION_DISPLAY.keys())

    def test_role_locations_point_to_existing(self):
        for role, key in ROLE_LOCATIONS.items():
            assert key in LOCATIONS, f"{role} 的专属地点 {key} 不在 LOCATIONS"

    def test_social_spots_resolved(self):
        assert len(SOCIAL_SPOTS) == 4
        for spot in SOCIAL_SPOTS:
            assert spot[0] == "the Ville"

    def test_shichen_format(self):
        assert shichen(1, "子时") == "第1日子时"
        assert shichen(10, "辰时议会") == "第10日辰时议会"

    def test_display_from_address_known(self):
        assert location_display_from_address(LOCATIONS["teahouse"]) == "听雨茶馆"
        assert location_display_from_address(LOCATIONS["dyehouse"]) == "后山染坊"

    def test_display_from_address_unknown_fallback(self):
        # 未匹配时回退到末段拼接
        result = location_display_from_address(["the Ville", "某宅", "某厅"])
        assert "某宅" in result or "某厅" in result


# =========================================================================
# text_utils
# =========================================================================
class TestTextUtils:
    def test_clean_text_strips_whitespace(self):
        assert clean_text("  hello world  ", 20) == "hello world"

    def test_clean_text_truncates(self):
        result = clean_text("一二三四五六七八九十", 5)
        assert len(result) <= 6  # 含可能附加的句号

    def test_clean_text_empty_falls_back(self):
        assert clean_text("", 10) == "我还需要再观察一下。"
        assert clean_text("   ", 10) == "我还需要再观察一下。"

    def test_match_choice_exact(self):
        assert match_choice("张三", ["张三", "李四"], "李四") == "张三"

    def test_match_choice_substring(self):
        assert match_choice("我选张三", ["张三", "李四"], "李四") == "张三"

    def test_match_choice_whitespace_normalized(self):
        assert match_choice("张 三", ["张三"], "X") == "张三"

    def test_match_choice_fallback(self):
        assert match_choice("完全不沾边", ["A", "B"], "B") == "B"

    def test_join_names(self):
        assert join_names(["a", "b"]) == "a、b"
        assert join_names([]) == ""
        assert join_names(["a", "", "b"]) == "a、b"


# =========================================================================
# rules
# =========================================================================
class TestRulesConstants:
    def test_role_deck_has_12_with_4_wolves(self):
        assert len(rules.ROLE_DECK) == 12
        assert rules.ROLE_DECK.count("werewolf") == 4
        assert rules.ROLE_DECK.count("villager") == 4
        for god in ["seer", "witch", "hunter", "guard"]:
            assert rules.ROLE_DECK.count(god) == 1, f"{god} 应该正好 1 名"

    def test_role_names_and_goals_cover_all_roles(self):
        all_roles = set(rules.ROLE_DECK)
        assert all_roles == set(rules.ROLE_NAMES.keys())
        assert all_roles == set(rules.ROLE_GOALS.keys())


class TestResolveNightDeaths:
    def test_only_wolf_kill_no_protection(self):
        deaths, _ = rules.resolve_night_deaths("A", None, None, None)
        assert deaths == {"A": ["狼人夜袭"]}

    def test_guard_only_protects(self):
        deaths, narr = rules.resolve_night_deaths("A", "A", None, None)
        assert "A" not in deaths
        assert any("守卫保护" in line for line in narr)

    def test_witch_save_only(self):
        deaths, narr = rules.resolve_night_deaths("A", None, "A", None)
        assert "A" not in deaths
        assert any("解药" in line for line in narr)

    def test_same_guard_same_save_dies(self):
        """标准规则：守卫和女巫救药都指向被刀者 → 仍死。"""
        deaths, narr = rules.resolve_night_deaths("A", "A", "A", None)
        assert deaths == {"A": ["同守同救"]}
        assert any("同守同救" in line or "互冲" in line for line in narr)

    def test_poison_kills_separately(self):
        deaths, _ = rules.resolve_night_deaths("A", None, None, "B")
        assert deaths == {"A": ["狼人夜袭"], "B": ["女巫毒药"]}

    def test_poison_kills_even_if_guarded(self):
        """毒药不可挡——即使被守护的人也会死。"""
        deaths, _ = rules.resolve_night_deaths(None, "C", None, "C")
        assert "C" in deaths and "女巫毒药" in deaths["C"]

    def test_no_wolf_kill_no_poison_nobody_dies(self):
        deaths, narr = rules.resolve_night_deaths(None, "A", None, None)
        assert deaths == {}


class TestCheckWinner:
    def test_good_wins_when_no_wolves(self):
        assert rules.check_winner([], ["a", "b"]) == "好人阵营"

    def test_wolves_win_when_parity(self):
        assert rules.check_winner(["a", "b"], ["c", "d"]) == "狼人阵营"

    def test_wolves_win_when_majority(self):
        assert rules.check_winner(["a", "b"], ["c"]) == "狼人阵营"

    def test_undetermined(self):
        assert rules.check_winner(["a"], ["b", "c", "d"]) is None


class TestVoteHelpers:
    def test_clear_winner(self):
        assert rules.resolve_vote({"a": "X", "b": "X", "c": "Y"}) == "X"

    def test_tie_returns_none(self):
        assert rules.resolve_vote({"a": "X", "b": "Y"}) is None

    def test_empty_votes(self):
        assert rules.resolve_vote({}) is None
        assert rules.tied_candidates({}) == []

    def test_tied_candidates_lists_all(self):
        tied = rules.tied_candidates({"a": "X", "b": "Y", "c": "X", "d": "Y"})
        assert sorted(tied) == ["X", "Y"]

    def test_majority_choice_deterministic_with_seed(self):
        rng = random.Random(42)
        result = rules.majority_choice(["A", "A", "B"], rng)
        assert result == "A"

    def test_majority_choice_breaks_tie_with_rng(self):
        # 'A' 和 'B' 各 2 票；rng 决断
        rng = random.Random(0)
        result = rules.majority_choice(["A", "A", "B", "B"], rng)
        assert result in ("A", "B")


# =========================================================================
# player
# =========================================================================
class TestWerewolfPlayer:
    def test_defaults(self):
        p = WerewolfPlayer(name="x", role="seer")
        assert p.alive is True
        assert p.death_reason == ""
        assert p.used_hunter_shot is False

    def test_role_name(self):
        assert WerewolfPlayer(name="x", role="werewolf").role_name == "狼人"
        assert WerewolfPlayer(name="x", role="hunter").role_name == "猎人"

    def test_camp(self):
        assert WerewolfPlayer(name="x", role="werewolf").camp == "狼人阵营"
        for good in ["seer", "witch", "hunter", "guard", "villager"]:
            assert WerewolfPlayer(name="x", role=good).camp == "好人阵营"


class TestRoleBrief:
    def test_seer_brief_mentions_role(self):
        p = WerewolfPlayer(name="x", role="seer")
        text = role_brief(p, [])
        assert "预言家" in text and "好人阵营" in text

    def test_werewolf_brief_lists_peers(self):
        p = WerewolfPlayer(name="x", role="werewolf")
        text = role_brief(p, ["狼2", "狼3", "狼4"])
        for peer in ["狼2", "狼3", "狼4"]:
            assert peer in text

    def test_witch_brief_mentions_potions(self):
        p = WerewolfPlayer(name="x", role="witch")
        text = role_brief(p, [])
        assert "解药" in text and "毒药" in text

    def test_hunter_brief_mentions_poison_caveat(self):
        p = WerewolfPlayer(name="x", role="hunter")
        text = role_brief(p, [])
        assert "毒" in text  # 提示被毒禁枪

    def test_guard_brief_mentions_no_repeat(self):
        p = WerewolfPlayer(name="x", role="guard")
        text = role_brief(p, [])
        assert "连续" in text or "两晚" in text


class TestFallbackSpeech:
    def test_all_roles_have_distinct_fallback(self):
        speeches = {role: fallback_speech(role) for role in ["werewolf", "seer", "witch", "hunter", "guard", "villager"]}
        # 不同身份不该撞台词
        assert len(set(speeches.values())) >= 5

    def test_villager_fallback_is_default(self):
        # 未定义身份回退到村民台词
        assert fallback_speech("villager") == fallback_speech("unknown_role")

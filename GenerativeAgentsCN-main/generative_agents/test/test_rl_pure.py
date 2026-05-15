# 文件作用：RL 三件套（beliefs / reward / trajectory）的纯模块单元测试。
# 跑法：cd generative_agents && python -m pytest test/test_rl_pure.py -v

from modules.werewolf import reward as rwd
from modules.werewolf.beliefs import (
    BeliefState,
    ROLE_COUNTS,
    ROLE_KEYS,
    init_for,
    merge_with_locks,
    normalize_distribution,
)
from modules.werewolf.trajectory import TrajectoryRecorder, snapshot_belief


# =========================================================================
# beliefs
# =========================================================================
class TestRoleCounts:
    def test_total_is_12(self):
        assert sum(ROLE_COUNTS.values()) == 12

    def test_four_wolves(self):
        assert ROLE_COUNTS["werewolf"] == 4

    def test_six_role_keys(self):
        assert set(ROLE_KEYS) == set(ROLE_COUNTS.keys())


class TestInitFor:
    PLAYERS = [f"p{i}" for i in range(12)]

    def test_villager_belief_excludes_self(self):
        bs = init_for("p0", "villager", self.PLAYERS)
        assert "p0" not in bs.beliefs
        assert len(bs.beliefs) == 11

    def test_villager_belief_per_target_sums_to_one(self):
        bs = init_for("p0", "villager", self.PLAYERS)
        for target, dist in bs.beliefs.items():
            s = sum(dist.values())
            assert abs(s - 1.0) < 1e-6, f"{target} sums to {s}"

    def test_villager_wolf_prob_is_4_over_11(self):
        bs = init_for("p0", "villager", self.PLAYERS)
        # 自己是村民，剩余 11 人中含 4 狼
        for target, dist in bs.beliefs.items():
            assert abs(dist["werewolf"] - 4 / 11) < 1e-6

    def test_wolf_knows_teammates(self):
        teammates = ["p1", "p2", "p3"]
        bs = init_for("p0", "werewolf", self.PLAYERS, wolf_teammates=teammates)
        for t in teammates:
            assert bs.locked[t] == "werewolf"
            assert bs.beliefs[t]["werewolf"] == 1.0

    def test_wolf_for_non_teammates_zero_wolf_prob(self):
        teammates = ["p1", "p2", "p3"]
        bs = init_for("p0", "werewolf", self.PLAYERS, wolf_teammates=teammates)
        for target in ["p4", "p5", "p6"]:
            assert bs.beliefs[target]["werewolf"] == 0.0

    def test_seer_check_wolf_locks(self):
        bs = init_for("p0", "seer", self.PLAYERS, seer_known_checks={"p5": "狼人"})
        assert bs.locked["p5"] == "werewolf"
        assert bs.beliefs["p5"]["werewolf"] == 1.0

    def test_seer_check_good_zeros_wolf(self):
        bs = init_for("p0", "seer", self.PLAYERS, seer_known_checks={"p5": "好人"})
        assert "p5" not in bs.locked
        assert bs.beliefs["p5"]["werewolf"] == 0.0
        # 其他身份概率重新归一
        assert abs(sum(bs.beliefs["p5"].values()) - 1.0) < 1e-6


class TestNormalizeDistribution:
    def test_basic(self):
        d = normalize_distribution({"werewolf": 2, "villager": 2})
        assert sum(d.values()) == 1.0
        assert d["werewolf"] == 0.5
        assert d["villager"] == 0.5

    def test_empty_falls_back_to_uniform(self):
        d = normalize_distribution({})
        assert sum(d.values()) == 1.0
        for v in d.values():
            assert abs(v - 1 / 6) < 1e-6

    def test_negative_values_clamped(self):
        d = normalize_distribution({"werewolf": -1, "villager": 1})
        assert d["werewolf"] == 0.0
        assert d["villager"] == 1.0


class TestMergeWithLocks:
    def test_overrides_with_locks(self):
        new = {"p1": {"werewolf": 0.3, "seer": 0.2, "witch": 0.1, "hunter": 0.1, "guard": 0.1, "villager": 0.2}}
        locked = {"p1": "werewolf"}
        merged = merge_with_locks(new, locked)
        assert merged["p1"]["werewolf"] == 1.0
        assert merged["p1"]["villager"] == 0.0


class TestRenderText:
    def test_locked_shows_role(self):
        bs = init_for("p0", "werewolf", [f"p{i}" for i in range(12)], wolf_teammates=["p1"])
        text = bs.render_text()
        assert "p1" in text
        assert "已确认" in text or "狼人" in text


class TestTopSuspect:
    def test_finds_most_likely_wolf(self):
        bs = BeliefState(
            holder="me",
            beliefs={
                "alice": {"werewolf": 0.9, "seer": 0.02, "witch": 0.02, "hunter": 0.02, "guard": 0.02, "villager": 0.02},
                "bob":   {"werewolf": 0.1, "seer": 0.2, "witch": 0.2, "hunter": 0.2, "guard": 0.1, "villager": 0.2},
            },
        )
        assert bs.top_suspect("werewolf") == "alice"


# =========================================================================
# reward
# =========================================================================
class TestRewardForSpeech:
    PLAYERS = ["w", "g1", "g2", "g3"]

    def _make(self, holder, target_probs):
        """快速造一个 belief_state，holder 对每个 target 的 werewolf 概率指定。"""
        beliefs = {}
        for target, p_wolf in target_probs.items():
            beliefs[target] = {r: 0.0 for r in ROLE_KEYS}
            beliefs[target]["werewolf"] = p_wolf
            beliefs[target]["villager"] = 1 - p_wolf
        return BeliefState(holder=holder, beliefs=beliefs)

    def test_wolf_speech_positive_when_suspicion_drops(self):
        prior = {
            "g1": self._make("g1", {"w": 0.5}),
            "g2": self._make("g2", {"w": 0.5}),
        }
        post = {
            "g1": self._make("g1", {"w": 0.3}),
            "g2": self._make("g2", {"w": 0.4}),
        }
        r = rwd.step_reward_for_speech(
            "w", "werewolf", prior, post, {"w": "werewolf"}, ["w", "g1", "g2"]
        )
        assert r > 0  # 别人对 w 的怀疑下降了

    def test_good_speech_positive_when_team_sees_wolf(self):
        prior = {
            "g2": self._make("g2", {"w": 0.3}),
            "g3": self._make("g3", {"w": 0.3}),
        }
        post = {
            "g2": self._make("g2", {"w": 0.7}),
            "g3": self._make("g3", {"w": 0.6}),
        }
        r = rwd.step_reward_for_speech(
            "g1", "seer", prior, post,
            {"w": "werewolf", "g1": "seer", "g2": "villager", "g3": "villager"},
            ["w", "g1", "g2", "g3"],
        )
        assert r > 0


class TestRewardForVote:
    REAL = {"w": "werewolf", "g": "villager"}

    def test_good_votes_wolf_positive(self):
        assert rwd.step_reward_for_vote("g", "villager", "w", self.REAL) == 1.0

    def test_good_votes_good_negative(self):
        assert rwd.step_reward_for_vote("g", "villager", "g", self.REAL) < 0

    def test_wolf_votes_own_team_negative(self):
        assert rwd.step_reward_for_vote("w", "werewolf", "w", self.REAL) < 0

    def test_wolf_votes_good_positive(self):
        assert rwd.step_reward_for_vote("w", "werewolf", "g", self.REAL) > 0


class TestRewardForSkill:
    REAL = {"wolf1": "werewolf", "good1": "villager"}

    def test_seer_check_wolf_positive(self):
        assert rwd.step_reward_for_skill("seer", "check", "wolf1", self.REAL) > 0

    def test_seer_check_good_slight_negative(self):
        assert rwd.step_reward_for_skill("seer", "check", "good1", self.REAL) < 0

    def test_witch_poison_wolf_positive(self):
        assert rwd.step_reward_for_skill("witch", "poison", "wolf1", self.REAL) > 0

    def test_witch_poison_good_very_negative(self):
        assert rwd.step_reward_for_skill("witch", "poison", "good1", self.REAL) <= -1.0

    def test_wolf_kill_teammate_very_negative(self):
        assert rwd.step_reward_for_skill("werewolf", "kill", "wolf1", self.REAL) <= -1.0


class TestEpisodeReward:
    def test_good_wins_for_good_agent(self):
        assert rwd.episode_reward("好人阵营", "villager") == 1.0
        assert rwd.episode_reward("好人阵营", "seer") == 1.0

    def test_good_wins_for_wolf(self):
        assert rwd.episode_reward("好人阵营", "werewolf") == -1.0

    def test_no_winner_zero(self):
        assert rwd.episode_reward(None, "villager") == 0.0


# =========================================================================
# trajectory
# =========================================================================
class TestTrajectoryRecorder:
    def test_record_assigns_step_id(self):
        r = TrajectoryRecorder()
        s1 = r.record("a", "p1", 1, "speech", {}, "hi")
        s2 = r.record("a", "p1", 1, "vote", {}, "b", ["b", "c"])
        assert s1.step_id == 0
        assert s2.step_id == 1

    def test_steps_in_phase_filters_correctly(self):
        r = TrajectoryRecorder()
        r.record("a", "p1", 1, "speech", {}, "x")
        r.record("b", "p1", 1, "speech", {}, "y")
        r.record("a", "p2", 1, "vote", {}, "b")
        in_p1 = r.steps_in_phase("p1")
        assert len(in_p1) == 2
        only_a_p1 = r.steps_in_phase("p1", agent="a")
        assert len(only_a_p1) == 1

    def test_fill_episode_reward(self):
        r = TrajectoryRecorder()
        s = r.record("a", "p1", 1, "speech", {}, "x")
        r.fill_episode_reward({"a": 1.0, "b": -1.0})
        assert s.reward_episode == 1.0

    def test_to_dict_serializable(self):
        r = TrajectoryRecorder()
        r.record("a", "p1", 1, "speech", {"x": 1}, "hello", candidates=None)
        d = r.to_dict()
        assert d["count"] == 1
        assert d["steps"][0]["agent"] == "a"
        assert d["steps"][0]["action"] == "hello"


class TestSnapshotBelief:
    def test_none_returns_none(self):
        assert snapshot_belief(None) is None

    def test_deepcopy_independent_of_source(self):
        bs = BeliefState(
            holder="me",
            beliefs={"a": {"werewolf": 0.5}},
            locked={"b": "seer"},
        )
        snap = snapshot_belief(bs)
        # 修改原 belief，snapshot 不受影响
        bs.beliefs["a"]["werewolf"] = 0.9
        assert snap["beliefs"]["a"]["werewolf"] == 0.5

# 文件作用：单进程多线程并行多 Game 的隔离性测试。
# 验证：
#   1. GameRegistry 能按 name 存取多 game
#   2. 每个线程的 ActiveGameContext 独立（thread-local）
#   3. utils.get_timer() 在不同线程返回各自 game 的 timer
#   4. 8 个线程同时推进 timer 互不串扰

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from modules.game import GameRegistry
from modules.utils import ActiveGameContext, get_timer
from modules.utils.timer import Timer


# ─────────────────────────────────────────────────────────────────
# Mock Game：避免依赖 maze.json / agent.json / LLM
# 只需要 .name + .timer 两个属性，足以测试隔离性
# ─────────────────────────────────────────────────────────────────
class MockGame:
    def __init__(self, name: str, start_time: str = "20240101-00:00"):
        self.name = name
        self.timer = Timer(start=start_time)


@pytest.fixture(autouse=True)
def _clean_state():
    """每个测试前后清理 registry + 线程活跃位。"""
    GameRegistry.clear()
    ActiveGameContext.clear()
    yield
    GameRegistry.clear()
    ActiveGameContext.clear()


# =========================================================================
# ActiveGameContext
# =========================================================================
class TestActiveGameContext:
    def test_set_and_get(self):
        g = MockGame("g1")
        ActiveGameContext.set(g)
        assert ActiveGameContext.get() is g

    def test_clear(self):
        ActiveGameContext.set(MockGame("g1"))
        ActiveGameContext.clear()
        assert ActiveGameContext.get() is None

    def test_bind_context_manager_restores(self):
        outer = MockGame("outer")
        inner = MockGame("inner")
        ActiveGameContext.set(outer)
        with ActiveGameContext.bind(inner):
            assert ActiveGameContext.get() is inner
        # bind 退出后恢复到 outer
        assert ActiveGameContext.get() is outer

    def test_bind_with_no_prior_clears_on_exit(self):
        g = MockGame("g")
        with ActiveGameContext.bind(g):
            assert ActiveGameContext.get() is g
        assert ActiveGameContext.get() is None

    def test_thread_local_isolation(self):
        """两个线程各自 set，互不影响。"""
        results = {}

        def worker(name: str):
            g = MockGame(name)
            ActiveGameContext.set(g)
            time.sleep(0.05)  # 故意让另一个线程也 set 后再读
            results[name] = ActiveGameContext.get().name

        t1 = threading.Thread(target=worker, args=("alpha",))
        t2 = threading.Thread(target=worker, args=("beta",))
        t1.start(); t2.start(); t1.join(); t2.join()

        assert results["alpha"] == "alpha"
        assert results["beta"] == "beta"


# =========================================================================
# get_timer 路由
# =========================================================================
class TestGetTimerRouting:
    def test_returns_active_game_timer(self):
        g = MockGame("g1", start_time="20240301-08:00")
        ActiveGameContext.set(g)
        assert get_timer() is g.timer
        assert get_timer().get_date("%Y%m%d-%H:%M") == "20240301-08:00"

    def test_falls_back_to_global_when_no_active(self):
        ActiveGameContext.clear()
        # 不应抛错；返回某个进程级 Timer
        t = get_timer()
        assert isinstance(t, Timer)

    def test_two_threads_two_timers(self):
        """两个线程的 get_timer() 各自返回各自 game 的 timer。"""
        observed = {}

        def worker(name: str, start: str):
            g = MockGame(name, start_time=start)
            with ActiveGameContext.bind(g):
                # 模拟线程内做点活
                time.sleep(0.02)
                t = get_timer()
                t.forward(60)  # 推进 60 分钟
                observed[name] = t.get_date("%Y%m%d-%H:%M")

        with ThreadPoolExecutor(max_workers=2) as ex:
            ex.submit(worker, "alpha", "20240101-00:00").result()
            ex.submit(worker, "beta", "20240601-12:00").result()

        # alpha 推进 60min → 01:00；beta 推进 60min → 13:00
        assert observed["alpha"] == "20240101-01:00"
        assert observed["beta"] == "20240601-13:00"


# =========================================================================
# GameRegistry
# =========================================================================
class TestGameRegistry:
    def test_register_and_get(self):
        # 用 monkey-style 直接放进去，绕过 Game 真实构造
        GameRegistry._games["x"] = MockGame("x")
        assert GameRegistry.get("x").name == "x"

    def test_remove(self):
        GameRegistry._games["x"] = MockGame("x")
        assert GameRegistry.remove("x") is True
        assert GameRegistry.get("x") is None
        assert GameRegistry.remove("x") is False

    def test_list_ids(self):
        GameRegistry._games["a"] = MockGame("a")
        GameRegistry._games["b"] = MockGame("b")
        ids = GameRegistry.list_ids()
        assert set(ids) == {"a", "b"}

    def test_activate_sets_thread_context(self):
        GameRegistry._games["g"] = MockGame("g")
        GameRegistry.activate("g")
        assert ActiveGameContext.get().name == "g"

    def test_activate_missing_raises(self):
        with pytest.raises(KeyError):
            GameRegistry.activate("nonexistent")


# =========================================================================
# 8 路并发，验证 timer 互不干扰
# =========================================================================
class TestEightParallelGames:
    def test_eight_threads_eight_timers_no_crosstalk(self):
        """8 个线程同时跑 mini-game，每个推进不同步数，最后核对 timer 与预期一致。"""
        N = 8
        ITERATIONS = 50  # 每个线程内部推进 50 次 timer

        results = {}

        def worker(idx: int):
            g = MockGame(f"g{idx}", start_time="20240101-00:00")
            GameRegistry._games[g.name] = g
            with ActiveGameContext.bind(g):
                for _ in range(ITERATIONS):
                    get_timer().forward(1)  # 每次 +1 min
                    # 故意让出 CPU，最大化交错可能
                    time.sleep(0.0001)
            results[idx] = get_timer_from_game(g).get_date("%Y%m%d-%H:%M")

        def get_timer_from_game(g):
            return g.timer

        with ThreadPoolExecutor(max_workers=N) as ex:
            futures = [ex.submit(worker, i) for i in range(N)]
            for f in futures:
                f.result()

        # 每个 game 都推进了 50 分钟 → 00:50
        for i in range(N):
            assert results[i] == "20240101-00:50", f"game {i} 时间错乱：{results[i]}"

    def test_active_context_isolation_under_load(self):
        """8 个线程各自 set 不同 game，并发读 ActiveGameContext，验证读到的永远是本线程的。"""
        N = 8
        errors = []

        def worker(idx: int):
            g = MockGame(f"g{idx}")
            with ActiveGameContext.bind(g):
                for _ in range(100):
                    seen = ActiveGameContext.get()
                    if seen is None or seen.name != f"g{idx}":
                        errors.append((idx, seen.name if seen else None))
                    time.sleep(0.0001)

        with ThreadPoolExecutor(max_workers=N) as ex:
            list(ex.map(worker, range(N)))

        assert errors == [], f"线程隔离失败：{errors}"

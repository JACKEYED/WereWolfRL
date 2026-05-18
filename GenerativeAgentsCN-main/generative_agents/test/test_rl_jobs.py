# 文件作用：RL 训练 job registry + dry worker 的纯模块测试。
# 不依赖 verl / vLLM / fastapi；只测 TrainingRegistry + run_training_job dry 路径。

import threading
import time

import pytest


# rl_sessions 顶层 import asyncio 是标准库；不需要 fastapi
@pytest.fixture
def fresh_registry():
    from api.rl_sessions import TrainingRegistry
    return TrainingRegistry()


# =========================================================================
# TrainingRegistry
# =========================================================================
class TestTrainingRegistry:
    def test_create_returns_pending_job(self, fresh_registry):
        job = fresh_registry.create({}, total_cycles=3, dry=True)
        assert job.state == "pending"
        assert job.total_cycles == 3
        assert job.dry is True
        assert job.id

    def test_only_one_active_at_a_time(self, fresh_registry):
        job = fresh_registry.create({}, total_cycles=1, dry=True)
        job.state = "running"  # 模拟启动后
        with pytest.raises(RuntimeError, match="已有训练 job"):
            fresh_registry.create({}, total_cycles=1, dry=True)

    def test_can_create_after_first_finished(self, fresh_registry):
        j1 = fresh_registry.create({}, total_cycles=1, dry=True)
        j1.state = "completed"
        j2 = fresh_registry.create({}, total_cycles=1, dry=True)
        assert j1.id != j2.id

    def test_get_returns_none_for_missing(self, fresh_registry):
        assert fresh_registry.get("nonexistent") is None

    def test_list_all(self, fresh_registry):
        j1 = fresh_registry.create({}, total_cycles=1, dry=True)
        j1.state = "completed"
        j2 = fresh_registry.create({}, total_cycles=1, dry=True)
        assert len(fresh_registry.list_all()) == 2

    def test_stop_sets_flag(self, fresh_registry):
        job = fresh_registry.create({}, total_cycles=10, dry=True)
        assert not job._stop_flag.is_set()
        assert fresh_registry.stop(job.id) is True
        assert job._stop_flag.is_set()

    def test_stop_unknown_returns_false(self, fresh_registry):
        assert fresh_registry.stop("nope") is False

    def test_remove(self, fresh_registry):
        job = fresh_registry.create({}, total_cycles=1, dry=True)
        assert fresh_registry.remove(job.id) is True
        assert fresh_registry.get(job.id) is None


# =========================================================================
# Dry worker：跑短 cycle 看完整状态机
# =========================================================================
class TestDryWorker:
    def test_dry_run_completes(self):
        """跑 2 cycle dry 模式，验证状态机走通 + metrics 累积。"""
        from api.rl_sessions import TrainingRegistry, run_training_job

        reg = TrainingRegistry()
        # 替换全局 registry 让 emit 路由到本测试 registry
        import api.rl_sessions as rs
        original = rs.registry
        rs.registry = reg
        try:
            job = reg.create({}, total_cycles=2, dry=True)
            t = threading.Thread(target=run_training_job, args=(job,))
            t.start()
            # 2 cycle × (1.2+0.3+0.8+0.2 = 2.5s) ≈ 5 秒；给 15 秒上限
            t.join(timeout=15)
            assert not t.is_alive(), "dry worker 超时未完成"

            assert job.state == "completed"
            assert len(job.cycle_metrics) == 2
            assert job.cycle_metrics[0].cycle == 0
            assert job.cycle_metrics[1].cycle == 1
            assert job.cycle_metrics[1].reward_mean > job.cycle_metrics[0].reward_mean - 1
            assert job.finished_at is not None
        finally:
            rs.registry = original

    def test_dry_run_stops_when_flag_set(self):
        from api.rl_sessions import TrainingRegistry, run_training_job

        reg = TrainingRegistry()
        import api.rl_sessions as rs
        original = rs.registry
        rs.registry = reg
        try:
            job = reg.create({}, total_cycles=100, dry=True)
            t = threading.Thread(target=run_training_job, args=(job,))
            t.start()
            time.sleep(0.5)
            reg.stop(job.id)
            t.join(timeout=10)
            assert not t.is_alive()
            assert job.state == "stopped"
            assert len(job.cycle_metrics) < 100
        finally:
            rs.registry = original


# =========================================================================
# Job 序列化
# =========================================================================
class TestJobSerialization:
    def test_to_dict_contains_all_fields(self, fresh_registry):
        job = fresh_registry.create({"cycles": 5}, total_cycles=5, dry=True)
        d = job.to_dict()
        assert d["state"] == "pending"
        assert d["total_cycles"] == 5
        assert d["dry"] is True
        assert "cycle_metrics" in d
        assert isinstance(d["log"], list)

    def test_summary_compact(self, fresh_registry):
        job = fresh_registry.create({}, total_cycles=10, dry=True)
        s = job.summary()
        # summary 不含 log / cfg / metric 详情
        assert "log" not in s
        assert "cycle_metrics" not in s
        assert s["id"] == job.id
        assert s["total_cycles"] == 10

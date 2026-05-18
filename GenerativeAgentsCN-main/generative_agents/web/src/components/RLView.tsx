// 文件作用：RL 训练视图。配置表单 + 当前 job 状态 + 阶段进度 + reward 曲线 + 实时日志。
//
// 设计：
//   - 同时只跟踪 1 个 active job
//   - 创建后立即 subscribe WS，所有事件累积到本地 events + 实时更新 cycle_metrics
//   - dry 模式默认勾上：让用户在没 GPU 时也能演示流程

import { useEffect, useRef, useState } from "react";
import * as api from "../api";
import type {
  CycleMetric, CyclePhase, JobFull, JobSummary,
  NewJobRequest, RLEvent,
} from "../types";
import { SimpleLineChart, Point } from "./SimpleLineChart";


const PHASE_LABEL: Record<CyclePhase, string> = {
  idle: "⏸ 空闲",
  collecting: "🎲 采集中（Phase A）",
  packaging: "📦 写 parquet（Phase B）",
  training: "🏋️ verl 训练（Phase C）",
  hotswapping: "🔄 推 LoRA（Phase D）",
};

const STATE_LABEL: Record<string, string> = {
  pending: "排队中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  stopped: "已停止",
};


export function RLView() {
  // 表单
  const [cycles, setCycles] = useState(30);
  const [groupSize, setGroupSize] = useState(8);
  const [groupsPerRole, setGroupsPerRole] = useState(20);
  const [dry, setDry] = useState(true);  // 默认勾上，演示友好
  const [submitting, setSubmitting] = useState(false);

  // 当前 job
  const [job, setJob] = useState<JobFull | null>(null);
  const [events, setEvents] = useState<RLEvent[]>([]);
  const [activeJobId, setActiveJobId] = useState<string | null>(null);
  const wsCloseRef = useRef<(() => void) | null>(null);
  const logBodyRef = useRef<HTMLDivElement>(null);

  // 进程启动时拉一次已有 job 列表，若有 running 的自动接管
  useEffect(() => {
    api.listTrainingJobs()
      .then((jobs) => {
        const running = jobs.find((j) => j.state === "running") ?? jobs[jobs.length - 1];
        if (running) setActiveJobId(running.id);
      })
      .catch(() => {});
  }, []);

  // 切 active job → 拉完整 status + 起 WS
  useEffect(() => {
    if (!activeJobId) {
      setJob(null);
      setEvents([]);
      return;
    }
    api.fetchTrainingStatus(activeJobId)
      .then((full) => setJob(full))
      .catch((e) => console.warn("fetchTrainingStatus failed", e));

    const close = api.subscribeTrainingJob(
      activeJobId,
      (ev) => {
        if (ev.type === "snapshot") {
          setJob(ev.job);
          return;
        }
        // 实时事件追加
        setEvents((prev) => [...prev.slice(-299), ev]);
        // 增量更新 job 字段
        setJob((prev) => {
          if (!prev) return prev;
          if (ev.type === "phase") {
            return { ...prev, current_phase: ev.phase, current_cycle: ev.cycle };
          }
          if (ev.type === "cycle_done") {
            const m = ev.metric as CycleMetric;
            return {
              ...prev,
              cycle_metrics: [...prev.cycle_metrics, m],
              current_cycle: ev.cycle,
            };
          }
          if (ev.type === "job_done") return { ...prev, state: "completed" };
          if (ev.type === "job_stop") return { ...prev, state: "stopped" };
          if (ev.type === "error") return { ...prev, state: "failed", error: ev.msg };
          return prev;
        });
      },
      (err) => console.warn("rl ws err", err),
    );
    wsCloseRef.current = close;
    return () => {
      close();
      wsCloseRef.current = null;
    };
  }, [activeJobId]);

  // 日志自动滚底
  useEffect(() => {
    if (logBodyRef.current) {
      logBodyRef.current.scrollTop = logBodyRef.current.scrollHeight;
    }
  }, [events.length, job?.log.length]);

  // 启动
  const handleStart = async () => {
    const isRunning = job?.state === "running";
    if (isRunning) {
      alert("已有训练 job 在运行，请先停止");
      return;
    }
    setSubmitting(true);
    try {
      const req: NewJobRequest = {
        cycles,
        group_size: groupSize,
        groups_per_role: groupsPerRole,
        dry,
      };
      const summary: JobSummary = await api.createTrainingJob(req);
      setEvents([]);
      setActiveJobId(summary.id);
    } catch (e) {
      alert("启动训练失败：" + (e as Error).message);
    } finally {
      setSubmitting(false);
    }
  };

  // 停止
  const handleStop = async () => {
    if (!job) return;
    if (!window.confirm("确定要停止当前训练 job 吗？已完成的 cycle 不会丢。")) return;
    try {
      await api.stopTrainingJob(job.id);
    } catch (e) {
      alert("停止失败：" + (e as Error).message);
    }
  };

  // 图表数据
  const rewardPoints: Point[] = (job?.cycle_metrics ?? []).map((m) => ({
    x: m.cycle, y: m.reward_mean,
  }));
  const lossPoints: Point[] = (job?.cycle_metrics ?? [])
    .filter((m) => m.loss !== null && m.loss !== undefined)
    .map((m) => ({ x: m.cycle, y: m.loss as number }));
  const klPoints: Point[] = (job?.cycle_metrics ?? [])
    .filter((m) => m.kl !== null && m.kl !== undefined)
    .map((m) => ({ x: m.cycle, y: m.kl as number }));

  // 合并文本日志：job.log + 当前 session 的 events 中文 msg
  const sessionLog = events
    .filter((e) => "msg" in e)
    .map((e) => `[${(e as any).ts ?? ""}] ${(e as any).msg}`);
  const fullLog = job ? [...job.log, ...sessionLog] : [];

  const progressPct = job && job.total_cycles > 0
    ? Math.round((job.current_cycle / job.total_cycles) * 100)
    : 0;

  return (
    <>
      <header className="header">
        <span className="status">
          {job
            ? `Job ${job.id} · ${STATE_LABEL[job.state]} · cycle ${job.current_cycle} / ${job.total_cycles}`
            : "尚未启动训练"}
        </span>
        <div style={{ marginLeft: "auto", display: "flex", gap: "0.4em", alignItems: "center" }}>
          <button
            onClick={handleStart}
            disabled={submitting || job?.state === "running"}
            className="primary"
          >
            {submitting ? "启动中…" : "▶ 启动训练"}
          </button>
          <button
            onClick={handleStop}
            disabled={!job || job.state !== "running"}
            className="danger"
          >
            ⏸ 停止
          </button>
        </div>
      </header>

      <main className="rl-main">
        {/* 左：配置表单 + 状态 */}
        <section className="panel rl-left">
          <h2>训练配置</h2>
          <div className="panel-body">
            <label className="field">
              <span className="field-label">Cycles（总轮数）</span>
              <input
                type="number" min={1} max={1000}
                value={cycles}
                onChange={(e) => setCycles(parseInt(e.target.value) || 1)}
                disabled={job?.state === "running"}
              />
            </label>
            <label className="field">
              <span className="field-label">Group size（同身份并行局数）</span>
              <input
                type="number" min={2} max={32}
                value={groupSize}
                onChange={(e) => setGroupSize(parseInt(e.target.value) || 2)}
                disabled={job?.state === "running"}
              />
            </label>
            <label className="field">
              <span className="field-label">Groups per role（每身份采几组）</span>
              <input
                type="number" min={1} max={100}
                value={groupsPerRole}
                onChange={(e) => setGroupsPerRole(parseInt(e.target.value) || 1)}
                disabled={job?.state === "running"}
              />
            </label>
            <label className="field field-check">
              <input
                type="checkbox"
                checked={dry}
                onChange={(e) => setDry(e.target.checked)}
                disabled={job?.state === "running"}
              />
              <span>
                <strong>Dry-run 模式</strong>
                <small> · 不真采集 / 不调 verl，模拟 metric 演示前端</small>
              </span>
            </label>
            <div className="field-hint">
              单 cycle 总局数 = 6 身份 × {groupsPerRole} × {groupSize} = <strong>{6 * groupsPerRole * groupSize}</strong>
            </div>

            {job && (
              <>
                <h3 style={{ marginTop: "1.2em", color: "var(--accent-dark)" }}>当前状态</h3>
                <div className="rl-status-grid">
                  <div><strong>Job ID</strong><span>{job.id}</span></div>
                  <div><strong>状态</strong><span className={`rl-state-${job.state}`}>{STATE_LABEL[job.state]}</span></div>
                  <div><strong>模式</strong><span>{job.dry ? "Dry-run" : "Real"}</span></div>
                  <div><strong>当前阶段</strong><span>{PHASE_LABEL[job.current_phase]}</span></div>
                  <div><strong>进度</strong><span>{job.current_cycle} / {job.total_cycles}</span></div>
                  <div><strong>启动于</strong><span>{job.started_at ?? "—"}</span></div>
                </div>
                <div className="rl-progress">
                  <div className="rl-progress-bar" style={{ width: `${progressPct}%` }} />
                  <span className="rl-progress-label">{progressPct}%</span>
                </div>
                {job.error && (
                  <div className="form-error" style={{ marginTop: "0.6em" }}>
                    {job.error.split("\n")[0]}
                  </div>
                )}
              </>
            )}
          </div>
        </section>

        {/* 中：训练曲线 */}
        <section className="panel rl-middle">
          <h2>训练曲线</h2>
          <div className="panel-body" style={{ padding: "0.6em" }}>
            <SimpleLineChart
              title="Reward mean (per cycle)"
              data={rewardPoints}
              stroke="#4a7a4a"
              fill="rgba(74,122,74,0.15)"
              yLabel="reward"
              refLine={0}
            />
            <SimpleLineChart
              title="Loss (per cycle)"
              data={lossPoints}
              stroke="#a04040"
              fill="rgba(160,64,64,0.12)"
              yLabel="loss"
              yMin={0}
            />
            <SimpleLineChart
              title="KL divergence (per cycle)"
              data={klPoints}
              stroke="#8a6a3a"
              fill="rgba(138,106,58,0.12)"
              yLabel="kl"
              yMin={0}
            />
          </div>
        </section>

        {/* 右：实时日志 */}
        <section className="panel rl-right">
          <h2>事件日志（{fullLog.length} 条）</h2>
          <div className="panel-body rl-log-body" ref={logBodyRef}>
            {fullLog.length === 0 ? (
              <div style={{ color: "#999" }}>点"启动训练"开始。</div>
            ) : (
              fullLog.slice(-100).map((line, i) => {
                let cls = "rl-log-line";
                if (line.includes("error") || line.includes("失败")) cls += " rl-log-error";
                else if (line.includes("cycle") && line.includes("完成")) cls += " rl-log-success";
                else if (line.includes("Phase") || line.includes("collecting") ||
                         line.includes("packaging") || line.includes("training") ||
                         line.includes("hotswapping")) cls += " rl-log-phase";
                return <div key={i} className={cls}>{line}</div>;
              })
            )}
          </div>
        </section>
      </main>
    </>
  );
}

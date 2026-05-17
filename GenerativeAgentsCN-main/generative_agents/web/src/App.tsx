// 文件作用：江南古镇狼人杀控制台主应用。支持多对局 tab，可同时观察多局并行游戏。
//
// 数据模型：
//   slots: Record<gameId, GameSlot>       所有打开的对局
//   activeId: string | null               当前 tab 选中的对局
//   busyById: Record<gameId, boolean>     每局独立 busy 状态（一局推进不影响另一局点）
//
// WebSocket：所有 slot 都各订阅一份；事件流到各自的 liveLog。
//            切换 tab 不影响订阅，背景对局也实时更新。

import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "./api";
import type { GameState, GameSummary, LiveEvent, StepPhase } from "./types";
import { MapPanel } from "./components/MapPanel";
import { TimelinePanel } from "./components/TimelinePanel";
import { AgentPanel } from "./components/AgentPanel";
import { NewGameDialog } from "./components/NewGameDialog";


interface GameSlot {
  summary: GameSummary;
  state: GameState | null;
  liveLog: LiveEvent[];
  selectedAgent: string | null;
}


export default function App() {
  const [slots, setSlots] = useState<Record<string, GameSlot>>({});
  const [activeId, setActiveId] = useState<string | null>(null);
  const [busyById, setBusyById] = useState<Record<string, boolean>>({});
  const [runningById, setRunningById] = useState<Record<string, boolean>>({});
  const [showNewGame, setShowNewGame] = useState(false);
  const [debugMode, setDebugMode] = useState(false);

  // 用 ref 持有 closers 防止 effect 重渲染丢失旧 ws 引用
  const wsClosers = useRef<Record<string, () => void>>({});

  const active = activeId ? slots[activeId] ?? null : null;
  const isActiveBusy = activeId ? !!busyById[activeId] : false;

  // ─── slot 更新 helper ─────────────────────────────────────
  const patchSlot = useCallback((id: string, patch: Partial<GameSlot>) => {
    setSlots((prev) => {
      const cur = prev[id];
      if (!cur) return prev;
      return { ...prev, [id]: { ...cur, ...patch } };
    });
  }, []);

  const setSlotBusy = useCallback((id: string, b: boolean) => {
    setBusyById((prev) => ({ ...prev, [id]: b }));
  }, []);

  // ─── WebSocket：每个 slot 各订一份；slot id 集合变化时重订 ───────
  const slotIds = Object.keys(slots).join(",");
  useEffect(() => {
    const curIds = new Set(slotIds ? slotIds.split(",") : []);
    // 关掉已不存在 slot 的 ws
    for (const id of Object.keys(wsClosers.current)) {
      if (!curIds.has(id)) {
        try { wsClosers.current[id](); } catch { /* noop */ }
        delete wsClosers.current[id];
      }
    }
    // 给新增 slot 开 ws
    for (const id of curIds) {
      if (wsClosers.current[id]) continue;
      const close = api.subscribeLive(
        id,
        (ev) => {
          setSlots((prev) => {
            const slot = prev[id];
            if (!slot) return prev;
            return {
              ...prev,
              [id]: { ...slot, liveLog: [...slot.liveLog.slice(-499), ev] },
            };
          });
        },
        (err) => console.warn(`ws[${id}] error`, err),
      );
      wsClosers.current[id] = close;
    }
  }, [slotIds]);

  // 组件卸载时关掉所有 ws
  useEffect(() => {
    return () => {
      for (const close of Object.values(wsClosers.current)) {
        try { close(); } catch { /* noop */ }
      }
      wsClosers.current = {};
    };
  }, []);

  // ─── 行为 ─────────────────────────────────────────────────
  const refreshState = useCallback(async (gameId: string) => {
    try {
      const s = await api.fetchState(gameId);
      patchSlot(gameId, { state: s });
    } catch (e) {
      console.warn(`fetchState[${gameId}] failed`, e);
    }
  }, [patchSlot]);

  const handleGameCreated = useCallback(async (created: GameSummary) => {
    // 加入 slot 集合并切到这个新 tab
    setSlots((prev) => ({
      ...prev,
      [created.id]: {
        summary: created,
        state: null,
        liveLog: [],
        selectedAgent: null,
      },
    }));
    setActiveId(created.id);
    setBusyById((prev) => ({ ...prev, [created.id]: false }));
    // 异步拉一次完整 state（setup 已完成）
    try {
      const s = await api.fetchState(created.id);
      patchSlot(created.id, { state: s });
    } catch (e) {
      console.warn("初始 state 拉取失败", e);
    }
  }, [patchSlot]);

  const handleStep = async (phase: StepPhase) => {
    if (!activeId || !active) return;
    const id = activeId;
    setSlotBusy(id, true);
    try {
      const s = await api.step(id, phase);
      patchSlot(id, { summary: s });
      await refreshState(id);
    } catch (e) {
      alert("推进失败：" + (e as Error).message);
    } finally {
      setSlotBusy(id, false);
    }
  };

  const handleRunToEnd = async () => {
    if (!activeId || !active) return;
    const id = activeId;
    setRunningById((prev) => ({ ...prev, [id]: true }));
    setSlotBusy(id, true);
    try {
      const s = await api.runGame(id);
      patchSlot(id, { summary: s });
      await refreshState(id);
    } catch (e) {
      alert(`对局 ${id} 自动跑完失败：` + (e as Error).message);
    } finally {
      setRunningById((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
      setSlotBusy(id, false);
    }
  };

  const handleEndGame = async (targetId?: string) => {
    const id = targetId ?? activeId;
    if (!id) return;
    const slot = slots[id];
    if (!slot) return;
    const confirmed = window.confirm(
      `确定要终止对局「${slot.summary.name}」吗？\n` +
        `内存会话会被销毁；磁盘上的 checkpoint / trajectory / 报告仍会保留。\n\n` +
        `若该对局正在推进某阶段，后端那一步会自然跑完，前端立即移除该 tab。`,
    );
    if (!confirmed) return;
    try {
      await api.deleteGame(id);
    } catch (e) {
      console.warn(`delete game[${id}] failed`, e);
    }
    // 关闭其 ws
    try { wsClosers.current[id]?.(); } catch { /* noop */ }
    delete wsClosers.current[id];
    // 从 slots 移除
    setSlots((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
    setBusyById((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
    // 如果关的是当前 tab，自动切到剩下的第一个；都没了则置空
    if (activeId === id) {
      const remaining = Object.keys(slots).filter((k) => k !== id);
      setActiveId(remaining[0] ?? null);
    }
  };

  // ─── UI ──────────────────────────────────────────────────
  const allIds = Object.keys(slots);

  return (
    <div className="app">
      <header className="header">
        <h1>江南古镇 · 狼人杀控制台</h1>
        <span className="status">
          {active
            ? `${active.summary.name} · [${active.summary.scene_mode === "game" ? "训练" : "观赏"}] · 第${active.summary.day}日 · ${
                active.summary.winner ?? "进行中"
              }`
            : `${allIds.length} 个对局已打开`}
        </span>
        <div style={{ marginLeft: "auto", display: "flex", gap: "0.4em", alignItems: "center" }}>
          <button onClick={() => setShowNewGame(true)}>
            新开一局…
          </button>
          <button
            onClick={handleRunToEnd}
            disabled={!active || active.summary.finished || isActiveBusy}
            className="primary"
            title="后端在线程池里跑完整局，前端通过 WebSocket 看进度。可以同时开多个 tab 自动跑。"
          >
            {activeId && runningById[activeId] ? "运行中…" : "自动跑完"}
          </button>

          {/* 调试折叠：单步推进按钮 */}
          <label
            className="debug-toggle"
            title="打开后显示单步推进按钮（夜晚/白天/申时）；正常用'自动跑完'即可"
          >
            <input
              type="checkbox"
              checked={debugMode}
              onChange={(e) => setDebugMode(e.target.checked)}
            />
            <span>调试</span>
          </label>

          {debugMode && (
            <>
              {active && active.summary.scene_mode !== "game" && (
                <button
                  onClick={() => handleStep("social-pre")}
                  disabled={isActiveBusy}
                  title="开场黄昏踩点（仅 social 模式）"
                >
                  申时·开场
                </button>
              )}
              <button
                onClick={() => handleStep("night")}
                disabled={isActiveBusy || !active || active.summary.finished}
              >
                {active?.summary.scene_mode === "game" ? "夜晚" : "子时·夜"}
              </button>
              <button
                onClick={() => handleStep("day")}
                disabled={isActiveBusy || !active || active.summary.finished}
              >
                {active?.summary.scene_mode === "game" ? "白天" : "辰时·议会"}
              </button>
              {active && active.summary.scene_mode !== "game" && (
                <button
                  onClick={() => handleStep("social-post")}
                  disabled={isActiveBusy || active.summary.finished}
                  title="申时余韵（仅 social 模式）"
                >
                  申时·余韵
                </button>
              )}
            </>
          )}

          <button
            onClick={() => handleEndGame()}
            disabled={!active}
            className="danger"
            title="销毁当前 tab 的内存会话；磁盘记录保留。任何阶段都可点。"
          >
            终止本局
          </button>
        </div>
      </header>

      {/* Tab 栏 */}
      {allIds.length > 0 && (
        <nav className="tab-bar">
          {allIds.map((id) => {
            const slot = slots[id];
            const isActive = id === activeId;
            const dayLabel = slot.summary.day > 0 ? `D${slot.summary.day}` : "init";
            const statusLabel = slot.summary.winner
              ? slot.summary.winner === "好人阵营" ? "✅ 好人" : "🐺 狼人"
              : runningById[id] ? "🔄 跑完中" : busyById[id] ? "⏳" : "🔵";
            const modeLabel = slot.summary.scene_mode === "game" ? "训" : "观";
            return (
              <div
                key={id}
                className={`tab${isActive ? " active" : ""}`}
                onClick={() => setActiveId(id)}
                title={`${slot.summary.name} · 创建于 ${slot.summary.created_at}`}
              >
                <span className="tab-mode">{modeLabel}</span>
                <span className="tab-name">{slot.summary.name}</span>
                <span className="tab-status">{dayLabel} {statusLabel}</span>
                <button
                  className="tab-close"
                  onClick={(e) => { e.stopPropagation(); handleEndGame(id); }}
                  title="关闭这个对局"
                >
                  ×
                </button>
              </div>
            );
          })}
        </nav>
      )}

      <main className="main">
        <MapPanel state={active?.state ?? null} liveLog={active?.liveLog ?? []} />
        <TimelinePanel state={active?.state ?? null} liveLog={active?.liveLog ?? []} />
        <AgentPanel
          gameId={active?.summary.id ?? null}
          state={active?.state ?? null}
          selected={active?.selectedAgent ?? null}
          onSelect={(name) => activeId && patchSlot(activeId, { selectedAgent: name })}
        />
      </main>

      <NewGameDialog
        open={showNewGame}
        onClose={() => setShowNewGame(false)}
        onCreated={handleGameCreated}
      />
    </div>
  );
}

// 文件作用：对局视图（原 App 主体逻辑搬到这里）。
// 支持多对局 tab，可同时观察多局并行游戏。

import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../api";
import type { GameState, GameSummary, LiveEvent, StepPhase } from "../types";
import { MapPanel } from "./MapPanel";
import { TimelinePanel } from "./TimelinePanel";
import { AgentPanel } from "./AgentPanel";
import { NewGameDialog } from "./NewGameDialog";
import { ResizableFrame } from "./ResizableFrame";


interface GameSlot {
  summary: GameSummary;
  state: GameState | null;
  liveLog: LiveEvent[];
  selectedAgent: string | null;
}


export function GamesView() {
  const [slots, setSlots] = useState<Record<string, GameSlot>>({});
  const [activeId, setActiveId] = useState<string | null>(null);
  const [busyById, setBusyById] = useState<Record<string, boolean>>({});
  const [runningById, setRunningById] = useState<Record<string, boolean>>({});
  const [showNewGame, setShowNewGame] = useState(false);
  const [debugMode, setDebugMode] = useState(false);

  const wsClosers = useRef<Record<string, () => void>>({});

  const active = activeId ? slots[activeId] ?? null : null;
  const isActiveBusy = activeId ? !!busyById[activeId] : false;

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

  useEffect(() => {
    let cancelled = false;
    api.listGames()
      .then((summaries) => {
        if (cancelled || summaries.length === 0) return;
        setSlots((prev) => {
          const next = { ...prev };
          for (const summary of summaries) {
            if (next[summary.id]) continue;
            next[summary.id] = {
              summary,
              state: null,
              liveLog: [],
              selectedAgent: null,
            };
          }
          return next;
        });
        setActiveId((prev) => prev ?? summaries[0].id);
        summaries.forEach((summary) => {
          api.fetchState(summary.id)
            .then((state) => {
              if (!cancelled) patchSlot(summary.id, { state });
            })
            .catch((e) => console.warn(`fetchState[${summary.id}] failed`, e));
        });
      })
      .catch((e) => console.warn("listGames failed", e));
    return () => {
      cancelled = true;
    };
  }, [patchSlot]);

  const slotIds = Object.keys(slots).join(",");
  useEffect(() => {
    const curIds = new Set(slotIds ? slotIds.split(",") : []);
    for (const id of Object.keys(wsClosers.current)) {
      if (!curIds.has(id)) {
        try { wsClosers.current[id](); } catch { /* noop */ }
        delete wsClosers.current[id];
      }
    }
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

  useEffect(() => {
    return () => {
      for (const close of Object.values(wsClosers.current)) {
        try { close(); } catch { /* noop */ }
      }
      wsClosers.current = {};
    };
  }, []);

  const refreshState = useCallback(async (gameId: string) => {
    try {
      const s = await api.fetchState(gameId);
      patchSlot(gameId, { state: s });
    } catch (e) {
      console.warn(`fetchState[${gameId}] failed`, e);
    }
  }, [patchSlot]);

  const handleGameCreated = useCallback(async (created: GameSummary) => {
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
    try { wsClosers.current[id]?.(); } catch { /* noop */ }
    delete wsClosers.current[id];
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
    if (activeId === id) {
      const remaining = Object.keys(slots).filter((k) => k !== id);
      setActiveId(remaining[0] ?? null);
    }
  };

  const allIds = Object.keys(slots);

  return (
    <>
      <header className="header">
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
          <label className="debug-toggle" title="打开后显示单步推进按钮">
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
            title="销毁当前 tab 的内存会话；磁盘记录保留。"
          >
            终止本局
          </button>
        </div>
      </header>

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
        <ResizableFrame id="map" defaultWidth={720} minWidth={420} minHeight={420}>
          <MapPanel state={active?.state ?? null} liveLog={active?.liveLog ?? []} />
        </ResizableFrame>
        <ResizableFrame id="timeline" defaultWidth={430} minWidth={300} minHeight={320}>
          <TimelinePanel state={active?.state ?? null} liveLog={active?.liveLog ?? []} />
        </ResizableFrame>
        <ResizableFrame id="agent" defaultWidth={330} minWidth={260} minHeight={320}>
          <AgentPanel
            gameId={active?.summary.id ?? null}
            state={active?.state ?? null}
            selected={active?.selectedAgent ?? null}
            onSelect={(name) => activeId && patchSlot(activeId, { selectedAgent: name })}
          />
        </ResizableFrame>
      </main>

      <NewGameDialog
        open={showNewGame}
        onClose={() => setShowNewGame(false)}
        onCreated={handleGameCreated}
      />
    </>
  );
}

import { useCallback, useEffect, useState } from "react";
import * as api from "./api";
import type { GameState, GameSummary, LiveEvent, StepPhase } from "./types";
import { MapPanel } from "./components/MapPanel";
import { TimelinePanel } from "./components/TimelinePanel";
import { AgentPanel } from "./components/AgentPanel";
import { NewGameDialog } from "./components/NewGameDialog";

export default function App() {
  const [summary, setSummary] = useState<GameSummary | null>(null);
  const [state, setState] = useState<GameState | null>(null);
  const [busy, setBusy] = useState(false);
  const [liveLog, setLiveLog] = useState<LiveEvent[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [showNewGame, setShowNewGame] = useState(false);

  // 启动 WebSocket 订阅
  useEffect(() => {
    if (!summary) return;
    const close = api.subscribeLive(
      summary.id,
      (ev) => setLiveLog((prev) => [...prev.slice(-499), ev]),
      (err) => console.warn("ws error", err),
    );
    return close;
  }, [summary?.id]);

  const refreshState = useCallback(async () => {
    if (!summary) return;
    try {
      const s = await api.fetchState(summary.id);
      setState(s);
    } catch (e) {
      console.warn("fetchState failed", e);
    }
  }, [summary?.id]);

  const handleGameCreated = useCallback(async (created: GameSummary) => {
    setSummary(created);
    setLiveLog([]);
    setSelectedAgent(null);
    // setup 已在 dialog 内调用完毕；这里只拉一次完整 state
    try {
      const s = await api.fetchState(created.id);
      setState(s);
    } catch (e) {
      console.warn("初始 state 拉取失败", e);
    }
  }, []);

  const handleStep = async (phase: StepPhase) => {
    if (!summary) return;
    setBusy(true);
    try {
      const s = await api.step(summary.id, phase);
      setSummary(s);
      await refreshState();
    } catch (e) {
      alert("推进失败：" + (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="app">
      <header className="header">
        <h1>江南古镇 · 狼人杀控制台</h1>
        <span className="status">
          {summary
            ? `当前对局：${summary.name} · 第${summary.day}日 · ${
                summary.winner ?? "进行中"
              }`
            : "尚未开局"}
        </span>
        <div style={{ marginLeft: "auto", display: "flex", gap: "0.4em" }}>
          <button onClick={() => setShowNewGame(true)} disabled={busy}>
            新开一局…
          </button>
          <button
            onClick={() => handleStep("social-pre")}
            disabled={busy || !summary}
            title="开场黄昏踩点"
          >
            申时·开场
          </button>
          <button
            onClick={() => handleStep("night")}
            disabled={busy || !summary || summary.finished}
          >
            子时·夜
          </button>
          <button
            onClick={() => handleStep("day")}
            disabled={busy || !summary || summary.finished}
          >
            辰时·议会
          </button>
          <button
            onClick={() => handleStep("social-post")}
            disabled={busy || !summary || summary.finished}
          >
            申时·余韵
          </button>
        </div>
      </header>

      <main className="main">
        <MapPanel state={state} liveLog={liveLog} />
        <TimelinePanel state={state} liveLog={liveLog} />
        <AgentPanel
          gameId={summary?.id ?? null}
          state={state}
          selected={selectedAgent}
          onSelect={setSelectedAgent}
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

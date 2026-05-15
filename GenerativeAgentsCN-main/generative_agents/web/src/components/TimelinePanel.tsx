// 文件作用：时间线面板。组合 state.phase_records（历史）和 liveLog（实时）。

import { useEffect, useRef } from "react";
import type { GameState, LiveEvent, PhaseRecord } from "../types";

interface Props {
  state: GameState | null;
  liveLog: LiveEvent[];
}

export function TimelinePanel({ state, liveLog }: Props) {
  const bodyRef = useRef<HTMLDivElement>(null);

  // 合并历史 + 实时（实时事件不一定能从 state 里覆盖到，所以两路都展示）
  const historical: PhaseRecord[] = state?.phase_records ?? [];
  const live: PhaseRecord[] = liveLog
    .filter((ev): ev is Extract<LiveEvent, { type: "record" }> => ev.type === "record")
    .map((ev) => ({
      time: "",
      day: ev.day,
      phase: ev.phase,
      scope: ev.scope as PhaseRecord["scope"],
      text: ev.text,
      actors: ev.actors,
      location: ev.location,
    }));

  // 去重：取后面发生的为准
  const dedupeKey = (r: PhaseRecord) => `${r.phase}|${r.scope}|${r.text}`;
  const seen = new Set<string>();
  const merged: PhaseRecord[] = [];
  for (const r of [...historical, ...live]) {
    const k = dedupeKey(r);
    if (seen.has(k)) continue;
    seen.add(k);
    merged.push(r);
  }

  // 自动滚到底
  useEffect(() => {
    if (bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  }, [merged.length]);

  return (
    <section className="panel">
      <h2>时间线（{merged.length} 条）</h2>
      <div className="panel-body" ref={bodyRef}>
        {merged.length === 0 ? (
          <div style={{ color: "#999" }}>暂无事件。</div>
        ) : (
          merged.map((r, i) => (
            <div key={i} className={`record scope-${r.scope}`}>
              <div className="meta">
                {r.phase}
                {r.location ? ` · ${r.location}` : ""}
                {r.actors.length ? ` · ${r.actors.join("、")}` : ""}
              </div>
              <div>
                <span className="scope">[{scopeLabel(r.scope)}]</span>
                {r.text}
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

function scopeLabel(scope: string): string {
  switch (scope) {
    case "public": return "公开";
    case "secret": return "暗记";
    case "social": return "私聊";
    case "movement": return "移动";
    case "system": return "系统";
    default: return scope;
  }
}

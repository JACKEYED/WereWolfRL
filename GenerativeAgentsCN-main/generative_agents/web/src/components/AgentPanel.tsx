// 文件作用：角色面板。左侧 12 玩家芯片，右侧选中者的私密记忆（身份/查验/私聊）。

import { useEffect, useState } from "react";
import * as api from "../api";
import type { AgentPrivate, GameState } from "../types";

interface Props {
  gameId: string | null;
  state: GameState | null;
  selected: string | null;
  onSelect: (name: string | null) => void;
}

export function AgentPanel({ gameId, state, selected, onSelect }: Props) {
  const [detail, setDetail] = useState<AgentPrivate | null>(null);

  useEffect(() => {
    if (!gameId || !selected) {
      setDetail(null);
      return;
    }
    api.fetchAgent(gameId, selected)
      .then(setDetail)
      .catch((e) => console.warn("fetchAgent failed", e));
  }, [gameId, selected, state?.phase_records.length]);

  const names = state ? Object.keys(state.players) : [];

  return (
    <section className="panel">
      <h2>角色 · 私密视角</h2>
      <div className="agent-list">
        {names.length === 0 && (
          <div style={{ color: "#999", gridColumn: "1 / -1" }}>
            尚未分发身份。
          </div>
        )}
        {names.map((name) => {
          const player = state!.players[name];
          return (
            <button
              key={name}
              className={
                "agent-chip" +
                (!player.alive ? " dead" : "") +
                (selected === name ? " selected" : "")
              }
              onClick={() => onSelect(selected === name ? null : name)}
              title={player.alive ? "存活" : `死于：${player.death_reason}`}
            >
              {name}
            </button>
          );
        })}
      </div>
      <div className="panel-body">
        {detail ? (
          <div className="agent-detail">
            <h3>{detail.name}</h3>
            <div className="role">
              身份：{detail.role_name}（{detail.camp}）
              {!detail.alive && ` · 已殁：${detail.death_reason}`}
            </div>
            {detail.seer_checks && Object.keys(detail.seer_checks).length > 0 && (
              <>
                <div style={{ fontWeight: 600, marginTop: "0.6em" }}>
                  预言家查验记录：
                </div>
                <ul>
                  {Object.entries(detail.seer_checks).map(([target, result]) => (
                    <li key={target}>
                      {target} → {result}
                    </li>
                  ))}
                </ul>
              </>
            )}
            <div style={{ fontWeight: 600, marginTop: "0.6em" }}>
              私密记忆（最近 {detail.private_log.length} 条）：
            </div>
            <ul>
              {detail.private_log.slice(-30).map((line, i) => (
                <li key={i}>{line}</li>
              ))}
            </ul>
          </div>
        ) : (
          <div style={{ color: "#999" }}>选一名玩家查看其私密视角。</div>
        )}
      </div>
    </section>
  );
}

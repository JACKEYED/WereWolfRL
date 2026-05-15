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

            {detail.belief && Object.keys(detail.belief.beliefs).length > 0 && (
              <>
                <div style={{ fontWeight: 600, marginTop: "0.6em" }}>
                  心里的怀疑表：
                </div>
                <BeliefTable belief={detail.belief} />
              </>
            )}

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

            {detail.trajectory_tail.length > 0 && (
              <>
                <div style={{ fontWeight: 600, marginTop: "0.6em" }}>
                  最近 {detail.trajectory_tail.length} 个决策点（含 step reward）：
                </div>
                <ul>
                  {detail.trajectory_tail.slice(-12).map((s) => (
                    <li key={s.step_id}>
                      <span style={{ color: "#7b7669", fontSize: "0.85em" }}>
                        {s.phase} · {decisionLabel(s.decision_type)}
                      </span>
                      <br />
                      → {String(s.action).slice(0, 80)}
                      <span style={{ marginLeft: "0.4em", color: stepRewardColor(s.reward_step) }}>
                        reward {s.reward_step.toFixed(2)}
                      </span>
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

const ROLE_ZH: Record<string, string> = {
  werewolf: "狼", seer: "预", witch: "巫",
  hunter: "猎", guard: "守", villager: "民",
};

function BeliefTable({ belief }: { belief: NonNullable<AgentPrivate["belief"]> }) {
  return (
    <table className="belief-table">
      <thead>
        <tr>
          <th>对象</th>
          <th>狼</th>
          <th>预</th>
          <th>巫</th>
          <th>猎</th>
          <th>守</th>
          <th>民</th>
        </tr>
      </thead>
      <tbody>
        {Object.entries(belief.beliefs).map(([target, dist]) => {
          const lockedRole = belief.locked[target];
          return (
            <tr key={target} className={lockedRole ? "belief-locked" : ""}>
              <td>{target}{lockedRole && ` · 已确认${ROLE_ZH[lockedRole]}`}</td>
              {(["werewolf", "seer", "witch", "hunter", "guard", "villager"] as const).map((r) => {
                const v = dist[r] ?? 0;
                const top = Math.max(...Object.values(dist));
                const isTop = v === top && v > 0;
                return (
                  <td key={r} className={isTop ? "belief-top" : ""}>
                    {(v * 100).toFixed(0)}
                  </td>
                );
              })}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function decisionLabel(t: string): string {
  return { speech: "发言", vote: "投票", skill: "技能", choice: "选择" }[t] ?? t;
}

function stepRewardColor(r: number): string {
  if (r > 0.1) return "#4a7a4a";
  if (r < -0.1) return "#a04040";
  return "#7b7669";
}

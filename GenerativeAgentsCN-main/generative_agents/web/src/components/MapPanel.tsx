// 文件作用：地图面板。当前是 8 江南地点的占位网格，后续可替换为 Phaser 渲染。

import type { GameState, LiveEvent } from "../types";

const LOCATIONS = [
  { key: "square",      label: "镇中广场",     hint: "白日议会、放逐示众" },
  { key: "teahouse",    label: "听雨茶馆",     hint: "黄昏私聊雅间" },
  { key: "clinic",      label: "同德医馆",     hint: "女巫专属" },
  { key: "stargazer",   label: "观星楼",       hint: "预言家专属" },
  { key: "watchman",    label: "更夫房",       hint: "守卫专属" },
  { key: "dyehouse",    label: "后山染坊",     hint: "狼人会议" },
  { key: "nightmarket", label: "码头夜市",     hint: "黄昏密聊" },
  { key: "inn",         label: "归云客栈",     hint: "客栈住宿" },
];

interface Props {
  state: GameState | null;
  liveLog: LiveEvent[];
}

export function MapPanel({ state, liveLog }: Props) {
  // 简易"在场玩家"推断：扫最近的 movement 记录，把姓名按 location 归类
  const occupancy: Record<string, string[]> = {};
  const recent = liveLog.slice(-30);
  for (const ev of recent) {
    if (ev.type === "record" && ev.scope === "movement" && ev.location) {
      const key = LOCATIONS.find((l) => l.label === ev.location)?.key;
      if (!key) continue;
      occupancy[key] = ev.actors;
    }
  }

  return (
    <section className="panel">
      <h2>江南古镇 · 地图</h2>
      <div className="map-placeholder">
        {state ? (
          <div className="location-grid">
            {LOCATIONS.map((loc) => (
              <div key={loc.key} className="location-tile">
                <div className="name">{loc.label}</div>
                <div className="occupants">
                  {occupancy[loc.key]?.length
                    ? occupancy[loc.key].join("、")
                    : <span style={{ color: "#bbb" }}>{loc.hint}</span>}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="hint">
            <p>尚未载入对局。</p>
            <p>点击右上角"新开一局"开始。</p>
            <p style={{ marginTop: "1em", fontSize: "0.85em", color: "#999" }}>
              Phaser 瓦片地图渲染将在美术资源就绪后接入此处。
            </p>
          </div>
        )}
      </div>
    </section>
  );
}

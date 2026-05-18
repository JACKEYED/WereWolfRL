// 文件作用：实时地图面板。把 phase_records / WebSocket 事件投影成可观察的人物走位与对话。

import {
  useEffect,
  useMemo,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";
import type { GameState, LiveEvent, PhaseRecord } from "../types";

type LocationKey =
  | "square"
  | "teahouse"
  | "clinic"
  | "stargazer"
  | "watchman"
  | "dyehouse"
  | "nightmarket"
  | "inn"
  | "graveyard";

type MapMode = "cinematic" | "tactical";

interface MapLocation {
  key: LocationKey;
  label: string;
  hint: string;
  aliases: string[];
  x: number;
  y: number;
}

interface MapRecord extends PhaseRecord {
  id: string;
  order: number;
}

interface PlayerMarker {
  name: string;
  role: string;
  roleName: string;
  alive: boolean;
  location: LocationKey;
  lastLine: string;
  lastPhase: string;
  speech: string;
  speechScope: string;
  mood: "idle" | "moving" | "speaking" | "dead";
  updatedAt: number;
}

interface MovementTrail {
  id: string;
  from: LocationKey;
  to: LocationKey;
  actor: string;
  order: number;
}

interface MapStats {
  aliveCount: number;
  deadCount: number;
  movingCount: number;
  speakingCount: number;
  hotLocation: MapLocation | null;
}

interface LocationLayout {
  x: number;
  y: number;
  scale: number;
}

interface SpeechDetail {
  speaker: string;
  roleName: string;
  location: string;
  phase: string;
  scope: string;
  text: string;
}

type ResizeHandle = "n" | "e" | "s" | "w" | "nw" | "ne" | "sw" | "se";

type LocationDrag =
  | {
      kind: "move";
      key: LocationKey;
      startClientX: number;
      startClientY: number;
      startX: number;
      startY: number;
    }
  | {
      kind: "resize";
      key: LocationKey;
      handle: ResizeHandle;
      startClientX: number;
      startClientY: number;
      startScale: number;
    };

interface Props {
  state: GameState | null;
  liveLog: LiveEvent[];
}

const LOCATIONS: MapLocation[] = [
  {
    key: "stargazer",
    label: "观星楼",
    hint: "预言家登楼查验",
    aliases: ["神职房"],
    x: 51,
    y: 15,
  },
  {
    key: "teahouse",
    label: "听雨茶馆",
    hint: "黄昏私聊",
    aliases: ["茶馆"],
    x: 35,
    y: 30,
  },
  {
    key: "clinic",
    label: "同德医馆",
    hint: "女巫配药",
    aliases: ["制药室"],
    x: 72,
    y: 33,
  },
  {
    key: "watchman",
    label: "更夫房",
    hint: "守卫值夜",
    aliases: ["值夜房"],
    x: 23,
    y: 49,
  },
  {
    key: "square",
    label: "镇中广场",
    hint: "白日议会",
    aliases: ["广场"],
    x: 51,
    y: 47,
  },
  {
    key: "dyehouse",
    label: "后山染坊",
    hint: "狼人会面",
    aliases: ["狼人议事室"],
    x: 77,
    y: 68,
  },
  {
    key: "nightmarket",
    label: "码头夜市",
    hint: "摊位闲谈",
    aliases: ["市场"],
    x: 32,
    y: 78,
  },
  {
    key: "inn",
    label: "归云客栈",
    hint: "住客落脚",
    aliases: ["客栈"],
    x: 58,
    y: 80,
  },
  {
    key: "graveyard",
    label: "镇外乱葬岗",
    hint: "出局者",
    aliases: ["墓地", "乱葬岗"],
    x: 18,
    y: 20,
  },
];

const LOCATION_BY_KEY = LOCATIONS.reduce(
  (acc, loc) => ({ ...acc, [loc.key]: loc }),
  {} as Record<LocationKey, MapLocation>,
);

const FALLBACK_LOCATIONS: LocationKey[] = [
  "inn",
  "square",
  "teahouse",
  "nightmarket",
];

const SPEECH_SCOPES = new Set(["public", "social", "secret"]);
const MAP_LAYOUT_STORAGE_KEY = "jiangnan-live-map-layout-v2";
const RESIZE_HANDLES: ResizeHandle[] = ["n", "e", "s", "w", "nw", "ne", "sw", "se"];

// 每个地点对应一种小建筑插画风格。
const BUILDING_KIND: Record<LocationKey, string> = {
  stargazer: "pagoda",
  teahouse: "pavilion",
  clinic: "shrine",
  watchman: "tower",
  square: "plaza",
  dyehouse: "workshop",
  nightmarket: "stall",
  inn: "inn",
  graveyard: "tomb",
};

// 萤火虫种子位置（夜间渲染）。
const FIREFLY_SEEDS = Array.from({ length: 18 }, (_, i) => {
  const angle = (i * 137.508) % 360;
  return {
    left: ((Math.sin(angle * 0.31) + 1) * 48 + 4).toFixed(2),
    top: ((Math.cos(angle * 0.47) + 1) * 46 + 3).toFixed(2),
    delay: (i * 0.31).toFixed(2),
    duration: (4 + (i % 5) * 0.6).toFixed(2),
  };
});

// 飘落花瓣种子（白天/黄昏）。
const PETAL_SEEDS = Array.from({ length: 10 }, (_, i) => ({
  left: ((i * 13 + 7) % 95).toFixed(2),
  delay: (i * 0.7).toFixed(2),
  duration: (9 + (i % 4) * 1.2).toFixed(2),
}));

export function MapPanel({ state, liveLog }: Props) {
  const [mode, setMode] = useState<MapMode>("cinematic");
  const [layoutMode, setLayoutMode] = useState(false);
  const [locationLayout, setLocationLayout] = useState<Record<LocationKey, LocationLayout>>(
    () => loadLocationLayout(),
  );
  const [locationDrag, setLocationDrag] = useState<LocationDrag | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [selectedLocation, setSelectedLocation] = useState<LocationKey | null>(null);
  const [speechDetail, setSpeechDetail] = useState<SpeechDetail | null>(null);
  const records = useMemo(() => mergeRecords(state, liveLog), [state, liveLog]);
  const built = useMemo(() => buildMapState(state, records), [state, records]);
  const visibleTrails = built.trails.slice(-14);
  const recentEvents = records
    .filter((r) => r.scope === "movement" || SPEECH_SCOPES.has(r.scope))
    .slice(-8)
    .reverse();
  const stats = buildStats(built.players, built.groups);
  const phaseTone = phaseToneClass(state?.phase ?? "");
  const selectedPlayer = selectedAgent
    ? built.players.find((p) => p.name === selectedAgent) ?? null
    : null;
  const focusedPlayer =
    selectedPlayer ??
    built.players.find((p) => p.mood === "speaking") ??
    built.players.find((p) => p.mood === "moving") ??
    built.players[0] ??
    null;
  const focusedLocationKey = selectedLocation ?? focusedPlayer?.location ?? stats.hotLocation?.key ?? "square";
  const focusedLocation = LOCATION_BY_KEY[focusedLocationKey];
  const focusedOccupants = built.groups[focusedLocationKey] ?? [];
  const focusEvents = records
    .filter((record) => isRecordInFocus(record, focusedPlayer?.name ?? null, focusedLocationKey))
    .slice(-5)
    .reverse();
  const activeLocationKeys = new Set(
    recentEvents
      .map((record) => resolveLocation(record.location) ?? resolveLocation(record.text))
      .filter((key): key is LocationKey => key !== null),
  );

  useEffect(() => {
    try {
      window.localStorage.setItem(MAP_LAYOUT_STORAGE_KEY, JSON.stringify(locationLayout));
    } catch {
      // ignore unavailable storage
    }
  }, [locationLayout]);

  useEffect(() => {
    if (!locationDrag) return;

    const previousUserSelect = document.body.style.userSelect;
    document.body.style.userSelect = "none";

    const handlePointerMove = (event: PointerEvent) => {
      const mapRect = document
        .querySelector<HTMLElement>(".town-map")
        ?.getBoundingClientRect();
      setLocationLayout((prev) => {
        const current = prev[locationDrag.key] ?? LOCATION_BY_KEY[locationDrag.key];
        if (locationDrag.kind === "move") {
          const width = mapRect?.width || 1;
          const height = mapRect?.height || 1;
          return {
            ...prev,
            [locationDrag.key]: {
              x: clamp(
                locationDrag.startX +
                  ((event.clientX - locationDrag.startClientX) / width) * 100,
                6,
                94,
              ),
              y: clamp(
                locationDrag.startY +
                  ((event.clientY - locationDrag.startClientY) / height) * 100,
                8,
                92,
              ),
              scale: current.scale ?? 1,
            },
          };
        }

        const delta = resizeDragDelta(
          locationDrag.handle,
          event.clientX - locationDrag.startClientX,
          event.clientY - locationDrag.startClientY,
        );
        return {
          ...prev,
          [locationDrag.key]: {
            x: current.x,
            y: current.y,
            scale: clamp(locationDrag.startScale + delta / 145, 0.68, 1.55),
          },
        };
      });
    };

    const handlePointerUp = () => setLocationDrag(null);
    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", handlePointerUp, { once: true });
    window.addEventListener("pointercancel", handlePointerUp, { once: true });

    return () => {
      document.body.style.userSelect = previousUserSelect;
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", handlePointerUp);
      window.removeEventListener("pointercancel", handlePointerUp);
    };
  }, [locationDrag]);

  const adjustLocation = (key: LocationKey, dx: number, dy: number, scaleDelta = 0) => {
    setLocationLayout((prev) => {
      const cur = prev[key] ?? LOCATION_BY_KEY[key];
      return {
        ...prev,
        [key]: {
          x: clamp(cur.x + dx, 6, 94),
          y: clamp(cur.y + dy, 8, 92),
          scale: clamp((cur.scale ?? 1) + scaleDelta, 0.68, 1.55),
        },
      };
    });
  };

  const resetLocationLayout = () => {
    setLocationLayout(createDefaultLocationLayout());
  };

  const beginMoveLocation = (
    key: LocationKey,
    layout: LocationLayout,
    event: ReactPointerEvent<HTMLDivElement>,
  ) => {
    if (!layoutMode) return;
    event.preventDefault();
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // Some browsers may not allow capture after synthetic delegation.
    }
    setSelectedLocation(key);
    setSelectedAgent(null);
    setLocationDrag({
      kind: "move",
      key,
      startClientX: event.clientX,
      startClientY: event.clientY,
      startX: layout.x,
      startY: layout.y,
    });
  };

  const beginResizeLocation = (
    key: LocationKey,
    handle: ResizeHandle,
    layout: LocationLayout,
    event: ReactPointerEvent<HTMLButtonElement>,
  ) => {
    if (!layoutMode) return;
    event.preventDefault();
    event.stopPropagation();
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // Window-level listeners still handle the drag.
    }
    setSelectedLocation(key);
    setSelectedAgent(null);
    setLocationDrag({
      kind: "resize",
      key,
      handle,
      startClientX: event.clientX,
      startClientY: event.clientY,
      startScale: layout.scale ?? 1,
    });
  };

  return (
    <section className="panel map-panel">
      <h2>
        <span>江南古镇 · 实时地图</span>
        {state && (
          <span className="map-phase">
            第{state.day}日 · {state.phase || "待机"}
          </span>
        )}
      </h2>
      <div className={`live-map${state ? "" : " live-map-empty"}`}>
        {state ? (
          <>
            <div
              className={`town-map mode-${mode} tone-${phaseTone}`}
              aria-label="江南古镇实时地图"
            >
              <div className="map-scenery">
                <div className="map-mountains" />
                <div className="map-water map-river" />
                <div className="map-water map-pond" />
                <div className="map-bridge map-bridge-north" />
                <div className="map-bridge map-bridge-south" />
                <div className="town-road road-main" />
                <div className="town-road road-vertical" />
                <div className="town-road road-hill" />
                <div className="map-tree tree-a" />
                <div className="map-tree tree-b" />
                <div className="map-tree tree-c" />
                <div className="map-market-row" />
                <div className="map-lotus map-lotus-a" />
                <div className="map-lotus map-lotus-b" />
              </div>
              <div className="map-atmosphere" aria-hidden="true">
                <div className={`sky-disc sky-disc-${phaseTone}`} />
                {phaseTone === "evening" && <div className="mist-veil" />}
                {phaseTone === "night" && (
                  <div className="firefly-layer">
                    {FIREFLY_SEEDS.map((f, i) => (
                      <span
                        key={`fly-${i}`}
                        className="firefly"
                        style={{
                          left: `${f.left}%`,
                          top: `${f.top}%`,
                          animationDelay: `${f.delay}s`,
                          animationDuration: `${f.duration}s`,
                        }}
                      />
                    ))}
                  </div>
                )}
                {(phaseTone === "day" || phaseTone === "evening") && (
                  <div className="petal-layer">
                    {PETAL_SEEDS.map((p, i) => (
                      <span
                        key={`petal-${i}`}
                        className="petal"
                        style={{
                          left: `${p.left}%`,
                          animationDelay: `${p.delay}s`,
                          animationDuration: `${p.duration}s`,
                        }}
                      />
                    ))}
                  </div>
                )}
                <div className="map-vignette" />
              </div>

              <div className="map-hud">
                <div className={`phase-card phase-card-${phaseTone}`}>
                  <div className={`phase-card-icon phase-icon-${phaseTone}`} aria-hidden="true">
                    {phaseTone === "night" ? "🌙" : phaseTone === "evening" ? "🌆" : phaseTone === "day" ? "☀️" : "✦"}
                  </div>
                  <div className="phase-card-body">
                    <span>当前幕</span>
                    <strong>{built.currentLabel}</strong>
                    <small>第{state.day}日 · {state.phase || "待机"}</small>
                  </div>
                </div>
                <div className="map-stat-grid">
                  <div>
                    <span>存活</span>
                    <strong>{stats.aliveCount}</strong>
                  </div>
                  <div>
                    <span>出局</span>
                    <strong>{stats.deadCount}</strong>
                  </div>
                  <div>
                    <span>移动</span>
                    <strong>{stats.movingCount}</strong>
                  </div>
                  <div>
                    <span>发言</span>
                    <strong>{stats.speakingCount}</strong>
                  </div>
                </div>
                <div className="map-controls" aria-label="地图模式">
                  <button
                    type="button"
                    className={mode === "cinematic" ? "active" : ""}
                    onClick={() => setMode("cinematic")}
                  >
                    观赏
                  </button>
                  <button
                    type="button"
                    className={mode === "tactical" ? "active" : ""}
                    onClick={() => setMode("tactical")}
                  >
                    推理
                  </button>
                  <button
                    type="button"
                    className={layoutMode ? "active" : ""}
                    onClick={() => setLayoutMode((v) => !v)}
                  >
                    布局
                  </button>
                </div>
                {layoutMode && (
                  <div className="layout-toolbar">
                    <strong>{focusedLocation.label}</strong>
                    <div className="layout-pad">
                      <button type="button" onClick={() => adjustLocation(focusedLocationKey, 0, -3)}>↑</button>
                      <button type="button" onClick={() => adjustLocation(focusedLocationKey, -3, 0)}>←</button>
                      <button type="button" onClick={() => adjustLocation(focusedLocationKey, 0, 3)}>↓</button>
                      <button type="button" onClick={() => adjustLocation(focusedLocationKey, 3, 0)}>→</button>
                      <button type="button" onClick={() => adjustLocation(focusedLocationKey, 0, 0, -0.08)}>−</button>
                      <button type="button" onClick={() => adjustLocation(focusedLocationKey, 0, 0, 0.08)}>＋</button>
                      <button type="button" onClick={resetLocationLayout}>复位</button>
                    </div>
                  </div>
                )}
              </div>

              <svg
                className="map-trails"
                viewBox="0 0 100 100"
                preserveAspectRatio="none"
              >
                <defs>
                  <marker
                    id="trail-arrow"
                    markerWidth="5"
                    markerHeight="5"
                    refX="4"
                    refY="2.5"
                    orient="auto"
                  >
                    <path d="M0,0 L5,2.5 L0,5 Z" />
                  </marker>
                </defs>
                {visibleTrails.map((trail) => {
                  const from = LOCATION_BY_KEY[trail.from];
                  const to = LOCATION_BY_KEY[trail.to];
                  return (
                    <line
                      key={trail.id}
                      x1={from.x}
                      y1={from.y}
                      x2={to.x}
                      y2={to.y}
                      vectorEffect="non-scaling-stroke"
                      markerEnd="url(#trail-arrow)"
                    />
                  );
                })}
              </svg>

              {LOCATIONS.map((loc) => {
                const occupants = built.groups[loc.key] ?? [];
                const isSelected = focusedLocationKey === loc.key;
                const isHot = activeLocationKeys.has(loc.key);
                const layout = locationLayout[loc.key] ?? { x: loc.x, y: loc.y, scale: 1 };
                return (
                  <div
                    role="button"
                    tabIndex={0}
                    key={loc.key}
                    className={[
                      "map-location",
                      `map-location-${loc.key}`,
                      `building-${BUILDING_KIND[loc.key]}`,
                      isSelected ? "selected" : "",
                      layoutMode ? "editable" : "",
                      locationDrag?.key === loc.key ? `dragging dragging-${locationDrag.kind}` : "",
                      isHot ? "hot" : "",
                      occupants.length > 0 ? "occupied" : "",
                    ]
                      .filter(Boolean)
                      .join(" ")}
                    style={positionStyle(layout.x, layout.y, layout.scale)}
                    onClick={() => {
                      setSelectedLocation(loc.key);
                      setSelectedAgent(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        setSelectedLocation(loc.key);
                        setSelectedAgent(null);
                      }
                    }}
                  >
                    <div className="location-dot" />
                    <div className="location-resize-shell">
                      <div
                        className="location-card"
                        onPointerDown={(e) => beginMoveLocation(loc.key, layout, e)}
                      >
                        <BuildingArt locKey={loc.key} />
                        <div className="location-name">{loc.label}</div>
                        <div className="location-meta">{loc.hint}</div>
                        <div className="location-occupants">
                          {formatOccupants(occupants)}
                        </div>
                        {occupants.length > 0 && (
                          <span className="occupant-badge">{occupants.length}</span>
                        )}
                      </div>
                      {layoutMode && (
                        <div className="resize-handles" aria-hidden="true">
                          {RESIZE_HANDLES.map((handle) => (
                            <button
                              type="button"
                              key={handle}
                              className={`resize-handle resize-${handle}`}
                              onPointerDown={(e) => beginResizeLocation(loc.key, handle, layout, e)}
                              tabIndex={-1}
                            />
                          ))}
                        </div>
                      )}
                    </div>
                    {layoutMode && isSelected && (
                      <div className="location-toolbox" onClick={(e) => e.stopPropagation()}>
                        <button type="button" onClick={() => adjustLocation(loc.key, 0, -2)}>↑</button>
                        <button type="button" onClick={() => adjustLocation(loc.key, -2, 0)}>←</button>
                        <button type="button" onClick={() => adjustLocation(loc.key, 2, 0)}>→</button>
                        <button type="button" onClick={() => adjustLocation(loc.key, 0, 2)}>↓</button>
                        <button type="button" onClick={() => adjustLocation(loc.key, 0, 0, -0.06)}>−</button>
                        <button type="button" onClick={() => adjustLocation(loc.key, 0, 0, 0.06)}>＋</button>
                      </div>
                    )}
                  </div>
                );
              })}

              {built.players.map((player) => {
                const loc = locationLayout[player.location] ?? LOCATION_BY_KEY[player.location];
                const displayLocation = LOCATION_BY_KEY[player.location];
                const group = built.groups[player.location] ?? [];
                const groupIndex = group.findIndex((p) => p.name === player.name);
                const offset = tokenOffset(groupIndex, group.length);
                const showBubble = player.speech && player.mood === "speaking";
                const tokenClass = [
                  "agent-token",
                  `role-${roleClass(player.role)}`,
                  `mood-${player.mood}`,
                  loc.x > 72 ? "edge-right" : "",
                  loc.x < 28 ? "edge-left" : "",
                  showBubble ? "has-bubble" : "",
                ]
                  .filter(Boolean)
                  .join(" ");
                const isFocused = focusedPlayer?.name === player.name;

                return (
                  <div
                    role="button"
                    tabIndex={0}
                    key={player.name}
                    className={`${tokenClass}${isFocused ? " focused" : ""}`}
                    style={tokenStyle(
                      loc.x,
                      loc.y,
                      offset.x,
                      offset.y,
                      (Math.max(groupIndex, 0) % 4) * 12,
                    )}
                    title={`${player.name} · ${displayLocation.label} · ${player.lastLine}`}
                    onClick={() => {
                      setSelectedAgent(player.name);
                      setSelectedLocation(player.location);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        setSelectedAgent(player.name);
                        setSelectedLocation(player.location);
                      }
                    }}
                  >
                    {showBubble && (
                      <button
                        type="button"
                        className="speech-bubble"
                        onClick={(e) => {
                          e.stopPropagation();
                          setSpeechDetail({
                            speaker: player.name,
                            roleName: player.roleName,
                            location: displayLocation.label,
                            phase: player.lastPhase,
                            scope: player.speechScope,
                            text: player.lastLine,
                          });
                        }}
                        title="展开完整发言"
                      >
                        <span>{shorten(player.speech, 20)}</span>
                      </button>
                    )}
                    <div className="agent-status">
                      <span className="agent-status-icon" aria-hidden="true">
                        {moodIcon(player.mood, player.alive)}
                      </span>
                    </div>
                    <div className="agent-avatar">
                      <span className="agent-head-glyph">{player.name.slice(0, 1)}</span>
                      <span className="agent-role-badge" title={player.roleName}>
                        {roleEmoji(player.role)}
                      </span>
                    </div>
                    <div className="agent-shadow" aria-hidden="true" />
                    <div className="agent-name">{player.name}</div>
                  </div>
                );
              })}

              <div className="map-status-chip">
                <span>{built.currentLabel}</span>
              </div>
              {speechDetail && (
                <div className="speech-inspector">
                  <div className="speech-inspector-head">
                    <div>
                      <strong>{speechDetail.speaker}</strong>
                      <span>
                        {speechDetail.roleName} · {speechDetail.location} · {scopeLabel(speechDetail.scope)}
                      </span>
                    </div>
                    <button type="button" onClick={() => setSpeechDetail(null)}>×</button>
                  </div>
                  <p>{speechDetail.text}</p>
                </div>
              )}
            </div>

            <div className="map-live-dock game-dock">
              <div className="dock-section focus-section">
                <div className="dock-title">焦点</div>
                <div className="focus-card">
                  <div className="focus-main">
                    <div className={`focus-avatar role-${roleClass(focusedPlayer?.role ?? "villager")}`}>
                      {focusedPlayer?.name.slice(0, 1) ?? "局"}
                    </div>
                    <div>
                      <strong>{focusedPlayer?.name ?? "全局观察"}</strong>
                      <span>
                        {focusedPlayer
                          ? `${focusedPlayer.roleName} · ${focusedPlayer.alive ? "存活" : "出局"}`
                          : "等待角色入场"}
                      </span>
                    </div>
                  </div>
                  <div className="focus-meta-grid">
                    <div>
                      <span>地点</span>
                      <strong>{focusedLocation.label}</strong>
                    </div>
                    <div>
                      <span>同场</span>
                      <strong>{focusedOccupants.length}</strong>
                    </div>
                    <div>
                      <span>状态</span>
                      <strong>{focusedPlayer ? moodLabel(focusedPlayer.mood) : "观察"}</strong>
                    </div>
                  </div>
                  <p>{focusedPlayer?.lastLine ?? "暂无角色行动。"}</p>
                </div>
              </div>

              <div className="dock-section">
                <div className="dock-title">现场播报</div>
                <div className="event-feed">
                  {(focusEvents.length ? focusEvents : recentEvents).length === 0 ? (
                    <div className="event-empty">暂无现场事件。</div>
                  ) : (
                    (focusEvents.length ? focusEvents : recentEvents).map((record) => (
                      <button
                        type="button"
                        key={record.id}
                        className={`event-row event-${record.scope}`}
                        onClick={() => {
                          const actor = record.actors[0] ?? null;
                          const loc = resolveLocation(record.location) ?? resolveLocation(record.text);
                          setSelectedAgent(actor);
                          setSelectedLocation(loc);
                        }}
                        title={record.text}
                      >
                        <span>{scopeLabel(record.scope)}</span>
                        <p>{shorten(record.text, 92)}</p>
                      </button>
                    ))
                  )}
                </div>
              </div>

              <div className="dock-section roster-section">
                <div className="dock-title">行动板</div>
                <div className="roster-grid">
                  {built.players.map((player) => {
                    const isFocused = focusedPlayer?.name === player.name;
                    return (
                      <button
                        type="button"
                        key={player.name}
                        className={`roster-agent roster-${player.mood}${isFocused ? " selected" : ""}`}
                        title={player.lastLine}
                        onClick={() => {
                          setSelectedAgent(player.name);
                          setSelectedLocation(player.location);
                        }}
                      >
                        <span className={`roster-dot role-${roleClass(player.role)}`} />
                        <span className="roster-name">{player.name}</span>
                        <span className="roster-place">
                          {LOCATION_BY_KEY[player.location].label}
                        </span>
                      </button>
                    );
                  })}
                </div>
                <div className="location-strip">
                  {LOCATIONS.filter((loc) => loc.key !== "graveyard").map((loc) => (
                    <button
                      type="button"
                      key={loc.key}
                      className={focusedLocationKey === loc.key ? "selected" : ""}
                      onClick={() => {
                        setSelectedLocation(loc.key);
                        setSelectedAgent(null);
                      }}
                    >
                      {loc.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          </>
        ) : (
          <div className="map-empty-state">
            <strong>等待开局</strong>
            <span>江南古镇的街巷、角色和对话将在这里展开。</span>
          </div>
        )}
      </div>
    </section>
  );
}

function mergeRecords(state: GameState | null, liveLog: LiveEvent[]): MapRecord[] {
  const historical = state?.phase_records ?? [];
  const live = liveLog
    .filter((ev): ev is Extract<LiveEvent, { type: "record" }> => ev.type === "record")
    .map<PhaseRecord>((ev) => ({
      time: "",
      day: ev.day,
      phase: ev.phase,
      scope: ev.scope as PhaseRecord["scope"],
      text: ev.text,
      actors: ev.actors,
      location: ev.location,
    }));
  const seen = new Set<string>();
  const merged: MapRecord[] = [];

  [...historical, ...live].forEach((record, index) => {
    const id = [
      record.day,
      record.phase,
      record.scope,
      record.location,
      record.actors.join(","),
      record.text,
    ].join("|");
    if (seen.has(id)) return;
    seen.add(id);
    merged.push({ ...record, id, order: index });
  });

  return merged;
}

function buildMapState(state: GameState | null, records: MapRecord[]) {
  const markers = new Map<string, PlayerMarker>();
  const lastLocation = new Map<string, LocationKey>();
  const trails: MovementTrail[] = [];
  const players = state?.players ?? {};

  Object.entries(players).forEach(([name, player], index) => {
    const location = player.alive
      ? FALLBACK_LOCATIONS[index % FALLBACK_LOCATIONS.length]
      : "graveyard";
    markers.set(name, {
      name,
      role: player.role,
      roleName: state?.role_names[name] ?? player.role,
      alive: player.alive,
      location,
      lastLine: "等待新的行动。",
      lastPhase: state?.phase ?? "init",
      speech: "",
      speechScope: "",
      mood: player.alive ? "idle" : "dead",
      updatedAt: -1,
    });
    lastLocation.set(name, location);
  });

  records.forEach((record) => {
    const location = resolveLocation(record.location) ?? resolveLocation(record.text);
    const actors = record.actors.filter(Boolean);

    if (record.scope === "movement" && location) {
      actors.forEach((actor) => {
        const marker = ensureMarker(markers, lastLocation, actor, state);
        const from = lastLocation.get(actor) ?? marker.location;
        if (from !== location) {
          trails.push({
            id: `${record.id}-${actor}`,
            from,
            to: location,
            actor,
            order: record.order,
          });
        }
        marker.location = location;
        marker.lastLine = record.text;
        marker.lastPhase = record.phase;
        marker.mood = marker.alive ? "moving" : "dead";
        marker.updatedAt = record.order;
        lastLocation.set(actor, location);
      });
      return;
    }

    if (actors.length === 0) return;

    actors.forEach((actor) => {
      const marker = ensureMarker(markers, lastLocation, actor, state);
      if (location) {
        marker.location = location;
        lastLocation.set(actor, location);
      }
      marker.lastLine = record.text;
      marker.lastPhase = record.phase;
      marker.updatedAt = record.order;
      if (SPEECH_SCOPES.has(record.scope)) {
        marker.speech = extractSpeech(record.text, actor);
        marker.speechScope = record.scope;
        marker.mood = marker.alive ? "speaking" : "dead";
      } else {
        marker.mood = marker.alive ? "idle" : "dead";
      }
    });
  });

  for (const marker of markers.values()) {
    const player = players[marker.name];
    if (player && !player.alive) {
      marker.alive = false;
      marker.location = "graveyard";
      marker.mood = "dead";
      marker.lastLine = player.death_reason || marker.lastLine;
    }
  }

  const sortedPlayers = Array.from(markers.values()).sort((a, b) =>
    a.name.localeCompare(b.name, "zh-Hans-CN"),
  );
  const groups = sortedPlayers.reduce(
    (acc, player) => {
      acc[player.location] = acc[player.location] ?? [];
      acc[player.location].push(player);
      return acc;
    },
    {} as Record<LocationKey, PlayerMarker[]>,
  );
  const current = records[records.length - 1];

  return {
    players: sortedPlayers,
    groups,
    trails: trails.sort((a, b) => a.order - b.order),
    currentLabel: current ? `${current.phase} · ${scopeLabel(current.scope)}` : "等待事件",
  };
}

function buildStats(
  players: PlayerMarker[],
  groups: Record<LocationKey, PlayerMarker[]>,
): MapStats {
  const aliveCount = players.filter((p) => p.alive).length;
  const deadCount = players.length - aliveCount;
  const movingCount = players.filter((p) => p.mood === "moving").length;
  const speakingCount = players.filter((p) => p.mood === "speaking").length;
  const hotLocationKey = Object.entries(groups)
    .filter(([key]) => key !== "graveyard")
    .sort((a, b) => b[1].length - a[1].length)[0]?.[0] as LocationKey | undefined;

  return {
    aliveCount,
    deadCount,
    movingCount,
    speakingCount,
    hotLocation: hotLocationKey ? LOCATION_BY_KEY[hotLocationKey] : null,
  };
}

function createDefaultLocationLayout(): Record<LocationKey, LocationLayout> {
  return LOCATIONS.reduce(
    (acc, loc) => {
      acc[loc.key] = { x: loc.x, y: loc.y, scale: 1 };
      return acc;
    },
    {} as Record<LocationKey, LocationLayout>,
  );
}

function loadLocationLayout(): Record<LocationKey, LocationLayout> {
  const fallback = createDefaultLocationLayout();
  if (typeof window === "undefined") return fallback;

  try {
    const raw = window.localStorage.getItem(MAP_LAYOUT_STORAGE_KEY);
    if (!raw) return fallback;
    const parsed = JSON.parse(raw) as Partial<Record<LocationKey, Partial<LocationLayout>>>;
    const merged = { ...fallback };
    for (const loc of LOCATIONS) {
      const item = parsed[loc.key];
      if (!item) continue;
      merged[loc.key] = {
        x: clamp(Number(item.x ?? loc.x), 6, 94),
        y: clamp(Number(item.y ?? loc.y), 8, 92),
        scale: clamp(Number(item.scale ?? 1), 0.68, 1.55),
      };
    }
    return merged;
  } catch {
    return fallback;
  }
}

function clamp(value: number, min: number, max: number): number {
  if (!Number.isFinite(value)) return min;
  return Math.min(max, Math.max(min, value));
}

function resizeDragDelta(handle: ResizeHandle, dx: number, dy: number): number {
  switch (handle) {
    case "n":
      return -dy;
    case "e":
      return dx;
    case "s":
      return dy;
    case "w":
      return -dx;
    case "ne":
      return Math.max(dx, -dy);
    case "nw":
      return Math.max(-dx, -dy);
    case "se":
      return Math.max(dx, dy);
    case "sw":
      return Math.max(-dx, dy);
    default:
      return 0;
  }
}

function isRecordInFocus(
  record: MapRecord,
  playerName: string | null,
  locationKey: LocationKey | null,
): boolean {
  if (playerName && record.actors.includes(playerName)) return true;
  if (!locationKey) return false;
  const recordLocation = resolveLocation(record.location) ?? resolveLocation(record.text);
  return recordLocation === locationKey;
}

function phaseToneClass(phase: string): string {
  if (phase.includes("夜") || phase.includes("子时") || phase.toLowerCase().includes("night")) {
    return "night";
  }
  if (phase.includes("黄昏") || phase.includes("申时") || phase.includes("evening")) {
    return "evening";
  }
  if (phase.includes("议会") || phase.includes("白天") || phase.toLowerCase().includes("day")) {
    return "day";
  }
  return "neutral";
}

function ensureMarker(
  markers: Map<string, PlayerMarker>,
  lastLocation: Map<string, LocationKey>,
  name: string,
  state: GameState | null,
): PlayerMarker {
  const existing = markers.get(name);
  if (existing) return existing;

  const location = FALLBACK_LOCATIONS[markers.size % FALLBACK_LOCATIONS.length];
  const marker: PlayerMarker = {
    name,
    role: "villager",
    roleName: "村民",
    alive: true,
    location,
    lastLine: "刚刚进入小镇。",
    lastPhase: state?.phase ?? "init",
    speech: "",
    speechScope: "",
    mood: "idle",
    updatedAt: -1,
  };
  markers.set(name, marker);
  lastLocation.set(name, location);
  return marker;
}

function resolveLocation(raw: string): LocationKey | null {
  const text = raw.trim();
  if (!text) return null;
  for (const loc of LOCATIONS) {
    const names = [loc.label, ...loc.aliases];
    if (names.some((name) => text === name || text.includes(name))) {
      return loc.key;
    }
  }
  return null;
}

function extractSpeech(text: string, actor: string): string {
  const match = text.match(/(?:公开发言|私下说|闲谈)：(.+)$/);
  if (match?.[1]) return shorten(match[1], 48);

  const actorPrefix = `${actor}：`;
  if (text.startsWith(actorPrefix)) {
    return shorten(text.slice(actorPrefix.length), 48);
  }

  const colon = text.lastIndexOf("：");
  return shorten(colon >= 0 ? text.slice(colon + 1) : text, 48);
}

function tokenOffset(index: number, total: number) {
  if (total <= 1) return { x: 0, y: 0 };
  const angle = (Math.PI * 2 * Math.max(index, 0)) / total - Math.PI / 2;
  const radius = total > 8 ? 68 : total > 5 ? 54 : 32;
  return {
    x: Math.cos(angle) * radius,
    y: Math.sin(angle) * radius,
  };
}

function positionStyle(x: number, y: number, scale = 1): CSSProperties {
  return {
    left: `${x}%`,
    top: `${y}%`,
    "--loc-scale": scale,
  } as CSSProperties;
}

function tokenStyle(
  x: number,
  y: number,
  offsetX: number,
  offsetY: number,
  bubbleLift = 0,
): CSSProperties {
  return {
    left: `${x}%`,
    top: `${y}%`,
    transform: `translate(calc(-50% + ${offsetX}px), calc(-50% + ${offsetY}px))`,
    "--bubble-lift": `${bubbleLift}px`,
  } as CSSProperties;
}

function formatOccupants(players: PlayerMarker[]): string {
  if (players.length === 0) return "暂无停留";
  const names = players.slice(0, 3).map((p) => p.name);
  return players.length > 3 ? `${names.join("、")} 等${players.length}人` : names.join("、");
}

function shorten(text: string, max: number): string {
  const clean = text.replace(/\s+/g, " ").trim();
  return clean.length > max ? `${clean.slice(0, max - 1)}…` : clean;
}

function scopeLabel(scope: string): string {
  switch (scope) {
    case "public":
      return "公开";
    case "secret":
      return "暗记";
    case "social":
      return "私聊";
    case "movement":
      return "移动";
    case "system":
      return "系统";
    default:
      return scope;
  }
}

function moodLabel(mood: PlayerMarker["mood"]): string {
  switch (mood) {
    case "moving":
      return "移动";
    case "speaking":
      return "发言";
    case "dead":
      return "出局";
    default:
      return "待机";
  }
}

function roleClass(role: string): string {
  switch (role) {
    case "werewolf":
      return "werewolf";
    case "seer":
      return "seer";
    case "witch":
      return "witch";
    case "guard":
      return "guard";
    case "hunter":
      return "hunter";
    default:
      return "villager";
  }
}

function roleEmoji(role: string): string {
  switch (role) {
    case "werewolf":
      return "狼";
    case "seer":
      return "预";
    case "witch":
      return "巫";
    case "guard":
      return "守";
    case "hunter":
      return "猎";
    default:
      return "民";
  }
}

function moodIcon(mood: PlayerMarker["mood"], alive: boolean): string {
  if (!alive || mood === "dead") return "💀";
  switch (mood) {
    case "speaking":
      return "💬";
    case "moving":
      return "👣";
    default:
      return "";
  }
}

// 各地点的微型建筑插画——纯 div + CSS 渲染，避免引入图片资源。
function BuildingArt({ locKey }: { locKey: LocationKey }) {
  switch (locKey) {
    case "stargazer":
      return (
        <div className="building-art building-art-pagoda" aria-hidden="true">
          <div className="bldg-roof bldg-roof-top" />
          <div className="bldg-roof bldg-roof-mid" />
          <div className="bldg-wall">
            <span className="bldg-window" />
          </div>
          <div className="bldg-lantern" />
        </div>
      );
    case "teahouse":
      return (
        <div className="building-art building-art-pavilion" aria-hidden="true">
          <div className="bldg-roof bldg-roof-wide" />
          <div className="bldg-wall bldg-wall-open">
            <span className="bldg-pillar" />
            <span className="bldg-pillar" />
          </div>
          <div className="bldg-lantern bldg-lantern-left" />
          <div className="bldg-lantern bldg-lantern-right" />
        </div>
      );
    case "clinic":
      return (
        <div className="building-art building-art-shrine" aria-hidden="true">
          <div className="bldg-roof bldg-roof-shrine" />
          <div className="bldg-wall">
            <span className="bldg-door" />
            <span className="bldg-cross">✚</span>
          </div>
          <div className="bldg-lantern" />
        </div>
      );
    case "watchman":
      return (
        <div className="building-art building-art-tower" aria-hidden="true">
          <div className="bldg-roof bldg-roof-pointy" />
          <div className="bldg-wall bldg-wall-narrow">
            <span className="bldg-window-small" />
            <span className="bldg-window-small" />
          </div>
          <div className="bldg-lantern" />
        </div>
      );
    case "dyehouse":
      return (
        <div className="building-art building-art-workshop" aria-hidden="true">
          <div className="bldg-roof bldg-roof-flat" />
          <div className="bldg-wall bldg-wall-stripe" />
          <div className="bldg-banner" />
          <div className="bldg-lantern bldg-lantern-red" />
        </div>
      );
    case "nightmarket":
      return (
        <div className="building-art building-art-stall" aria-hidden="true">
          <div className="bldg-roof bldg-roof-stall" />
          <div className="bldg-wall bldg-wall-stall">
            <span className="bldg-stall-bar" />
            <span className="bldg-stall-bar" />
            <span className="bldg-stall-bar" />
          </div>
          <div className="bldg-lantern bldg-lantern-red" />
        </div>
      );
    case "inn":
      return (
        <div className="building-art building-art-inn" aria-hidden="true">
          <div className="bldg-roof bldg-roof-wide" />
          <div className="bldg-wall">
            <span className="bldg-door bldg-door-large" />
            <span className="bldg-banner">客</span>
          </div>
          <div className="bldg-lantern bldg-lantern-left" />
          <div className="bldg-lantern bldg-lantern-right" />
        </div>
      );
    case "graveyard":
      return (
        <div className="building-art building-art-tomb" aria-hidden="true">
          <div className="bldg-tomb" />
          <div className="bldg-tomb bldg-tomb-back" />
          <div className="bldg-mist" />
        </div>
      );
    case "square":
    default:
      return (
        <div className="building-art building-art-plaza" aria-hidden="true">
          <div className="bldg-plaza-stone" />
          <div className="bldg-plaza-stone bldg-plaza-stone-b" />
          <div className="bldg-plaza-flag" />
        </div>
      );
  }
}

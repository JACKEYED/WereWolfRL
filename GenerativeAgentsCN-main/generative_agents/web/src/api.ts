// 文件作用：与 FastAPI 后端通信的薄封装。dev 模式下走 Vite proxy（/api 转发到 :8000）。

import type {
  AgentPrivate,
  GameState,
  GameSummary,
  LiveEvent,
  StepPhase,
} from "./types";

async function jsonRequest<T>(
  url: string,
  init: RequestInit = {},
): Promise<T> {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`${res.status} ${res.statusText}: ${detail}`);
  }
  return (await res.json()) as T;
}

export async function listGames(): Promise<GameSummary[]> {
  return jsonRequest("/api/games");
}

export async function createGame(opts: {
  name?: string;
  seed?: number;
  use_llm?: boolean;
}): Promise<GameSummary> {
  return jsonRequest("/api/games", {
    method: "POST",
    body: JSON.stringify(opts),
  });
}

export async function setup(gameId: string): Promise<GameSummary> {
  return jsonRequest(`/api/games/${gameId}/setup`, { method: "POST" });
}

export async function step(
  gameId: string,
  phase: StepPhase,
): Promise<GameSummary> {
  return jsonRequest(`/api/games/${gameId}/step`, {
    method: "POST",
    body: JSON.stringify({ phase }),
  });
}

export async function fetchState(gameId: string): Promise<GameState> {
  return jsonRequest(`/api/games/${gameId}/state`);
}

export async function fetchAgent(
  gameId: string,
  name: string,
): Promise<AgentPrivate> {
  return jsonRequest(
    `/api/games/${gameId}/agent/${encodeURIComponent(name)}`,
  );
}

export async function deleteGame(gameId: string): Promise<void> {
  await jsonRequest(`/api/games/${gameId}`, { method: "DELETE" });
}

/** 打开 WebSocket，收到 LiveEvent 时回调。返回 close 函数。 */
export function subscribeLive(
  gameId: string,
  onEvent: (event: LiveEvent) => void,
  onError?: (err: Event) => void,
): () => void {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${window.location.host}/ws/games/${gameId}`);
  ws.onmessage = (msg) => {
    try {
      onEvent(JSON.parse(msg.data) as LiveEvent);
    } catch (e) {
      console.warn("ws message parse failed", e);
    }
  };
  ws.onerror = (err) => onError?.(err);
  return () => ws.close();
}

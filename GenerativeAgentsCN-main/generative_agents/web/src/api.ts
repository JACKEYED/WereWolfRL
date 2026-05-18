// 文件作用：与 FastAPI 后端通信的薄封装。dev 模式下走 Vite proxy（/api 转发到 :8000）。

import type {
  AgentPrivate,
  GameState,
  GameSummary,
  JobFull,
  JobSummary,
  LiveEvent,
  NewJobRequest,
  RLEvent,
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
  write_memory?: boolean;
  scene_mode?: "social" | "game";
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

/** 后端在线程池里自动跑完整局。一直 await 到分出胜负或达到安全上限。 */
export async function runGame(gameId: string): Promise<GameSummary> {
  return jsonRequest(`/api/games/${gameId}/run`, { method: "POST" });
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


// ──────────── RL 训练接口 ────────────
export async function createTrainingJob(req: NewJobRequest): Promise<JobSummary> {
  return jsonRequest("/api/rl/jobs", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function listTrainingJobs(): Promise<JobSummary[]> {
  return jsonRequest("/api/rl/jobs");
}

export async function fetchTrainingStatus(jobId: string): Promise<JobFull> {
  return jsonRequest(`/api/rl/jobs/${jobId}/status`);
}

export async function stopTrainingJob(jobId: string): Promise<JobSummary> {
  return jsonRequest(`/api/rl/jobs/${jobId}/stop`, { method: "POST" });
}

export async function deleteTrainingJob(jobId: string): Promise<void> {
  await jsonRequest(`/api/rl/jobs/${jobId}`, { method: "DELETE" });
}

export function subscribeTrainingJob(
  jobId: string,
  onEvent: (event: RLEvent) => void,
  onError?: (err: Event) => void,
): () => void {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${window.location.host}/ws/rl/jobs/${jobId}`);
  ws.onmessage = (msg) => {
    try {
      onEvent(JSON.parse(msg.data) as RLEvent);
    } catch (e) {
      console.warn("rl ws parse failed", e);
    }
  };
  ws.onerror = (err) => onError?.(err);
  return () => ws.close();
}

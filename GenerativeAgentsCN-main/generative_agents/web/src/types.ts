// 文件作用：前后端共享的数据类型定义。与 api/server.py 的响应模型对齐。

export interface GameSummary {
  id: string;
  name: string;
  created_at: string;
  day: number;
  winner: string | null;
  finished: boolean;
}

export interface PlayerState {
  name: string;
  role: string;
  alive: boolean;
  death_reason: string;
  death_day: number | null;
  used_hunter_shot: boolean;
}

export interface GameState {
  name: string;
  phase: string;
  day: number;
  winner: string | null;
  players: Record<string, PlayerState>;
  role_names: Record<string, string>;
  alive: string[];
  witch: { antidote: boolean; poison: boolean };
  guard_last_target: string | null;
  seer_checks: Record<string, Record<string, string>>;
  public_log: string[];
  private_log: Record<string, string[]>;
  phase_records: PhaseRecord[];
}

export interface PhaseRecord {
  time: string;
  day: number;
  phase: string;
  scope: "public" | "secret" | "social" | "movement" | "system";
  text: string;
  actors: string[];
  location: string;
}

export interface BeliefDist {
  werewolf: number;
  seer: number;
  witch: number;
  hunter: number;
  guard: number;
  villager: number;
}

export interface BeliefState {
  holder: string;
  beliefs: Record<string, BeliefDist>;
  locked: Record<string, string>;
}

export interface TrajectoryStep {
  step_id: number;
  agent: string;
  phase: string;
  day: number;
  decision_type: "speech" | "vote" | "skill" | "choice";
  obs: Record<string, unknown>;
  candidates: string[] | null;
  action: unknown;
  reward_step: number;
  reward_episode: number;
}

export interface AgentPrivate {
  name: string;
  role: string;
  role_name: string;
  camp: string;
  alive: boolean;
  death_reason: string;
  private_log: string[];
  seer_checks: Record<string, string> | null;
  belief: BeliefState | null;
  trajectory_tail: TrajectoryStep[];
}

export type LiveEvent =
  | { type: "snapshot"; summary: GameSummary }
  | {
      type: "record";
      scope: string;
      phase: string;
      text: string;
      actors: string[];
      location: string;
      day: number;
    };

export type StepPhase = "social-pre" | "night" | "day" | "social-post";

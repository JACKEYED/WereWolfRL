// 文件作用：新开一局对话框。让用户勾选 use_llm / write_memory，并可选填名字 + 种子。

import { useEffect, useState } from "react";
import * as api from "../api";
import type { GameSummary } from "../types";

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: (summary: GameSummary) => void;
}

export function NewGameDialog({ open, onClose, onCreated }: Props) {
  const [name, setName] = useState("");
  const [useLlm, setUseLlm] = useState(false);
  const [writeMemory, setWriteMemory] = useState(false);
  const [seed, setSeed] = useState("");
  const [sceneMode, setSceneMode] = useState<"social" | "game">("social");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 打开时重置表单
  useEffect(() => {
    if (open) {
      setName("");
      setUseLlm(false);
      setWriteMemory(false);
      setSeed("");
      setSceneMode("social");
      setError(null);
    }
  }, [open]);

  if (!open) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const opts: {
        name?: string;
        use_llm: boolean;
        write_memory: boolean;
        seed?: number;
        scene_mode: "social" | "game";
      } = {
        use_llm: useLlm,
        write_memory: writeMemory,
        scene_mode: sceneMode,
      };
      if (name.trim()) opts.name = name.trim();
      if (seed.trim()) {
        const n = Number(seed.trim());
        if (!Number.isFinite(n) || !Number.isInteger(n)) {
          setError("种子必须是整数");
          setBusy(false);
          return;
        }
        opts.seed = n;
      }
      const summary = await api.createGame(opts);
      // 自动 setup（发身份牌、move 到家）
      const ready = await api.setup(summary.id);
      onCreated(ready);
      onClose();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onClick={(e) => {
      if (e.target === e.currentTarget && !busy) onClose();
    }}>
      <form className="modal" onSubmit={submit}>
        <header className="modal-header">
          <h3>新开一局</h3>
          <button
            type="button"
            className="modal-close"
            onClick={onClose}
            disabled={busy}
            aria-label="关闭"
          >
            ×
          </button>
        </header>

        <div className="modal-body">
          <label className="field">
            <span className="field-label">对局名（可选）</span>
            <input
              type="text"
              placeholder="留空则用 api-时间戳"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={busy}
              autoFocus
            />
          </label>

          <div className="field">
            <span className="field-label">场景模式</span>
            <div className="field-radio-group">
              <label className="radio-option">
                <input
                  type="radio"
                  name="scene_mode"
                  value="social"
                  checked={sceneMode === "social"}
                  onChange={() => setSceneMode("social")}
                  disabled={busy}
                />
                <span>
                  <strong>观赏模式（social）</strong>
                  <small> · 民国江南古镇叙事完整版，含开场社交、辩论、申时余韵、NPC 流言</small>
                </span>
              </label>
              <label className="radio-option">
                <input
                  type="radio"
                  name="scene_mode"
                  value="game"
                  checked={sceneMode === "game"}
                  onChange={() => setSceneMode("game")}
                  disabled={busy}
                />
                <span>
                  <strong>训练模式（game / v1）</strong>
                  <small> · 纯狼人杀，跳开场社交+申时余韵，辩论缩到 2 轮，中性现代汉语 prompt，专为 RL 训练设计</small>
                </span>
              </label>
            </div>
          </div>

          <label className="field field-check">
            <input
              type="checkbox"
              checked={useLlm}
              onChange={(e) => setUseLlm(e.target.checked)}
              disabled={busy}
            />
            <span>
              <strong>调用 LLM</strong>
              <small> · 真实大模型决策（费 API quota，慢但智能）</small>
            </span>
          </label>

          <label className="field field-check">
            <input
              type="checkbox"
              checked={writeMemory}
              onChange={(e) => setWriteMemory(e.target.checked)}
              disabled={busy}
            />
            <span>
              <strong>写向量长期记忆</strong>
              <small> · 把事件写进 Agent 的 LlamaIndex（要 embedding 服务）</small>
            </span>
          </label>

          <label className="field">
            <span className="field-label">随机种子（可选）</span>
            <input
              type="number"
              placeholder="留空则随机"
              value={seed}
              onChange={(e) => setSeed(e.target.value)}
              disabled={busy}
            />
            <small className="field-hint">
              固定种子可复现身份分配 / 投票兜底 / 平票决断，但 LLM temperature&gt;0 时仍可能不同。
            </small>
          </label>

          {error && <div className="form-error">{error}</div>}

          {useLlm && (
            <div className="form-warn">
              ⚠ 调 LLM 模式下一局会发 100+ 次 API 调用，整局耗时数十秒到几分钟。
            </div>
          )}

          {busy && (
            <div className="form-info">
              正在初始化对局……这一步会加载 853KB 地图、创建 12 个 Agent 并初始化 LLM 客户端，
              通常 5-15 秒。请保持页面打开。
            </div>
          )}
        </div>

        <footer className="modal-footer">
          <button type="button" onClick={onClose} disabled={busy}>
            取消
          </button>
          <button type="submit" className="primary" disabled={busy}>
            {busy ? "创建中…" : "创建"}
          </button>
        </footer>
      </form>
    </div>
  );
}

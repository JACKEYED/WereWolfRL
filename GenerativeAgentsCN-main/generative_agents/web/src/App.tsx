// 文件作用：顶层 App。只做视图切换：[对局] / [RL 训练]。
// 各视图内部自带 header + body。

import { useState } from "react";
import { GamesView } from "./components/GamesView";
import { RLView } from "./components/RLView";

type View = "games" | "rl";

export default function App() {
  const [view, setView] = useState<View>("games");

  return (
    <div className="app">
      <nav className="top-nav">
        <h1>江南古镇 · 狼人杀控制台</h1>
        <div className="top-nav-tabs">
          <button
            className={`top-nav-tab${view === "games" ? " active" : ""}`}
            onClick={() => setView("games")}
          >
            对局
          </button>
          <button
            className={`top-nav-tab${view === "rl" ? " active" : ""}`}
            onClick={() => setView("rl")}
          >
            RL 训练
          </button>
        </div>
      </nav>
      {view === "games" ? <GamesView /> : <RLView />}
    </div>
  );
}

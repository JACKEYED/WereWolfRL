#!/usr/bin/env bash
# 文件作用：江南古镇狼人杀项目的一键启动脚本。
# 用法：./run.sh [up|install|test|smoke|backend|frontend|help]
# 平台：Linux / macOS / Windows（在 Git Bash 或 WSL 中执行）。

set -euo pipefail

# ──────────────── 颜色（终端不支持时为空字符串） ────────────────
if [[ -t 1 ]]; then
  C_RESET='\033[0m'
  C_BACKEND='\033[36m'   # cyan
  C_FRONTEND='\033[32m'  # green
  C_INFO='\033[33m'      # yellow
  C_ERR='\033[31m'       # red
else
  C_RESET='' C_BACKEND='' C_FRONTEND='' C_INFO='' C_ERR=''
fi

ROOT="$(cd "$(dirname "$0")" && pwd)"
WORK="$ROOT/generative_agents"
cmd="${1:-up}"

# Windows 控制台默认按 GBK 处理 Python 的 stdout/stderr，被 sed 加前缀后中文会乱码。
# 强制 Python 全程 UTF-8（文件 IO 已经手动指定 encoding，这里只影响打印）。
export PYTHONIOENCODING="utf-8"
export PYTHONUTF8="1"

usage() {
  cat <<EOF
江南古镇狼人杀 · 一键启动

用法：
  ./run.sh [up]         启动后端（FastAPI :8000）+ 前端（Vite :5173），并行打印日志（默认）
  ./run.sh test         跑 pytest（43 个纯模块单元测试）
  ./run.sh smoke        跑一局烟雾测试（不调 LLM、不写向量记忆）
  ./run.sh backend      仅启后端
  ./run.sh frontend     仅启前端
  ./run.sh help         显示本帮助

前置条件（本脚本不负责安装）：
  - Python 3.12+ 且已 pip install requirements.txt + fastapi + uvicorn
  - Node.js 18+ 且已在 generative_agents/web 下 npm install
  Windows 用户请在 Git Bash / WSL 中运行本脚本。
EOF
}

# ──────────────── 工具函数 ────────────────
log_info() { printf "%b[run.sh]%b %s\n" "$C_INFO" "$C_RESET" "$*"; }
log_err()  { printf "%b[run.sh]%b %s\n" "$C_ERR"  "$C_RESET" "$*" >&2; }

ensure_python() {
  if ! command -v python >/dev/null 2>&1; then
    log_err "找不到 python，请先安装 Python 3.12+"
    exit 1
  fi
}

ensure_node() {
  if ! command -v npm >/dev/null 2>&1; then
    log_err "找不到 npm，请先安装 Node.js 18+"
    exit 1
  fi
}

# 给一条日志行加前缀色块。
# 用 awk + fflush() 而非 sed —— sed 在 Git Bash for Windows 的管道里会块缓冲，
# 导致 backend print 看不到。awk 每行强制 fflush，跨平台 line-buffered 稳定。
prefix_pipe() {
  local color="$1"; local label="$2"
  local prefix
  prefix="$(printf "%b" "${color}")[${label}]$(printf "%b" "$C_RESET") "
  awk -v p="$prefix" '{ print p $0; fflush() }' 2>/dev/null \
    || sed -e "s/^/[${label}] /"
}

# ──────────────── 子命令 ────────────────
run_test() {
  ensure_python
  cd "$WORK"
  python -m pytest test/test_werewolf_pure.py -v
}

run_smoke() {
  ensure_python
  local stamp
  stamp="$(date +%Y%m%d-%H%M%S)"
  cd "$WORK"
  python start.py --name "smoke-$stamp" --no-llm --no-memory
}

run_backend() {
  ensure_python
  cd "$WORK"
  # -u 关闭 stdout 缓冲，让 print() 立即可见（否则被管道吞住 4KB 才 flush）
  exec python -u -m uvicorn api.server:app --reload --port 8000
}

run_frontend() {
  ensure_node
  cd "$WORK/web"
  exec npm run dev
}

run_up() {
  ensure_python
  ensure_node

  log_info "启动后端 :8000 + 前端 :5173；Ctrl+C 一并停止"

  # 后端
  ( cd "$WORK" && python -u -m uvicorn api.server:app --reload --port 8000 2>&1 \
      | prefix_pipe "$C_BACKEND" "backend" ) &
  BACKEND_PID=$!

  # 前端
  ( cd "$WORK/web" && npm run dev 2>&1 \
      | prefix_pipe "$C_FRONTEND" "frontend" ) &
  FRONTEND_PID=$!

  cleanup() {
    echo
    log_info "收到中断，停止子进程"
    kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
    # 给子孙进程一点时间退出
    sleep 0.5
    kill -9 "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
    exit 0
  }
  trap cleanup INT TERM

  wait
}

# ──────────────── 入口 ────────────────
case "$cmd" in
  up|"")          run_up ;;
  test)           run_test ;;
  smoke)          run_smoke ;;
  backend)        run_backend ;;
  frontend)       run_frontend ;;
  help|-h|--help) usage ;;
  *)              log_err "未知命令：$cmd"; usage; exit 2 ;;
esac

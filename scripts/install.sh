#!/usr/bin/env bash
# Aegis One-Click Installer for Linux (Debian/Ubuntu)
# Usage: curl -fsSL https://raw.githubusercontent.com/cwen0708/aegis/main/scripts/install.sh | bash
#   or:  bash install.sh [-d /path/to/install] [-f]

set -euo pipefail

# ============================================================
# Configuration
# ============================================================
REPO_URL="https://github.com/cwen0708/aegis.git"
BACKEND_PORT=8899
FRONTEND_PORT=5173
INSTALL_DIR=""
FORCE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        -d|--dir)    INSTALL_DIR="$2"; shift 2 ;;
        -f|--force)  FORCE=true; shift ;;
        *)           shift ;;
    esac
done

# ============================================================
# Helpers
# ============================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
GRAY='\033[0;90m'
WHITE='\033[1;37m'
NC='\033[0m'

log_step()  { echo -e "  ${CYAN}[$(date +%H:%M:%S)] $1${NC}"; }
log_ok()    { echo -e "  ${GREEN}[OK]${NC} $1"; }
log_warn()  { echo -e "  ${YELLOW}[!]${NC} $1"; }
log_err()   { echo -e "  ${RED}[X]${NC} $1"; }

banner() {
    echo ""
    echo -e "  ${MAGENTA}============================================${NC}"
    echo -e "  ${MAGENTA}     Aegis Installer v1.0 (Linux)${NC}"
    echo -e "  ${MAGENTA}     AI Engineering Grid & Intelligence${NC}"
    echo -e "  ${MAGENTA}============================================${NC}"
    echo ""
}

command_exists() { command -v "$1" &>/dev/null; }

# ============================================================
# Main Installation
# ============================================================
main() {
    banner

    # ----------------------------------------------------------
    # Step 0: Determine install directory
    # ----------------------------------------------------------
    if [[ -z "$INSTALL_DIR" ]]; then
        local default_dir="$HOME/Aegis"
        echo -e "  ${WHITE}安裝目錄 (直接 Enter 使用預設):${NC}"
        echo -e "  ${GRAY}預設: $default_dir${NC}"
        read -rp "  路徑: " user_input
        INSTALL_DIR="${user_input:-$default_dir}"
    fi

    mkdir -p "$INSTALL_DIR"
    LOG_FILE="$INSTALL_DIR/install.log"
    : > "$LOG_FILE"

    log_step "安裝目錄: $INSTALL_DIR"
    log_step "記錄檔: $LOG_FILE"

    # ----------------------------------------------------------
    # Step 1: Check system
    # ----------------------------------------------------------
    echo ""
    echo -e "  ${WHITE}[1/7] 檢查系統環境${NC}"
    echo -e "  ${GRAY}─────────────────────────────────${NC}"

    # Detect package manager
    local pkg_mgr=""
    if command_exists apt-get; then
        pkg_mgr="apt"
    elif command_exists dnf; then
        pkg_mgr="dnf"
    elif command_exists yum; then
        pkg_mgr="yum"
    else
        log_err "不支援的套件管理器 (需要 apt/dnf/yum)"
        return 1
    fi
    log_ok "套件管理器: $pkg_mgr"

    # Check network
    if curl -sf --max-time 5 https://www.google.com > /dev/null 2>&1; then
        log_ok "網路連線正常"
    else
        log_err "無法連線到網路"
        return 1
    fi

    # ----------------------------------------------------------
    # Step 2: Install Git, Python, Node.js
    # ----------------------------------------------------------
    echo ""
    echo -e "  ${WHITE}[2/7] 安裝基礎工具 (Git, Python, Node.js)${NC}"
    echo -e "  ${GRAY}─────────────────────────────────${NC}"

    # Ensure sudo is available
    local SUDO=""
    if [[ $EUID -ne 0 ]]; then
        if command_exists sudo; then
            SUDO="sudo"
        else
            log_warn "非 root 且沒有 sudo，嘗試直接安裝"
        fi
    fi

    # Update package list
    log_step "更新套件清單..."
    case "$pkg_mgr" in
        apt) $SUDO apt-get update -qq > /dev/null 2>&1 ;;
        dnf) $SUDO dnf check-update -q > /dev/null 2>&1 || true ;;
        yum) $SUDO yum check-update -q > /dev/null 2>&1 || true ;;
    esac

    # Git
    if ! $FORCE && command_exists git; then
        log_ok "Git 已安裝"
    else
        log_step "正在安裝 Git..."
        case "$pkg_mgr" in
            apt) $SUDO apt-get install -y -qq git > /dev/null 2>&1 ;;
            dnf) $SUDO dnf install -y -q git > /dev/null 2>&1 ;;
            yum) $SUDO yum install -y -q git > /dev/null 2>&1 ;;
        esac
        log_ok "Git 安裝完成"
    fi

    # Python 3
    if ! $FORCE && command_exists python3; then
        log_ok "Python3 已安裝"
    else
        log_step "正在安裝 Python3..."
        case "$pkg_mgr" in
            apt) $SUDO apt-get install -y -qq python3 python3-venv python3-pip > /dev/null 2>&1 ;;
            dnf) $SUDO dnf install -y -q python3 python3-pip > /dev/null 2>&1 ;;
            yum) $SUDO yum install -y -q python3 python3-pip > /dev/null 2>&1 ;;
        esac
        log_ok "Python3 安裝完成"
    fi

    # Node.js (via NodeSource if not present)
    if ! $FORCE && command_exists node; then
        log_ok "Node.js 已安裝"
    else
        log_step "正在安裝 Node.js..."
        if [[ "$pkg_mgr" == "apt" ]]; then
            # Use NodeSource for recent LTS
            if ! command_exists node; then
                curl -fsSL https://deb.nodesource.com/setup_lts.x | $SUDO bash - > /dev/null 2>&1
                $SUDO apt-get install -y -qq nodejs > /dev/null 2>&1
            fi
        else
            $SUDO $pkg_mgr install -y -q nodejs npm > /dev/null 2>&1 || true
        fi
        log_ok "Node.js 安裝完成"
    fi

    # Show versions
    local git_ver python_ver node_ver
    git_ver=$(git --version 2>/dev/null || echo "N/A")
    python_ver=$(python3 --version 2>/dev/null || echo "N/A")
    node_ver=$(node --version 2>/dev/null || echo "N/A")
    log_step "版本: $git_ver | $python_ver | Node $node_ver"

    # ----------------------------------------------------------
    # Step 3: Clone repository
    # ----------------------------------------------------------
    echo ""
    echo -e "  ${WHITE}[3/7] 取得 Aegis 原始碼${NC}"
    echo -e "  ${GRAY}─────────────────────────────────${NC}"

    if [[ -d "$INSTALL_DIR/.git" ]]; then
        log_ok "專案已存在，執行 git pull"
        git -C "$INSTALL_DIR" pull --ff-only > /dev/null 2>&1 || true
    else
        log_step "正在 clone 專案..."
        if [[ -d "$INSTALL_DIR" && "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ]]; then
            # Directory exists with files (e.g. install.log), clone to temp
            local temp_clone="$INSTALL_DIR-clone-tmp"
            rm -rf "$temp_clone"
            git clone "$REPO_URL" "$temp_clone" > /dev/null 2>&1
            # Move contents into install dir
            shopt -s dotglob
            mv "$temp_clone"/* "$INSTALL_DIR"/ 2>/dev/null || true
            shopt -u dotglob
            rm -rf "$temp_clone"
        else
            git clone "$REPO_URL" "$INSTALL_DIR" > /dev/null 2>&1
        fi
        log_ok "Clone 完成"
    fi

    # ----------------------------------------------------------
    # Step 4: Backend setup
    # ----------------------------------------------------------
    echo ""
    echo -e "  ${WHITE}[4/7] 設定後端 (Python + FastAPI)${NC}"
    echo -e "  ${GRAY}─────────────────────────────────${NC}"

    local backend_dir="$INSTALL_DIR/backend"
    local venv_dir="$backend_dir/venv"

    if [[ ! -d "$venv_dir" ]]; then
        log_step "建立 Python 虛擬環境..."
        python3 -m venv "$venv_dir"
    fi
    log_ok "虛擬環境就緒"

    log_step "安裝 Python 套件..."
    "$venv_dir/bin/pip" install -q -r "$backend_dir/requirements.txt" > /dev/null 2>&1
    if [[ $? -ne 0 ]]; then
        log_warn "部分 Python 套件安裝可能有問題，但嘗試繼續"
    else
        log_ok "Python 套件安裝完成"
    fi

    # Seed database if needed
    if [[ ! -f "$backend_dir/local.db" ]]; then
        log_step "初始化資料庫..."
        (cd "$backend_dir" && "$venv_dir/bin/python" seed.py > /dev/null 2>&1)
        log_ok "資料庫初始化完成"
    else
        log_ok "資料庫已存在"
    fi

    # ----------------------------------------------------------
    # Step 5: Frontend setup
    # ----------------------------------------------------------
    echo ""
    echo -e "  ${WHITE}[5/7] 設定前端 (Vue 3 + Vite)${NC}"
    echo -e "  ${GRAY}─────────────────────────────────${NC}"

    local frontend_dir="$INSTALL_DIR/frontend"

    log_step "安裝前端套件 (這可能需要幾分鐘)..."
    (cd "$frontend_dir" && npm install > /dev/null 2>&1)
    log_ok "前端套件安裝完成"

    # ----------------------------------------------------------
    # Step 6: AI CLIs (optional)
    # ----------------------------------------------------------
    echo ""
    echo -e "  ${WHITE}[6/7] 安裝 AI 工具 (選用，失敗不影響)${NC}"
    echo -e "  ${GRAY}─────────────────────────────────${NC}"

    # Claude Code CLI
    if command_exists claude; then
        log_ok "Claude Code CLI 已安裝"
    else
        log_step "安裝 Claude Code CLI..."
        if npm install -g @anthropic-ai/claude-code > /dev/null 2>&1; then
            log_ok "Claude Code CLI 安裝完成"
        else
            log_warn "Claude Code CLI 安裝失敗（不影響核心功能）"
        fi
    fi

    # Gemini CLI
    if command_exists gemini; then
        log_ok "Gemini CLI 已安裝"
    else
        log_step "安裝 Gemini CLI..."
        if npm install -g @google/gemini-cli > /dev/null 2>&1; then
            log_ok "Gemini CLI 安裝完成"
        else
            log_warn "Gemini CLI 安裝失敗（不影響核心功能）"
        fi
    fi

    # ----------------------------------------------------------
    # Step 7: Create launcher script
    # ----------------------------------------------------------
    echo ""
    echo -e "  ${WHITE}[7/7] 建立啟動腳本${NC}"
    echo -e "  ${GRAY}─────────────────────────────────${NC}"

    local start_script="$INSTALL_DIR/start-aegis.sh"
    cat > "$start_script" << 'LAUNCHER'
#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "  Starting Aegis..."
echo ""

# Start backend
echo "  [1/2] Starting backend server..."
(cd "$SCRIPT_DIR/backend" && source venv/bin/activate && python -m uvicorn app.main:app --host 127.0.0.1 --port 8899 &)

# Wait for backend
echo "  [2/2] Waiting for backend..."
for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:8899/health > /dev/null 2>&1; then
        break
    fi
    sleep 2
done
echo "  [OK] Backend is ready"

# Start frontend
(cd "$SCRIPT_DIR/frontend" && npx vite --host 127.0.0.1 --port 5173 &)
sleep 3

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║  Aegis is running!                   ║"
echo "  ║                                      ║"
echo "  ║  Frontend: http://localhost:5173     ║"
echo "  ║  Backend:  http://localhost:8899      ║"
echo "  ║                                      ║"
echo "  ║  Press Ctrl+C to stop.               ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# Wait for Ctrl+C
trap "kill 0; exit" SIGINT SIGTERM
wait
LAUNCHER
    chmod +x "$start_script"
    log_ok "啟動腳本已建立: start-aegis.sh"

    # ----------------------------------------------------------
    # Done!
    # ----------------------------------------------------------
    echo ""
    echo -e "  ${GREEN}============================================${NC}"
    echo -e "  ${GREEN}     安裝完成！${NC}"
    echo -e "  ${GREEN}============================================${NC}"
    echo ""
    echo -e "  ${WHITE}啟動方式:${NC}"
    echo -e "  ${GRAY}  cd $INSTALL_DIR && ./start-aegis.sh${NC}"
    echo ""
    echo -e "  ${WHITE}首次使用提示:${NC}"
    echo -e "  ${GRAY}  - Gemini API Key 可在 Settings 頁面設定${NC}"
    echo -e "  ${GRAY}  - Claude / Gemini CLI 登入請在終端機執行:${NC}"
    echo -e "  ${YELLOW}    claude login${NC}"
    echo -e "  ${YELLOW}    gemini auth login${NC}"
    echo ""
}

main "$@"

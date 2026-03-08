#!/bin/bash
# Aegis Linux Installation Script
# Usage: curl -fsSL https://raw.githubusercontent.com/cwen0708/aegis/main/scripts/install-linux.sh | bash
# Or: ./install-linux.sh [--install-dir /opt/aegis] [--skip-cli] [--dev]

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

print_step() { echo -e "\n${CYAN}[*] $1${NC}"; }
print_success() { echo -e "${GREEN}[+] $1${NC}"; }
print_warn() { echo -e "${YELLOW}[!] $1${NC}"; }
print_error() { echo -e "${RED}[-] $1${NC}"; }

# Default values
INSTALL_DIR="$HOME/.local/aegis"
SKIP_CLI=false
DEV_MODE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --install-dir)
            INSTALL_DIR="$2"
            shift 2
            ;;
        --skip-cli)
            SKIP_CLI=true
            shift
            ;;
        --dev)
            DEV_MODE=true
            shift
            ;;
        --help|-h)
            echo "Aegis Installation Script for Linux"
            echo ""
            echo "Usage:"
            echo "  ./install-linux.sh [options]"
            echo ""
            echo "Options:"
            echo "  --install-dir <path>   Installation directory (default: ~/.local/aegis)"
            echo "  --skip-cli             Skip Claude CLI and Gemini CLI installation"
            echo "  --dev                  Clone with git instead of downloading release"
            echo "  --help                 Show this help message"
            echo ""
            echo "Examples:"
            echo "  ./install-linux.sh"
            echo "  ./install-linux.sh --install-dir /opt/aegis"
            echo "  ./install-linux.sh --skip-cli --dev"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo -e "${CYAN}"
cat << 'EOF'
    _    _____ ____ ___ ____
   / \  | ____/ ___|_ _/ ___|
  / _ \ |  _|| |  _ | |\___ \
 / ___ \| |__| |_| || | ___) |
/_/   \_\_____\____|___|____/

  AI Agent Management Dashboard

EOF
echo -e "${NC}"

# ============================================
# Check Prerequisites
# ============================================
print_step "Checking prerequisites..."

# Check Node.js
if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version)
    print_success "Node.js: $NODE_VERSION"
else
    print_error "Node.js not found. Please install Node.js 18+"
    echo "  Ubuntu/Debian: curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt-get install -y nodejs"
    echo "  Or use nvm: curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.0/install.sh | bash"
    exit 1
fi

# Check npm
if command -v npm &> /dev/null; then
    NPM_VERSION=$(npm --version)
    print_success "npm: $NPM_VERSION"
else
    print_error "npm not found"
    exit 1
fi

# Check Python
PYTHON_CMD=""
for cmd in python3 python; do
    if command -v $cmd &> /dev/null; then
        PY_VERSION=$($cmd --version 2>&1)
        if [[ $PY_VERSION =~ Python\ 3\.([0-9]+) ]]; then
            MINOR=${BASH_REMATCH[1]}
            if [ "$MINOR" -ge 10 ]; then
                PYTHON_CMD=$cmd
                print_success "Python: $PY_VERSION"
                break
            fi
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    print_error "Python 3.10+ not found. Please install Python 3.10 or later."
    echo "  Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
    exit 1
fi

# Check Git (only for dev mode)
if [ "$DEV_MODE" = true ]; then
    if command -v git &> /dev/null; then
        GIT_VERSION=$(git --version)
        print_success "Git: $GIT_VERSION"
    else
        print_error "Git not found. Required for --dev mode."
        echo "  Ubuntu/Debian: sudo apt install git"
        exit 1
    fi
fi

# ============================================
# Create Installation Directory
# ============================================
print_step "Setting up installation directory..."

if [ -d "$INSTALL_DIR" ]; then
    print_warn "Directory exists: $INSTALL_DIR"
    read -p "Overwrite? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 0
    fi
fi

mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"
print_success "Install directory: $INSTALL_DIR"

# ============================================
# Download or Clone Aegis
# ============================================
print_step "Downloading Aegis..."

if [ "$DEV_MODE" = true ]; then
    if [ -d ".git" ]; then
        echo "  Updating existing repository..."
        git pull
    else
        git clone https://github.com/cwen0708/aegis.git .
    fi
else
    # Download latest release
    RELEASE_URL="https://github.com/cwen0708/aegis/archive/refs/heads/main.zip"
    TMP_ZIP="/tmp/aegis-main.zip"

    echo "  Downloading from GitHub..."
    curl -fsSL "$RELEASE_URL" -o "$TMP_ZIP"

    echo "  Extracting..."
    unzip -q "$TMP_ZIP" -d /tmp

    # Move contents from extracted folder
    EXTRACTED_DIR=$(find /tmp -maxdepth 1 -type d -name "aegis-*" -o -name "Aegis-*" 2>/dev/null | head -1)
    if [ -z "$EXTRACTED_DIR" ]; then
        print_error "Failed to find extracted Aegis folder"
        exit 1
    fi
    mv "$EXTRACTED_DIR"/* "$INSTALL_DIR"/

    rm -f "$TMP_ZIP"
    rm -rf "$EXTRACTED_DIR"
fi

print_success "Aegis downloaded"

# ============================================
# Setup Backend (Python)
# ============================================
print_step "Setting up backend..."

cd "$INSTALL_DIR/backend"

# Create virtual environment
echo "  Creating Python virtual environment..."
$PYTHON_CMD -m venv venv

# Activate and install dependencies
echo "  Installing Python dependencies..."
./venv/bin/pip install -q -r requirements.txt

print_success "Backend ready"

# ============================================
# Setup Frontend (Node.js)
# ============================================
print_step "Setting up frontend..."

cd "$INSTALL_DIR/frontend"

echo "  Installing npm dependencies..."
npm install --force 2>/dev/null || {
    print_warn "npm install had issues, retrying with clean install..."
    rm -rf node_modules
    npm install --force 2>/dev/null
}

echo "  Building frontend..."
if npm run build 2>/dev/null; then
    print_success "Frontend ready"
else
    print_error "Frontend build failed. You can retry later with: cd frontend && npm run build"
    print_warn "Continuing installation..."
fi

# ============================================
# Install CLI Tools (Optional)
# ============================================
if [ "$SKIP_CLI" = false ]; then
    print_step "Installing AI CLI tools..."

    echo "  Installing Claude CLI..."
    if npm install -g @anthropic-ai/claude-code 2>/dev/null; then
        print_success "Claude CLI installed"
    else
        print_warn "Claude CLI installation failed (you can install it later)"
    fi

    echo "  Installing Gemini CLI..."
    if npm install -g @google/gemini-cli 2>/dev/null; then
        print_success "Gemini CLI installed"
    else
        print_warn "Gemini CLI installation failed (you can install it later)"
    fi
fi

# ============================================
# Create Startup Script
# ============================================
print_step "Creating startup scripts..."

cd "$INSTALL_DIR"

# Create start script
cat > start-aegis.sh << 'SCRIPT'
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/backend"
source venv/bin/activate
exec python -m uvicorn app.main:app --host 127.0.0.1 --port 8899
SCRIPT
chmod +x start-aegis.sh

print_success "Created start-aegis.sh"

# Create systemd service file (optional)
cat > aegis.service << EOF
[Unit]
Description=Aegis AI Agent Dashboard
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$INSTALL_DIR/backend
ExecStart=$INSTALL_DIR/backend/venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8899
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

print_success "Created aegis.service (systemd unit file)"

# ============================================
# Done!
# ============================================
echo ""
echo -e "${GREEN}==================================================${NC}"
echo -e "${GREEN}  Installation Complete!${NC}"
echo -e "${GREEN}==================================================${NC}"

cat << EOF

To start Aegis:
  1. Run: $INSTALL_DIR/start-aegis.sh
  2. Open http://localhost:8899 in your browser

For systemd service (optional):
  sudo cp $INSTALL_DIR/aegis.service /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable aegis
  sudo systemctl start aegis

Configuration:
  - Install directory: $INSTALL_DIR
  - Backend: $INSTALL_DIR/backend
  - Frontend: $INSTALL_DIR/frontend
  - Database: $INSTALL_DIR/backend/local.db

Next steps:
  1. Start the server
  2. Complete the onboarding wizard
  3. Add your AI accounts (Claude/Gemini)
  4. Create projects and start automating!

EOF

# Ask if user wants to start now
read -p "Start Aegis now? (Y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    "$INSTALL_DIR/start-aegis.sh" &
    sleep 3
    if command -v xdg-open &> /dev/null; then
        xdg-open "http://localhost:8899"
    elif command -v open &> /dev/null; then
        open "http://localhost:8899"
    else
        echo "Open http://localhost:8899 in your browser"
    fi
fi

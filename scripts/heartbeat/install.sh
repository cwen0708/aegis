#!/bin/bash
# Aegis Heartbeat 安裝腳本（L1 + L2）
# L3 由 Aegis 內部排程執行（CronJob #1）
# 用法: sudo bash install.sh [--uninstall]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_BIN="$(which claude 2>/dev/null || echo '/usr/bin/claude')"
PYTHON_BIN="$(which python3 2>/dev/null || echo '/usr/bin/python3')"
USER="${SUDO_USER:-$(whoami)}"

# 讀取 config.json 的 AI 設定
L2_MODEL="haiku"
if [ -f "$SCRIPT_DIR/config.json" ]; then
    L2_MODEL=$(python3 -c "import json; print(json.load(open('$SCRIPT_DIR/config.json')).get('ai',{}).get('l2_model','haiku'))" 2>/dev/null || echo "haiku")
fi

if [ "$1" = "--uninstall" ]; then
    echo "Uninstalling heartbeat timers..."
    for level in l1 l2 l3; do
        systemctl stop "aegis-heartbeat-${level}.timer" 2>/dev/null || true
        systemctl disable "aegis-heartbeat-${level}.timer" 2>/dev/null || true
        rm -f "/etc/systemd/system/aegis-heartbeat-${level}.service"
        rm -f "/etc/systemd/system/aegis-heartbeat-${level}.timer"
    done
    # 移除舊的單層版本
    systemctl stop aegis-heartbeat.timer 2>/dev/null || true
    systemctl disable aegis-heartbeat.timer 2>/dev/null || true
    rm -f /etc/systemd/system/aegis-heartbeat.service
    rm -f /etc/systemd/system/aegis-heartbeat.timer
    systemctl daemon-reload
    echo "Done."
    exit 0
fi

echo "Installing Aegis Heartbeat (L1 + L2)..."
echo "  Script dir: $SCRIPT_DIR"
echo "  User: $USER"
echo "  Claude: $CLAUDE_BIN"
echo "  L2 model: $L2_MODEL"

# ─── L1: Basic Check (5 min) ───
cat > /etc/systemd/system/aegis-heartbeat-l1.service << EOF
[Unit]
Description=Aegis Heartbeat L1 — Basic Check
After=network.target

[Service]
Type=oneshot
User=$USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=$PYTHON_BIN $SCRIPT_DIR/heartbeat.py
TimeoutSec=60
KillMode=process
EOF

cat > /etc/systemd/system/aegis-heartbeat-l1.timer << EOF
[Unit]
Description=Aegis Heartbeat L1 Timer (every 5 min)

[Timer]
OnBootSec=60
OnUnitActiveSec=5min
AccuracySec=30s

[Install]
WantedBy=timers.target
EOF

# ─── L2: AI Diagnose (30 min) ───
cat > /etc/systemd/system/aegis-heartbeat-l2.service << EOF
[Unit]
Description=Aegis Heartbeat L2 — AI Diagnose
After=network.target

[Service]
Type=oneshot
User=$USER
WorkingDirectory=$SCRIPT_DIR
ExecStart=$CLAUDE_BIN -p "read heartbeat-diagnose.md and execute all steps" --model $L2_MODEL --dangerously-skip-permissions --max-turns 10 --output-format text
TimeoutSec=120
KillMode=process
EOF

cat > /etc/systemd/system/aegis-heartbeat-l2.timer << EOF
[Unit]
Description=Aegis Heartbeat L2 Timer (every 30 min)

[Timer]
OnBootSec=300
OnUnitActiveSec=30min
AccuracySec=60s

[Install]
WantedBy=timers.target
EOF

# ─── 清理 L3（已移至 Aegis CronJob #1）───
systemctl stop aegis-heartbeat-l3.timer 2>/dev/null || true
systemctl disable aegis-heartbeat-l3.timer 2>/dev/null || true
rm -f /etc/systemd/system/aegis-heartbeat-l3.service
rm -f /etc/systemd/system/aegis-heartbeat-l3.timer

# ─── 啟動 ───
systemctl daemon-reload

for level in l1 l2; do
    systemctl enable "aegis-heartbeat-${level}.timer"
    systemctl start "aegis-heartbeat-${level}.timer"
    echo "  ✓ aegis-heartbeat-${level}.timer enabled"
done

# 停用舊的單層版本（如果存在）
systemctl stop aegis-heartbeat.timer 2>/dev/null || true
systemctl disable aegis-heartbeat.timer 2>/dev/null || true

echo ""
echo "Installation complete. Check status:"
echo "  systemctl list-timers 'aegis-heartbeat-*'"
echo ""
echo "View logs:"
echo "  journalctl -u aegis-heartbeat-l1 --since '1 hour ago'"
echo "  journalctl -u aegis-heartbeat-l2 --since '1 hour ago'"
echo ""
echo "Note: L3 (deep analysis) runs inside Aegis as CronJob #1 (every 2 hours)"

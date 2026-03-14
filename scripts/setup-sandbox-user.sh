#!/bin/bash
# Setup aegis-sandbox user for AI task isolation (Linux only)
# Run as root or with sudo
#
# This creates a restricted user that AI tasks will run as,
# preventing them from accessing the main Aegis process or sensitive files.

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}Error: This script must be run as root (sudo)${NC}"
    exit 1
fi

SANDBOX_USER="aegis-sandbox"
SANDBOX_HOME="/var/lib/aegis-sandbox"

# 1. Create sandbox user
if id "$SANDBOX_USER" &>/dev/null; then
    echo -e "${YELLOW}User '$SANDBOX_USER' already exists, skipping creation${NC}"
else
    useradd -r -s /usr/sbin/nologin -m -d "$SANDBOX_HOME" "$SANDBOX_USER"
    echo -e "${GREEN}Created user '$SANDBOX_USER' (home: $SANDBOX_HOME)${NC}"
fi

# 2. Setup Claude CLI credentials for sandbox user
MAIN_USER="${SUDO_USER:-$(logname 2>/dev/null || echo '')}"
if [ -n "$MAIN_USER" ]; then
    MAIN_HOME=$(eval echo "~$MAIN_USER")
    CLAUDE_CREDS="$MAIN_HOME/.claude/.credentials.json"

    if [ -f "$CLAUDE_CREDS" ]; then
        SANDBOX_CLAUDE="$SANDBOX_HOME/.claude"
        mkdir -p "$SANDBOX_CLAUDE"
        cp "$CLAUDE_CREDS" "$SANDBOX_CLAUDE/.credentials.json"
        chown -R "$SANDBOX_USER:$SANDBOX_USER" "$SANDBOX_CLAUDE"
        chmod 600 "$SANDBOX_CLAUDE/.credentials.json"
        echo -e "${GREEN}Copied Claude credentials to sandbox user${NC}"
    else
        echo -e "${YELLOW}No Claude credentials found at $CLAUDE_CREDS${NC}"
        echo "  You may need to manually set up authentication for the sandbox user."
    fi
fi

# 3. Create shared group for project directory access
SHARED_GROUP="aegis-projects"
if getent group "$SHARED_GROUP" &>/dev/null; then
    echo -e "${YELLOW}Group '$SHARED_GROUP' already exists${NC}"
else
    groupadd "$SHARED_GROUP"
    echo -e "${GREEN}Created group '$SHARED_GROUP'${NC}"
fi

# Add both main user and sandbox user to the shared group
if [ -n "$MAIN_USER" ]; then
    usermod -aG "$SHARED_GROUP" "$MAIN_USER" 2>/dev/null || true
fi
usermod -aG "$SHARED_GROUP" "$SANDBOX_USER" 2>/dev/null || true
echo -e "${GREEN}Added users to '$SHARED_GROUP' group${NC}"

# 4. Summary
echo ""
echo -e "${GREEN}=== Setup Complete ===${NC}"
echo ""
echo "The sandbox user '$SANDBOX_USER' has been created."
echo ""
echo "Next steps:"
echo "  1. Set project directories to group-writable:"
echo "     chgrp -R $SHARED_GROUP /path/to/project"
echo "     chmod -R g+rw /path/to/project"
echo ""
echo "  2. Ensure the Aegis main process has CAP_SETUID capability:"
echo "     sudo setcap cap_setuid,cap_setgid+ep \$(which python3)"
echo "     OR run Aegis as root (not recommended)"
echo ""
echo "  3. Restart Aegis to enable sandbox isolation."

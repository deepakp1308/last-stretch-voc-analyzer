#!/bin/bash
# Last Stretch VOC Analyzer — daily runner
# Triggered by macOS launchd at 7 AM PST
# Opens Cursor and sends the analysis prompt via CLI

LOG_DIR="$HOME/cursor/last-stretch-voc-analyzer/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/run-$(date +%Y-%m-%d).log"

echo "=== VOC Analysis Run: $(date) ===" >> "$LOG_FILE"

# Check if Cursor CLI is available
CURSOR_CMD=""
if command -v cursor &>/dev/null; then
    CURSOR_CMD="cursor"
elif [ -x "/usr/local/bin/cursor" ]; then
    CURSOR_CMD="/usr/local/bin/cursor"
elif [ -x "$HOME/.local/bin/cursor" ]; then
    CURSOR_CMD="$HOME/.local/bin/cursor"
elif [ -d "/Applications/Cursor.app" ]; then
    CURSOR_CMD="/Applications/Cursor.app/Contents/MacOS/Cursor"
fi

if [ -z "$CURSOR_CMD" ]; then
    echo "ERROR: Cursor CLI not found" >> "$LOG_FILE"
    exit 1
fi

echo "Using Cursor: $CURSOR_CMD" >> "$LOG_FILE"

# Open the workspace if not already open
"$CURSOR_CMD" "$HOME/cursor" >> "$LOG_FILE" 2>&1 &
sleep 5

# Use the Cursor CLI agent mode to trigger the skill
"$CURSOR_CMD" --chat "Run the Last Stretch VOC Analyzer skill: read all 3 Slack channels from March 24 to today, classify and deduplicate VOCs, thematically categorize R&A-related negative feedback, calculate MRR exposure, self-evaluate quality, push dashboard to GitHub Pages, and DM me the summary on Slack." >> "$LOG_FILE" 2>&1

echo "=== Run complete: $(date) ===" >> "$LOG_FILE"

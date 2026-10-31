#!/bin/bash
# Opens a Terminal window and starts Simorgh
# Used by the LaunchAgent at startup

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Use AppleScript to open Terminal and run Simorgh
osascript <<EOF
tell application "Terminal"
    activate
    do script "cd '$REPO_ROOT' && ./sim.sh run --max-rollbacks 0"
end tell
EOF

exit 0

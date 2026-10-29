#!/bin/bash
# Installs Narrator's helpers into ~/.claude/voice_claude and starts the Control+Option+R hotkey at login.
# The narrator plugin runs this through /narrator setup; its own hooks flash the screen and
# prepare the summary when Claude finishes.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/.claude/voice_claude"
LABEL="com.voiceclaude.hotkey"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PYTHON="/usr/bin/python3"

mkdir -p "$DEST" "$HOME/Library/LaunchAgents"
cp "$SRC/voice_claude.py" "$DEST/voice_claude.py"
[ -f "$DEST/config.json" ] || cat > "$DEST/config.json" <<'JSON'
{
  "engine": "say",
  "voice": "Samantha",
  "rate": 185,
  "model": "haiku",
  "summarize": true,
  "flash": true,
  "away_after_seconds": 60,
  "prefetch": true,
  "detail": "medium",
  "elevenlabs_voice_id": "",
  "elevenlabs_model": "eleven_flash_v2"
}
JSON

command -v swiftc >/dev/null || { echo "Needs Apple's command line tools: run  xcode-select --install  then /narrator setup again." >&2; exit 1; }
echo "Compiling hotkey helper and screen flash..."
swiftc -O "$SRC/hotkey.swift" -o "$DEST/voice-claude-hotkey"
swiftc -O "$SRC/flash.swift" -o "$DEST/voice-claude-flash"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$DEST/voice-claude-hotkey</string>
    <string>$PYTHON</string>
    <string>$DEST/voice_claude.py</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$DEST/hotkey.log</string>
  <key>StandardErrorPath</key><string>$DEST/hotkey.log</string>
</dict>
</plist>
PLIST

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Installed. Press Control+Option+R to hear Claude's latest reply (press again to stop)."

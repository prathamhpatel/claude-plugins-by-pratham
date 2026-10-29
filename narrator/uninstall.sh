#!/bin/bash
# Stops the Narrator hotkey and removes everything install.sh added (/narrator uninstall runs this).
LABEL="com.voiceclaude.hotkey"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
rm -rf "$HOME/.claude/voice_claude"
echo "Narrator's hotkey, settings and cloned voices are removed. The ElevenLabs key stays in your Keychain (service voice-claude-elevenlabs); the cloning model stays in ~/.cache/huggingface (folders with chatterbox-turbo and S3TokenizerV2 in their names, about 3.5 GB)."

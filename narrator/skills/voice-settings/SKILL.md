---
name: voice-settings
description: Change how the narrator reads Claude's replies aloud. Use when the person asks to switch the reading voice (a saved ElevenLabs voice or a Mac voice), save a new cloned voice ID, change or turn off the screen flash, or fix the Control+Option+R hotkey.
---

Narrator speaks a short summary of Claude's latest reply when the person presses Control+Option+R, and dims and pulses the screen when a task finishes while they're away. Its settings live in `~/.claude/voice_claude/config.json`; change them through the CLI rather than editing the file:

```bash
python3 ~/.claude/voice_claude/voice_claude.py status                 # what's set now
python3 ~/.claude/voice_claude/voice_claude.py use me                 # a saved voice, or a Mac voice like "Daniel"
python3 ~/.claude/voice_claude/voice_claude.py add me <voice-id>      # save an ElevenLabs voice under a name
python3 ~/.claude/voice_claude/voice_claude.py clone me <audio-file>  # clone a voice on this Mac, free (10-15 s of speech)
python3 ~/.claude/voice_claude/voice_claude.py clone me-local me      # free Mac copy of the saved ElevenLabs voice "me", its backup
python3 ~/.claude/voice_claude/voice_claude.py flash 120              # flash after 2 min away; on | off | 0 = always
python3 ~/.claude/voice_claude/voice_claude.py detail medium          # how much it keeps: short | medium | full
python3 ~/.claude/voice_claude/voice_claude.py test                   # speak a test line in the current voice
```

The person can run the same as `/narrator <command>`. Things to know:

- A new cloned voice is made on elevenlabs.io (Voices → Instant Voice Clone, about a minute of the person's speech, with their consent); the person gives you its voice ID, never the API key.
- The ElevenLabs API key is in the macOS Keychain (service `voice-claude-elevenlabs`). Never print or ask for it; the person stores it with `security add-generic-password -U -s voice-claude-elevenlabs -a "$USER" -w` in their own Terminal.
- A voice cloned on this Mac (`clone`) needs no account and works offline; it starts about 5 seconds after the hotkey unless the turn-end hook made the audio already. A copy made from an ElevenLabs voice is that voice's backup whenever ElevenLabs fails.
- When ElevenLabs fails, it falls back to the voice cloned on this Mac, else the Mac voice and logs why in `~/.claude/voice_claude/voice_claude.log`; read that first when the person says the voice sounds wrong.
- If the hotkey does nothing, `status` says whether the helper runs; `/narrator setup` (re)installs it.

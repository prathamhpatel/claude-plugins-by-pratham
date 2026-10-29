# Narrator

Reading Claude Code's replies gets tiring. Narrator reads them to you instead: press **Control + Option + R** anywhere on your Mac and you hear Claude's latest reply, rewritten in plain everyday words, in a Mac voice or any ElevenLabs voice (including a clone of your own). Press it again to stop.

When you step away while Claude works, the screen dims and pulses so you notice from across the room: **orange** when Claude has finished, **blue** when it's waiting on you (a question, a plan to approve, a permission prompt). The summary is written the moment Claude finishes, so it starts speaking as soon as you press the keys.

## Requirements

- macOS, with Apple's command line tools (`xcode-select --install`), which provide `python3` and `swiftc`
- Claude Code, signed in. Summaries are written by Haiku through your own `claude` login.
- Optional: an [ElevenLabs](https://elevenlabs.io) account for cloned voices, and `brew install ffmpeg` so that voice starts playing while it streams

## Install

```bash
claude plugin marketplace add prathamhpatel/claude-plugins-by-pratham
claude plugin install narrator@pratham-plugins
```

Restart Claude Code, then run **`/narrator setup`**. It compiles two small helpers (the hotkey and the screen flash) into `~/.claude/voice_claude` and adds a login item (`~/Library/LaunchAgents/com.voiceclaude.hotkey.plist`) so the hotkey works after a restart. Run `/narrator test` to hear the voice.

## Commands

| Command | What it does |
|---|---|
| `/narrator` | What's set now: voice, detail, flash, hotkey |
| `/narrator read` / `stop` | Read the latest reply, or stop (same as the hotkey) |
| `/narrator use <name>` | Switch to a saved ElevenLabs voice or any Mac voice, e.g. `use Daniel` |
| `/narrator add <name> <voice-id>` | Save an ElevenLabs voice under a name |
| `/narrator detail short\|medium\|full` | How much of the reply the summary keeps (default `medium`: every point, one sentence each) |
| `/narrator flash on\|off\|<seconds>` | Flash only after you've been away this many seconds (`0` = always) |
| `/narrator test` | Speak a test line in the current voice |
| `/narrator setup` / `uninstall` | Install or remove the hotkey helper and its settings |

Claude can also change these for you: just ask ("read in Daniel's voice", "only flash after two minutes").

## Use your own voice (ElevenLabs)

1. On elevenlabs.io: Voices → Add a new voice → Instant Voice Clone. Upload one to two minutes of clear speech (with that person's permission). [`recording-script.txt`](recording-script.txt) is a 90-second script written to sound like Claude's replies. Copy the voice ID.
2. Create an API key (Developers → API Keys, with text-to-speech access) and save it in your Keychain. Run this in your own Terminal; it asks for the key twice, hidden:
   ```bash
   security add-generic-password -U -s voice-claude-elevenlabs -a "$USER" -w
   ```
3. In Claude Code: `/narrator add me <voice-id>`, then `/narrator use me`, then `/narrator test`.

The key never goes into a file or the chat. If ElevenLabs fails (offline, out of credits), Narrator falls back to the Mac voice and writes the reason to `~/.claude/voice_claude/voice_claude.log`. Longer summaries use more ElevenLabs credits.

## Settings

The commands above write `~/.claude/voice_claude/config.json`. A few more keys can be edited there by hand:

| Key | Default | What it does |
|---|---|---|
| `voice` | `Samantha` | Mac voice, also the fallback for ElevenLabs. Nicer ones: System Settings → Accessibility → Spoken Content → System Voice → Manage Voices |
| `rate` | `185` | Mac voice speed, words per minute |
| `model` | `haiku` | Model that writes the summary |
| `summarize` | `true` | `false` reads the whole reply word for word |
| `prefetch` | `true` | Write the summary as soon as Claude finishes (one Haiku call per reply) |
| `elevenlabs_model` | `eleven_flash_v2` | Fastest. `eleven_flash_v2_5` for other languages, `eleven_multilingual_v2` for a richer, slower voice |

## How it works

When Claude finishes a turn, the plugin's hook checks how long the keyboard and mouse have been idle, flashes the screen if you're away, and asks Haiku to rewrite the reply for listening. The hotkey helper runs `voice_claude.py read`, which finds the most recent Claude Code transcript in `~/.claude/projects`, takes the reply after your last message, and speaks the summary. Nothing leaves your Mac except the Haiku call through your Claude login and, if you use it, the text sent to ElevenLabs.

After updating the plugin, run `/narrator setup` again so the hotkey uses the new version.

## Uninstall

```bash
# in Claude Code
/narrator uninstall
# then
claude plugin uninstall narrator@pratham-plugins
```

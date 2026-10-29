#!/usr/bin/env python3
"""Voice Claude: speak a plain-words summary of Claude Code's latest reply.

  voice_claude.py read [--detach]          toggle: start reading, or stop if already reading
  voice_claude.py stop                     stop reading
  voice_claude.py status                   show the voice, saved voices, flash and hotkey
  voice_claude.py use <name>               switch to a saved voice or any Mac voice
  voice_claude.py add <name> <voice-id>    save an ElevenLabs voice under a name
  voice_claude.py clone <name> <audio>     clone a voice on this Mac from 10-15 seconds of speech,
                                           or from a saved ElevenLabs voice: clone <name> <its name>
  voice_claude.py flash on|off|<seconds>   flash after replies when away this long
  voice_claude.py detail short|medium|full how much of the reply the summary keeps
  voice_claude.py preview                  print the reply and its summary without speaking
  voice_claude.py test                     speak a short test line in the current voice
  voice_claude.py on-stop [done|ask]       turn-end hook: flash the screen, prepare the summary
  voice_claude.py alert                    Claude is waiting on you: flash blue if you're away
"""
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import wave
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HOME = Path.home()
PROJECTS = HOME / ".claude" / "projects"
STATE = HOME / ".claude" / "voice_claude"
PID_FILE = STATE / "reader.pid"
CACHE_FILE = STATE / "last_summary.json"
CONFIG_FILE = STATE / "config.json"
LOG_FILE = STATE / "voice_claude.log"
FLASH_BIN = STATE / "voice-claude-flash"
VOICES_DIR = STATE / "voices"
TTS_ENV = STATE / "tts-env"  # Python environment for the voice cloned on this Mac
TTS_PYTHON = TTS_ENV / "bin" / "python"
LOCAL_TTS = Path(__file__).resolve().parent / "local_tts.py"
KEYCHAIN_SERVICE = "voice-claude-elevenlabs"

DEFAULTS = {
    "engine": "say",  # "say" (Mac voices), "elevenlabs" (cloned voice online) or "local" (cloned on this Mac)
    "voice": "Samantha",
    "rate": 185,
    "model": "haiku",
    "summarize": True,
    "detail": "medium",  # how much the summary keeps: short, medium or full (see LENGTHS)
    "flash": True,  # dim and pulse the screen when Claude finishes...
    "away_after_seconds": 60,  # ...but only if the keyboard and mouse were idle this long (0 = always)
    "prefetch": True,  # write the summary when Claude finishes, so the hotkey speaks at once
    "elevenlabs_voice_id": "",
    "elevenlabs_model": "eleven_flash_v2",
    "voices": {},  # saved ElevenLabs voices by name, e.g. {"me": "<voice id>"}
    "local_voice": "",  # the voice cloned on this Mac in use, also the fallback when ElevenLabs fails
    "local_voices": {},  # voices cloned on this Mac by name, e.g. {"me": "<path to its clip>"}
    "backups": {},  # ElevenLabs voice -> its copy on this Mac, used when ElevenLabs fails
    "local_model": "mlx-community/chatterbox-turbo-fp16",
}
MAX_INPUT_CHARS = 12000
START_SOUND = "/System/Library/Sounds/Tink.aiff"
TEST_LINE = "Hi! This is the voice I'll use to read Claude's replies to you."
SAMPLE_LINE = ("Okay, so here's what happened. I fixed the login page, and now it loads a lot faster. "
               "All the tests pass, which is great. There's one small thing you'll want to check "
               "before you ship it, though.")  # what an ElevenLabs voice says to be cloned on this Mac
DETACHED = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL, "start_new_session": True}

LENGTHS = {
    "short": "2 to 4 short sentences, under 70 words: only what matters most.",
    "medium": "Cover every point the reply makes, in its order: what was done, the results, any "
              "problems, and anything the user needs to do or decide. One plain sentence per point, "
              "up to about 160 words.",
    "full": "Keep every point and detail, leaving nothing out, at whatever length that takes.",
}

PROMPT = """You are the voice of a coding assistant. You get the assistant's latest reply \
from a terminal session. Rewrite it for the user to listen to.
- Speak as the assistant, in first person, like telling a friend what happened.
- Simple everyday words. If a technical term is unavoidable, explain it in a few words.
- {length} Lead with the result or the answer.
- If the user needs to do or decide something, say it clearly at the end.
- Never read out code, file paths, URLs, commands or long identifiers; describe them instead.
- No markdown, lists or emojis. Output only the words to speak."""

child = None  # the current `claude` or `say` subprocess, killed on stop


def load_config():
    try:
        saved = json.loads(CONFIG_FILE.read_text())
    except (OSError, ValueError):
        saved = {}
    return {**DEFAULTS, "voices": {}, "local_voices": {}, "backups": {}, **saved}


def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2) + "\n")


def latest_transcript():
    transcripts = list(PROJECTS.glob("*/*.jsonl"))
    return max(transcripts, key=lambda p: p.stat().st_mtime) if transcripts else None


def last_reply(transcript):
    """Text Claude wrote after its last tool call or user message."""
    chunks = []
    for line in reversed(transcript.read_text(errors="ignore").splitlines()):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("isSidechain"):
            continue
        if entry.get("type") == "assistant":
            content = entry.get("message", {}).get("content") or []
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            text = "\n".join(b.get("text", "") for b in content
                             if isinstance(b, dict) and b.get("type") == "text").strip()
            if text:
                chunks.append(text)
        elif entry.get("type") == "user" and chunks:
            break
    return "\n\n".join(reversed(chunks))


def clean_for_speech(text):
    text = re.sub(r"```.*?```", " (code snippet) ", text, flags=re.S)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"https?://\S+", "a link", text)
    text = re.sub(r"[`*_#>|~]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def summarize(reply, model, detail):
    global child
    claude = shutil.which("claude") or str(HOME / ".local" / "bin" / "claude")
    prompt = PROMPT.format(length=LENGTHS.get(detail, LENGTHS["medium"]))
    child = subprocess.Popen(
        [claude, "-p", "--model", model,
         "--settings", '{"disableAllHooks":true}', "--strict-mcp-config",
         "--tools", "", "--no-session-persistence", "--system-prompt", prompt],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, cwd=STATE)
    try:
        out, _ = child.communicate(reply[:MAX_INPUT_CHARS], timeout=60)
    except subprocess.TimeoutExpired:
        child.kill()
        return None
    return out.strip() if child.returncode == 0 and out.strip() else None


def spoken_text(reply, cfg):
    if not cfg["summarize"]:
        return clean_for_speech(reply)
    key = hashlib.sha1(f"{cfg['model']}\n{cfg['detail']}\n{reply}".encode()).hexdigest()
    try:
        cached = json.loads(CACHE_FILE.read_text())
        if cached.get("key") == key:
            return cached["summary"]
    except (OSError, ValueError, KeyError):
        pass
    summary = summarize(reply, cfg["model"], cfg["detail"])
    if not summary:
        return "I couldn't make a summary, so here's the start of it. " + clean_for_speech(reply)[:600]
    summary = clean_for_speech(summary)
    CACHE_FILE.write_text(json.dumps({"key": key, "summary": summary}))
    return summary


def log(message):
    with LOG_FILE.open("a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


def elevenlabs_key():
    if os.environ.get("ELEVENLABS_API_KEY"):
        return os.environ["ELEVENLABS_API_KEY"]
    found = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                           capture_output=True, text=True)
    return found.stdout.strip()


def elevenlabs_speech(voice_id, model, text, key):
    """The streamed mp3 of `text` in an ElevenLabs voice."""
    request = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{urllib.parse.quote(voice_id, safe='')}/stream"
        "?output_format=mp3_44100_128",
        data=json.dumps({"text": text, "model_id": model}).encode(),
        headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"})
    return urllib.request.urlopen(request, timeout=30)


def play_elevenlabs(text, cfg):
    """Speak `text` in the ElevenLabs voice, playing it as it streams in. False if it can't."""
    global child
    voice_id, key = cfg["elevenlabs_voice_id"], elevenlabs_key()
    if not voice_id or not key:
        log("elevenlabs: missing voice id or API key, using the Mac voice")
        return False
    digest = hashlib.sha1(f"{voice_id}\n{cfg['elevenlabs_model']}\n{text}".encode()).hexdigest()
    audio_file = STATE / f"audio-{digest[:16]}.mp3"
    if audio_file.exists():
        child = subprocess.Popen(["afplay", str(audio_file)])
        child.wait()
        return True
    try:
        response = elevenlabs_speech(voice_id, cfg["elevenlabs_model"], text, key)
    except urllib.error.HTTPError as e:
        log(f"elevenlabs: HTTP {e.code} {e.read()[:300]!r}")
        return False
    except OSError as e:
        log(f"elevenlabs: {e}")
        return False

    ffplay = shutil.which("ffplay")
    if ffplay:  # start playing from the first bytes instead of waiting for the whole file
        child = subprocess.Popen(
            [ffplay, "-nodisp", "-autoexit", "-loglevel", "quiet", "-fflags", "nobuffer",
             "-probesize", "32", "-analyzeduration", "0", "-f", "mp3", "-i", "-"],
            stdin=subprocess.PIPE)
    audio = bytearray()
    with response:
        for chunk in iter(lambda: response.read(4096), b""):
            audio += chunk
            if ffplay:
                child.stdin.write(chunk)
                child.stdin.flush()
    for old in STATE.glob("audio-*.mp3"):
        old.unlink()
    audio_file.write_bytes(audio)
    if ffplay:
        child.stdin.close()
    else:
        child = subprocess.Popen(["afplay", str(audio_file)])
    child.wait()
    return True


def local_audio_file(text, cfg):
    clip = cfg["local_voices"].get(cfg["local_voice"], "")
    digest = hashlib.sha1(f"{clip}\n{cfg['local_model']}\n{text}".encode()).hexdigest()
    return STATE / f"audio-{digest[:16]}.wav"


def stop_maker(lock):
    """Stop the turn-end hook if it is still making this audio: speaking it now is quicker."""
    try:
        os.kill(int(lock.read_text()), signal.SIGTERM)
    except (OSError, ValueError):
        pass


def local_voice(text, cfg, play):
    """Say `text` in the voice cloned on this Mac, or with play=False only make it for later.
    False if it can't."""
    global child
    clip = cfg["local_voices"].get(cfg["local_voice"])
    if not clip or not TTS_PYTHON.exists():
        log("local voice: none cloned yet, using the Mac voice")
        return False
    audio_file = local_audio_file(text, cfg)
    lock = audio_file.with_suffix(".lock")
    if play:
        stop_maker(lock)
    if audio_file.exists():
        if play:
            child = subprocess.Popen(["afplay", str(audio_file)])
            child.wait()
        return True
    for old in STATE.glob("audio-*.wav"):
        old.unlink()
    child = subprocess.Popen(
        [str(TTS_PYTHON), str(LOCAL_TTS), "--ref", clip, "--out", str(audio_file),
         "--model", cfg["local_model"], *(["--play"] if play else [])],
        stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    lock.write_text(str(child.pid))
    try:
        _, err = child.communicate(text)
    finally:
        if lock.exists() and lock.read_text() == str(child.pid):
            lock.unlink()
    if child.returncode != 0:
        log(f"local voice: {err.strip()[-300:]!r}")
        return False
    return True


def speak(text, cfg):
    global child
    if cfg["engine"] == "elevenlabs" and play_elevenlabs(text, cfg):
        return
    # The voice cloned on this Mac, also when ElevenLabs fails (say the subscription ended).
    if (cfg["engine"] == "local" or cfg["local_voice"]) and local_voice(text, cfg, play=True):
        return
    child = subprocess.Popen(["say", "-v", cfg["voice"], "-r", str(cfg["rate"]), text])
    child.wait()


def running_reader():
    """PID of a reader that is still running, or None."""
    try:
        pid = int(PID_FILE.read_text())
    except (OSError, ValueError):
        return None
    ps = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True)
    return pid if "voice_claude.py" in ps.stdout else None


def stop():
    pid = running_reader()
    if pid:
        os.kill(pid, signal.SIGTERM)
    PID_FILE.unlink(missing_ok=True)
    return bool(pid)


def on_term(*_):
    if child and child.poll() is None:
        child.terminate()
    sys.exit(0)


def read():
    global child
    if stop():  # pressing the shortcut while reading stops it
        return
    PID_FILE.write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM, on_term)
    try:
        cfg = load_config()
        subprocess.Popen(["afplay", START_SOUND])
        transcript = latest_transcript()
        reply = last_reply(transcript) if transcript else ""
        text = spoken_text(reply, cfg) if reply else "There's no Claude reply to read yet."
        speak(text, cfg)
    finally:
        if running_reader() == os.getpid():
            PID_FILE.unlink(missing_ok=True)


def preview():
    transcript = latest_transcript()
    reply = last_reply(transcript) if transcript else ""
    print(f"transcript: {transcript}\n\n--- reply ---\n{reply}\n\n--- spoken ---")
    print(spoken_text(reply, load_config()) if reply else "(no reply found)")


def test():
    speak(TEST_LINE, load_config())


def idle_seconds():
    """Seconds since the last keyboard or mouse input."""
    out = subprocess.run(["ioreg", "-c", "IOHIDSystem", "-d", "4"], capture_output=True, text=True).stdout
    match = re.search(r'"HIDIdleTime" = (\d+)', out)
    return int(match.group(1)) / 1e9 if match else 0


def flash_if_away(kind, cfg):
    if cfg["flash"] and FLASH_BIN.exists() and idle_seconds() >= cfg["away_after_seconds"]:
        subprocess.Popen([str(FLASH_BIN), kind], **DETACHED)


def on_stop(args):
    """Turn-end hook: flash the screen and prepare the summary, without blocking Claude Code."""
    try:
        event = json.load(sys.stdin)
    except ValueError:
        event = {}
    cfg = load_config()
    flash_if_away("ask" if args[:1] == ["ask"] else "done", cfg)
    # Only once /narrator setup has run: until then nobody can press the hotkey.
    if cfg["prefetch"] and cfg["summarize"] and (STATE / "voice-claude-hotkey").exists():
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "prepare",
                          event.get("transcript_path", "")], **DETACHED)


def alert():
    """Claude is waiting on the person (a question, a plan, a permission): flash blue if away."""
    flash_if_away("ask", load_config())


def prepare():
    """Summarize the latest reply now so the hotkey can speak it right away."""
    time.sleep(1)  # give Claude Code a moment to finish writing the transcript
    path = Path(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else latest_transcript()
    reply = last_reply(path) if path and path.exists() else ""
    if reply:
        cfg = load_config()
        text = spoken_text(reply, cfg)
        if cfg["engine"] == "local":
            local_voice(text, cfg, play=False)


def read_detached():
    if stop():
        print("Stopped reading.")
        return
    subprocess.Popen([sys.executable, os.path.abspath(__file__), "read"], **DETACHED)
    print("Reading Claude's latest reply. Run it again to stop.")


def cli_stop():
    print("Stopped reading." if stop() else "Nothing is playing.")


def mac_voices():
    listing = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
    return [re.split(r"\s{2,}", line.strip())[0] for line in listing.splitlines() if line.strip()]


def status():
    cfg = load_config()
    names = {voice_id: name for name, voice_id in cfg["voices"].items()}
    if cfg["engine"] == "elevenlabs":
        current = names.get(cfg["elevenlabs_voice_id"], cfg["elevenlabs_voice_id"] or "no voice ID set")
        voice = f"{current} (ElevenLabs, {cfg['elevenlabs_model']})"
        if cfg["local_voice"]:
            voice += f", or {cfg['local_voice']} on this Mac when ElevenLabs fails"
    elif cfg["engine"] == "local":
        voice = f"{cfg['local_voice']} (cloned on this Mac)"
    else:
        voice = f"{cfg['voice']} (Mac voice)"
    if not cfg["flash"]:
        flash = "off"
    elif cfg["away_after_seconds"]:
        flash = f"after replies, when you've been away {cfg['away_after_seconds']}s"
    else:
        flash = "after every reply"
    helper = subprocess.run(["pgrep", "-f", "voice-claude-hotkey"], capture_output=True)
    hotkey = "Control+Option+R" if helper.returncode == 0 else "not running (run /narrator setup)"
    detail = cfg["detail"] if cfg["summarize"] else "whole reply, no summary"
    saved = [*cfg["voices"], *(f"{name} (on this Mac)" for name in cfg["local_voices"])]
    print(f"Voice: {voice}\nSaved voices: {', '.join(saved) or 'none'}\n"
          f"Detail: {detail}\nScreen flash: {flash}\nHotkey: {hotkey}")


def use(args):
    name = " ".join(args)
    cfg = load_config()
    mac = {v.lower(): v for v in mac_voices()}
    by_first_word = {v.split(" (")[0].lower(): v for v in mac.values()}
    if name in cfg["voices"]:
        cfg.update(engine="elevenlabs", elevenlabs_voice_id=cfg["voices"][name],
                   local_voice=cfg["backups"].get(name, ""))
    elif name in cfg["local_voices"]:
        cfg.update(engine="local", local_voice=name)
    elif name.lower() in mac or name.lower() in by_first_word:
        cfg.update(engine="say", voice=mac.get(name.lower()) or by_first_word[name.lower()])
    else:
        saved = ", ".join([*cfg["voices"], *cfg["local_voices"]]) or "none yet"
        sys.exit(f"No voice called '{name}'. Saved voices: {saved}. Mac voices: say -v '?'")
    save_config(cfg)
    print(f"Now reading with the Mac voice {cfg['voice']}." if cfg["engine"] == "say" else f"Now reading in {name}'s voice.")


def add(args):
    if len(args) != 2:
        sys.exit("Usage: add <name> <elevenlabs-voice-id>")
    name, voice_id = args
    cfg = load_config()
    cfg["voices"][name] = voice_id
    save_config(cfg)
    print(f"Saved '{name}'. Switch to it with: use {name}")


def clone(args):
    if len(args) != 2:
        sys.exit("Usage: clone <name> <audio file with 10-15 seconds of one person speaking clearly, "
                 "or the name of a saved ElevenLabs voice>")
    name, source = args
    cfg = load_config()
    VOICES_DIR.mkdir(parents=True, exist_ok=True)
    from_elevenlabs = source in cfg["voices"]
    if from_elevenlabs:  # record a sample of it to clone, about 200 characters of credits
        sample = VOICES_DIR / f"{name}-sample.mp3"
        try:
            with elevenlabs_speech(cfg["voices"][source], "eleven_multilingual_v2", SAMPLE_LINE, elevenlabs_key()) as r:
                sample.write_bytes(r.read())
        except OSError as e:
            sys.exit(f"Couldn't get a sample of {source} from ElevenLabs: {e}")
        audio = sample
    else:
        audio = Path(source).expanduser()
        if not audio.is_file():
            sys.exit(f"No audio file at {audio}")
    if not TTS_PYTHON.exists():
        uv = shutil.which("uv") or "/opt/homebrew/bin/uv"
        if not Path(uv).exists():
            sys.exit("Cloning on this Mac needs uv first: brew install uv")
        print("Installing the voice cloning tools, one time...", flush=True)
        subprocess.run([uv, "venv", "--quiet", "--python", "3.12", str(TTS_ENV)], check=True)
        subprocess.run([uv, "pip", "install", "--quiet", "--python", str(TTS_PYTHON), "mlx-audio"], check=True)
    clip = VOICES_DIR / f"{name}.wav"
    converted = subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@24000", "-c", "1", str(audio), str(clip)],
                               capture_output=True, text=True)
    if converted.returncode != 0:
        sys.exit(f"Couldn't read {audio.name}; save it as .m4a, .mp3 or .wav and try again.")
    with wave.open(str(clip)) as w:  # the model listens to the first 15 seconds at most
        params, frames = w.getparams(), w.readframes(w.getframerate() * 15)
    with wave.open(str(clip), "wb") as w:
        w.setparams(params)
        w.writeframes(frames)
    cfg["local_voices"][name] = str(clip)
    print("Making a first line in the new voice (the first time downloads the model, about 3 GB)...", flush=True)
    if not local_voice(TEST_LINE, {**cfg, "local_voice": name}, play=False):  # so `test` plays at once
        sys.exit(f"Cloning failed; the reason is in {LOG_FILE}")
    if from_elevenlabs:  # a backup: keep the voice in use, and step in when ElevenLabs fails
        cfg["backups"][source] = name
        if cfg["engine"] == "elevenlabs" and cfg["elevenlabs_voice_id"] == cfg["voices"][source]:
            cfg["local_voice"] = name
        save_config(cfg)
        print(f"Saved {name}, a copy of {source} made on this Mac. It reads instead of {source} "
              f"whenever ElevenLabs fails. Switch to it with: use {name}")
    else:
        cfg.update(engine="local", local_voice=name)
        save_config(cfg)
        print(f"Now reading in {name}'s voice, made on this Mac. Hear it with: test")


def flash_setting(args):
    cfg = load_config()
    choice = args[0].lower() if args else ""
    if choice in ("on", "off"):
        cfg["flash"] = choice == "on"
    elif choice.isdigit():
        cfg.update(flash=True, away_after_seconds=int(choice))
    else:
        sys.exit("Usage: flash on | off | <seconds away before it flashes, 0 = always>")
    save_config(cfg)
    if not cfg["flash"]:
        print("Screen flash is off.")
    elif cfg["away_after_seconds"]:
        print(f"Screen flashes after a reply when you've been away {cfg['away_after_seconds']} seconds.")
    else:
        print("Screen flashes after every reply.")


def detail_setting(args):
    choice = args[0].lower() if args else ""
    if choice not in LENGTHS:
        sys.exit("Usage: detail short | medium | full")
    cfg = load_config()
    cfg.update(detail=choice, summarize=True)
    save_config(cfg)
    print({"short": "Summaries keep only the most important points.",
           "medium": "Summaries cover every point, one plain sentence each.",
           "full": "Summaries keep every detail of the reply."}[choice])


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    command, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("read", [])
    actions = {
        "read": read_detached if "--detach" in args else read,
        "stop": cli_stop,
        "status": status,
        "use": lambda: use(args),
        "add": lambda: add(args),
        "clone": lambda: clone(args),
        "flash": lambda: flash_setting(args),
        "detail": lambda: detail_setting(args),
        "preview": preview,
        "test": test,
        "on-stop": lambda: on_stop(args),
        "alert": alert,
        "prepare": prepare,
    }
    if command not in actions:
        sys.exit(__doc__)
    actions[command]()


if __name__ == "__main__":
    main()

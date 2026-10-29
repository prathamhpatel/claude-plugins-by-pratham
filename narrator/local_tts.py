#!/usr/bin/env python3
"""Speak text in a cloned voice on this Mac, with no account (Chatterbox Turbo through mlx-audio).

  local_tts.py --ref <voice clip> --out <file.wav> [--model <repo>] [--play]    text on stdin

Runs in Narrator's own Python environment (~/.claude/voice_claude/tts-env). It makes the
audio a sentence at a time; with --play each sentence plays as soon as it is ready.
"""
import argparse
import os
import queue
import re
import signal
import subprocess
import sys
import tempfile
import threading

import numpy as np
from mlx_audio.audio_io import write
from mlx_audio.tts.utils import load_model

player = None  # the afplay of the sentence playing now, stopped with us


def stop(*_):
    if player and player.poll() is None:
        player.terminate()
    os._exit(0)


def play_in_order(sentences):
    global player
    while (path := sentences.get()) is not None:
        player = subprocess.Popen(["afplay", path])
        player.wait()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ref", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", default="mlx-community/chatterbox-turbo-fp16")
    parser.add_argument("--play", action="store_true")
    args = parser.parse_args()
    text = sys.stdin.read().strip()
    signal.signal(signal.SIGTERM, stop)

    model = load_model(args.model)
    model.prepare_conditionals(args.ref)
    sentences = queue.Queue()
    player_thread = threading.Thread(target=play_in_order, args=(sentences,), daemon=True)
    if args.play:
        player_thread.start()
    chunks = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, sentence in enumerate(s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()):
            audio = np.concatenate([np.array(r.audio) for r in model.generate(text=sentence, verbose=False)])
            chunks.append(audio)
            if args.play:
                path = os.path.join(tmp, f"{i}.wav")
                write(path, audio, model.sample_rate)
                sentences.put(path)
        partial = args.out + ".part"
        write(partial, np.concatenate(chunks), model.sample_rate, format="wav")
        os.replace(partial, args.out)
        if args.play:
            sentences.put(None)
            player_thread.join()


if __name__ == "__main__":
    main()

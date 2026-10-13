"""Step 1 test: does your Gnani API key work?  Run from the project folder:

    python scripts/gnani_check.py

It speaks a Hindi sentence (text-to-speech), saves hello.wav, then listens to that file
(speech-to-text) and prints what it heard. No server needed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, gnani  # noqa: E402

if not gnani.enabled():
    sys.exit("GNANI_API_KEY is empty. Put it in the .env file (GNANI_API_KEY=your-key) and run again.")

text = "नमस्ते गुरमीत जी। अमलोडिपिन की दवाई लेने का समय हो गया है। क्या आपने दवाई ली?"
print("1) Text to speech ...")
audio = gnani.synthesize(text, "hi")
Path("hello.wav").write_bytes(audio)
print(f"   OK, saved hello.wav ({len(audio)} bytes). Double-click it to listen.")

print("2) Speech to text on the same file ...")
heard = gnani.transcribe(audio, "hi")
print(f"   Heard: {heard}")
print("\nAll good. Your key works.")

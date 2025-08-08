import subprocess
from pathlib import Path

def render_tts(text: str, out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["espeak-ng", "-v", "de", text, "-w", str(out_path)], check=True)
    return out_path

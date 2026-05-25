from __future__ import annotations

import time
from pathlib import Path

from PIL import ImageGrab


def capture_screen_png(output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    image = ImageGrab.grab(all_screens=True)
    path = output_dir / f"screen-{time.strftime('%Y%m%d-%H%M%S')}.png"
    image.save(path)
    return path

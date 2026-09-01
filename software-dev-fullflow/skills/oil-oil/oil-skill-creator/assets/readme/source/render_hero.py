from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image


SOURCE_DIR = Path(__file__).resolve().parent
LAYOUT = SOURCE_DIR / "hero-layout.svg"
SUBJECT = SOURCE_DIR / "hero-subject.png"
OUTPUT = SOURCE_DIR.parent / "hero.png"
CANVAS = (1200, 420)
SUBJECT_BOX = (548, 18, 632, 390)


def render_layout(output: Path) -> None:
    rsvg = shutil.which("rsvg-convert")
    if rsvg:
        subprocess.run(
            [rsvg, "--width", "1200", "--height", "420", "--output", str(output), str(LAYOUT)],
            check=True,
        )
        return

    sips = shutil.which("sips")
    if sips:
        subprocess.run(
            [sips, "-s", "format", "png", str(LAYOUT), "--out", str(output)],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        return

    raise SystemExit("需要 rsvg-convert，或在 macOS 上使用系统自带的 sips。")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="oil-skill-creator-hero-") as temp_dir:
        base_path = Path(temp_dir) / "base.png"
        render_layout(base_path)

        with Image.open(base_path).convert("RGBA") as base, Image.open(SUBJECT).convert("RGBA") as subject:
            if base.size != CANVAS:
                raise SystemExit(f"布局尺寸错误：{base.size}，预期 {CANVAS}")

            alpha = subject.getchannel("A")
            bounds = alpha.getbbox()
            if bounds is None:
                raise SystemExit("透明插画没有可见内容。")

            subject = subject.crop(bounds)
            x, y, width, height = SUBJECT_BOX
            subject.thumbnail((width, height), Image.Resampling.LANCZOS)
            position = (x + (width - subject.width) // 2, y + (height - subject.height) // 2)
            base.alpha_composite(subject, position)
            base.save(OUTPUT, optimize=True)

    print(f"hero: {OUTPUT}")


if __name__ == "__main__":
    main()

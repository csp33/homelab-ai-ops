#!/usr/bin/env bash
# Export every Archify HTML diagram in docs/diagrams to a cropped PNG in docs/assets.
# Requires Google Chrome and `uv` (Pillow is fetched on demand).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
TMP="$(mktemp -d)"

for html in "$ROOT"/docs/diagrams/*.html; do
  name="$(basename "$html" .html)"
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars \
    --force-device-scale-factor=2 --window-size=1400,1700 --virtual-time-budget=4000 \
    --screenshot="$TMP/$name.png" "file://$html?embed=1&theme=dark" >/dev/null 2>&1
done

uv run --with pillow python - "$TMP" "$ROOT/docs/assets" <<'EOF'
import glob, os, sys
from PIL import Image, ImageChops

src, dst = sys.argv[1:3]
os.makedirs(dst, exist_ok=True)
for f in sorted(glob.glob(f"{src}/*.png")):
    im = Image.open(f).convert("RGB")
    bg = Image.new("RGB", im.size, im.getpixel((im.width - 1, im.height - 1)))
    box = ImageChops.difference(im, bg).convert("L").point(lambda p: 255 if p > 14 else 0).getbbox()
    im.crop(box).save(os.path.join(dst, os.path.basename(f)), optimize=True)
    print("wrote", os.path.join(dst, os.path.basename(f)))
EOF

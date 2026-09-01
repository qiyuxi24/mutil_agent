#!/bin/bash
# Computer-use init — run once at the start of each task.
# Sets up three things: scale factor, scroll tool, snap helper.
# Safe to re-run; only recompiles scroll tool if source changed.

SKILL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# ── 1. Retina scale factor ─────────────────────────────────────────────────
# screencapture gives pixel dimensions; cliclick uses logical points.
# On Retina screens these differ (typically 2×). We need the ratio so
# coordinates read from screenshots can be used directly for cliclick.
screencapture -x /tmp/_cu_check.png
PX=$(sips -g pixelWidth /tmp/_cu_check.png | awk '/pixelWidth/{print $2}')
LW=$(osascript -e 'tell application "Finder" to get item 3 of (get bounds of window of desktop)' 2>/dev/null || echo 1512)
SCALE=$(python3 -c "print(round($PX/$LW))")
echo "$SCALE" > /tmp/_cu_scale
echo "scale=$SCALE  (screenshot=${PX}px  logical=${LW}px)"

# ── 2. Scroll tool ─────────────────────────────────────────────────────────
# cliclick has no scroll wheel command; keyboard shortcuts are stolen by
# chat-app input boxes. We compile a tiny Swift binary using CGEvent instead.
cp "$SKILL_DIR/scripts/scroll.swift" /tmp/_cu_scroll.swift
if [ ! -f /tmp/_cu_scroll ] || [ /tmp/_cu_scroll.swift -nt /tmp/_cu_scroll ]; then
    swiftc /tmp/_cu_scroll.swift -o /tmp/_cu_scroll && echo "scroll tool compiled"
else
    echo "scroll tool up-to-date"
fi

# ── 3. Snap helper ─────────────────────────────────────────────────────────
# Wraps screencapture + resize-to-logical-resolution + optional crop.
# After cu_snap, coordinates in the image == cliclick logical coordinates.
# Keeping screenshots at logical resolution (rather than retina pixels)
# reduces vision-model token cost by ~30-50%.
#
# Usage:
#   /tmp/_cu_snap.sh <out.png>
#   /tmp/_cu_snap.sh <out.png> <W> <H> <x_offset> <y_offset>   # crop after resize
cat << 'SH' > /tmp/_cu_snap.sh
#!/bin/bash
OUT=${1:-/tmp/cu.png}
S=$(cat /tmp/_cu_scale 2>/dev/null || echo 2)
screencapture -x "$OUT"
PW=$(sips -g pixelWidth  "$OUT" | awk '/pixelWidth/{print $2}')
PH=$(sips -g pixelHeight "$OUT" | awk '/pixelHeight/{print $2}')
LW=$((PW / S)); LH=$((PH / S))
sips -z "$LH" "$LW" "$OUT" --out "$OUT" > /dev/null
if [ -n "$2" ]; then
    sips "$OUT" --cropToHeightWidth "$3" "$2" --cropOffset "${5:-0}" "${4:-0}" \
        --out "$OUT" > /dev/null
fi
echo "snap: ${LW}x${LH}$([ -n "$2" ] && echo " → crop $2×$3") → $OUT"
SH
chmod +x /tmp/_cu_snap.sh
echo "snap helper ready"

# ── 4. Visible processes ───────────────────────────────────────────────────
# Always print so you know the real process name before calling osascript.
# (e.g. Feishu ≠ Lark, WeChat ≠ 微信)
echo "--- visible processes ---"
osascript -e 'tell application "System Events" to get name of every process whose visible is true'

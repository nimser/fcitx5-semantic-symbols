#!/usr/bin/env bash
# Record scripted input through the real addon in an isolated headless compositor.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "${1:-}" != --bounded ]; then
    exec timeout --signal=TERM --kill-after=10s 180s bash "$0" --bounded
fi
work="$(mktemp -d)"
echo "Demo work/log directory: $work" >&2
outer_wayland="${WAYLAND_DISPLAY:-}"
outer_display="${DISPLAY:-}"
outer_swaysock="${SWAYSOCK:-}"
for tool in timeout sway swaymsg wf-recorder xdotool grim ffmpeg ffprobe gifski alacritty nvim fcitx5 python3; do
    command -v "$tool" >/dev/null || { echo "Missing: $tool" >&2; exit 1; }
done

# Use Oxocarbon colors and readable type in a compact canvas.
cat > "$work/alacritty.toml" <<'TOML'
[font]
size = 16.0
normal = { family = "monospace", style = "Regular" }
[window]
padding = { x = 20, y = 16 }
decorations = "none"
[colors.primary]
background = "#161616"
foreground = "#f2f4f8"
[colors.normal]
black = "#262626"
red = "#ee5396"
green = "#42be65"
yellow = "#82cfff"
blue = "#33b1ff"
magenta = "#ff7eb6"
cyan = "#3ddbd9"
white = "#dde1e6"
[colors.bright]
black = "#393939"
red = "#ee5396"
green = "#42be65"
yellow = "#82cfff"
blue = "#33b1ff"
magenta = "#ff7eb6"
cyan = "#3ddbd9"
white = "#ffffff"
TOML
cat > "$work/init.lua" <<'LUA'
vim.opt.number = false
vim.opt.laststatus = 0
vim.opt.ruler = false
vim.opt.showmode = false
vim.opt.linebreak = true
vim.opt.termguicolors = true
vim.cmd('highlight Normal guibg=#161616 guifg=#f2f4f8')
vim.cmd('highlight NonText guifg=#161616')
LUA
: > "$work/RELEASE.md"

# Check all preferred glyphs before starting the compositor or sending input.
echo 'Checking preferred glyphs (20s limit)...' >&2
timeout -k 2s 20s python3 - "$work/picks.json" <<'PY'
import json
import os
from pathlib import Path
import socket
import sys

picks = {}
for query, glyph in [('celebrate', '🥳'), ('grateful', '🙏'), ('exhausted', '😴'), ('equilibrium', '⇌')]:
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(5)
        client.connect(str(Path(os.environ['XDG_RUNTIME_DIR']) / 'fcitx5-semantic-symbols/search.sock'))
        client.sendall((query + '\n').encode())
        with client.makefile(encoding='utf-8') as reply:
            rows = [line.split('\t', 1)[0] for line in reply]
    if glyph not in rows[:28]:
        raise SystemExit(f'{query}: {glyph} is not in the grid; review the scene before recording')
    picks[query] = divmod(rows.index(glyph), 7)
Path(sys.argv[1]).write_text(json.dumps(picks))
PY

cat > "$work/sway.conf" <<CONF
output HEADLESS-1 resolution 820x500
default_border none
exec sh -c 'echo \$SWAYSOCK > $work/swaysock; echo \$DISPLAY > $work/xdisplay; echo \$WAYLAND_DISPLAY > $work/display; fcitx5 -d --disable=notifications >$work/fcitx.log 2>&1; sleep 3; touch $work/ready; env -u WAYLAND_DISPLAY XMODIFIERS=@im=fcitx alacritty --config-file $work/alacritty.toml -e nvim -u $work/init.lua -c startinsert $work/RELEASE.md'
CONF

echo 'Starting isolated compositor (40s limit)...' >&2
export WLR_BACKENDS=headless WLR_LIBINPUT_NO_DEVICES=1 WLR_RENDERER=pixman
env -u WAYLAND_DISPLAY -u DISPLAY -u SWAYSOCK dbus-run-session -- sway -c "$work/sway.conf" >"$work/sway.log" 2>&1 &
stage=$!
stop_recorder() {
    local signal tick
    for signal in INT TERM KILL; do
        kill -"$signal" "$recorder" 2>/dev/null || break
        for ((tick=0; tick<20; tick++)); do
            kill -0 "$recorder" 2>/dev/null || break 2
            sleep 0.1
        done
    done
    wait "$recorder" 2>/dev/null || true
    recorder=""
}
cleanup() {
    local status=$?
    trap '' INT TERM
    if [ -n "${recorder:-}" ]; then stop_recorder; fi
    if [ -s "$work/swaysock" ]; then
        socket="$(<"$work/swaysock")"
        if [ -n "$socket" ] && [ "$socket" != "$outer_swaysock" ]; then
            timeout -k 1s 2s swaymsg -s "$socket" exit >/dev/null 2>&1 || true
        fi
    fi
    kill -KILL "$stage" 2>/dev/null || true
    wait "$stage" 2>/dev/null || true
    if [ "$status" -eq 0 ]; then
        rm -rf "$work"
    else
        echo "Demo failed (exit $status); diagnostics retained in $work" >&2
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for _ in $(seq 1 160); do [ -e "$work/ready" ] && break; sleep 0.25; done
[ -e "$work/ready" ] || { echo 'Stage never came up' >&2; exit 1; }
sleep 6
export DISPLAY="$(<"$work/xdisplay")"
demo_wayland="$(<"$work/display")"
if [ -z "$DISPLAY" ] || [ "$DISPLAY" = "$outer_display" ] ||
   [ -z "$demo_wayland" ] || [ "$demo_wayland" = "$outer_wayland" ]; then
    echo 'Refusing input: nested displays are missing or match the outer session' >&2
    exit 1
fi

say() { timeout -k 1s 5s xdotool type --delay "${2:-45}" "$1"; }
press() { timeout -k 1s 5s xdotool key "$1"; }
pick() {
    local down right
    read -r down right < <(python3 -c 'import json,sys; print(*json.load(open(sys.argv[1]))[sys.argv[2]])' "$work/picks.json" "$1")
    press ctrl+shift+u; sleep 0.5
    say "$1" 90; sleep 1.2
    # Show browsing even when the preferred glyph is ranked first.
    press Right; sleep 0.4; press Left; sleep 0.4
    for ((i=0; i<down; i++)); do press Down; sleep 0.4; done
    for ((i=0; i<right; i++)); do press Right; sleep 0.4; done
    sleep 0.7
    press space; press space; sleep 0.6
}

# The first synthetic keystroke after startup is swallowed by the X server.
press shift; sleep 0.5

WAYLAND_DISPLAY="$demo_wayland" wf-recorder -o HEADLESS-1 -f "$work/demo.mp4" \
    -c libx264 -p preset=veryfast -p crf=20 -r 30 >"$work/recorder.log" 2>&1 &
recorder=$!
sleep 0.8

echo 'Recording four short scenes...' >&2
kill -0 "$recorder" || { echo 'Recorder exited; inspect recorder.log' >&2; exit 1; }
say 'Shipped! '; pick celebrate
press Return
say 'Thanks, team '; pick grateful
press Return
say 'Logging off '; pick exhausted
press Return
say 'H2 + I2 '; pick equilibrium; say ' 2HI'
sleep 1.5

echo 'Finalizing capture (bounded signal escalation)...' >&2
stop_recorder
timeout -k 1s 5s ffprobe -v error "$work/demo.mp4"
WAYLAND_DISPLAY="$demo_wayland" timeout -k 1s 5s grim "$work/screenshot.png"

# Preserve the compact canvas in the README animation.
echo 'Encoding preview (30s frames, 60s GIF limit)...' >&2
timeout -k 2s 30s ffmpeg -y -loglevel error -i "$work/demo.mp4" -vf 'fps=16' "$work/f%04d.png"
timeout -k 2s 60s gifski --quiet --fps 16 --width 820 --quality 85 --lossy-quality 75 -o "$work/demo.gif" "$work"/f*.png
cp "$work"/{demo.gif,demo.mp4,screenshot.png} "$here/"
printf 'demo.gif %s, demo.mp4 %s\n' "$(du -h "$here/demo.gif" | cut -f1)" "$(du -h "$here/demo.mp4" | cut -f1)"

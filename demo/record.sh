#!/usr/bin/env bash
# Record scripted input through the real addon in an isolated headless compositor.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
work="$(mktemp -d)"
outer_wayland="${WAYLAND_DISPLAY:-}"
outer_display="${DISPLAY:-}"
outer_swaysock="${SWAYSOCK:-}"
for tool in sway swaymsg wf-recorder xdotool grim ffmpeg gifski alacritty nvim fcitx5 python3; do
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
python3 - "$work/picks.json" <<'PY'
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

export WLR_BACKENDS=headless WLR_LIBINPUT_NO_DEVICES=1 WLR_RENDERER=pixman
env -u WAYLAND_DISPLAY -u DISPLAY -u SWAYSOCK dbus-run-session -- sway -c "$work/sway.conf" >"$work/sway.log" 2>&1 &
stage=$!
cleanup() {
    if [ -n "${recorder:-}" ]; then
        kill -INT "$recorder" 2>/dev/null || true
        wait "$recorder" 2>/dev/null || true
    fi
    if [ -s "$work/swaysock" ]; then
        socket="$(<"$work/swaysock")"
        if [ -n "$socket" ] && [ "$socket" != "$outer_swaysock" ]; then
            swaymsg -s "$socket" exit >/dev/null 2>&1 || true
        fi
    fi
    kill "$stage" 2>/dev/null || true
    wait "$stage" 2>/dev/null || true
    rm -rf "$work"
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

say() { xdotool type --delay "${2:-45}" "$1"; }
press() { xdotool key "$1"; }
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

say 'Shipped! '; pick celebrate
press Return
say 'Thanks, team '; pick grateful
press Return
say 'Logging off '; pick exhausted
press Return
say 'H2 + I2 '; pick equilibrium; say ' 2HI'
sleep 1.5

kill -INT "$recorder" 2>/dev/null || true
wait "$recorder"
recorder=""
WAYLAND_DISPLAY="$demo_wayland" grim "$here/screenshot.png" || true

# Preserve the compact canvas in the README animation.
ffmpeg -y -loglevel error -i "$work/demo.mp4" -vf 'fps=16' "$work/f%04d.png"
gifski --quiet --fps 16 --width 820 --quality 85 --lossy-quality 75 -o "$here/demo.gif" "$work"/f*.png
cp "$work/demo.mp4" "$here/demo.mp4"
printf 'demo.gif %s, demo.mp4 %s\n' "$(du -h "$here/demo.gif" | cut -f1)" "$(du -h "$here/demo.mp4" | cut -f1)"

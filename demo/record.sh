#!/usr/bin/env bash
# Record scripted input through the installed addon in an isolated headless compositor.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ "${1:-}" != --bounded ]; then
    exec timeout --signal=TERM --kill-after=10s 240s bash "$0" --bounded
fi
work="$(mktemp -d)"
outer_wayland="${WAYLAND_DISPLAY:-}"
outer_display="${DISPLAY:-}"
echo "Work directory: $work" >&2

for tool in timeout sway swaymsg wf-recorder xdotool grim ffmpeg ffprobe gifski alacritty nvim fcitx5 python3 dbus-run-session; do
    command -v "$tool" >/dev/null || { echo "Missing: $tool" >&2; exit 1; }
done
installed="${XDG_DATA_HOME:-$HOME/.local/share}/fcitx5/addon/semantic-symbols.conf"
[ -f "$installed" ] || { echo "Run ./install.sh first: $installed is missing" >&2; exit 1; }

# Isolate the input-method profile but preserve installed font discovery.
fonts="${XDG_CONFIG_HOME:-$HOME/.config}/fontconfig"
export XDG_CONFIG_HOME="$work/config" XDG_DATA_HOME="$work/data"
mkdir -p "$XDG_CONFIG_HOME/fontconfig"
[ -d "$fonts" ] && cp -r "$fonts/." "$XDG_CONFIG_HOME/fontconfig/"
theme="$XDG_DATA_HOME/fcitx5/themes/oxocarbon"
mkdir -p "$XDG_CONFIG_HOME/fcitx5/conf" "$XDG_DATA_HOME/fcitx5/addon" "$theme"
cp "$installed" "$XDG_DATA_HOME/fcitx5/addon/"
cat > "$XDG_CONFIG_HOME/fcitx5/profile" <<'PROFILE'
[Groups/0]
Name=Default
Default Layout=us
DefaultIM=keyboard-us

[Groups/0/Items/0]
Name=keyboard-us

[GroupOrder]
0=Default
PROFILE
cat > "$XDG_CONFIG_HOME/fcitx5/conf/classicui.conf" <<'CONF'
Font="Noto Serif 16"
Theme=oxocarbon
PerScreenDPI=False
CONF
cat > "$theme/theme.conf" <<'CONF'
[Metadata]
Name=Oxocarbon
Version=1
Author=fcitx5-semantic-symbols
Description=Dark rounded panel matching the Oxocarbon palette
ScaleWithDPI=False

[InputPanel]
NormalColor=#f2f4f8ff
HighlightCandidateColor=#161616ff
HighlightColor=#161616ff
HighlightBackgroundColor=#33b1ffff
Spacing=4

[InputPanel/Background]
Image=panel.svg
Margin/Left=14
Margin/Right=14
Margin/Top=14
Margin/Bottom=14

[InputPanel/Highlight]
Image=highlight.svg
Margin/Left=6
Margin/Right=6
Margin/Top=5
Margin/Bottom=5

[InputPanel/ContentMargin]
Left=6
Right=6
Top=6
Bottom=6

[Menu]
NormalColor=#f2f4f8ff
[Menu/Background]
Image=panel.svg
Margin/Left=14
Margin/Right=14
Margin/Top=14
Margin/Bottom=14
[Menu/Highlight]
Image=highlight.svg
CONF
cat > "$theme/panel.svg" <<'SVG'
<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40">
  <rect x="1.5" y="1.5" width="37" height="37" rx="10" ry="10" fill="#161616" stroke="#525252" stroke-width="1.5"/>
</svg>
SVG
cat > "$theme/highlight.svg" <<'SVG'
<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24">
  <rect x="0" y="0" width="24" height="24" rx="6" ry="6" fill="#33b1ff"/>
</svg>
SVG

cat > "$work/alacritty.toml" <<'TOML'
[font]
size = 18.0
normal = { family = "monospace", style = "Regular" }
[window]
padding = { x = 22, y = 14 }
decorations = "none"
[colors.primary]
background = "#161616"
foreground = "#f2f4f8"
TOML
cat > "$work/init.lua" <<'LUA'
vim.opt.number = false
vim.opt.laststatus = 0
vim.opt.ruler = false
vim.opt.showmode = false
vim.opt.termguicolors = true
vim.cmd('highlight Normal guibg=#161616 guifg=#f2f4f8')
vim.cmd('highlight NonText guifg=#161616')
LUA
: > "$work/notes.md"

# Check the glyphs the scenes rely on before starting the compositor.
echo 'Checking the search service...' >&2
timeout -k 2s 20s python3 - "$work/picks.json" <<'PY'
import json, os, socket, sys
from pathlib import Path

picks = {}
for query, glyph in [('celebrate', '🎉'), ('grateful', '🙏'), ('exhausted', '🥱'),
                     ('equilibrium', '⇌')]:
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(5)
        client.connect(str(Path(os.environ['XDG_RUNTIME_DIR']) / 'fcitx5-semantic-symbols/search.sock'))
        client.sendall((query + '\n').encode())
        with client.makefile(encoding='utf-8') as reply:
            rows = [line.split('\t', 1)[0] for line in reply]
    if glyph not in rows[:28]:
        raise SystemExit(f'{query}: {glyph} is not on the grid; revisit the scene')
    picks[query] = divmod(rows.index(glyph), 7)
Path(sys.argv[1]).write_text(json.dumps(picks))
PY

cat > "$work/sway.conf" <<CONF
output HEADLESS-1 resolution 600x360
output HEADLESS-1 render_bit_depth 8
default_border none
exec sh -c 'echo \$SWAYSOCK > $work/swaysock; echo \$DISPLAY > $work/xdisplay; echo \$WAYLAND_DISPLAY > $work/display; fcitx5 --disable=notifications >$work/fcitx.log 2>&1 & echo \$! > $work/fcitx.pid; sleep 3; touch $work/ready; env -u WAYLAND_DISPLAY XMODIFIERS=@im=fcitx LIBGL_ALWAYS_SOFTWARE=1 alacritty --config-file $work/alacritty.toml -e nvim -u $work/init.lua -c startinsert $work/notes.md >$work/editor.log 2>&1'
CONF

echo 'Starting the headless stage...' >&2
export WLR_BACKENDS=headless WLR_LIBINPUT_NO_DEVICES=1 WLR_RENDERER=pixman
bus=()
# Nix and other prefix installs ship the session bus config outside /etc.
if [ ! -f /etc/dbus-1/session.conf ]; then
    config="$(dirname "$(readlink -f "$(command -v dbus-run-session)")")/../share/dbus-1/session.conf"
    [ -f "$config" ] || { echo 'No D-Bus session configuration found' >&2; exit 1; }
    bus=(--config-file="$config")
fi
env -u WAYLAND_DISPLAY -u DISPLAY -u SWAYSOCK dbus-run-session "${bus[@]}" -- sway -c "$work/sway.conf" >"$work/sway.log" 2>&1 &
stage=$!
recorder=""
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
    if [ -n "$recorder" ]; then stop_recorder; fi
    if [ -s "$work/fcitx.pid" ]; then kill -TERM "$(<"$work/fcitx.pid")" 2>/dev/null || true; fi
    if [ -s "$work/swaysock" ]; then
        timeout -k 1s 2s swaymsg -s "$(<"$work/swaysock")" exit >/dev/null 2>&1 || true
    fi
    kill -TERM "$stage" 2>/dev/null || true
    sleep 0.2
    kill -KILL "$stage" 2>/dev/null || true
    wait "$stage" 2>/dev/null || true
    [ "$status" -eq 0 ] && rm -rf "$work" || echo "Failed (exit $status); logs kept in $work" >&2
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for _ in $(seq 1 160); do [ -e "$work/ready" ] && break; sleep 0.25; done
[ -e "$work/ready" ] || { echo 'The stage never came up' >&2; exit 1; }
sleep 6
export DISPLAY="$(<"$work/xdisplay")"
demo_wayland="$(<"$work/display")"
if [ -z "$DISPLAY" ] || [ "$DISPLAY" = "$outer_display" ] ||
   [ -z "$demo_wayland" ] || [ "$demo_wayland" = "$outer_wayland" ]; then
    echo 'Refusing to type: the nested displays are missing or match the outer session' >&2
    exit 1
fi

say() { timeout -k 1s 8s xdotool type --delay "${2:-42}" "$1"; }
press() { timeout -k 1s 5s xdotool key "$1"; }
pick() {
    local down right
    read -r down right < <(python3 -c 'import json,sys; print(*json.load(open(sys.argv[1]))[sys.argv[2]])' "$work/picks.json" "$1")
    press ctrl+shift+u; sleep 0.4
    say "$1" 85; sleep 1.1
    for ((i=0; i<down; i++)); do press Down; sleep 0.45; done
    for ((i=0; i<right; i++)); do press Right; sleep 0.45; done
    sleep 0.6
    press space; press space; sleep 0.5
}

timeout -k 1s 10s xdotool search --sync --onlyvisible --class Alacritty >/dev/null
press Shift_L; sleep 0.5

# Continuous CPU capture also delivers idle frames and lets SIGINT finish promptly.
WAYLAND_DISPLAY="$demo_wayland" wf-recorder -D --no-dmabuf -o HEADLESS-1 \
    -c libx264 -x yuv420p -r 30 -p crf=20 -f "$work/demo.mp4" >"$work/recorder.log" 2>&1 &
recorder=$!
sleep 0.4
kill -0 "$recorder" || { echo 'Recorder exited; inspect recorder.log' >&2; exit 1; }

echo 'Recording...' >&2
say 'Shipped! '; pick celebrate
press Return
say 'Thanks! '; pick grateful
press Return
say 'Logging off '; pick exhausted
press Return
say 'H2 + I2 '; pick equilibrium; say ' 2HI'
sleep 1.6

echo 'Encoding...' >&2
stop_recorder
WAYLAND_DISPLAY="$demo_wayland" timeout -k 1s 5s grim "$work/screenshot.png"
press Escape; say ':silent w' 10; press Return
python3 - "$work/notes.md" <<'PY'
from pathlib import Path
import sys
expected = 'Shipped! 🎉\nThanks! 🙏\nLogging off 🥱\nH2 + I2 ⇌ 2HI\n'
actual = Path(sys.argv[1]).read_text()
if actual != expected:
    raise SystemExit(f'Insertion verification failed: {actual!r}')
print('Verified all four inserted glyphs.')
PY
timeout -k 1s 5s ffprobe -v error -show_entries stream=codec_name,width,height -of json "$work/demo.mp4"
timeout -k 2s 60s ffmpeg -y -loglevel error -i "$work/demo.mp4" -vf fps=16 "$work/gif-%04d.png"
timeout -k 2s 120s gifski --quiet --fps 16 --width 600 --quality 88 --lossy-quality 80 \
    -o "$work/demo.gif" "$work"/gif-*.png
cp "$work"/{demo.gif,demo.mp4,screenshot.png} "$here/"
printf 'demo.gif %s, demo.mp4 %s\n' "$(du -h "$here/demo.gif" | cut -f1)" "$(du -h "$here/demo.mp4" | cut -f1)"

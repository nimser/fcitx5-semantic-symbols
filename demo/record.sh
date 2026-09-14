#!/usr/bin/env bash
# Record the demo inside a headless compositor, so the capture is reproducible
# and never touches the desktop it is launched from.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
work="$(mktemp -d)"
for tool in sway wf-recorder xdotool grim ffmpeg gifski alacritty nvim fcitx5; do
    command -v "$tool" >/dev/null || { echo "Missing: $tool" >&2; exit 1; }
done

# The editor is the real one, with the palette the rest of the desktop uses.
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

cat > "$work/sway.conf" <<CONF
output HEADLESS-1 resolution 1280x720
default_border none
exec sh -c 'echo \$DISPLAY > $work/xdisplay; echo \$WAYLAND_DISPLAY > $work/display; fcitx5 -d --disable=notifications >$work/fcitx.log 2>&1; sleep 3; touch $work/ready; env -u WAYLAND_DISPLAY XMODIFIERS=@im=fcitx alacritty --config-file $work/alacritty.toml -e nvim -u $work/init.lua -c startinsert $work/RELEASE.md'
CONF

export WLR_BACKENDS=headless WLR_LIBINPUT_NO_DEVICES=1 WLR_RENDERER=pixman
env -u WAYLAND_DISPLAY -u DISPLAY dbus-run-session -- sway -c "$work/sway.conf" >"$work/sway.log" 2>&1 &
stage=$!
cleanup() { pkill -f "sway -c $work" 2>/dev/null || true; rm -rf "$work"; }
trap cleanup EXIT

for _ in $(seq 1 160); do [ -e "$work/ready" ] && break; sleep 0.25; done
[ -e "$work/ready" ] || { echo 'Stage never came up' >&2; exit 1; }
sleep 6
export DISPLAY="$(cat "$work/xdisplay")"
demo_wayland="$(cat "$work/display")"

say() { xdotool type --delay "${2:-45}" "$1"; }
press() { xdotool key "$1"; }
search() { xdotool key ctrl+shift+u; }

# The first synthetic keystroke after startup is swallowed by the X server.
press shift; sleep 0.5

WAYLAND_DISPLAY="$demo_wayland" wf-recorder -o HEADLESS-1 -f "$work/demo.mp4" \
    -c libx264 -p preset=veryfast -p crf=20 -r 30 >"$work/recorder.log" 2>&1 &
recorder=$!
sleep 2.5

say '# Release notes' 42; press Return; press Return; sleep 0.4
say 'Semantic symbol search ships today ' 42
search; sleep 0.8
say 'celebrate our success' 55; sleep 1.8
press space; press space; sleep 1.2

press Return
say 'Lookups take ' 42
search; sleep 0.7
say 'at most' 60; sleep 1.6
press space; press space; sleep 1.2
say ' 10 ms, and nothing leaves the laptop.' 42; sleep 0.8

press Return
say 'Queries and glyphs travel ' 42
search; sleep 0.7
say 'goes both ways' 60; sleep 1.6
press Down; sleep 1.0
press Up; sleep 0.8
press Right; sleep 1.0
press space; press space; sleep 1.2

press Return
say 'Cannot name it? Describe it ' 42
search; sleep 0.7
say 'not sure' 60; sleep 1.8
press space; press space; sleep 2.2

kill -INT "$recorder" 2>/dev/null || true
for _ in $(seq 1 40); do kill -0 "$recorder" 2>/dev/null || break; sleep 0.25; done
WAYLAND_DISPLAY="$demo_wayland" grim "$here/screenshot.png" || true

# GitHub renders a committed GIF everywhere; video tags only survive uploads.
ffmpeg -y -loglevel error -i "$work/demo.mp4" -vf 'fps=16,scale=1000:-2:flags=lanczos' "$work/f%04d.png"
gifski --quiet --fps 16 --width 1000 --quality 85 --lossy-quality 75 -o "$here/demo.gif" "$work"/f*.png
cp "$work/demo.mp4" "$here/demo.mp4"
printf 'demo.gif %s, demo.mp4 %s\n' "$(du -h "$here/demo.gif" | cut -f1)" "$(du -h "$here/demo.mp4" | cut -f1)"

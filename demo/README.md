# Recording

Run `./demo/record.sh` with the addon installed and its search service running.
It works inside a container; a host desktop is not required.

The v0.1.0 stack is retained: headless sway + Xwayland, Alacritty + Neovim,
Fcitx5, xdotool, wf-recorder, grim, FFmpeg and gifski. Also required: D-Bus,
GNU timeout, Python 3, software OpenGL, Noto Serif and Noto Color Emoji.
Fcitx5 must be at least 5.1.22, including its loaded libraries.

The 600×360 scene types short messages and searches `celebrate` → 🎉,
`grateful` → 🙏, `exhausted` → 🥱 and `equilibrium` → ⇌. Arrow keys select
actual results; double-space inserts them. The saved editor buffer must match
all four intended glyphs before the script publishes any media.

The compositor, D-Bus session and input-method profile are isolated. Font
configuration is preserved. Input is refused if display names are missing or
match the outer session. Cleanup uses captured PIDs and the private compositor
socket, never process-name searches.

wf-recorder uses continuous CPU capture on an 8-bit output, including idle
frames. A 240-second deadline bounds the run; recorder shutdown escalates
through INT, TERM and KILL. Progress messages identify each stage, and failures
retain logs and partial media in the printed work directory.

Outputs are `demo.gif`, `demo.mp4` and `screenshot.png`. Review the recording for
clipping, missing glyphs and error banners before committing it.

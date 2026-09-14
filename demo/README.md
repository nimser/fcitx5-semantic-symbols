# Recording

Run on a graphical Linux host with the addon installed and its search service
running:

```sh
./demo/record.sh
```

Dependencies: sway (with Xwayland), alacritty, nvim, Fcitx5, xdotool, swaymsg,
wf-recorder, grim, ffmpeg, gifski and Python 3.

The script uses a private headless compositor and D-Bus session. It checks the
preferred glyphs against the search service before recording, rejects missing
or outer-session display names before sending input, and shuts down its own
compositor by its IPC socket.

The 820×500 scene uses short messages: `celebrate` → 🥳, `grateful` → 🙏,
`exhausted` → 😴, and `equilibrium` → ⇌ in a reversible reaction. Arrow keys
browse the actual ranked candidates; double-space inserts the selection.

Outputs overwrite `demo.gif`, `demo.mp4` and `screenshot.png`. Review the whole
recording before committing: check the selected glyphs, popup clipping, focus,
error banners and unused space. The committed media is the v0.1.0 recording;
the compact script has not yet been visually verified.

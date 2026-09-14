#!/usr/bin/env bash
# Build the addon, fetch the model, index the catalogue and register with Fcitx5.
set -euo pipefail

source="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
data="${XDG_DATA_HOME:-$HOME/.local/share}/fcitx5"
config="${XDG_CONFIG_HOME:-$HOME/.config}"
project="$data/semantic-symbols"
lib="$HOME/.local/lib/fcitx5"

for tool in uv g++ pkg-config; do
    command -v "$tool" >/dev/null || { echo "Missing build dependency: $tool" >&2; exit 1; }
done
pkg-config --atleast-version=5.1.22 Fcitx5Core || {
    echo 'Fcitx5 >= 5.1.22 development headers are required (temp mode API).' >&2
    exit 1
}

mkdir -p "$project" "$lib" "$data/addon" "$config/systemd/user"
if [ "$source" != "$project" ]; then
    cp -f "$source"/{addon.cpp,search.py,descriptions.py,pyproject.toml,uv.lock} "$project/"
    if [ -f "$source/descriptions.json" ]; then
        cp -f "$source/descriptions.json" "$project/"
    else
        rm -f "$project/descriptions.json"
    fi
fi

uv sync --frozen --project "$project" --python 3.13
"$project/.venv/bin/python" "$project/search.py" --prepare

output=$(mktemp "$lib/.semantic-symbols.XXXXXX")
trap 'rm -f "$output"' EXIT
# pkg-config emits compiler argument lists.
g++ -std=c++20 -O2 -Wall -Wextra -Werror -shared -fPIC -pthread \
    $(pkg-config --cflags Fcitx5Core) "$project/addon.cpp" \
    -o "$output" $(pkg-config --libs Fcitx5Core)
chmod 755 "$output"
mv -f "$output" "$lib/libsemantic-symbols.so"

cat > "$data/addon/semantic-symbols.conf" <<CONF
[Addon]
Name=Semantic Symbols
Comment=Local semantic emoji and Unicode search
Type=SharedLibrary
Library=$lib/libsemantic-symbols
Category=Module
Version=0.1.1
OnDemand=False

[Addon/Dependencies]
0=core:5.1.22
CONF

cat > "$config/systemd/user/fcitx5-semantic-symbols.service" <<UNIT
[Unit]
Description=Local semantic emoji and Unicode search for Fcitx5
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=simple
ExecStart=%h/.local/share/fcitx5/semantic-symbols/.venv/bin/python %h/.local/share/fcitx5/semantic-symbols/search.py
Environment=HF_HUB_OFFLINE=1
Environment=TOKENIZERS_PARALLELISM=false
Environment=OMP_NUM_THREADS=2
Environment=OPENBLAS_NUM_THREADS=1
Environment=PYTHONDONTWRITEBYTECODE=1
UMask=0077
RuntimeDirectory=fcitx5-semantic-symbols
RuntimeDirectoryMode=0700
Restart=on-failure
RestartSec=5
NoNewPrivileges=yes
RestrictAddressFamilies=AF_UNIX
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=%t/fcitx5-semantic-symbols
PrivateTmp=yes

[Install]
WantedBy=graphical-session.target
UNIT

systemctl --user daemon-reload
systemctl --user enable --now fcitx5-semantic-symbols.service
systemctl --user restart fcitx5.service 2>/dev/null || echo 'Restart Fcitx5 to load the addon.'
printf '%s\n' 'Installed. Press Control+Shift+U and describe the symbol you want.'

# fcitx5-semantic-symbols

Describe what you mean, get the glyph. A native [Fcitx5](https://fcitx-im.org/)
input mode that searches emoji **and** visible Unicode symbols together, by
meaning, entirely on your machine.

```
Control+Alt+U  ->  not sure              ->  ❓ 🤞 😕 ❔
Control+Alt+U  ->  goes both ways        ->  ⇄ ↔ ⇌
Control+Alt+U  ->  roughly the same      ->  ≈ ≡ ≅
Control+Alt+U  ->  celebrate our success ->  🎉 👏 🙌 🥳 🏆
Control+Alt+U  ->  at most               ->  ≤
```

Enter inserts the highlighted candidate into whatever you were typing in.
Escape cancels. No browser tab, no clipboard round trip, no network.

## Why this exists

Every semantic emoji search I could find is a web app: you leave your editor,
search in a browser, copy, come back, paste. Meanwhile the input method
framework already owns a candidate popup over every application on the desktop
— that is where this belongs. Fcitx5's own Unicode search needs the official
character name, which is exactly the thing you do not know.

It also refuses to treat mathematical and typographic symbols as second-class:
`≤`, `⇄`, `∴` and `‰` are ranked in the same list as 🎉, because "at most" and
"goes both ways" are how people actually describe them.

## How it works

- **Native addon** (`addon.cpp`, ~260 lines of C++) registers a Fcitx5
  `TempMode`. It owns the keyboard only while the popup is open, then hands
  control straight back to your regular input method.
- **Search service** (`search.py`) holds a quantized
  [BGE-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5) ONNX model
  and a precomputed matrix of catalogue embeddings, and answers queries over a
  `0600` Unix socket in the user runtime directory.
- **Catalogue** merges the Unicode emoji data with symbol and punctuation
  categories, plus hand-written intent descriptions for the glyphs whose
  official names hide their meaning ("left right arrow" is not how anyone asks
  for ↔).
- The addon never blocks the event loop: lookups run on a worker thread and are
  dispatched back through Fcitx5's `EventDispatcher`. Every reply carries a
  generation counter, so a slow answer for an abandoned query is discarded
  instead of overwriting a newer one.

Queries return in roughly 10 ms. The service costs about 250 MB resident; the
addon itself is negligible.

## Privacy and safety

- Nothing leaves the machine. The service speaks only `AF_UNIX`, and its unit
  sets `RestrictAddressFamilies=AF_UNIX`, `ProtectSystem=strict` and
  `ProtectHome=read-only`.
- The trigger is ignored when the focused input has the `Password` or
  `Sensitive` capability.
- The trigger is ignored while a composition is in progress, so it can never
  eat a half-typed Pinyin or Japanese phrase.
- If the service is not running, the popup shows a status line and typing keeps
  working. It never blocks keys on a missing backend.

## Install

Requires Fcitx5 >= 5.1.22 (the temp mode API), a C++20 compiler, `pkg-config`
and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/nimser/fcitx5-semantic-symbols
cd fcitx5-semantic-symbols
./install.sh
```

The script builds the addon into `~/.local/lib/fcitx5`, downloads and indexes
the model, writes the addon descriptor and the user service, then restarts
Fcitx5. Rerun it after an Fcitx5 ABI bump.

Fcitx5's name-based Unicode search shares the default `Control+Alt+U` binding.
Move it (Configure Fcitx5 -> Addons -> Unicode) or change the trigger in
`addon.cpp`; upstream's own default for that addon is `Control+Alt+Shift+U`.

## Keys

| Key | Action |
| --- | --- |
| `Control+Alt+U` | Open, or close when already open |
| Type freely | Refine the query |
| `Up` / `Down`, `Tab` / `Shift+Tab` | Move through candidates |
| `Page Up` / `Page Down` | Page through candidates |
| `Control+U` | Clear the query |
| `Enter` | Insert the highlighted glyph |
| `Escape` | Cancel |

## Tests

```bash
python -m unittest discover tests                       # native addon, isolated Fcitx5 instance
SEMANTIC_TEST_PYTHON=~/.local/share/fcitx5/semantic-symbols/.venv/bin/python \
    python -m unittest discover tests                   # plus real-model retrieval
```

The native test builds the addon, starts a private Fcitx5 instance with a stub
search service, and asserts insertion, cancellation, backspace, paging, the
discarding of stale replies, and the password and composition gates. The
retrieval test asserts that plain-language queries actually rank the right
glyph.

## Roadmap

Ideas worth stealing from the web-app generation of emoji search:

- **LLM-written descriptions.** [emojeez](https://github.com/badrex/emojeez)
  generates a rich description per emoji before embedding. Hand-written intent
  text is in here for ~120 glyphs and it measurably fixes the worst queries;
  generating it for the whole catalogue is the single largest accuracy win
  available.
- **Multilingual queries.** A multilingual encoder would let the query be typed
  in the language you are already writing in — which, in an input method, is
  the obvious thing to want.
- **Usage learning.** Rank recently chosen glyphs higher, the way every real
  input method does with words.

## License

MIT

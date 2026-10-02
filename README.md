# LEGO World Builder (HTML5)

*LEGO World Builder* and *LEGO World Builder 2*, the Shockwave construction games from
LEGO.com, running in a modern browser with no Shockwave plugin.

This is not a remake. The pages play the original movies' own content — their bitmaps,
text, sounds, score and behaviors, and their Lingo translated line for line into
JavaScript — on a small Director-compatible player written for them. The aim is that
they look, sound and play exactly like the Shockwave originals.

Played at [wb.viosarcade.xyz](https://wb.viosarcade.xyz): the front page chooses between
the two games, at `wb1/` and `wb2/`.

## Playing

Hosted with GitHub Pages. To run it locally, serve the repository root over HTTP (opening
`index.html` from disk will not work, because browsers block `fetch` on `file://`):

```
python -m http.server 8000
```

then open <http://localhost:8000/>.

The games are played as they always were: with the mouse, and the arrow keys to scroll
the map. Progress is kept in the browser.

## How it works

| Step | Tool | Output |
|---|---|---|
| Unprotect the movies and decompile their Lingo | `tools/extract.py` (runs [ProjectorRays](https://github.com/ProjectorRays/ProjectorRays)) | `work/pr/` (not committed) |
| Read the movies: casts, score, bitmaps, text, sound, fonts | `tools/build_library.py` with `tools/director/` | `data/*.json`, `assets/*/` |
| Translate the Lingo to JavaScript | `tools/transpile.py` with `tools/lingo/` | `src/games/*/scripts.js` |

`tools/transpile.py` also corrects one slip of ProjectorRays 0.2.0 with Director 8
bytecode, checking each script's bytecode listing: a chunk of a local used as a target
(`delete tmline.char[1]`) can come out naming the wrong local, and in World Builder 2 that
made the map's terrain table loop forever.

`tools/extract.py` takes the folder the two `.dcr` files are in. It also builds a small
helper that reads the fonts the movies embed (Director's PFR1 format) with
[LibreShockwave](https://github.com/Quackster/LibreShockwave)'s parser, fetched to
`work/` at a pinned commit; nothing of LibreShockwave is in this repository.

At runtime, `src/director/` is the player:

- `movie.js` — the score and its frame cycle, Director's event order, mouse and keyboard
  input, `the` properties and the built-in functions
- `lingo.js` — Lingo's values and operators: integers kept apart from floats, symbols,
  lists and property lists, points and rects, string chunks
- `sprite.js`, `members.js` — sprite channels and cast members as Lingo sees them
- `render.js` — the stage on a canvas, with Director's Copy, Matte and Background
  Transparent inks, blend, flips and sprite colours
- `text.js` — text members laid out as Director's text engine laid them out
- `image.js` — imaging Lingo (the minimap is drawn with it)
- `sound.js` — the eight sound channels on Web Audio, playlists played back to back

`src/main.js` loads a game and starts it.

### What the movies are made of

Both are Director 8 movies, 610 × 440, playing at 15 frames a second, with six cast
libraries: *Internal* (scripts, map files, interface), *title and levels*, *audio*,
*terrain and models*, *translation* and *tutorial*.

| | World Builder | World Builder 2 |
|---|---|---|
| Bitmaps | 758 | 821 |
| Text members (maps, config, labels) | 203 | 186 |
| Sounds | 33 | 33 |
| Scripts | 121 | 128 |
| Score frames | 31 | 28 |
| Worlds | 1–3, Ocean, Prehistoric | 1–2 |

Bitmaps come in every depth Director had (1, 2, 4, 8, 16 and 32 bits, some of them JPEG
with a separate alpha channel); 1567 of 1571 decode identically to Director's own export
of them. Text members are the Text Asset Xtra's, whose format is set out in
`tools/director/text.py`. Sounds are Shockwave Audio, which is MPEG audio in a wrapper.
The one font drawn from the movies themselves is 04b_08, the pixel font of the buttons;
the movies' embedded Arial and Arial Black are drawn with those typefaces.

## Differences from the original

- **Size.** The 610 × 440 stage is scaled to fit the window, letterboxed, and drawn at
  the screen's resolution, so text stays sharp.
- **Saving.** Director wrote the progress file (`gmlbLegoWB`, `gmlbLegoWB2`) with
  `setPref`; here it goes to the browser's localStorage under the same names.
- **Sound** starts after the first click on the page, because browsers keep it off until
  then; the page asks for that click before the game starts.
- **Fonts.** Arial and Arial Black are the system's (with Liberation Sans as the fallback
  where there is no Arial), where Director drew the subsets the movies embed.
- **Network.** The movies checked for streamed media and could load sound casts over the
  network in authoring mode; everything they need is already here, so those checks
  always find it ready.

## Where JavaScript and Lingo differ

The translated scripts run as JavaScript, so wherever the two languages disagree the
runtime or the translator supplies Lingo's behaviour. The ones these games depend on:

- Names are case-insensitive: handlers, properties, globals, locals and symbols.
- `5 / 2` is 2 and `5.0 / 2` is 2.5: integers and floats are different types.
- `VOID = 0` is true.
- Strings compare without regard to case; a string that reads as a number compares as one.
- Lists are 1-based, setting past the end pads with zeros, a sorted list stays sorted as
  items are added, and property lists can be keyed by points (the pathfinder's are).
- Lists compare by their values, in order, so a sorted list of property lists is ordered
  by their first values (the pathfinder's open list again).
- `and` and `or` evaluate both sides.
- `repeat with i = a to b` evaluates `b` again on every pass.
- A handler inherited from an ancestor runs with `me` set to the ancestor.
- `x.voidp`, `s.value` and the like: a one-argument function written as a property.
- `symbol("trigger ")` is `#trigger`; the tutorial's script depends on it.
- `go` from an event handler enters the new frame before the handler carries on, as
  Director's frozen-script mechanism does; the tutorial needs the mission's map to exist
  right after `go`.
- Mouse events go to the topmost sprite that has a script, so labels laid over buttons
  let clicks through.

A loop that never ends stops with a script error after five million passes, rather than
freezing the page.

## Checking it

For repeatable runs, open a game as `wb1/?test&seed=1`: the clock stops, frames advance
only when `__step(n)` is called, and random numbers follow the seed.
`tools/verify/drive.py` scripts runs that way (clicks, keys, screenshots), and
`tools/verify/soak.py` starts every mission and gives it random input for a while,
failing on any script error. Both need Python with Playwright.

## Credits

*LEGO World Builder* and *LEGO World Builder 2* were made by
[Gamelab](https://en.wikipedia.org/wiki/Gamelab) for The LEGO Group. LEGO is a trademark
of The LEGO Group, which does not sponsor, authorise or endorse this project; this is an
unofficial, non-commercial port. The game files were preserved by the
[BioMedia Project](https://www.biomediaproject.com/).

The port's own code is offered for anyone to read and learn from. The games' content —
the data in `data/` and `assets/` — is LEGO's and Gamelab's, included so the port is
playable; no ownership of it is claimed. If The LEGO Group would rather it were not
distributed, it will be taken down.

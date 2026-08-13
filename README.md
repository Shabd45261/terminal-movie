# Termux Movies

A complete movie & series streaming unit that runs **entirely inside Termux on your Android phone** — no app downloads, no sideloading. Launch `bash movies` and you get a full **keyboard-driven terminal UI** with a Netflix-style homescreen, then play anything in your **browser** in an adaptive player that automatically matches the video resolution to your connection speed.

<p align="center">
  <b>Terminal UI</b> → arrow keys browse genre rows → <kbd>Ctrl+P</kbd> play → browser player with adaptive quality
</p>

Powered by the **MovieBox** API (scraper ported from the CloudX-V2 CloudStream extension).

---

## Features

- **Keyboard-first terminal UI** (curses) — works over SSH, in Termux, or any terminal.
- **Genre-segregated homescreen**: Trending, Popular, Anime, Indonesian, **K-Drama**, Western, C-Drama, Thai, Indonesian Horror, Animated — each row in its **own color**.
- **Poster thumbnails**: true-color poster art rendered with Pillow when available, graceful **blur-hash color art** fallback.
- **Full search** (`/` key): live results across the whole catalog.
- **Series support**: open a series, browse episodes, play any episode.
- **Browser player** (`http://localhost:8080/player`):
  - **Adaptive bitrate (Auto)**: probes your connection every 8 seconds and shifts between the 360p / 480p / 720p / 1080p encodes so playback never stutters.
  - **Manual override**: force any resolution from the top bar.
- **Local streaming proxy** that injects the CDN `Referer` header browsers can't send — seeking/scrubbing works normally.
- **Zero storage**: streams are resolved live from the backend; nothing is downloaded or saved.

---

## Requirements

- An Android phone with **[Termux](https://github.com/termux/termux-app)** installed
- Termux package: `python`
- (optional) **[Termux:API](https://github.com/termux/termux-api)** so pressing play auto-opens the browser
- (optional) `pkg install python-pillow` for real poster thumbnails (blur-hash art is the automatic fallback)

---

## Installation

```bash
# 1. clone the repo (or download the zip and extract it)
git clone https://github.com/Shabd45261/Termux_Movies.git
cd Termux_Movies

# 2. run it
bash movies
```

The launcher installs dependencies (`flask`) on first run, starts the local server, waits until it's ready, and drops you into the keyboard UI.

> **Note on `./movies`:** Android's `/sdcard` filesystem doesn't allow executable permission bits, so use `bash movies`. If you clone into Termux's internal storage (`~/Termux_Movies`) instead, you can `chmod +x movies` and run `./movies`.

---

## Usage — Keyboard Controls

The app opens straight into the **search bar** — just start typing a movie or
series name and matching results appear live as you type.

| Key | Action |
| --- | ------ |
| *(type)* | Live search — results update as you type |
| `↑` / `↓` | Move through search results / episodes |
| `Enter` / `Ctrl+P` | Play the selected movie · **open** the selected series |
| `←` / `→` · `1`–`9` | In a series: switch **season** |
| `↑` / `↓` | In a series: navigate episodes of the chosen season |
| `Enter` / `Ctrl+P` | Play the selected episode |
| `/` / `s` | From the browse view: jump back to search |
| `Esc` | Clear search → back one step → browse home → quit prompt (y to confirm) |
| `Esc` `Esc` | Quit immediately (Ctrl+Esc on Termux) |

Pressing play opens the video in your browser at `http://localhost:<port>/player`.

### The browser player

- **Auto (default):** starts on the best quality and probes your connection every 8s. If your speed can't sustain the current quality, it shifts down (and back up) automatically — **never buffering more than you can handle**.
- **Manual:** click any quality (360p–1080p) from the top bar to lock it; Auto resumes when you pick "Auto".
- Your playback position is preserved when the quality switches.

---

## How it works — project architecture

```
movies                        Shell launcher: installs deps, starts the server,
                              waits for it to come up, runs the TUI, cleans up on exit
└── server/
    ├── __init__.py
    ├── app.py                Flask API server (the local "backend")
    ├── moviebox.py           MovieBox client: token handshake, catalog, search,
    │                         detail, stream resolution (scraped from CloudX-V2)
    ├── tui.py                The curses terminal UI (home / series / search states)
    ├── poster.py             Poster rendering: Pillow real thumbnails, else
    │                         pure-Python blur-hash art
    ├── vlc.py                Legacy VLC launcher (no longer used by the UI)
    └── static/
        ├── index.html        Web homescreen (secondary browser UI)
        ├── app.js            Web UI logic: rows, suggest, search, detail, play
        ├── style.css
        ├── player.html       Browser player page
        └── player.js         Adaptive-bitrate player + manual quality override
```

### Request flow

1. **`bash movies`** → launcher installs `flask`, starts `python -m server.app` in the background, polls `http://127.0.0.1:8080/` until it answers, then runs `python -m server.tui`. When you quit the TUI, the server is stopped automatically.
2. **TUI** → `server/tui.py` pulls `GET /api/home` (10 genre rows), renders colored cards with poster art, handles arrows / `Ctrl+P` / `/` / `Esc`. Opening a series fetches `GET /api/detail?slug=...` for its episodes; playing builds a URL and opens the browser. Pressing `Esc` `Esc` (Ctrl+Esc) quits.
3. **Player** → the browser loads `http://localhost:8080/player?slug=...&id=...&se=...&ep=...`, which asks `GET /api/streams` for the list of encodes (quality, bitrate, proxied URL) and picks the highest the connection can sustain (Auto) or a fixed one (manual).
4. **Streaming** → the `<video>` element plays through `GET /stream?url=<encoded CDN url>`. The proxy injects the required `Referer` header and forwards `Range` requests, so seeking works. Everything stays on localhost — no content is stored.

### API endpoints

| Route | Purpose |
| ----- | ------- |
| `GET /` | Web homescreen |
| `GET /api/home` | 10 genre rows with items (title, year, rating, poster, blur-hash, detailPath) |
| `GET /api/suggest?q=` | Live search suggestions |
| `GET /api/search?q=` | Full catalog search |
| `GET /api/detail?slug=` | Movie/series detail + episode list |
| `GET /api/play` | Resolve a stream (legacy) |
| `GET /api/streams?slug=&id=&se=&ep=` | All encodes: `{quality, format, size, duration, bitrate, url}` |
| `GET /player?slug=&id=&se=&ep=` | The adaptive browser player |
| `GET /stream?url=` | Local CDN proxy (injects Referer, forwards Range) |

---

## Configuration

- **Port**: `PORT=9000 bash movies` (default `8080`).
- The web UI is always available alongside the TUI at `http://localhost:<port>/`.

## Troubleshooting

- **"python" not found / flask missing** — the launcher installs flask automatically on first run; if it fails, run `pkg install python` then `pip install -r requirements.txt` manually.
- **Color-art thumbnails instead of posters** — Pillow isn't installed; `pkg install python-pillow` enables real poster art (blur-hash art is used automatically until then).
- **Play doesn't open the browser** — install [Termux:API](https://github.com/termux/termux-api) (`pkg install termux-api`), or open the printed URL manually.
- **Nothing plays / streams stall** — the MovieBox backend endpoints are public and unauthenticated but rate-limited and occasionally slow; wait a moment and try again.

## License

MIT — see [LICENSE](LICENSE).

# Terminal Movies

A high-performance movie & series streaming unit that runs **entirely inside your terminal** — no app downloads, no sideloading. Launch `bash movies` and you get a full **keyboard-driven terminal UI** with a Netflix-style homescreen, then play anything in your **browser** in an adaptive player that automatically matches the video resolution to your connection speed.

<p align="center">
  <b>Terminal UI</b> → arrow keys browse genre rows → <kbd>Enter</kbd> play → browser player with adaptive quality
</p>

Powered by the **MovieBox** API (scraper ported from the CloudX-V2 CloudStream extension).

---

## Features

- **Keyboard-first terminal UI** (curses) — works over SSH, in Git Bash, or any standard terminal.
- **Cross-Platform**: Optimized for Windows, macOS, and Linux.
- **Genre-segregated homescreen**: Trending, Popular, Anime, Indonesian, **K-Drama**, Western, C-Drama, Thai, Indonesian Horror, Animated — each row in its **own color**.
- **Poster thumbnails**: true-color poster art rendered with Pillow when available, graceful **blur-hash color art** fallback.
- **Full search** (`/` key): live results across the whole catalog.
- **Series support**: open a series, browse episodes, play any episode.
- **Continue Watching**: Automatically saves your progress and allows you to resume from where you left off.
- **Browser player** (`http://localhost:8080/player`):
  - **Adaptive bitrate (Auto)**: probes your connection every 8 seconds and shifts between the 360p / 480p / 720p / 1080p encodes so playback never stutters.
  - **Manual override**: force any resolution from the top bar.
- **Local streaming proxy** that injects the CDN `Referer` header browsers can't send — seeking/scrubbing works normally.
- **Zero storage**: streams are resolved live from the backend; nothing is downloaded or saved.

---

## Requirements

- **Python 3.x**
- **FFmpeg** (on your system PATH)
- A modern web browser
- (optional) `pip install pillow` for real poster thumbnails (blur-hash art is the automatic fallback)

---

## Installation

```bash
# 1. clone the repo
git clone https://github.com/Shabd45261/terminal-movie.git
cd terminal-movie

# 2. install dependencies (automatically handled by the launcher, or run manually)
pip install -r requirements.txt

# 3. run it
bash movies
```

The launcher installs dependencies on first run, starts the local server, waits until it's ready, and drops you into the keyboard UI.

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
| `Esc` `Esc` | Quit immediately |

Pressing play opens the video in your browser at `http://localhost:<port>/player`.

### The browser player

- **Auto (default):** starts on the best quality and probes your connection every 8s. If your speed can't sustain the current quality, it shifts down (and back up) automatically — **never buffering more than you can handle**.
- **Manual:** click any quality (360p–1080p) from the top bar to lock it; Auto resumes when you pick "Auto".
- Your playback position is preserved when the quality switches and synced back to your local history.

---

## How it works — project architecture

```
movies                        Shell launcher: installs deps, starts the server,
                              waits for it to come up, runs the TUI, cleans up on exit
└── server/
    ├── __init__.py
    ├── app.py                Flask API server (the local "backend")
    ├── history.py            Persistence layer for "Continue Watching"
    ├── moviebox.py           MovieBox client: token handshake, catalog, search,
    │                         detail, stream resolution (scraped from CloudX-V2)
    ├── tui.py                The curses terminal UI (home / series / search states)
    ├── poster.py             Poster rendering: Pillow real thumbnails, else
    │                         pure-Python blur-hash art
    └── static/
        ├── index.html        Web homescreen (secondary browser UI)
        ├── app.js            Web UI logic: rows, suggest, search, detail, play
        ├── style.css
        ├── player.html       Browser player page
        └── player.js         Adaptive-bitrate player + manual quality override
```

### API endpoints

| Route | Purpose |
| ----- | ------- |
| `GET /` | Web homescreen |
| `GET /api/home` | 10 genre rows + Recent Watches |
| `GET /api/suggest?q=` | Live search suggestions |
| `GET /api/search?q=` | Full catalog search |
| `GET /api/detail?slug=` | Movie/series detail + episode list |
| `GET /api/streams?slug=&id=&se=&ep=` | All encodes: `{quality, format, size, duration, bitrate, url}` |
| `GET /player?slug=&id=&se=&ep=` | The adaptive browser player |
| `GET /stream?url=` | Local CDN proxy (injects Referer, forwards Range) |

---

## Configuration

- **Port**: `PORT=9000 bash movies` (default `8080`).
- The web UI is always available alongside the TUI at `http://localhost:<port>/`.

## License

MIT — see [LICENSE](LICENSE).

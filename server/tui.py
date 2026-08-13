import curses
import json
import os
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import webbrowser

from .poster import dominant_color

os.environ.setdefault("ESCDELAY", "50")

PORT = int(os.environ.get("PORT", "8080"))
BASE = "http://127.0.0.1:%d" % PORT

K_UP, K_DOWN, K_LEFT, K_RIGHT = 259, 258, 260, 261
K_ENTER, K_CTRLP, K_ESC, K_TAB = 10, 16, 27, 9
K_BSP = 127          # DEL
K_BS = 263           # KEY_BACKSPACE
K_BEL = 8            # raw \b

ESC_WINDOW = 0.6     # second Esc within this window (Ctrl+Esc) quits

ENTER_KEYS = (K_ENTER, 13)

ROW_PALETTE = [
    (255, 92, 92),    # trending          red
    (255, 196, 84),   # popular           amber
    (255, 110, 200),  # anime             pink
    (92, 222, 142),   # indonesian        green
    (120, 180, 255),  # k-drama           blue
    (255, 160, 80),   # western           orange
    (200, 120, 255),  # c-drama           purple
    (255, 230, 120),  # thai              yellow
    (190, 70, 70),    # horror            dark red
    (120, 230, 220),  # animated          teal
]

ACCENT = (255, 198, 60)
MUTED = (150, 158, 180)
HIGHLIGHT = (255, 255, 255)
INPUT_BG = (45, 50, 66)

_COLOR_OK = False
_pair_cache = {}
_pair_used = 0


def row_color(name, idx):
    n = (name or "").lower()
    if "anime" in n:
        return ROW_PALETTE[2]
    if "horror" in n:
        return ROW_PALETTE[8]
    if "k-" in n or "korean" in n:
        return ROW_PALETTE[4]
    if "indonesian" in n:
        return ROW_PALETTE[3]
    if "documentary" in n:
        return ROW_PALETTE[3]
    if "anima" in n:
        return ROW_PALETTE[9]
    return ROW_PALETTE[idx % len(ROW_PALETTE)]


def _rgb256(r, g, b):
    """nearest xterm-256 palette index for an (r,g,b) tuple."""
    r = max(0, min(255, int(r)))
    g = max(0, min(255, int(g)))
    b = max(0, min(255, int(b)))

    def cube(x):
        if x < 48:
            return 0
        if x < 115:
            return 1
        if x < 155:
            return 2
        if x < 195:
            return 3
        if x < 235:
            return 4
        return 5

    if r == g == b:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return 232 + int(round((r - 8) / 10))
    return 16 + 36 * cube(r) + 6 * cube(g) + cube(b)


def _pair_for(fg, bg):
    """curses color pair id for an (fg, bg) RGB-tuple pair, 0 if no color."""
    global _pair_used
    if not _COLOR_OK:
        return 0
    key = (fg, bg)
    p = _pair_cache.get(key)
    if p is not None:
        return p
    _pair_used += 1
    maxp = max(1, curses.COLOR_PAIRS - 1)
    if _pair_used > maxp:
        _pair_used = 1
    fi = -1 if fg is None else _rgb256(*fg)
    bi = -1 if bg is None else _rgb256(*bg)
    try:
        curses.init_pair(_pair_used, fi, bi)
    except curses.error:
        return 0
    _pair_cache[key] = _pair_used
    return _pair_used


def api(path):
    r = urllib.request.urlopen(BASE + path, timeout=40)
    return json.loads(r.read().decode())


def open_browser(url):
    # Desktop (Windows/Mac/Linux) standard
    try:
        if webbrowser.open(url):
            return True
    except Exception:
        pass

    # Termux specific fallback
    binary = "/data/data/com.termux/files/usr/bin/termux-open-url"
    if os.path.exists(binary):
        try:
            subprocess.Popen([binary, url], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
        except Exception:
            pass
    return False


def player_url(item, season=None, episode=None):
    q = {"slug": item.get("detailPath"), "id": item.get("id"),
         "se": season or item.get("se", 0), "ep": episode or item.get("ep", 0), "time": item.get("time", 0)}
    return "http://localhost:%d/player?%s" % (PORT, urllib.parse.urlencode(q))


def is_series(item):
    return (item.get("type") or "").lower() in ("series", "tv")


class TUI:
    def __init__(self, stdscr):
        self.scr = stdscr
        self.h, self.w = stdscr.getmaxyx()
        self.state = "search"          # search | home | series
        self._prev_state = "search"
        self.loading = True
        self.home_rows = []
        self.row_cursor = 0
        self.col_cursor = 0
        self.row_scroll = 0
        self.col_scroll = 0
        self.series = None             # detail dict
        self.seasons = []              # list of season numbers
        self.season_cursor = 0
        self.ep_cursor = 0
        self.ep_scroll = 0
        self.search_query = ""
        self.search_results = []
        self.search_loaded = False
        self.search_fetching = False
        self.search_pending = False
        self._search_fetch_q = None
        self._last_typed = 0.0
        self.search_cursor = 0
        self.search_scroll = 0
        self.msg = None
        self.dirty = True
        self._last_esc = 0.0
        curses.curs_set(0)
        curses.use_default_colors()
        self.scr.keypad(True)
        self.scr.timeout(100)
        self._load_thread(lambda: api("/api/home"), "home")

    # ---- async loading ------------------------------------------------
    def _load_thread(self, fetcher, kind):
        def run():
            try:
                data = fetcher()
            except Exception as e:
                data = {"error": str(e)}
            self._store(kind, data)
        threading.Thread(target=run, daemon=True).start()

    def _store(self, kind, data):
        if kind == "home":
            if isinstance(data, dict) and "rows" in data:
                self.home_rows = data["rows"]
            self.loading = False
        elif kind == "series":
            if isinstance(data, dict) and data.get("error"):
                self.msg = "Failed to load series: %s" % data["error"]
                self.series = {}
                self.seasons = []
            else:
                self.series = data
                self._rebuild_seasons()
            self.loading = False
        elif kind == "search":
            if self._search_fetch_q != self.search_query:
                self.search_fetching = False
                self.dirty = True
                return
            if isinstance(data, dict) and "error" in data:
                self.search_results = []
                self.msg = "Search failed: %s" % data["error"]
            else:
                self.search_results = data or []
            self.search_loaded = True
            self.search_fetching = False
            self.search_pending = False
            self.search_cursor = 0
            self.search_scroll = 0
        self.dirty = True

    def _rebuild_seasons(self):
        d = self.series or {}
        eps = d.get("episodes") or []
        seas = [s.get("se") for s in (d.get("seasons") or []) if s.get("se")]
        if not seas:
            seas = sorted({ep.get("season") for ep in eps if ep.get("season")})
        self.seasons = seas
        self.season_cursor = 0
        self.ep_cursor = 0
        self.ep_scroll = 0

    def _current_eps(self):
        d = self.series or {}
        eps = d.get("episodes") or []
        if not self.seasons:
            return eps
        se = self.seasons[self.season_cursor]
        return [ep for ep in eps if ep.get("season") == se]

    # ---- item helpers -------------------------------------------------
    def focus_item(self):
        try:
            row = self.home_rows[self.row_cursor]
            return row["items"][self.col_cursor]
        except (IndexError, KeyError):
            return None

    def _row_items(self, i):
        try:
            return self.home_rows[i]["items"]
        except (IndexError, KeyError):
            return []

    def visible_rows(self):
        y = 1
        rows = []
        for i in range(self.row_scroll, len(self.home_rows)):
            r = self.home_rows[i]
            hh = 4
            if y + hh > self.h - 8:
                break
            rows.append(i)
            y += hh
        return rows

    def card_w(self):
        return max(8, min(12, (self.w - 4) // 5))

    def cards_visible(self):
        return max(1, (self.w - 3) // (self.card_w() + 2))

    def episode_visible(self):
        return max(1, self.h - 9)

    def result_visible(self):
        return max(1, self.h - 6)

    def clamp_col(self):
        items = self._row_items(self.row_cursor)
        if self.col_cursor >= len(items):
            self.col_cursor = max(0, len(items) - 1)
        if self.col_cursor < self.col_scroll:
            self.col_scroll = self.col_cursor

    # ---- main loop -----------------------------------------------------
    def run(self):
        while True:
            if self.dirty:
                self.draw()
                self.dirty = False
            self._tick_search()
            key = self.scr.getch()
            if key == -1:
                continue
            if self.handle(key):
                break

    def _tick_search(self):
        """Debounced live search: fires ~300ms after the user stops typing."""
        if self.state != "search":
            return
        if not self.search_query.strip():
            return
        if not self.search_pending or self.search_fetching:
            return
        if time.time() - self._last_typed < 0.3:
            return
        self.search_pending = False
        self.search_fetching = True
        q = self.search_query
        self._search_fetch_q = q
        self.search_loaded = False
        self._load_thread(lambda: api("/api/search?q=%s" % urllib.parse.quote(q)),
                          "search")
        self.dirty = True

    def handle(self, key):
        if key == K_ESC:
            if time.time() - self._last_esc < ESC_WINDOW:
                return True
            self._last_esc = time.time()
        else:
            self._last_esc = 0.0

        if self.msg:
            if self.msg.startswith("Quit CloudX"):
                if key in (ord("y"), ord("Y")):
                    return True
                if key in (K_ESC,) + ENTER_KEYS + (ord("n"), ord("N")):
                    self.msg = None
                    self.dirty = True
            else:
                self.msg = None
                self.dirty = True
            return False

        if key in (K_BSP, K_BS, K_BEL):
            key = K_BSP

        if self.state == "search":
            return self._handle_search(key)
        if self.state == "home":
            return self._handle_home(key)
        if self.state == "series":
            return self._handle_series(key)
        return False

    def _handle_search(self, key):
        if key == K_ESC:
            if self.search_query:
                self.search_query = ""
                self._reset_search()
                self.dirty = True
            elif self.home_rows:
                self.state = "home"
                self.dirty = True
            else:
                self.msg = "Quit CloudX Movies?  (y=yes / n=no)"
                self.dirty = True
            return False
        if key in ENTER_KEYS + (K_CTRLP,):
            if self.search_results and self.search_cursor < len(self.search_results):
                self.activate(self.search_results[self.search_cursor])
            return False
        if key in (K_UP, K_DOWN):
            n = len(self.search_results)
            if n:
                if key == K_UP and self.search_cursor > 0:
                    self.search_cursor -= 1
                elif key == K_DOWN and self.search_cursor < n - 1:
                    self.search_cursor += 1
                if self.search_cursor < self.search_scroll:
                    self.search_scroll = self.search_cursor
                per = self.result_visible()
                if self.search_cursor >= self.search_scroll + per:
                    self.search_scroll = self.search_cursor - per + 1
                self.dirty = True
            return False
        if key == K_BSP:
            if self.search_query:
                self.search_query = self.search_query[:-1]
                self._reset_search()
                self.dirty = True
            return False
        if 32 <= key < 127:
            self.search_query += chr(key)
            self.search_pending = True
            self.search_loaded = False
            self._last_typed = time.time()
            self.dirty = True
        return False

    def _reset_search(self):
        self.search_results = []
        self.search_loaded = False
        self.search_fetching = False
        self.search_pending = bool(self.search_query.strip())
        self._search_fetch_q = None
        self.search_cursor = 0
        self.search_scroll = 0

    def _handle_home(self, key):
        if key in (ord("/"), ord("s"), ord("S")):
            self.state = "search"
            self.search_query = ""
            self._reset_search()
            self.dirty = True
            return False
        if key == K_UP:
            if self.row_cursor > 0:
                self.row_cursor -= 1
                while self.row_cursor < self.row_scroll:
                    self.row_scroll -= 1
                self.clamp_col()
                self.dirty = True
        elif key == K_DOWN:
            if self.row_cursor < len(self.home_rows) - 1:
                self.row_cursor += 1
                while self.row_cursor >= self.row_scroll + len(self.visible_rows()):
                    self.row_scroll += 1
                self.clamp_col()
                self.dirty = True
        elif key == K_LEFT:
            if self.col_cursor > 0:
                self.col_cursor -= 1
                if self.col_cursor < self.col_scroll:
                    self.col_scroll = self.col_cursor
                self.dirty = True
        elif key == K_RIGHT:
            items = self._row_items(self.row_cursor)
            if self.col_cursor < len(items) - 1:
                self.col_cursor += 1
                if self.col_cursor >= self.col_scroll + self.cards_visible():
                    self.col_scroll = self.col_cursor - self.cards_visible() + 1
                self.dirty = True
        elif key in ENTER_KEYS + (K_CTRLP,):
            item = self.focus_item()
            if item:
                self.activate(item)
        elif key == K_ESC:
            self.msg = "Quit CloudX Movies?  (y=yes / n=no)"
            self.dirty = True
        return False

    def _handle_series(self, key):
        if key == K_ESC:
            self.state = self._prev_state if self._prev_state in ("home", "search") \
                else "search"
            self.series = None
            self.seasons = []
            self.dirty = True
            return False
        eps = self._current_eps()
        if key in (K_LEFT, K_RIGHT, K_TAB) and len(self.seasons) > 1:
            if key == K_LEFT:
                self.season_cursor = (self.season_cursor - 1) % len(self.seasons)
            else:
                self.season_cursor = (self.season_cursor + 1) % len(self.seasons)
            self.ep_cursor = 0
            self.ep_scroll = 0
            self.dirty = True
            return False
        if ord("1") <= key <= ord("9") and len(self.seasons) > 1:
            i = key - ord("1")
            if i < len(self.seasons):
                self.season_cursor = i
                self.ep_cursor = 0
                self.ep_scroll = 0
                self.dirty = True
            return False
        if key == K_UP and self.ep_cursor > 0:
            self.ep_cursor -= 1
            if self.ep_cursor < self.ep_scroll:
                self.ep_scroll = self.ep_cursor
            self.dirty = True
        elif key == K_DOWN and self.ep_cursor < len(eps) - 1:
            self.ep_cursor += 1
            per = self.episode_visible()
            if self.ep_cursor >= self.ep_scroll + per:
                self.ep_scroll = self.ep_cursor - per + 1
            self.dirty = True
        elif key in ENTER_KEYS + (K_CTRLP,) and eps:
            self.play_episode(eps[self.ep_cursor])
        return False

    def activate(self, item):
        if is_series(item):
            self._prev_state = self.state
            self.state = "series"
            self.series = None
            self.seasons = []
            self.loading = True
            self.ep_cursor = 0
            self.ep_scroll = 0
            self.dirty = True
            self._load_thread(lambda: api("/api/detail?slug=%s" %
                                          urllib.parse.quote(item["detailPath"])),
                              "series")
        else:
            self.play(item)

    def play(self, item, episode=None):
        se = episode["season"] if episode else item.get("se", 0)
        ep = episode["episode"] if episode else item.get("ep", 0)
        url = player_url(item, se, ep)
        if open_browser(url):
            self.msg = "Opening player in browser\u2026\n\n%s" % url
        else:
            self.msg = "Open this URL in your browser:\n\n%s" % url
        self.dirty = True

    def play_episode(self, episode):
        self.play(self.series, episode)

    # ---- drawing -------------------------------------------------------
    def draw(self):
        self.h, self.w = self.scr.getmaxyx()
        self.scr.erase()
        try:
            self._header()
            if self.state == "home":
                self._draw_home()
            elif self.state == "series":
                self._draw_series()
            else:
                self._draw_search()
            self._help()
            if self.msg:
                self._message()
        except Exception:
            import traceback
            with open("/tmp/cloudx-tui-errors.log", "a") as f:
                f.write(traceback.format_exc())
        self.scr.refresh()

    def _header(self):
        title = " CLOUDX MOVIES "
        self.add(0, 0, title, ACCENT, bold=True)
        n = len(title)
        if self.state == "search":
            status = "Search"
        elif self.state == "series":
            status = "Series"
        else:
            status = "Browse"
        if self.loading and self.state == "series":
            status = "Loading episodes\u2026"
        self.add(0, n, " " + status, MUTED)

    def _help(self):
        y = self.h - 1
        if self.state == "search":
            bar = "type to search \u00b7 \u2191\u2193 pick \u00b7 Enter play/open \u00b7 Esc clear \u00b7 Esc Esc quit"
        elif self.state == "series":
            bar = "\u2191\u2193 episode \u00b7 \u2190\u2192 / 1-9 season \u00b7 Enter play \u00b7 Esc back \u00b7 Esc Esc quit"
        else:
            bar = "\u2191\u2193 row \u2190\u2192 pick \u00b7 Enter play/open \u00b7 / search \u00b7 Esc Esc quit"
        self.add(y, 0, " " + bar, MUTED)

    def _draw_home(self):
        if self.loading:
            self.add(self.h // 2 - 2, 0, "  Loading home rows\u2026", MUTED)
            return
        if not self.home_rows:
            self.add(self.h // 2 - 2, 0, "  No content loaded.", MUTED)
            return
        y = 1
        for ri in self.visible_rows():
            row = self.home_rows[ri]
            color = row_color(row.get("title"), ri)
            focused = ri == self.row_cursor
            name = row.get("title") or ""
            if name == "Trending Indonesian Movies":
                name = "Indonesian Movies"
            if name == "Animated Films":
                name = "Animated"
            n = len(self._row_items(ri))
            mark = "\u25b8 " if focused else "  "
            self.add(y, 0, mark + name, color, bold=focused)
            self.add(y, len(mark) + len(name) + 1, "(%d)" % n, MUTED)
            y += 1
            y = self._draw_cards(ri, y, focused)
        self._detail_panel()

    def _draw_cards(self, ri, y, focused):
        items = self._row_items(ri)
        if not items:
            return y + 4
        cw = self.card_w()
        gap = 2
        cv = self.cards_visible()
        self.col_scroll = min(self.col_scroll, max(0, len(items) - cv))
        color = row_color(self.home_rows[ri].get("title"), ri)
        for k in range(cv):
            idx = self.col_scroll + k
            if idx >= len(items):
                break
            it = items[idx]
            x = 2 + k * (cw + gap)
            self._draw_card(x, y, it, cw, color,
                            focused and ri == self.row_cursor and idx == self.col_cursor)
        return y + 4

    def _draw_card(self, x, y, item, cw, color, selected):
        dc = self._card_color(item)
        for i in range(3):
            self.add(y + i, x, " " * cw, bg=color if selected else dc)
        title = (item.get("title") or "")[:cw]
        self.add(y + 3, x, title, color, bold=selected, reverse=selected)

    def _card_color(self, item):
        key = ("cardc", item.get("poster"), item.get("blurHash"))
        if key not in card_cache:
            card_cache[key] = dominant_color(item.get("poster"), item.get("blurHash"))
        return card_cache[key]

    def _detail_panel(self):
        item = self.focus_item()
        if not item:
            return
        y = self.h - 6
        pv = 12
        dc = self._card_color(item)
        for i in range(5):
            self.add(y + i, 1, " " * pv, bg=dc)
        tx = pv + 3
        color = row_color(self.home_rows[self.row_cursor].get("title"),
                          self.row_cursor) if self.home_rows else ACCENT
        t = (item.get("title") or "")[:max(0, self.w - tx - 2)]
        self.add(y, tx, t, color, bold=True)
        meta = []
        if item.get("year"):
            meta.append(str(item["year"]))
        if item.get("rating"):
            meta.append("\u2605 " + str(item["rating"]))
        if item.get("country"):
            meta.append(str(item["country"]))
        if meta:
            self.add(y + 1, tx, "  ".join(meta), MUTED)
        self.add(y + 2, tx,
                 "Series \u2014 Enter for seasons & episodes" if is_series(item)
                 else "Movie \u2014 Enter to play", MUTED)
        act = "\u25b6 PLAY" if not is_series(item) else "\u25bc OPEN SERIES"
        self.add(y + 3, tx, act, ACCENT, bold=True)

    def _draw_series(self):
        if self.series is None:
            self.add(self.h // 2 - 2, 0, "  Loading episodes\u2026", MUTED)
            return
        d = self.series
        eps = self._current_eps()
        color = (200, 120, 255)
        title = (d.get("title") or "")[:max(0, self.w - 4)]
        self.add(1, 0, "  " + title, color, bold=True)
        meta = []
        if d.get("year"):
            meta.append(str(d["year"]))
        if d.get("rating"):
            meta.append("\u2605 " + str(d["rating"]))
        if eps:
            meta.append("%d episodes" % len(eps))
        if meta:
            self.add(2, 0, "   " + "  ".join(meta), MUTED)
        if self.seasons:
            sy = 4
            label = "   Season:"
            self.add(sy, 0, label, MUTED)
            x = len(label) + 1
            for i, se in enumerate(self.seasons):
                sel = i == self.season_cursor
                lab = " %d " % se
                self.add(sy, x, lab, ACCENT if sel else MUTED,
                         bold=sel, reverse=sel)
                x += len(lab)
            if len(self.seasons) > 1:
                self.add(sy, x + 1, "\u2190\u2192 / 1-9", MUTED)
        ey = 6
        per = self.episode_visible()
        self.ep_scroll = min(self.ep_scroll, max(0, len(eps) - per))
        for k in range(per):
            idx = self.ep_scroll + k
            if idx >= len(eps):
                break
            ep = eps[idx]
            sel = idx == self.ep_cursor
            name = ep.get("name") or "S%02dE%02d" % (
                ep.get("season") or 0, ep.get("episode") or 0)
            line = " %s  %s" % ("\u25b8" if sel else " ", name)
            self.add(ey + k, 0, line, ACCENT if sel else MUTED, bold=sel)

    def _draw_search(self):
        y = 1
        label = "  Search: "
        self.add(y, 0, label, ACCENT, bold=True)
        lx = len(label)
        box = " " * max(1, min(44, self.w - lx - 2))
        self.add(y, lx, box, bg=INPUT_BG)
        disp = self.search_query[:len(box)]
        self.add(y, lx, disp, HIGHLIGHT, bold=True)
        if self.search_query and not self.search_fetching and len(disp) < len(box):
            self.add(y, lx + len(disp), "\u2588", HIGHLIGHT)
        y += 2

        if self.search_fetching:
            self.add(y, 0, "  Searching\u2026", MUTED)
            return
        if not self.search_query.strip():
            self.add(y, 0, "  Type a movie or series name to search the catalog.", MUTED)
            if self.home_rows:
                self.add(y + 1, 0, "  Press Esc to browse the home rows instead.", MUTED)
            return
        if not self.search_loaded:
            self.add(y, 0, "  \u2026", MUTED)
            return
        res = self.search_results
        if not res:
            self.add(y, 0, '  No results for "%s"' % self.search_query, MUTED)
            return
        per = self.result_visible()
        self.search_scroll = min(self.search_scroll, max(0, len(res) - per))
        for k in range(per):
            idx = self.search_scroll + k
            if idx >= len(res):
                break
            it = res[idx]
            sel = idx == self.search_cursor
            t = (it.get("title") or "")[:max(0, self.w - 34)]
            kind = "Series" if is_series(it) else "Movie"
            meta = "%s  %s%s" % (kind, it.get("year") or "?",
                                 "  \u2605%s" % it.get("rating") if it.get("rating")
                                 else "")
            mx = max(4 + len(t), self.w - 28)
            if mx + len(meta) >= self.w:
                mx = self.w - len(meta)
            line = " %s %s" % ("\u25b8" if sel else " ", t)
            self.add(y + k, 0, line, HIGHLIGHT if sel else MUTED, bold=sel)
            self.add(y + k, mx, meta, ACCENT if sel else MUTED)

    def _message(self):
        y = self.h // 2 - 2
        lines = self.msg.split("\n")
        width = max((len(l) for l in lines), default=20) + 4
        width = min(width, self.w - 2)
        x = max(0, (self.w - width) // 2)
        for i in range(len(lines) + 2):
            self.add(y + i, x, " " * width)
        for i, line in enumerate(lines):
            self.add(y + 1 + i, x + 2, line[:width - 4], ACCENT)
        self.add(y + len(lines) + 1, x, " " * width)
        self.add(y + 2, x, " " * width)

    # ---- low-level drawing ---------------------------------------------
    def add(self, y, x, s, fg=None, bg=None, bold=False, reverse=False, dim=False):
        if y < 0 or y >= self.h or x < 0 or x >= self.w:
            return
        if len(s) > self.w - x:
            s = s[:self.w - x]
        try:
            attr = 0
            if fg is not None or bg is not None:
                attr |= curses.color_pair(_pair_for(fg, bg))
            if bold:
                attr |= curses.A_BOLD
            if reverse:
                attr |= curses.A_REVERSE
            if dim:
                attr |= curses.A_DIM
            self.scr.addstr(y, x, s, attr)
        except curses.error:
            pass


card_cache = {}


def main(stdscr):
    global _COLOR_OK
    try:
        curses.start_color()
        _COLOR_OK = True
    except curses.error:
        _COLOR_OK = False
    t = TUI(stdscr)
    t.run()


if __name__ == "__main__":
    curses.wrapper(main)

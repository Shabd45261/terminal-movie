import io
import math
import urllib.request

_cache = {}

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False


# ---- blurhash -------------------------------------------------------------
_B83 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz#$%*+,-.:;=?@[]^_{|}~"


def _b83_val(c):
    return _B83.index(c)


def _b83(s, frm, to):
    v = 0
    for i in range(frm, to):
        v = v * 83 + _b83_val(s[i])
    return v


def _signpow(v, e):
    return math.copysign(math.pow(abs(v), e), v) if v != 0 else 0.0


def _decode(blurhash):
    s = blurhash.strip()
    if not s or len(s) < 6:
        return None
    try:
        n = _b83(s, 0, 1)
        nby = n // 9 + 1
        nbx = n % 9 + 1
        qmax = _b83(s, 1, 2) + 1
        colors = []
        dc = _b83(s, 2, 5)
        colors.append([
            _signpow((dc >> 16) * qmax / 255.0, 2.2),
            _signpow(((dc >> 8) & 255) * qmax / 255.0, 2.2),
            _signpow((dc & 255) * qmax / 255.0, 2.2),
        ])
        i = 5
        for y in range(nby):
            for x in range(nbx):
                if x == 0 and y == 0:
                    continue
                v = _b83(s, i, i + 2)
                i += 2
                colors.append([
                    _signpow(((v >> 16) - 9) / 9.0, 2) * qmax,
                    _signpow((((v >> 8) & 0xff) - 9) / 9.0, 2) * qmax,
                    _signpow(((v & 0xff) - 9) / 9.0, 2) * qmax,
                ])
        return nby, nbx, colors
    except Exception:
        return None


def _render_pixels(blurhash, w, h):
    """Render w x h RGB pixels (list of rows) from a blurhash."""
    parsed = _decode(blurhash)
    if not parsed:
        return None
    nby, nbx, colors = parsed
    out = []
    for y in range(h):
        row = []
        for x in range(w):
            r = g = b = 0.0
            ci = 0
            for jy in range(nby):
                for ix in range(nbx):
                    basis = math.cos(math.pi * ix * x / w) * \
                        math.cos(math.pi * jy * y / h)
                    c = colors[ci]
                    ci += 1
                    r += c[0] * basis
                    g += c[1] * basis
                    b += c[2] * basis
            row.append((_srgb(r), _srgb(g), _srgb(b)))
        out.append(row)
    return out


def _srgb(v):
    v = max(0.0, min(1.0, v))
    if v <= 0.0031308:
        return int(round(v * 12.92 * 255))
    return int(round((1.055 * math.pow(v, 1 / 2.4) - 0.055) * 255))


# ---- image fetching ---------------------------------------------------------
def _load(url, timeout=15):
    if url not in _cache:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            _cache[url] = urllib.request.urlopen(req, timeout=timeout).read()
        except Exception:
            _cache[url] = None
    return _cache[url]


def _resize_pixels(data, w, h):
    img = Image.open(io.BytesIO(data)).convert("RGB")
    ratio = img.height / img.width
    tw = w
    th = int(w * ratio)
    img = img.resize((tw, th), Image.LANCZOS)
    if th > h:
        img = img.crop((0, (th - h) // 3, tw, (th - h) // 3 + h))
    px = img.load()
    return [[px[x, y] for x in range(img.width)] for y in range(min(img.height, h))]


# ---- dominant color (for curses-safe card art) -------------------------------
def dominant_color(url, blurhash=None, samples=6):
    """Average RGB of the poster, rendered with the same Pillow/blurhash
    pipeline but returned as plain pixels (no ANSI codes)."""
    key = ("dom", url, blurhash, samples)
    if key in _cache:
        return _cache[key]
    px = None
    if _HAS_PIL and url:
        data = _load(url)
        if data:
            try:
                img = Image.open(io.BytesIO(data)).convert("RGB")
                img = img.resize((samples, samples), Image.LANCZOS)
                px = list(img.getdata())
            except Exception:
                px = None
    if px is None and blurhash:
        r = _render_pixels(blurhash, samples, samples)
        if r:
            px = [p for row in r for p in row]
    if not px:
        px = [(62, 68, 88)]
    n = len(px)
    r = sum(p[0] for p in px) // n
    g = sum(p[1] for p in px) // n
    b = sum(p[2] for p in px) // n
    _cache[key] = (r, g, b)
    return _cache[key]


# ---- rendering ---------------------------------------------------------------
def poster_lines(url, cols, rows, blurhash=None):
    """rows x cols grid of half-block true-color art. Uses JPEG via Pillow when
    available, otherwise falls back to a blurhash approximation."""
    key = (url, blurhash, cols, rows)
    if key in _cache:
        return _cache[key]

    px = None
    if _HAS_PIL and url:
        data = _load(url)
        if data:
            try:
                px = _resize_pixels(data, cols * 2, rows * 2)
            except Exception:
                px = None
    if px is None and blurhash:
        px = _render_pixels(blurhash, cols * 2, rows * 2)
    if px is None:
        px = [[(62, 68, 88)] * (cols * 2) for _ in range(rows * 2)]

    lines = []
    for y in range(0, rows * 2, 2):
        sb = []
        for x in range(cols * 2):
            r1, g1, b1 = px[y][x] if y < len(px) else (20, 22, 30)
            r2, g2, b2 = px[y + 1][x] if y + 1 < len(px) else (20, 22, 30)
            sb.append("\x1b[38;2;%d;%d;%dm\x1b[48;2;%d;%d;%dm\u2580"
                      % (r1, g1, b1, r2, g2, b2))
        lines.append("".join(sb) + "\x1b[0m")
    _cache[key] = lines
    return lines

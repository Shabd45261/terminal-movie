import os
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from flask import Flask, Response, jsonify, request, send_from_directory

from .moviebox import HOME_ROWS, PLAY_BASE, USER_AGENT, MovieBox
from .vlc import launch_stream, open_play_store, vlc_installed
from .history import HistoryManager

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
mb = MovieBox()
hm = HistoryManager()

app = Flask(__name__)

CDN_HOSTS = ("hakunaymatata.com",)


def _proxied_url(url):
    port = int(os.environ.get("PORT", "8080"))
    q = urllib.parse.quote(url, safe="")
    return "http://127.0.0.1:%d/stream?url=%s&referer=%s" % (
        port, q, urllib.parse.quote(PLAY_BASE + "/", safe=""))


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/stream")
def stream():
    url = request.args.get("url") or ""
    referer = request.args.get("referer") or (PLAY_BASE + "/")
    try:
        host = urllib.parse.urlparse(url).hostname or ""
    except ValueError:
        return "bad url", 400
    if not host.endswith(CDN_HOSTS):
        return "forbidden", 403

    headers = {"User-Agent": USER_AGENT, "Referer": referer}
    rng = request.headers.get("Range")
    if rng:
        headers["Range"] = rng
    try:
        upstream = urllib.request.urlopen(
            urllib.request.Request(url, headers=headers), timeout=30)
    except Exception:
        return "upstream error", 502

    def generate():
        try:
            while True:
                chunk = upstream.read(64 * 1024)
                if not chunk:
                    break
                yield chunk
        finally:
            upstream.close()

    resp = Response(generate(), status=upstream.status)
    for h in ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges"):
        v = upstream.headers.get(h)
        if v:
            resp.headers[h] = v
    return resp


def _fetch_row(row_id, title):
    try:
        items = mb.home(row_id)
        return {"id": row_id, "title": title, "items": items} if items else None
    except Exception:
        return None


@app.route("/api/home")
def api_home():
    history = hm.get_history()
    rows = []

    # Add history rows if they have content
    if history["movies"]:
        rows.append({"id": "history_movies", "title": "Recent Movies", "items": history["movies"]})
    if history["series"]:
        rows.append({"id": "history_series", "title": "Recent Series", "items": history["series"]})

    with ThreadPoolExecutor(max_workers=len(HOME_ROWS)) as pool:
        results = list(pool.map(partial(_fetch_row), *zip(*HOME_ROWS)))

    rows.extend([r for r in results if r])
    return jsonify({"rows": rows})


@app.route("/api/progress", methods=["POST"])
def api_progress():
    data = request.json
    if not data or "item" not in data or "time" not in data:
        return "missing data", 400

    hm.save_progress(
        data["item"],
        data["time"],
        data.get("se", 0),
        data.get("ep", 0)
    )
    return "ok"


@app.route("/api/suggest")
def api_suggest():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify([])
    try:
        return jsonify(mb.suggestions(q))
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/search")
def api_search():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify([])
    try:
        return jsonify(mb.search(q))
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/detail")
def api_detail():
    slug = (request.args.get("slug") or "").strip()
    if not slug:
        return jsonify({"error": "missing slug"}), 400
    try:
        return jsonify(mb.detail(slug))
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/play")
def api_play():
    slug = (request.args.get("slug") or "").strip()
    sid = (request.args.get("id") or "").strip()
    se = request.args.get("se", type=int)
    ep = request.args.get("ep", type=int)
    if not slug or not sid:
        return jsonify({"error": "missing slug or id"}), 400
    try:
        streams, captions = mb.streams(slug, sid, se, ep)
        if not streams:
            return jsonify({"error": "No playable stream found"}), 404
        best = max(streams, key=lambda s: _quality(s.get("quality")))
        play_url = _proxied_url(best["url"])
        result = launch_stream(play_url, best.get("quality"))
        result["streams"] = streams
        result["captions"] = captions
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/player")
def player():
    return send_from_directory(STATIC_DIR, "player.html")


@app.route("/api/streams")
def api_streams():
    slug = (request.args.get("slug") or "").strip()
    sid = (request.args.get("id") or "").strip()
    se = request.args.get("se", type=int)
    ep = request.args.get("ep", type=int)
    if not slug or not sid:
        return jsonify({"error": "missing slug or id"}), 400
    try:
        streams, captions = mb.streams(slug, sid, se, ep)
        out = []
        for s in streams:
            bitrate = 0
            if s.get("size") and s.get("duration"):
                bitrate = int(int(s["size"]) * 8 / max(int(s["duration"]), 1))
            out.append({
                "quality": s.get("quality"),
                "format": s.get("format"),
                "size": s.get("size"),
                "duration": s.get("duration"),
                "bitrate": bitrate,
                "url": _proxied_url(s["url"]),
            })
        return jsonify({"streams": sorted(out, key=lambda x: int(x["quality"] or 0)),
                        "captions": captions})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/vlc")
def api_vlc():
    try:
        return jsonify({"installed": vlc_installed()})
    except Exception as e:
        return jsonify({"installed": None, "error": str(e)})


@app.route("/api/vlc/install")
def api_vlc_install():
    try:
        return jsonify(open_play_store())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


def _quality(q):
    if not q:
        return 0
    try:
        return int(q)
    except ValueError:
        return 0


def main():
    port = int(os.environ.get("PORT", "8080"))
    print("\n  Movie Streamer running ->  http://localhost:%d\n" % port)
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()

import hashlib
import json
import threading
import time
import urllib.request

# The MovieBox web frontend (moviebox.ph) proxies to this backend. We talk to
# the backend directly - moviebox.ph's own CloudFront edge is unreliable from
# some networks and can hang, while h5-api.aoneroom.com responds fine.
API_BASE = "https://h5-api.aoneroom.com"
H5_API = "https://h5-api.aoneroom.com"
PLAY_BASE = "https://fmoviesunblocked.net"

USER_AGENT = "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 Chrome/120 Mobile"

HOME_ROWS = [
    ("872031290915189720", "Trending Now"),
    ("997144265920760504", "Popular Movies"),
    ("5404290953194750296", "Trending Anime"),
    ("6528093688173053896", "Trending Indonesian Movies"),
    ("4380734070238626200", "K-Drama"),
    ("7736026911486755336", "Western TV"),
    ("8624142774394406504", "C-Drama"),
    ("1164329479448281992", "Thai Drama"),
    ("5848753831881965888", "Indonesian Horror"),
    ("7132534597631837112", "Animated Films"),
]

_UA = lambda s: s.encode() if isinstance(s, str) else s


def _client_token():
    secs = int(time.time())
    rev = str(secs)[::-1]
    digest = hashlib.md5(rev.encode()).hexdigest()
    return "%d,%s" % (secs, digest)


class MovieBox:
    def __init__(self, timeout=30):
        self.timeout = timeout
        self._token = None
        self._lock = threading.Lock()

    # -- low level -----------------------------------------------------
    def _request(self, path, base=API_BASE, method="GET", body=None,
                 headers=None, referer=None, use_auth=False):
        hdrs = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Client-Info": json.dumps({"timezone": "Asia/Jakarta"}),
            "X-Request-Lang": "en",
        }
        if headers:
            hdrs.update(headers)
        if referer:
            hdrs["Referer"] = referer
        if use_auth:
            with self._lock:
                token = self._token
            hdrs["Authorization"] = "Bearer %s" % token
        else:
            hdrs["X-Client-Token"] = _client_token()

        data = _UA(json.dumps(body)) if body is not None else None
        req = urllib.request.Request(base + path, data=data, headers=hdrs, method=method)
        resp = urllib.request.urlopen(req, timeout=self.timeout)
        xuser = resp.headers.get("x-user")
        if xuser:
            try:
                parsed = json.loads(xuser)
                if parsed.get("token"):
                    with self._lock:
                        self._token = parsed["token"]
            except ValueError:
                pass
        return json.loads(resp.read().decode())

    def _auth_request(self, path, **kw):
        try:
            return self._request(path, use_auth=True, **kw)
        except urllib.error.HTTPError as e:
            # token expired / invalid -> refresh once and retry
            if e.code == 400:
                with self._lock:
                    self._token = None
                return self._request(path, use_auth=True, **kw)
            raise

    # -- helpers --------------------------------------------------------
    @staticmethod
    def _item(item):
        cover = item.get("cover") or {}
        return {
            "id": item.get("subjectId"),
            "type": "series" if item.get("subjectType") == 2 else "movie",
            "title": item.get("title") or "",
            "year": (item.get("releaseDate") or "")[:4],
            "poster": cover.get("url"),
            "blurHash": cover.get("blurHash"),
            "rating": item.get("imdbRatingValue"),
            "detailPath": item.get("detailPath"),
            "country": item.get("countryName"),
        }

    # -- home ------------------------------------------------------------
    def home(self, row_id, page=1, per_page=12):
        path = "/wefeed-h5api-bff/ranking-list/content?id=%s&page=%d&perPage=%d" % (
            row_id, page, per_page)
        data = self._request(path).get("data") or {}
        return [self._item(i) for i in (data.get("subjectList") or [])]

    # -- search ------------------------------------------------------------
    def search(self, query, page=1, per_page=20):
        body = {"keyword": query, "page": str(page), "perPage": str(per_page),
                "subjectType": "0"}
        data = self._auth_request("/wefeed-h5api-bff/subject/search",
                                  method="POST", body=body).get("data") or {}
        return [self._item(i) for i in (data.get("items") or [])]

    def suggestions(self, query):
        body = {"keyword": query, "perPage": 8}
        data = self._request("/wefeed-h5api-bff/subject/search-suggest",
                             method="POST", body=body).get("data") or {}
        words = []
        for it in (data.get("items") or []):
            if it.get("subject"):
                words.append(self._item(it["subject"]))
            elif it.get("word"):
                words.append({"title": it["word"]})
        return words

    # -- detail ------------------------------------------------------------
    def detail(self, detail_path):
        data = self._request("/wefeed-h5api-bff/detail?detailPath=%s" % detail_path,
                             base=H5_API).get("data") or {}
        subject = data.get("subject") or {}
        d = self._item(subject)
        d["description"] = subject.get("description")
        d["genre"] = (subject.get("genre") or "").split(",")
        d["actors"] = [a.get("name") for a in (data.get("stars") or []) if a.get("name")]
        seasons = (data.get("resource") or {}).get("seasons") or []
        episodes = []
        for s in seasons:
            se = s.get("se")
            all_ep = (s.get("allEp") or "").strip()
            max_ep = s.get("maxEp") or 0
            if all_ep:
                nums = [int(x) for x in all_ep.split(",") if x.strip()]
            else:
                nums = list(range(1, max_ep + 1))
            for ep in nums:
                episodes.append({"season": se, "episode": ep, "name": "S%02dE%02d" % (se, ep)})
        d["seasons"] = seasons
        d["episodes"] = episodes
        return d

    # -- streams ------------------------------------------------------------
    def streams(self, detail_path, subject_id, season=0, episode=0):
        if season is None:
            season = 0
        if episode is None:
            episode = 0
        referer = "%s/spa/videoPlayPage/movies/%s?id=%s&type=/movie/detail&lang=en" % (
            PLAY_BASE, detail_path, subject_id)
        path = "/wefeed-h5-bff/web/subject/play?subjectId=%s&se=%d&ep=%d" % (
            subject_id, season, episode)
        data = self._request(path, base=PLAY_BASE, referer=referer).get("data") or {}
        result = []
        for s in (data.get("streams") or []):
            result.append({
                "url": s.get("url"),
                "quality": s.get("resolutions"),
                "format": s.get("format"),
                "size": s.get("size"),
                "duration": s.get("duration"),
            })
        captions = []
        if data.get("captions"):
            captions = [{"lang": c.get("lan"), "name": c.get("lanName"), "url": c.get("url")}
                        for c in data["captions"]]
        return result, captions

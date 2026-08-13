import shlex
import subprocess

VLC_PACKAGE = "org.videolan.vlc"
VLC_ACTIVITY = "org.videolan.vlc/.gui.video.VideoPlayerActivity"
PLAY_STORE_URL = "market://details?id=org.videolan.vlc"


def _run(cmd):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return out.returncode, out.stdout.strip() + out.stderr.strip()
    except Exception as e:
        return -1, str(e)


def _has_am():
    return _run(["am", "--help"])[0] == 0


def vlc_installed():
    code, out = _run(["pm", "list", "packages", VLC_PACKAGE])
    if code == 0:
        return VLC_PACKAGE in out
    # fallback: cmd package
    code, out = _run(["cmd", "package", "list", "packages", VLC_PACKAGE])
    return code == 0 and VLC_PACKAGE in out


def open_play_store():
    code, out = _run(["am", "start", "-a", "android.intent.action.VIEW", "-d", PLAY_STORE_URL])
    return {"ok": code == 0, "output": out}


def launch_stream(url, quality=None):
    if not _has_am():
        return {
            "ok": False,
            "reason": "no-am",
            "url": url,
            "message": "Android 'am' tool unavailable in this shell. Open the URL manually: %s" % url,
        }

    if not vlc_installed():
        store = open_play_store()
        return {
            "ok": False,
            "reason": "vlc-missing",
            "url": url,
            "play_store_opened": store["ok"],
            "message": "VLC is not installed. Opening Play Store to download it...",
        }

    quoted = shlex.quote(url)
    attempts = [
        ["am", "start", "-a", "android.intent.action.VIEW",
         "-d", quoted, "-t", "video/*", "-n", VLC_ACTIVITY],
        ["am", "start", "-a", "android.intent.action.VIEW",
         "-d", quoted, "-t", "video/*"],
        ["am", "start", "-a", "android.intent.action.VIEW", "-d", quoted],
    ]
    last = ("", "")
    for attempt in attempts:
        code, out = _run(attempt)
        last = (out, str(code))
        if code == 0 and "Error" not in out and "error" not in out:
            return {"ok": True, "url": url, "quality": quality, "output": out}
    return {"ok": False, "reason": "am-failed", "url": url, "output": last[0]}

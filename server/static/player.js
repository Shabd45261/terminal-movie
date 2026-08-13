const video = document.getElementById("video");
const status = document.getElementById("status");
const qBox = document.getElementById("quality");
const errBox = document.getElementById("err");

const params = new URLSearchParams(location.search);
const slug = params.get("slug") || "";
const id = params.get("id") || "";
const se = params.get("se") || "0";
const ep = params.get("ep") || "0";
const startTime = parseFloat(params.get("time")) || 0;

let streams = [];          // [{quality, bitrate, url}]
let mode = "auto";         // 'auto' | fixed quality number
let current = null;        // current stream object
let probeTimer = null;
let lastProbe = 0;
let measuredBps = 0;

// ---- fetch streams -------------------------------------------------
async function init() {
  try {
    const r = await fetch(`/api/streams?slug=${encodeURIComponent(slug)}&id=${encodeURIComponent(id)}&se=${se}&ep=${ep}`);
    const j = await r.json();
    if (j.error) throw new Error(j.error);
    streams = (j.streams || []).filter((s) => s.url);
    if (!streams.length) throw new Error("No streams available");
    buildQualityMenu();
    await setQuality("auto", true);
    startProbe();
    startProgressTracking();
  } catch (e) {
    errBox.textContent = "Playback error: " + e.message;
    errBox.classList.remove("hidden");
    video.classList.add("hidden");
  }
}

// ---- quality menu ----------------------------------------------------
function buildQualityMenu() {
  qBox.innerHTML = "";
  const add = (label, value, active) => {
    const b = document.createElement("button");
    b.textContent = label;
    if (active) b.classList.add("active");
    b.addEventListener("click", () => setQuality(value));
    qBox.appendChild(b);
  };
  add("Auto", "auto", mode === "auto");
  streams.forEach((s) => add(s.quality + "p", s.quality, String(mode) === String(s.quality)));
}

function showStatus(msg, good = true) {
  status.innerHTML = msg;
  if (good) status.querySelector("b").style.color = "#7ee787";
}

function estSpeedStr(bps) {
  if (!bps) return "";
  if (bps >= 1e6) return (bps / 1e6).toFixed(1) + " Mbps";
  return Math.round(bps / 1e3) + " kbps";
}

// ---- quality switching -------------------------------------------------
async function setQuality(q, first = false) {
  const prevMode = mode;
  mode = q;
  buildQualityMenu();
  const target = q === "auto" ? pickForAuto() : streams.find((s) => String(s.quality) === String(q));
  if (!target) return;

  if (current && current.url === target.url) {
    if (prevMode === "auto" && q !== "auto") { stopProbe(); }
    if (q === "auto") startProbe();
    return;
  }
  const t = first ? startTime : video.currentTime;
  const playing = !video.paused;
  current = target;
  video.src = target.url;
  try { await video.play(); } catch (e) { /* autoplay may be blocked; user clicks */ }
  if (t > 0) {
    const wait = () => {
      if (video.readyState >= 1) { video.currentTime = t; if (playing) video.play(); }
      else setTimeout(wait, 200);
    };
    wait();
  }
  updateStatus();
  if (q === "auto") startProbe();
  else stopProbe();
}

// ---- progress reporting --------------------------------------------------
let lastSavedTime = 0;
function startProgressTracking() {
    setInterval(() => {
        if (!video.paused && Math.abs(video.currentTime - lastSavedTime) > 10) {
            saveProgress();
        }
    }, 10000);
}

async function saveProgress() {
    if (!slug || !id) return;
    lastSavedTime = video.currentTime;
    try {
        await fetch("/api/progress", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                item: { id, detailPath: slug, title: document.title, type: se !== "0" || ep !== "0" ? "series" : "movie" },
                time: video.currentTime,
                se: parseInt(se),
                ep: parseInt(ep)
            })
        });
    } catch (e) {}
}

window.addEventListener("beforeunload", saveProgress);

function pickForAuto() {
  if (!measuredBps) {
    return streams[streams.length - 1]; // start highest, adapt down
  }
  const budget = measuredBps * 0.7;
  let chosen = streams[0];
  for (const s of streams) {
    if (s.bitrate <= budget) chosen = s;
    else break;
  }
  return chosen;
}

function updateStatus() {
  const auto = mode === "auto";
  showStatus(
    `streaming <b>${current.quality}p</b>${auto ? " (auto)" : ""}` +
    (measuredBps ? ` · net ${estSpeedStr(measuredBps)}` : "") +
    ` · buffer ${Math.round(video.buffered.length ? video.buffered.end(video.buffered.length - 1) - video.currentTime : 0)}s`
  );
}

// ---- adaptive probing ----------------------------------------------------
function startProbe() {
  if (probeTimer) return;
  probe();
  probeTimer = setInterval(probe, 8000);
}
function stopProbe() {
  clearInterval(probeTimer);
  probeTimer = null;
}

async function probe() {
  if (mode !== "auto") return;
  const now = Date.now();
  if (now - lastProbe < 4000) return;
  const stream = current || streams[streams.length - 1];
  if (!stream) return;
  lastProbe = now;
  const CHUNK = 2 * 1024 * 1024; // 2 MB
  try {
    const resp = await fetch(stream.url, { headers: { Range: "bytes=0-" + (CHUNK - 1) } });
    if (!resp.ok && resp.status !== 206) return;
    const start = now;
    const reader = resp.body.getReader();
    let got = 0;
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      got += value.length;
      if (got >= CHUNK) { reader.cancel(); break; }
    }
    const bps = (got * 8) / ((Date.now() - start) / 1000);
    if (bps > 0) measuredBps = Math.round(bps);
    const target = pickForAuto();
    if (target && current && target.url !== current.url) {
      await setQuality("auto");
    }
    updateStatus();
  } catch (e) { /* probe failed; keep current */ }
}

video.addEventListener("error", () => {
  errBox.textContent = "Stream error: " + (video.error ? video.error.message : "unknown");
  errBox.classList.remove("hidden");
});

init();

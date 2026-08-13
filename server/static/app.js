const $ = (id) => document.getElementById(id);

let current = null; // {slug, id, type, episodes}

async function getJSON(url) {
  const r = await fetch(url);
  const j = await r.json();
  if (j && j.error) throw new Error(j.error);
  return j;
}

function toast(msg, ms = 2600) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.add("hidden"), ms);
}

function banner(msg, isError = false) {
  const b = $("banner");
  b.textContent = msg;
  b.className = "banner" + (isError ? " error" : "");
}

function card(item) {
  const el = document.createElement("div");
  el.className = "card";
  el.dataset.slug = item.detailPath || "";
  el.dataset.id = item.id || "";
  el.dataset.title = item.title || "";
  el.innerHTML = `
    <div style="position:relative">
      <img loading="lazy" src="${item.poster || ''}" alt="" onerror="this.src='data:image/svg+xml;charset=utf-8,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 width=%22122%22 height=%22172%22%3E%3Crect width=%22100%25%22 height=%22100%25%22 fill=%22%2310141f%22/%3E%3C/svg%3E'">
      ${item.type === "series" ? '<span class="c-badge">SERIES</span>' : ""}
    </div>
    <div class="c-meta">
      <div class="t">${escapeHtml(item.title)}</div>
      <div class="y">${item.year || ""}${item.rating ? " · " + item.rating : ""}</div>
    </div>`;
  el.addEventListener("click", () => openDetail(item));
  return el;
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s || "";
  return d.innerHTML;
}

function renderRow(row) {
  const sec = document.createElement("section");
  sec.className = "row";
  const h = document.createElement("h2");
  h.textContent = row.title;
  const sc = document.createElement("div");
  sc.className = "scroll";
  row.items.forEach((it) => sc.appendChild(card(it)));
  sec.appendChild(h);
  sec.appendChild(sc);
  $("home").appendChild(sec);
}

async function loadHome() {
  $("home").innerHTML = '<div class="spin"></div>';
  try {
    const data = await getJSON("/api/home");
    $("home").innerHTML = "";
    if (!data.rows || !data.rows.length) {
      banner("Could not load movies. Check your internet connection.");
      return;
    }
    data.rows.forEach(renderRow);
  } catch (e) {
    $("home").innerHTML = "";
    banner("Failed to load: " + e.message, true);
  }
}

// ---- search ----
let debounceTimer = null;
function onSearchInput() {
  clearTimeout(debounceTimer);
  const q = $("search").value.trim();
  const sug = $("suggest");
  if (!q) { sug.classList.add("hidden"); return; }
  debounceTimer = setTimeout(async () => {
    try {
      const items = await getJSON("/api/suggest?q=" + encodeURIComponent(q));
      if (!$("search").value.trim()) return;
      if (!items.length) { sug.classList.add("hidden"); return; }
      sug.innerHTML = "";
      items.forEach((it) => {
        const d = document.createElement("div");
        d.className = "s-item";
        d.innerHTML = `${it.poster ? `<img src="${it.poster}" onerror="this.style.display='none'">` : ""}<span>${escapeHtml(it.title)}</span>`;
        d.addEventListener("click", () => {
          $("search").value = it.title || it.word;
          sug.classList.add("hidden");
          if (it.detailPath) openDetail(it);
          else doSearch(it.title || it.word);
        });
        sug.appendChild(d);
      });
      sug.classList.remove("hidden");
    } catch (e) { /* ignore suggest errors */ }
  }, 250);
}

function closeSuggest(e) {
  if (!e.target.closest(".search-wrap")) $("suggest").classList.add("hidden");
}

async function doSearch(q) {
  $("suggest").classList.add("hidden");
  const grid = $("results-grid");
  const title = $("results-title");
  grid.innerHTML = '<div class="spin"></div>';
  $("home").classList.add("hidden");
  $("results").classList.remove("hidden");
  title.textContent = `Results for "${q}"`;
  try {
    const items = await getJSON("/api/search?q=" + encodeURIComponent(q));
    grid.innerHTML = "";
    if (!items.length) {
      grid.innerHTML = '<p style="color:var(--muted);padding:20px">No results found.</p>';
      return;
    }
    items.forEach((it) => grid.appendChild(card(it)));
  } catch (e) {
    grid.innerHTML = `<p style="color:#e06666;padding:20px">${escapeHtml(e.message)}</p>`;
  }
}

// ---- detail ----
async function openDetail(item) {
  if (!item.detailPath) return;
  const modal = $("modal");
  $("modal-body").innerHTML = '<div class="spin"></div>';
  modal.classList.remove("hidden");
  try {
    const d = await getJSON("/api/detail?slug=" + encodeURIComponent(item.detailPath));
    current = d;
    renderDetail(d);
  } catch (e) {
    $("modal-body").innerHTML = `<p style="color:#e06666">${escapeHtml(e.message)}</p>`;
  }
}

function renderDetail(d) {
  const isSeries = d.episodes && d.episodes.length > 0;
  const tags = (d.genre || []).filter(Boolean).slice(0, 6).map((t) => `<span>${escapeHtml(t)}</span>`).join("");
  let eps = "";
  if (isSeries) {
    eps = `<div class="eps"><h4>Episodes</h4><div class="eps-grid">` +
      d.episodes.map((e, i) => `<div class="ep" data-i="${i}">${e.name}</div>`).join("") +
      `</div></div>`;
  }
  $("modal-body").innerHTML = `
    <div class="d-head">
      <img src="${d.poster || ''}" onerror="this.style.display='none'">
      <div>
        <h3>${escapeHtml(d.title)}</h3>
        <div class="sub">${d.year || ""}${d.country ? " · " + escapeHtml(d.country) : ""}</div>
        ${d.rating ? `<div class="rating">★ ${d.rating}</div>` : ""}
        <div class="d-tags">${tags}</div>
      </div>
    </div>
    ${d.description ? `<p>${escapeHtml(d.description)}</p>` : ""}
    ${isSeries ? eps : `<button class="play-btn" id="play-main">▶ Play</button>`}`;

  $("modal-body").querySelectorAll(".ep").forEach((el) => {
    el.addEventListener("click", () => play(d, d.episodes[el.dataset.i]));
  });
  const pb = $("play-main");
  if (pb) pb.addEventListener("click", () => play(d, null));
}

async function play(d, episode) {
  const se = episode ? episode.season : null;
  const ep = episode ? episode.episode : null;
  const url = `/player?slug=${encodeURIComponent(d.detailPath)}&id=${d.id}&se=${se || 0}&ep=${ep || 0}`;
  window.open(url, "_blank");
  toast(episode ? `Opening ${episode.name} in player...` : "Opening player...");
}

// ---- init ----
$("search").addEventListener("input", onSearchInput);
$("search").addEventListener("keydown", (e) => {
  if (e.key === "Enter") doSearch($("search").value.trim());
});
document.addEventListener("click", closeSuggest);
$("modal-close").addEventListener("click", () => $("modal").classList.add("hidden"));
$("modal").addEventListener("click", (e) => {
  if (e.target === $("modal")) $("modal").classList.add("hidden");
});

loadHome();

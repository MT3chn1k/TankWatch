"use strict";
// TankWatch admin page. Everything shown comes from /api/overview; join codes only from /api/join, when asked.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
let data = null, watching = null;
// Build API URLs from the origin: a page opened as http://admin:pass@hub:8088/ would otherwise make fetch() refuse them
const api = (p) => new URL(p, location.origin).href;

function toast(msg) { const t = $("toast"); t.textContent = msg; t.style.display = "block";
  clearTimeout(toast.t); toast.t = setTimeout(() => (t.style.display = "none"), 3500); }
function ago(t) { const s = Math.max(0, Date.now() / 1000 - t); return s < 120 ? Math.round(s) + " s ago" : s < 7200 ? Math.round(s / 60) + " min ago" : s < 172800 ? Math.round(s / 3600) + " h ago" : Math.round(s / 86400) + " days ago"; }
function bar(label, v) { const p = v == null ? 0 : Math.min(100, Math.max(0, v)); const c = p >= 90 ? "high" : p >= 75 ? "mid" : "";
  return `<div class="bar"><span>${label}</span><span class="track"><span class="fill ${c}" data-w="${p}"></span></span><span class="v">${v == null ? "--" : Math.round(v) + "%"}</span></div>`; }
const f1 = (v, unit) => (v == null ? "--" : v.toFixed(1) + unit);

// Copying: the page is plain HTTP on your network, where browsers often don't offer the clipboard API,
// so fall back to selecting the text and the older copy command.
function copy(el) {
  const text = el.textContent;
  const sel = window.getSelection(), range = document.createRange();
  range.selectNodeContents(el); sel.removeAllRanges(); sel.addRange(range);
  if (navigator.clipboard && window.isSecureContext) { navigator.clipboard.writeText(text).then(() => toast("Copied")); return; }
  try { document.execCommand("copy") ? toast("Copied") : toast("Selected: press Ctrl+C to copy"); } catch (e) { toast("Selected: press Ctrl+C to copy"); }
}
document.addEventListener("click", (e) => { const c = e.target.closest("pre.cmd"); if (c && !c.hidden) copy(c); });

function renderCollectors() {
  const joined = watching ? watching.joined : [];
  $("collector-grid").innerHTML = data.collectors.map((n) => {
    const h = n.health, flags = [];
    if (h.undervolt_occurred) flags.push("undervolted since boot");
    if (h.throttled_occurred) flags.push("throttled since boot");
    const where = [...new Set(data.sources.filter((s) => s.node === n.node).map((s) => s.location || "(no location)"))];
    return `<div class="card ${n.status}${joined.includes(n.node) ? " joined" : ""}">
      <div class="row"><span><span class="name">${esc(n.node)}</span> ${n.new ? '<span class="pill new">new</span>' : ""}</span>
        <span class="name">${h.temp_f == null ? "--" : Math.round(h.temp_f) + "°F"}</span></div>
      <div class="why small ${n.status}">${esc(n.why || (n.status === "up" ? "reporting" : ""))}</div>
      <div class="bars">${bar("Mem", h.mem_used_pct)}${bar("Disk", h.disk_used_pct)}</div>
      <div class="small muted">${esc(["last report " + ago(n.seen), h.load1 != null ? "load " + h.load1 : "", h.ext5v_v ? h.ext5v_v.toFixed(2) + " V" : ""].filter(Boolean).join(" · "))}</div>
      ${flags.length ? `<div class="small why warn">${esc(flags.join(" · "))}</div>` : ""}
      <div class="small muted">${where.length ? "reports " + esc(where.join(", ")) : "health only, no sensors yet"}</div></div>`;
  }).join("") || '<p class="muted">No collector has reported yet. Add one below.</p>';
  // widths set here, not in style="": the page's Content-Security-Policy blocks inline styles
  document.querySelectorAll("[data-w]").forEach((el) => (el.style.width = el.dataset.w + "%"));
}

function latest(s) {
  const f = s.fields, out = [];
  if (f.temp_f != null) out.push(f1(f.temp_f, "°F"));
  if (f.humidity != null) out.push(Math.round(f.humidity) + "% RH");
  for (const [k, v] of Object.entries(f)) if (/_pct$/.test(k) && v != null) out.push(k.replace(/_pct$/, "") + " " + Math.round(v) + "%");
  for (const [k, v] of Object.entries(f)) if (!/^(temp_[cf]|humidity)$/.test(k) && !/_pct$/.test(k)) out.push(k + " " + v);
  return out.join(" · ");
}

function renderSources() {
  $("source-rows").innerHTML = data.sources.map((s) => {
    const stale = Date.now() / 1000 - s.t > 900;
    const sensor = [s.sensor, s.probe_name || s.probe].filter(Boolean).join(" ");
    return `<tr><td><b>${esc(s.location || "(no location)")}</b></td><td>${esc(s.measurement)}</td><td>${esc(s.node)}</td>
      <td class="small">${esc(sensor)}</td><td class="${stale ? "stale" : ""}">${esc(latest(s))}</td><td class="small ${stale ? "stale" : ""}">${ago(s.t)}</td></tr>`;
  }).join("") || '<tr><td colspan="6" class="muted">No readings in the last 7 days.</td></tr>';
}

function renderHub() {
  $("hub-name").textContent = "hub " + (data.hub.name || data.hub.id || "?");
  $("services").innerHTML = Object.entries(data.services).map(([k, ok]) => `<span class="${ok ? "ok" : "bad"}">${esc(k)}: ${ok ? "answering" : "not answering"}</span>`).join("");
  const host = location.hostname;
  $("links").innerHTML = [["Dashboards (Grafana)", data.hub.ports.grafana], ["InfluxDB", data.hub.ports.influx]]
    .map(([n, p]) => `<a href="http://${esc(host)}:${+p}/" target="_blank" rel="noopener">${n}</a>`).join("") +
    '<a href="https://github.com/MT3chn1k/TankWatch/blob/main/docs/operating-the-hub.md" target="_blank" rel="noopener">Backups, upgrades, troubleshooting</a>';
  const err = $("error"); err.hidden = !data.error; err.textContent = data.error || "";
}

// ---- status sign config, built here in the browser
let signRows = null;
function renderSignForm() {
  const f = $("sign-form");
  if (!signRows) {   // first time: offer every collector, the first four ticked
    signRows = data.collectors.map((n, i) => ({ on: i < 4, name: n.node, label: (n.node.match(/\d+/) ? "N" + n.node.match(/\d+/)[0] : n.node).slice(0, 3).toUpperCase(), address: "", kind: "fish" }));
    $("sign-nodes").innerHTML = signRows.map((r, i) => `<div class="signrow" data-i="${i}">
      <input type="checkbox" ${r.on ? "checked" : ""} aria-label="show ${esc(r.name)}"><span class="name small">${esc(r.name)}</span>
      <input class="lbl" maxlength="3" value="${esc(r.label)}" aria-label="label">
      <input class="opt addr" placeholder="address (optional)" aria-label="address">
      <select class="opt kind" aria-label="icon"><option value="fish">fish</option><option value="hub">hub (heart)</option></select></div>`).join("")
      || '<span class="muted small">No collectors yet.</span>';
    const locs = (m) => [...new Set(data.sources.filter((s) => s.measurement === m).map((s) => s.location).filter(Boolean))];
    f.air.innerHTML = '<option value="">(none)</option>' + locs("air").map((l) => `<option>${esc(l)}</option>`).join("");
    f.water.innerHTML = '<option value="">(none)</option>' + locs("water").map((l) => `<option>${esc(l)}</option>`).join("");
    f.air.selectedIndex = Math.min(1, f.air.options.length - 1); f.water.selectedIndex = Math.min(1, f.water.options.length - 1);
  }
  buildSign();
}
function signConfig() {
  const f = $("sign-form"), n = (k) => Number(f[k].value);
  document.querySelectorAll(".signrow").forEach((el) => {
    const r = signRows[+el.dataset.i];
    r.on = el.querySelector("input[type=checkbox]").checked; r.label = el.querySelector(".lbl").value.trim().toUpperCase();
    r.address = el.querySelector(".addr").value.trim(); r.kind = el.querySelector(".kind").value;
  });
  const nodes = signRows.filter((r) => r.on).slice(0, 4).map((r) => {
    const o = { name: r.name, label: r.label || r.name.slice(0, 3).toUpperCase() };
    if (r.address) o.address = r.address;
    if (r.kind === "hub") { o.hub = true; o.icon = "heart"; } else o.icon = "fish";
    return o;
  });
  return { hub_url: `http://${location.hostname}:${data.hub.ports.influx}`, org: data.hub.org, bucket: data.hub.bucket,
    wifi_country: (f.country.value || "US").toUpperCase(), nodes, air_location: f.air.value, water_location: f.water.value,
    air_range_f: [n("alo"), n("ahi")], water_range_f: [n("wlo"), n("whi")], hot_cpu_c: n("hot") };
}
function buildSign() { $("sign-json").textContent = JSON.stringify(signConfig(), null, 2) + "\n"; }
$("sign-form").addEventListener("input", buildSign);
$("sign-form").addEventListener("change", buildSign);
$("sign-download").onclick = () => {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(signConfig(), null, 2) + "\n"], { type: "application/json" }));
  a.download = "config.json"; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
};

// ---- join codes (fetched only when you ask to see one)
async function showCode(role, btn, pre) {
  if (!pre.hidden) { pre.hidden = true; btn.textContent = btn.dataset.label; return; }
  try {
    const j = await (await fetch(api("/api/join"), { cache: "no-store" })).json();
    pre.textContent = j[role]; pre.hidden = false;
    btn.dataset.label = btn.dataset.label || btn.textContent; btn.textContent = "Hide the code";
    if (/^(this-host|localhost)$/.test(j.address)) toast("Open this page by the hub's network address so the code points at it");
  } catch (e) { toast("Couldn't get the join code"); }
}
$("show-collector").onclick = (e) => showCode("collector", e.target, $("collector-code"));
$("show-display").onclick = (e) => showCode("display", e.target, $("display-code"));

// ---- watching for a new collector
$("start-watch").onclick = () => {
  if (watching) return;
  watching = { known: new Set(data.collectors.map((n) => n.node)), until: Date.now() + 20 * 60 * 1000, joined: [] };
  $("start-watch").hidden = true;
  $("watch").textContent = "Watching for a new collector… (run ./setup.sh on the Pi now)";
  watching.timer = setInterval(async () => {
    await load();
    const fresh = data.collectors.filter((n) => !watching.known.has(n.node) && n.status !== "down").map((n) => n.node);
    if (fresh.length) {
      watching.joined.push(...fresh); fresh.forEach((n) => watching.known.add(n));
      $("watch").textContent = "✓ " + watching.joined.join(", ") + " joined and is reporting. It's marked above.";
      renderCollectors();
    } else if (Date.now() > watching.until) {
      clearInterval(watching.timer); watching = null; $("start-watch").hidden = false;
      $("watch").textContent = "Nothing new in 20 minutes. If the wizard finished, check the Pi with: docker logs tankwatch-node";
    }
  }, 5000);
};

async function load() {
  try {
    const r = await fetch(api("/api/overview"), { cache: "no-store" });
    if (!r.ok) throw new Error(r.status);
    data = await r.json();
  } catch (e) { const err = $("error"); err.hidden = false; err.textContent = "The admin page isn't answering. Is the hub running?"; return; }
  $("updated").textContent = "updated " + new Date(data.time * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", second: "2-digit" });
  renderHub(); renderCollectors(); renderSources(); renderSignForm();
}
$("refresh").onclick = load;
load();
setInterval(() => { if (!watching) load(); }, 30000);

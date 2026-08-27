const state = {
  overview: null,
  events: [],
  days: 14,
};

const $ = (id) => document.getElementById(id);

function fmtHours(value) {
  return Number(value || 0).toFixed(2).replace(/\.00$/, "");
}

function fmtSeconds(value) {
  const seconds = Number(value || 0);
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const minutes = seconds / 60;
  if (minutes < 60) return `${minutes.toFixed(1).replace(/\.0$/, "")}m`;
  return `${(minutes / 60).toFixed(1).replace(/\.0$/, "")}h`;
}

function fmtTime(value) {
  if (!value) return "none";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove("show"), 2800);
}

async function getJson(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.error || `Request failed: ${response.status}`);
  }
  return data;
}

function setStatus(overview) {
  const status = $("sensorStatus");
  const events = overview.totals.events_in_window;
  const age = overview.totals.last_age_seconds;
  const collector = overview.collector || {};
  const running = collector.installed && ["active", "running"].includes(collector.state);
  status.classList.toggle("ready", running && events > 0 && age !== null && age < 120);
  if (running && age !== null && age < 120) {
    status.textContent = "Collecting";
  } else if (running && events > 0) {
    status.textContent = `Running · last ${fmtSeconds(age)} ago`;
  } else if (running) {
    status.textContent = "Running · waiting";
  } else if (!events) {
    status.textContent = "Dashboard only";
  } else {
    status.textContent = `Paused · last ${fmtSeconds(age)} ago`;
  }
}

function renderMetrics(overview) {
  $("eventCount").textContent = overview.totals.events_in_window;
  $("hoursCount").textContent = fmtHours(overview.totals.hours);
  $("domainCount").textContent = overview.domains.length;
  setStatus(overview);
}

function renderInsights(items) {
  const root = $("insightsList");
  root.innerHTML = "";
  for (const item of items) {
    const node = document.createElement("article");
    node.className = `insight ${item.tone || ""}`;
    node.innerHTML = `<h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.body)}</p>`;
    root.appendChild(node);
  }
}

function renderDomains(domains) {
  const root = $("domainBars");
  root.innerHTML = "";
  if (!domains.length) {
    root.innerHTML = `<div class="empty">No domain signal yet. Take a sample or run the collector in the background.</div>`;
    return;
  }
  for (const item of domains) {
    const row = document.createElement("div");
    row.className = "domain-row";
    const pct = Math.round(item.share * 100);
    row.innerHTML = `
      <div>
        <div class="domain-name">${escapeHtml(item.domain)}</div>
        <div class="domain-meta">${item.events} events</div>
      </div>
      <div class="bar-track" aria-label="${escapeHtml(item.domain)} ${pct}%">
        <div class="bar-fill" style="width: ${Math.max(4, pct)}%"></div>
      </div>
      <div class="domain-meta">${pct}% · ${fmtHours(item.hours)}h</div>
    `;
    root.appendChild(row);
  }
}

function renderHeatmap(items) {
  const root = $("heatmap");
  root.innerHTML = "";
  for (const item of items) {
    const cell = document.createElement("div");
    cell.className = "heat-cell";
    const alpha = 0.08 + item.intensity * 0.82;
    cell.style.background = `rgba(0, 166, 166, ${alpha})`;
    cell.style.color = item.intensity > 0.55 ? "#ffffff" : "#455160";
    cell.title = `${item.label}: ${fmtSeconds(item.dwell_seconds)}`;
    cell.textContent = String(item.hour);
    root.appendChild(cell);
  }
}

function renderRankList(id, items) {
  const root = $(id);
  root.innerHTML = "";
  if (!items.length) {
    root.innerHTML = `<div class="empty">No ranked items yet.</div>`;
    return;
  }
  for (const item of items.slice(0, 6)) {
    const node = document.createElement("article");
    node.className = "rank-item";
    node.innerHTML = `
      <div class="rank-top">
        <div class="rank-name">${escapeHtml(item.name)}</div>
        <span class="chip">${escapeHtml(item.domain || "")}</span>
      </div>
      <div class="rank-meta">${fmtHours(item.hours)}h · ${item.visits} visits</div>
    `;
    root.appendChild(node);
  }
}

function renderTransitions(items) {
  const root = $("transitions");
  root.innerHTML = "";
  if (!items.length) {
    root.innerHTML = `<div class="empty">No domain switches have been observed in this window.</div>`;
    return;
  }
  for (const item of items) {
    const node = document.createElement("div");
    node.className = "transition-item";
    node.innerHTML = `
      <span>${escapeHtml(item.transition)}</span>
      <span class="chip transition-count">${item.count}</span>
    `;
    root.appendChild(node);
  }
}

function profileScores(profile) {
  if (!profile || profile.status !== "ready") return [0, 0, 0, 0, 0];
  const domainCount = Object.keys(profile.v_dom?.distribution || {}).length;
  const topShare = Math.max(0, ...Object.values(profile.v_dom?.distribution || {}));
  const revisit = profile.v_rhythm?.revisit_rate || 0;
  const owned = profile.v_resp?.likely_owned_domains?.length || 0;
  const divergence = profile.v_div?.kl_short_vs_long || 0;
  return [
    Math.min(1, topShare),
    Math.min(1, revisit * 3),
    Math.min(1, domainCount / 6),
    Math.min(1, owned / 4),
    Math.min(1, divergence * 2.5),
  ];
}

function renderSignature(profile) {
  const canvas = $("signatureCanvas");
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#eef2f7";
  ctx.fillRect(0, 0, width, height);

  const labels = ["Focus", "Revisit", "Diversity", "Ownership", "Divergence"];
  const scores = profileScores(profile);
  const cx = width / 2;
  const cy = height / 2 + 12;
  const radius = Math.min(width, height) * 0.34;
  const angleFor = (i) => -Math.PI / 2 + (i * Math.PI * 2) / labels.length;

  ctx.strokeStyle = "#d9e0ea";
  ctx.lineWidth = 1;
  for (let ring = 1; ring <= 4; ring += 1) {
    ctx.beginPath();
    for (let i = 0; i < labels.length; i += 1) {
      const a = angleFor(i);
      const r = radius * (ring / 4);
      const x = cx + Math.cos(a) * r;
      const y = cy + Math.sin(a) * r;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.stroke();
  }

  for (let i = 0; i < labels.length; i += 1) {
    const a = angleFor(i);
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.cos(a) * radius, cy + Math.sin(a) * radius);
    ctx.stroke();
    ctx.fillStyle = "#5f6b7a";
    ctx.font = "600 13px Inter, system-ui, sans-serif";
    ctx.textAlign = Math.cos(a) > 0.25 ? "left" : Math.cos(a) < -0.25 ? "right" : "center";
    ctx.textBaseline = Math.sin(a) > 0.25 ? "top" : Math.sin(a) < -0.25 ? "bottom" : "middle";
    ctx.fillText(labels[i], cx + Math.cos(a) * (radius + 28), cy + Math.sin(a) * (radius + 24));
  }

  const gradient = ctx.createLinearGradient(0, 0, width, height);
  gradient.addColorStop(0, "rgba(0, 166, 166, 0.44)");
  gradient.addColorStop(0.55, "rgba(109, 93, 252, 0.32)");
  gradient.addColorStop(1, "rgba(255, 122, 89, 0.26)");
  ctx.beginPath();
  for (let i = 0; i < scores.length; i += 1) {
    const a = angleFor(i);
    const r = radius * scores[i];
    const x = cx + Math.cos(a) * r;
    const y = cy + Math.sin(a) * r;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.closePath();
  ctx.fillStyle = gradient;
  ctx.fill();
  ctx.strokeStyle = "#00a6a6";
  ctx.lineWidth = 3;
  ctx.stroke();

  for (let i = 0; i < scores.length; i += 1) {
    const a = angleFor(i);
    const r = radius * scores[i];
    ctx.beginPath();
    ctx.arc(cx + Math.cos(a) * r, cy + Math.sin(a) * r, 5, 0, Math.PI * 2);
    ctx.fillStyle = i % 2 ? "#6d5dfc" : "#00a6a6";
    ctx.fill();
  }

  renderSignatureCards(profile);
}

function renderSignatureCards(profile) {
  const root = $("signatureCards");
  root.innerHTML = "";
  if (!profile || profile.status !== "ready") {
    root.innerHTML = `<div class="empty">No Digital Twin Signature yet.</div>`;
    return;
  }
  const cards = [
    ["v_dom", "Domain Attention", topPairs(profile.v_dom?.distribution)],
    ["v_rhythm", "Behavioral Rhythm", `median dwell ${fmtSeconds(profile.v_rhythm?.median_dwell_seconds)} · revisit ${Math.round((profile.v_rhythm?.revisit_rate || 0) * 100)}%`],
    ["v_base", "Baseline", topPairs(profile.v_base?.distribution)],
    ["v_resp", "Responsibility", (profile.v_resp?.likely_owned_domains || []).map((item) => item.domain).join(", ") || "not enough signal"],
    ["v_div", "Divergence", `KL ${profile.v_div?.kl_short_vs_long || 0}`],
  ];
  for (const [key, title, body] of cards) {
    const node = document.createElement("article");
    node.className = "signature-card";
    node.innerHTML = `<h3>${key} · ${title}</h3><p>${escapeHtml(body || "not enough signal")}</p>`;
    root.appendChild(node);
  }
}

function topPairs(obj = {}) {
  const entries = Object.entries(obj).sort((a, b) => b[1] - a[1]).slice(0, 3);
  if (!entries.length) return "not enough signal";
  return entries.map(([key, value]) => `${key} ${Math.round(value * 100)}%`).join(" · ");
}

function renderEvents(events) {
  const tbody = $("eventsBody");
  const filter = $("eventFilter").value.trim().toLowerCase();
  tbody.innerHTML = "";
  const filtered = events.filter((event) => {
    const text = `${event.app} ${event.artifact} ${event.domain} ${event.title}`.toLowerCase();
    return !filter || text.includes(filter);
  });
  if (!filtered.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="event-meta">No matching events.</td></tr>`;
    return;
  }
  for (const event of filtered) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${fmtTime(event.ts_start)}</td>
      <td>${escapeHtml(event.app)}</td>
      <td class="artifact-cell">${escapeHtml(event.artifact)}</td>
      <td><span class="chip">${escapeHtml(event.domain)}</span></td>
      <td>${fmtSeconds(event.dwell_seconds)}</td>
    `;
    tbody.appendChild(row);
  }
}

function renderPrivacy(privacy) {
  $("capturedList").innerHTML = privacy.captured.map((item) => `<div class="privacy-item">${escapeHtml(item)}</div>`).join("");
  $("notCapturedList").innerHTML = privacy.not_captured.map((item) => `<div class="privacy-item">${escapeHtml(item)}</div>`).join("");
  $("dataLocation").textContent = privacy.data_location;
  const findings = Object.entries(privacy.redaction_summary || {});
  const summary = findings.length
    ? findings.map(([key, value]) => `${key}: ${value}`).join(" · ")
    : "no sensitive text detected yet";
  $("privacyFlags").innerHTML = `
    <span class="flag ${privacy.capture_window_title ? "enabled" : ""}">window titles ${privacy.capture_window_title ? "on" : "off"}</span>
    <span class="flag ${privacy.redact_sensitive_titles ? "enabled" : ""}">sensitive redaction ${privacy.redact_sensitive_titles ? "on" : "off"}</span>
    <span class="flag ${privacy.mask_pii ? "enabled" : ""}">PII masking ${privacy.mask_pii ? "on" : "off"}</span>
    <span class="flag ${privacy.redact_url_paths ? "enabled" : ""}">URL paths ${privacy.redact_url_paths ? "masked" : "stored"}</span>
    <span class="flag enabled">redacted: ${escapeHtml(summary)}</span>
  `;
}

async function runEvidenceQuery(text) {
  const encoded = encodeURIComponent(text);
  const result = await getJson(`/api/query?q=${encoded}&days=${state.days}&top_k=8`);
  const root = $("evidenceResult");
  root.innerHTML = "";
  const filters = document.createElement("div");
  filters.className = "filter-row";
  filters.innerHTML = result.selected_filters
    .map(([name, weight]) => `<span class="chip">${escapeHtml(name)} · ${Math.round(weight * 100)}%</span>`)
    .join("");
  root.appendChild(filters);

  if (!result.results.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "No evidence matched. Collect more samples or broaden the query.";
    root.appendChild(empty);
    return;
  }

  for (const item of result.results) {
    const node = document.createElement("article");
    node.className = "evidence-card";
    const why = item.why.map((reason) => `<div>${escapeHtml(reason)}</div>`).join("");
    node.innerHTML = `
      <div class="evidence-head">
        <div>
          <div class="evidence-title">${escapeHtml(item.artifact)}</div>
          <div class="rank-meta">${escapeHtml(item.app)} · ${escapeHtml(item.domain)} · ${item.visits} visits · ${fmtSeconds(item.dwell_seconds)}</div>
        </div>
        <span class="chip weight">w ${item.weight}</span>
      </div>
      <div class="why-list">${why}</div>
    `;
    root.appendChild(node);
  }
}

async function refresh() {
  const overview = await getJson(`/api/overview?days=${state.days}&limit=120`);
  state.overview = overview;
  state.events = overview.recent_events;
  renderMetrics(overview);
  renderInsights(overview.insights);
  renderDomains(overview.domains);
  renderHeatmap(overview.hourly_heatmap);
  renderRankList("topArtifacts", overview.top_artifacts);
  renderRankList("topApps", overview.top_apps);
  renderTransitions(overview.transitions);
  renderSignature(overview.profile);
  renderEvents(state.events);
  renderPrivacy(overview.privacy);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function bindUi() {
  $("refreshBtn").addEventListener("click", async () => {
    try {
      await refresh();
      showToast("Dashboard refreshed");
    } catch (error) {
      showToast(error.message);
    }
  });

  $("collectBtn").addEventListener("click", async () => {
    try {
      const result = await getJson("/api/collect-once", { method: "POST" });
      showToast(result.stored ? "Collected one attention sample" : "Current app ignored");
      await refresh();
    } catch (error) {
      showToast(error.message);
    }
  });

  $("daysSelect").addEventListener("change", async (event) => {
    state.days = Number(event.target.value);
    await refresh();
  });

  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((tab) => tab.classList.remove("active"));
      document.querySelectorAll(".view").forEach((view) => view.classList.remove("active-view"));
      button.classList.add("active");
      $(button.dataset.view).classList.add("active-view");
      if (button.dataset.view === "signature" && state.overview) {
        window.requestAnimationFrame(() => renderSignature(state.overview.profile));
      }
    });
  });

  $("eventFilter").addEventListener("input", () => renderEvents(state.events));

  $("queryForm").addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = $("queryInput").value.trim();
    if (!text) return;
    try {
      await runEvidenceQuery(text);
    } catch (error) {
      showToast(error.message);
    }
  });

  document.querySelectorAll(".query-chips button").forEach((button) => {
    button.addEventListener("click", async () => {
      $("queryInput").value = button.textContent;
      await runEvidenceQuery(button.textContent);
    });
  });
}

bindUi();
refresh()
  .then(() => runEvidenceQuery($("queryInput").value))
  .catch((error) => showToast(error.message));

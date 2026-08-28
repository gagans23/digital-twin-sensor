const state = {
  overview: null,
  events: [],
  days: 14,
};

const $ = (id) => document.getElementById(id);

const graphColors = {
  subject: "#151922",
  domain: "#00a6a6",
  task: "#ff7a59",
  artifact: "#6d5dfc",
  app: "#14845d",
  time: "#d99000",
  "private-signal": "#b42318",
};

const graphTypeOrder = ["subject", "domain", "task", "artifact", "app", "time", "private-signal"];

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

function fmtCompact(value) {
  const number = Number(value || 0);
  if (number >= 1000) return `${(number / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  return String(Math.round(number));
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
  $("activityCount").textContent = overview.working_spheres?.stats?.sphere_count || 0;
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

function activityStateLabel(stateName) {
  if (stateName === "active") return "active";
  if (stateName === "suspended") return "suspended";
  if (stateName === "dormant") return "dormant";
  return "unknown";
}

function renderActivities(activities) {
  $("activityDepth").textContent = `Depth ${activities?.capture_depth ?? 1}`;
  renderActivityStats(activities);
  renderActivityPipeline(activities?.pipeline || []);
  renderActivityExplanation(activities?.explanations || []);
  renderSphereCards(activities?.spheres || []);
  renderSurfaceDetails(state.overview?.surface_details || []);
  renderActivityTimeline(activities?.timeline || []);
  renderSphereTransitions(activities?.transitions || []);
}

function renderActivityStats(activities) {
  const root = $("activityStats");
  if (!root) return;
  const stats = activities?.stats || {};
  root.innerHTML = `
    <div class="activity-stat"><strong>${fmtCompact(stats.sphere_count || 0)}</strong><span>shown spheres</span></div>
    <div class="activity-stat"><strong>${fmtCompact(stats.active_count || 0)}</strong><span>active</span></div>
    <div class="activity-stat"><strong>${fmtCompact(stats.suspended_count || 0)}</strong><span>suspended</span></div>
    <div class="activity-stat"><strong>${fmtCompact(stats.gated_spheres || 0)}</strong><span>privacy gated</span></div>
  `;
}

function renderActivityPipeline(items) {
  const root = $("activityPipeline");
  if (!root) return;
  if (!items.length) {
    root.innerHTML = `<div class="empty">No activity pipeline yet.</div>`;
    return;
  }
  root.innerHTML = items
    .map((item) => `
      <div class="activity-stage">
        <b>${escapeHtml(item.stage)}</b>
        <span>${escapeHtml(item.state)}</span>
        <p>${escapeHtml(item.output)}</p>
      </div>
    `)
    .join("");
}

function renderActivityExplanation(items) {
  const root = $("activityExplanation");
  if (!root) return;
  if (!items.length) {
    root.innerHTML = `<div class="empty">No inference ledger yet.</div>`;
    return;
  }
  root.innerHTML = items
    .map((item) => `
      <article class="activity-note">
        <h3>${escapeHtml(item.title)}</h3>
        <p>${escapeHtml(item.body)}</p>
      </article>
    `)
    .join("");
}

function renderSphereCards(items) {
  const root = $("sphereList");
  if (!root) return;
  if (!items.length) {
    root.innerHTML = `<div class="empty">No working spheres yet. The detector needs non-system focus events in this time window.</div>`;
    return;
  }
  root.innerHTML = "";
  for (const item of items) {
    const card = document.createElement("article");
    const sphereState = ["active", "suspended", "dormant"].includes(item.state) ? item.state : "unknown";
    card.className = `sphere-card ${sphereState} ${item.gate_mode === "masked" ? "masked" : ""}`;
    const artifacts = (item.artifacts || [])
      .slice(0, 4)
      .map((artifact) => `
        <div class="sphere-artifact">
          <span>${escapeHtml(artifact.name)}</span>
          <b>${fmtSeconds(artifact.dwell_seconds)}</b>
        </div>
      `)
      .join("");
    const apps = (item.apps || [])
      .map((app) => `<span class="chip">${escapeHtml(app.name)} · ${app.events}</span>`)
      .join("");
    const explanation = (item.explanation || [])
      .map((line) => `<li>${escapeHtml(line)}</li>`)
      .join("");
    const resume = item.resume_pack || {};
    card.innerHTML = `
      <div class="sphere-head">
        <div>
          <h3>${escapeHtml(item.label)}</h3>
          <div class="sphere-meta">
            <span class="chip">${escapeHtml(item.domain)}</span>
            <span class="chip task-chip">${escapeHtml(item.task)}</span>
            <span class="chip confidence-chip">${Math.round((item.confidence || 0) * 100)}% confidence</span>
          </div>
        </div>
        <span class="sphere-state ${sphereState}">${activityStateLabel(item.state)}</span>
      </div>
      <div class="sphere-measures">
        <div><b>${fmtHours(item.hours)}h</b><span>dwell</span></div>
        <div><b>${item.events || 0}</b><span>events</span></div>
        <div><b>${item.session_count || 0}</b><span>sessions</span></div>
        <div><b>${item.return_count || 0}</b><span>returns</span></div>
      </div>
      <div class="sphere-section">
        <h4>Surfaces</h4>
        <div class="sphere-chip-row">${apps || `<span class="muted-text">No app signal</span>`}</div>
      </div>
      <div class="sphere-section">
        <h4>Artifacts</h4>
        <div class="sphere-artifacts">${artifacts || `<div class="muted-text">No artifact signal</div>`}</div>
      </div>
      <div class="sphere-section">
        <h4>Why grouped</h4>
        <ul class="sphere-explanation">${explanation}</ul>
      </div>
      <div class="resume-strip">
        <div>
          <span>Last seen ${fmtTime(resume.last_seen)}</span>
          <b>${escapeHtml(resume.last_app || "unknown app")} · ${escapeHtml(resume.last_artifact || "unknown artifact")}</b>
        </div>
        <p>${escapeHtml(resume.next_action_guess || "Review the latest artifact and decide the next action.")}</p>
        <small>${escapeHtml(resume.privacy_gate || "Depth 1 metadata only")}</small>
      </div>
    `;
    root.appendChild(card);
  }
}

function renderSurfaceDetails(items) {
  const root = $("surfaceDetails");
  if (!root) return;
  if (!items.length) {
    root.innerHTML = `<div class="empty">No app surface details yet.</div>`;
    return;
  }
  root.innerHTML = "";
  for (const item of items) {
    const card = document.createElement("article");
    const statusText = String(item.status || "");
    const statusClass = statusText.includes("captured")
      ? "captured"
      : statusText.includes("opaque")
        ? "opaque"
        : "available";
    const fields = (item.known_fields || [])
      .map((field) => `<span class="chip">${escapeHtml(field)}</span>`)
      .join("");
    const domains = (item.browser_domains || [])
      .map((domain) => `<span class="chip domain-chip">${escapeHtml(domain.domain)} · ${domain.events}</span>`)
      .join("");
    const artifacts = (item.top_artifacts || [])
      .slice(0, 3)
      .map((artifact) => `<div class="surface-artifact"><span>${escapeHtml(artifact.name)}</span><b>${artifact.events}</b></div>`)
      .join("");
    card.className = `surface-card ${statusClass}`;
    card.innerHTML = `
      <div class="surface-head">
        <div>
          <h3>${escapeHtml(item.app)}</h3>
          <p>${escapeHtml(item.detail_level)} · ${fmtSeconds(item.dwell_seconds)} · ${item.events} events</p>
        </div>
        <span class="surface-status ${statusClass}">${escapeHtml(statusText || "unknown")}</span>
      </div>
      <div class="surface-section">
        <h4>Known fields</h4>
        <div class="sphere-chip-row">${fields}</div>
      </div>
      ${domains ? `<div class="surface-section"><h4>Browser domains</h4><div class="sphere-chip-row">${domains}</div></div>` : ""}
      <div class="surface-section">
        <h4>Observed artifacts</h4>
        <div class="surface-artifacts">${artifacts || `<div class="muted-text">No artifact detail yet</div>`}</div>
      </div>
      <div class="surface-section">
        <h4>What it knows</h4>
        <p>${escapeHtml(item.what_we_know)}</p>
      </div>
      <div class="surface-section">
        <h4>How to deepen</h4>
        <p>${escapeHtml(item.how_to_deepen)}</p>
      </div>
      <small>${escapeHtml(item.privacy_boundary)}</small>
    `;
    root.appendChild(card);
  }
}

function renderActivityTimeline(items) {
  const root = $("activityTimeline");
  if (!root) return;
  if (!items.length) {
    root.innerHTML = `<div class="empty">No sessions yet.</div>`;
    return;
  }
  root.innerHTML = "";
  for (const item of items.slice(0, 12)) {
    const node = document.createElement("div");
    node.className = "timeline-item";
    node.innerHTML = `
      <div class="timeline-dot" aria-hidden="true"></div>
      <div>
        <b>${escapeHtml(item.label)}</b>
        <span>${fmtTime(item.start)} · ${fmtSeconds(item.dwell_seconds)} · ${item.events} events · ${escapeHtml(item.top_app)}</span>
      </div>
    `;
    root.appendChild(node);
  }
}

function renderSphereTransitions(items) {
  const root = $("sphereTransitions");
  if (!root) return;
  if (!items.length) {
    root.innerHTML = `<div class="empty">No repeated sphere-to-sphere transitions yet.</div>`;
    return;
  }
  root.innerHTML = "";
  for (const item of items) {
    const node = document.createElement("article");
    node.className = "sphere-transition";
    node.innerHTML = `
      <div class="relationship-flow">
        <span><b>${escapeHtml(item.source)}</b></span>
        <span class="relationship-arrow">→</span>
        <span><b>${escapeHtml(item.target)}</b></span>
      </div>
      <p>${item.count} switches · last ${fmtTime(item.last_seen)}</p>
    `;
    root.appendChild(node);
  }
}

function hashNumber(value) {
  let hash = 2166136261;
  const text = String(value);
  for (let i = 0; i < text.length; i += 1) {
    hash ^= text.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function setupCanvas(canvas, fallbackWidth = 960, fallbackHeight = 520) {
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(320, Math.round(rect.width || fallbackWidth));
  const height = Math.max(360, Math.round(rect.height || fallbackHeight));
  const dpr = window.devicePixelRatio || 1;
  if (canvas.width !== Math.round(width * dpr) || canvas.height !== Math.round(height * dpr)) {
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  return { ctx, width, height };
}

function nodeRadius(node) {
  const dwell = Math.sqrt(Number(node.dwell_seconds || 0)) / 7;
  const visits = Math.log1p(Number(node.events || 0)) * 2.2;
  return clamp(8 + dwell + visits, 9, node.type === "subject" ? 26 : 22);
}

function layoutContextGraph(graph, width, height) {
  const nodes = (graph.nodes || []).map((node) => ({ ...node }));
  const edges = graph.edges || [];
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const groups = {};
  for (const type of graphTypeOrder) groups[type] = [];
  for (const node of nodes) {
    if (!groups[node.type]) groups[node.type] = [];
    groups[node.type].push(node);
  }

  const cx = width / 2;
  const cy = height / 2;
  const ring = Math.min(width, height) / 2 - 54;
  const ringByType = {
    subject: 0,
    domain: 0.32,
    task: 0.5,
    app: 0.66,
    artifact: 0.82,
    time: 0.92,
    "private-signal": 0.58,
  };

  for (const type of Object.keys(groups)) {
    const items = groups[type];
    const offset = (hashNumber(type) % 360) * (Math.PI / 180);
    items.forEach((node, index) => {
      if (type === "subject") {
        node.x = cx;
        node.y = cy;
        return;
      }
      const angle = offset + (index / Math.max(items.length, 1)) * Math.PI * 2;
      const jitter = ((hashNumber(node.id) % 100) / 100 - 0.5) * 22;
      const radius = ring * (ringByType[type] || 0.72) + jitter;
      node.x = cx + Math.cos(angle) * radius;
      node.y = cy + Math.sin(angle) * radius;
    });
  }

  for (let tick = 0; tick < 90; tick += 1) {
    for (let i = 0; i < nodes.length; i += 1) {
      const a = nodes[i];
      if (a.type === "subject") continue;
      for (let j = i + 1; j < nodes.length; j += 1) {
        const b = nodes[j];
        const dx = a.x - b.x;
        const dy = a.y - b.y;
        const distSq = Math.max(dx * dx + dy * dy, 25);
        const force = 54 / distSq;
        const fx = dx * force;
        const fy = dy * force;
        if (a.type !== "subject") {
          a.x += fx;
          a.y += fy;
        }
        if (b.type !== "subject") {
          b.x -= fx;
          b.y -= fy;
        }
      }
    }

    for (const edge of edges) {
      const source = byId.get(edge.source);
      const target = byId.get(edge.target);
      if (!source || !target) continue;
      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
      const desired = edge.relation === "focused_in" ? 110 : 135;
      const strength = edge.relation === "next_context" ? 0.012 : 0.025;
      const pull = (dist - desired) * strength;
      const fx = (dx / dist) * pull;
      const fy = (dy / dist) * pull;
      if (source.type !== "subject") {
        source.x += fx;
        source.y += fy;
      }
      if (target.type !== "subject") {
        target.x -= fx;
        target.y -= fy;
      }
    }

    for (const node of nodes) {
      if (node.type === "subject") {
        node.x = cx;
        node.y = cy;
        continue;
      }
      node.x += (cx - node.x) * 0.004;
      node.y += (cy - node.y) * 0.004;
      const radius = nodeRadius(node) + 8;
      node.x = clamp(node.x, radius, width - radius);
      node.y = clamp(node.y, radius, height - radius);
    }
  }

  return new Map(nodes.map((node) => [node.id, node]));
}

function roundedRectPath(ctx, x, y, width, height, radius) {
  if (ctx.roundRect) {
    ctx.roundRect(x, y, width, height, radius);
    return;
  }
  const r = Math.min(radius, width / 2, height / 2);
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + width - r, y);
  ctx.quadraticCurveTo(x + width, y, x + width, y + r);
  ctx.lineTo(x + width, y + height - r);
  ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
  ctx.lineTo(x + r, y + height);
  ctx.quadraticCurveTo(x, y + height, x, y + height - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
}

function drawGraphLabel(ctx, text, x, y, align = "center") {
  const label = String(text || "");
  const maxChars = 28;
  const short = label.length > maxChars ? `${label.slice(0, maxChars - 1)}...` : label;
  ctx.font = "700 11px Inter, system-ui, sans-serif";
  const metrics = ctx.measureText(short);
  const padding = 5;
  const width = metrics.width + padding * 2;
  const height = 20;
  const left = align === "left" ? x : align === "right" ? x - width : x - width / 2;
  ctx.fillStyle = "rgba(255, 255, 255, 0.88)";
  ctx.strokeStyle = "rgba(217, 224, 234, 0.9)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  roundedRectPath(ctx, left, y - height / 2, width, height, 5);
  ctx.fill();
  ctx.stroke();
  ctx.fillStyle = "#2c3440";
  ctx.textAlign = align;
  ctx.textBaseline = "middle";
  ctx.fillText(short, x, y);
}

function renderContextGraph(graph) {
  const canvas = $("contextGraphCanvas");
  if (!canvas) return;
  const { ctx, width, height } = setupCanvas(canvas);
  ctx.fillStyle = "#eef2f7";
  ctx.fillRect(0, 0, width, height);

  $("graphDepth").textContent = `Depth ${graph?.capture_depth ?? 1}`;
  renderGraphStats(graph);
  renderPrivacyGates(graph?.privacy_gates || []);
  renderRelationships(graph?.top_relationships || []);
  renderGraphLegend(graph);

  if (!graph || graph.status !== "ready" || !(graph.nodes || []).length) {
    ctx.fillStyle = "#5f6b7a";
    ctx.font = "700 16px Inter, system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText("No graph signal yet", width / 2, height / 2);
    return;
  }

  const positions = layoutContextGraph(graph, width, height);
  const edges = [...(graph.edges || [])].sort((a, b) => Number(a.weight || 0) - Number(b.weight || 0));

  for (const edge of edges) {
    const source = positions.get(edge.source);
    const target = positions.get(edge.target);
    if (!source || !target) continue;
    const widthScale = clamp(Math.log1p(Number(edge.events || 1)) * 0.8, 0.8, 4);
    ctx.beginPath();
    ctx.moveTo(source.x, source.y);
    ctx.lineTo(target.x, target.y);
    ctx.strokeStyle = edge.gate_mode === "masked" ? "rgba(180, 35, 24, 0.28)" : "rgba(95, 107, 122, 0.24)";
    ctx.lineWidth = widthScale;
    ctx.setLineDash(edge.relation === "next_context" ? [4, 5] : []);
    ctx.stroke();
  }
  ctx.setLineDash([]);

  const sortedNodes = [...positions.values()].sort((a, b) => Number(a.weight || 0) - Number(b.weight || 0));
  for (const node of sortedNodes) {
    const radius = nodeRadius(node);
    const color = graphColors[node.type] || "#5f6b7a";
    ctx.beginPath();
    ctx.arc(node.x, node.y, radius, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.globalAlpha = node.gate_mode === "masked" ? 0.82 : 0.95;
    ctx.fill();
    ctx.globalAlpha = 1;
    ctx.lineWidth = node.gate_mode === "masked" ? 3 : 1.5;
    ctx.strokeStyle = node.gate_mode === "masked" ? "#b42318" : "#ffffff";
    ctx.stroke();

    if (node.type === "private-signal") {
      ctx.beginPath();
      ctx.arc(node.x, node.y, Math.max(3, radius * 0.34), 0, Math.PI * 2);
      ctx.fillStyle = "#ffffff";
      ctx.fill();
    }
  }

  const labeled = [...positions.values()]
    .sort((a, b) => Number(b.weight || 0) - Number(a.weight || 0))
    .slice(0, width < 680 ? 12 : 22);
  for (const node of labeled) {
    const align = node.x < width * 0.22 ? "left" : node.x > width * 0.78 ? "right" : "center";
    const offset = node.y < height * 0.18 ? nodeRadius(node) + 14 : -(nodeRadius(node) + 14);
    drawGraphLabel(ctx, node.label, node.x, node.y + offset, align);
  }
}

function renderGraphStats(graph) {
  const root = $("graphStats");
  if (!root) return;
  const stats = graph?.stats || {};
  const gates = stats.gates || {};
  root.innerHTML = `
    <div class="graph-stat"><strong>${fmtCompact(stats.node_count || 0)}</strong><span>nodes</span></div>
    <div class="graph-stat"><strong>${fmtCompact(stats.edge_count || 0)}</strong><span>edges</span></div>
    <div class="graph-stat"><strong>${fmtCompact(stats.events || 0)}</strong><span>events</span></div>
    <div class="graph-stat"><strong>${fmtCompact((gates.masked || 0) + (gates.generalized || 0) + (gates.withheld || 0))}</strong><span>gated</span></div>
  `;
}

function renderPrivacyGates(gates) {
  const root = $("gateList");
  if (!root) return;
  if (!gates.length) {
    root.innerHTML = `<div class="empty">No gate data yet.</div>`;
    return;
  }
  root.innerHTML = "";
  for (const gate of gates) {
    const node = document.createElement("article");
    const detail = typeof gate.detail === "object"
      ? Object.entries(gate.detail).map(([key, value]) => `${key}: ${value}`).join(" · ")
      : gate.detail;
    const mode = /redaction|sensitive/i.test(gate.name) ? "masked" : /minimization|depth/i.test(gate.name) ? "generalized" : "";
    node.className = `gate-item ${mode}`;
    node.innerHTML = `
      <h3>${escapeHtml(gate.name)} · ${escapeHtml(gate.status)}</h3>
      <p>${escapeHtml(gate.decision)}</p>
      <p>${escapeHtml(detail || "")}</p>
    `;
    root.appendChild(node);
  }
}

function renderRelationships(items) {
  const root = $("relationshipList");
  if (!root) return;
  if (!items.length) {
    root.innerHTML = `<div class="empty">No relationships yet.</div>`;
    return;
  }
  root.innerHTML = "";
  for (const item of items) {
    const node = document.createElement("article");
    node.className = "relationship-item";
    node.innerHTML = `
      <div class="relationship-flow">
        <span><b>${escapeHtml(item.source)}</b><br><small>${escapeHtml(item.source_type)}</small></span>
        <span class="relationship-arrow">→</span>
        <span><b>${escapeHtml(item.target)}</b><br><small>${escapeHtml(item.target_type)}</small></span>
      </div>
      <p>${escapeHtml(item.relation)} · ${item.events} events · ${fmtSeconds(item.dwell_seconds)} · ${escapeHtml(item.gate_mode)}</p>
    `;
    root.appendChild(node);
  }
}

function renderGraphLegend(graph) {
  const root = $("graphLegend");
  if (!root) return;
  const presentTypes = new Set((graph?.nodes || []).map((node) => node.type));
  const types = graphTypeOrder.filter((type) => presentTypes.has(type));
  const displayTypes = types.length ? types : graphTypeOrder.slice(0, 6);
  root.innerHTML = displayTypes
    .map((type) => `
      <div class="legend-item">
        <span class="legend-dot" style="background: ${graphColors[type] || "#5f6b7a"}"></span>
        <div><h3>${escapeHtml(type.replace("-", " "))}</h3><p>${escapeHtml(type === "private-signal" ? "masked or blocked sensitive text" : "derived from redacted event metadata")}</p></div>
      </div>
    `)
    .join("");
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
  renderActivities(overview.working_spheres);
  renderContextGraph(overview.context_graph);
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
      if (button.dataset.view === "graph" && state.overview) {
        window.requestAnimationFrame(() => renderContextGraph(state.overview.context_graph));
      }
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

  window.addEventListener("resize", () => {
    window.clearTimeout(bindUi.resizeTimer);
    bindUi.resizeTimer = window.setTimeout(() => {
      if (document.querySelector("#graph.active-view") && state.overview) {
        renderContextGraph(state.overview.context_graph);
      }
      if (document.querySelector("#signature.active-view") && state.overview) {
        renderSignature(state.overview.profile);
      }
    }, 120);
  });
}

bindUi();
refresh()
  .then(() => runEvidenceQuery($("queryInput").value))
  .catch((error) => showToast(error.message));

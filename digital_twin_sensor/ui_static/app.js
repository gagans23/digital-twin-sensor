const state = {
  overview: null,
  events: [],
  contextPack: null,
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

function fmtBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb.toFixed(1).replace(/\.0$/, "")} KB`;
  return `${(kb / 1024).toFixed(1).replace(/\.0$/, "")} MB`;
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

function pct(value, digits = 0) {
  return `${(Number(value || 0) * 100).toFixed(digits).replace(/\.0$/, "")}%`;
}

function primarySphere(overview) {
  const spheres = overview?.working_spheres?.spheres || [];
  return spheres.find((sphere) => sphere.state === "active") || spheres[0] || null;
}

function topWorkDomain(overview) {
  const domains = overview?.domains || [];
  return domains.find((item) => item.domain !== "system") || domains[0] || null;
}

function collectorHealth(overview) {
  const collector = overview?.collector || {};
  const age = overview?.totals?.last_age_seconds;
  const running = collector.installed && ["active", "running"].includes(collector.state);
  if (running && age !== null && age !== undefined && age < 120) {
    return { label: "Live", tone: "ready", detail: `last sample ${fmtSeconds(age)} ago` };
  }
  if (running) {
    return { label: "Running", tone: "attention", detail: age ? `last sample ${fmtSeconds(age)} ago` : "waiting for signal" };
  }
  return { label: "Paused", tone: "blocked", detail: "collector is not active" };
}

function twinFidelityScore(overview) {
  const totals = overview?.totals || {};
  const graph = overview?.context_graph?.stats || {};
  const spheres = overview?.working_spheres?.stats || {};
  const pack = overview?.context_pack || {};
  const eventScore = clamp(Number(totals.events_in_window || 0) / 600, 0, 1);
  const graphScore = clamp(Number(graph.node_count || 0) / 42, 0, 1);
  const sphereScore = clamp(Number(spheres.sphere_count || 0) / 8, 0, 1);
  const depthScore = clamp(Number(overview?.context_graph?.capture_depth || 1) / 3, 0.25, 1);
  const age = Number(totals.last_age_seconds ?? 999999);
  const recencyScore = age < 120 ? 1 : age < 900 ? 0.72 : age < 3600 ? 0.48 : 0.22;
  const privacyScore = pack?.privacy?.raw_events_included === false && pack?.privacy?.subject_id_included === false ? 1 : 0.45;
  const score = eventScore * 0.24 + graphScore * 0.18 + sphereScore * 0.2 + depthScore * 0.12 + recencyScore * 0.16 + privacyScore * 0.1;
  return Math.round(clamp(score, 0, 1) * 100);
}

function renderTwinExperience(overview) {
  if (!$("twinMapCanvas")) return;
  const health = collectorHealth(overview);
  const sphere = primarySphere(overview);
  const domain = topWorkDomain(overview);
  const pack = overview.context_pack || {};
  const fidelity = twinFidelityScore(overview);
  const graphStats = overview.context_graph?.stats || {};
  const sphereStats = overview.working_spheres?.stats || {};
  const privateSignals = graphStats.gates
    ? Number(graphStats.gates.masked || 0) + Number(graphStats.gates.generalized || 0) + Number(graphStats.gates.withheld || 0)
    : 0;

  $("twinHeroStatus").textContent = health.label;
  $("twinHeroStatus").className = `live-pill ${health.tone}`;
  $("twinName").textContent = "Local User Twin";
  $("twinNarrative").textContent = sphere
    ? `${sphere.label} is the strongest live sphere, grounded by ${fmtCompact(overview.totals.events_in_window)} recent samples and ${fmtCompact(graphStats.node_count || 0)} context nodes.`
    : `The twin is waiting for enough non-system focus signal in the selected ${overview.days}-day window.`;
  $("twinFidelityBadge").textContent = `${fidelity}%`;
  $("twinActiveSphereBadge").textContent = sphere ? sphere.state : "none";
  $("twinPrivacyBadge").textContent = pack.status === "ready" ? `${pack.admission?.counts?.deny || 0} denied` : pack.status || "empty";
  $("focusGate").textContent = pack.status === "ready" ? "summary-only" : pack.status || "gate";

  renderFocusNow(overview, sphere, health);
  renderAttentionCompass(overview.domains || []);
  renderFabricLanes(overview, fidelity);
  renderTwinVitals(overview, { fidelity, privateSignals });
  renderSimulationCards(overview, sphere, domain);
  renderGovernanceStack(overview);
  drawTwinMap(overview);
}

function renderFocusNow(overview, sphere, health) {
  const root = $("focusNow");
  if (!root) return;
  if (!sphere) {
    root.innerHTML = `<div class="empty">No active working sphere in this window.</div>`;
    return;
  }
  const resume = sphere.resume_pack || {};
  const apps = (sphere.apps || [])
    .slice(0, 3)
    .map((item) => `<span class="chip">${escapeHtml(item.name)} · ${item.events}</span>`)
    .join("");
  root.innerHTML = `
    <article class="focus-card ${sphere.gate_mode === "masked" ? "masked" : ""}">
      <div class="focus-title-row">
        <div>
          <h3>${escapeHtml(sphere.label)}</h3>
          <p>${escapeHtml(sphere.domain)} / ${escapeHtml(sphere.task)} / ${health.detail}</p>
        </div>
        <span class="confidence-ring" style="--score:${Math.round((sphere.confidence || 0) * 100)}">${Math.round((sphere.confidence || 0) * 100)}%</span>
      </div>
      <div class="focus-measures">
        <div><b>${fmtHours(sphere.hours)}</b><span>hours</span></div>
        <div><b>${fmtCompact(sphere.events)}</b><span>events</span></div>
        <div><b>${fmtCompact(sphere.return_count)}</b><span>returns</span></div>
      </div>
      <p class="focus-resume">${escapeHtml(resume.next_action_guess || "Review the latest artifact and continue.")}</p>
      <div class="sphere-chip-row">${apps || `<span class="muted-text">No app signal</span>`}</div>
    </article>
  `;
}

function renderAttentionCompass(domains) {
  const root = $("attentionCompass");
  if (!root) return;
  const items = domains.filter((item) => item.domain !== "system").slice(0, 4);
  if (!items.length) {
    root.innerHTML = `<div class="empty">No work-domain signal yet.</div>`;
    return;
  }
  root.innerHTML = `
    <h3>Attention compass</h3>
    ${items.map((item) => `
      <div class="compass-row">
        <span>${escapeHtml(item.domain)}</span>
        <div class="compass-track"><div style="width:${Math.max(5, Math.round(item.share * 100))}%"></div></div>
        <b>${pct(item.share)}</b>
      </div>
    `).join("")}
  `;
}

function renderFabricLanes(overview, fidelity) {
  const root = $("fabricLanes");
  if (!root) return;
  const graphStats = overview.context_graph?.stats || {};
  const sphereStats = overview.working_spheres?.stats || {};
  const pack = overview.context_pack || {};
  const policy = overview.fleet?.active_policy || {};
  const lanes = [
    {
      name: "Sense",
      value: `${fmtCompact(overview.totals.events_in_window)} samples`,
      detail: `Depth ${policy.capture_depth || overview.context_graph?.capture_depth || 1}, ${fmtCompact(overview.top_apps?.length || 0)} surfaces`,
      score: clamp(Number(overview.totals.events_in_window || 0) / 600, 0, 1),
    },
    {
      name: "Synthesize",
      value: `${fmtCompact(graphStats.node_count || 0)} nodes`,
      detail: `${fmtCompact(graphStats.edge_count || 0)} relationships, ${fmtCompact(graphStats.events || 0)} work events`,
      score: clamp(Number(graphStats.node_count || 0) / 42, 0, 1),
    },
    {
      name: "Twin",
      value: `${fmtCompact(sphereStats.sphere_count || 0)} spheres`,
      detail: `${fmtCompact(sphereStats.active_count || 0)} active, ${fmtCompact(sphereStats.gated_spheres || 0)} gated`,
      score: clamp(Number(sphereStats.sphere_count || 0) / 8, 0, 1),
    },
    {
      name: "Simulate",
      value: `${fidelity}% fidelity`,
      detail: `${pack.status || "empty"} pack, ${fmtCompact(pack.admission?.counts?.deny || 0)} denied fields`,
      score: fidelity / 100,
    },
  ];
  root.innerHTML = lanes
    .map((lane) => `
      <article class="fabric-lane">
        <div class="lane-top"><h3>${escapeHtml(lane.name)}</h3><b>${escapeHtml(lane.value)}</b></div>
        <div class="lane-meter"><div style="width:${Math.round(lane.score * 100)}%"></div></div>
        <p>${escapeHtml(lane.detail)}</p>
      </article>
    `)
    .join("");
}

function renderTwinVitals(overview, extras) {
  const root = $("twinVitals");
  if (!root) return;
  const pack = overview.context_pack || {};
  const graphStats = overview.context_graph?.stats || {};
  const vitals = [
    ["Fidelity", `${extras.fidelity}%`, "fit between recent signals, graph, recency, and governance"],
    ["Graph load", `${fmtCompact(graphStats.node_count || 0)} / ${fmtCompact(graphStats.edge_count || 0)}`, "nodes and relationships in the work graph"],
    ["Private signals", fmtCompact(extras.privateSignals || 0), "masked, generalized, or withheld graph elements"],
    ["Pack gate", pack.status || "empty", `${fmtCompact(pack.admission?.counts?.deny || 0)} denied, ${fmtCompact(pack.admission?.counts?.summarize || 0)} summarized`],
  ];
  root.innerHTML = vitals
    .map(([label, value, detail]) => `
      <article class="vital-row">
        <div><span>${escapeHtml(label)}</span><b>${escapeHtml(value)}</b></div>
        <p>${escapeHtml(detail)}</p>
      </article>
    `)
    .join("");
}

function renderSimulationCards(overview, sphere, domain) {
  const root = $("simulationCards");
  if (!root) return;
  const pack = overview.context_pack || {};
  const opaque = (overview.surface_details || []).find((item) => String(item.status || "").includes("opaque"));
  const systemShare = overview.domains?.find((item) => item.domain === "system")?.share || 0;
  const fleet = overview.fleet || {};
  const cards = [
    {
      title: "Continue active sphere",
      state: sphere ? "ready" : "waiting",
      signal: sphere ? `${sphere.label} with ${fmtCompact(sphere.events)} events` : "no active sphere",
      outcome: sphere ? sphere.resume_pack?.next_action_guess || "Continue current context." : "Collect more foreground work signal.",
    },
    {
      title: "Handoff to agent",
      state: pack.status === "ready" ? "ready" : pack.status || "waiting",
      signal: `${fmtCompact(pack.admission?.counts?.summarize || 0)} summarized fields, ${fmtCompact(pack.admission?.counts?.deny || 0)} denied`,
      outcome: "Use the Context Packs tab for Kiro, Codex, or GitLab-safe Markdown.",
    },
    {
      title: "Deepen opaque app",
      state: opaque ? "attention" : "steady",
      signal: opaque ? `${opaque.app} exposes Depth 1 only` : "no opaque app is dominating",
      outcome: opaque ? "Add a per-app Accessibility connector before considering local OCR summaries." : "Keep current metadata boundary.",
    },
    {
      title: "Deploy portable twin",
      state: fleet.status === "enrolled" ? "ready" : "next",
      signal: fleet.status === "enrolled" ? "control plane enrolled" : "local-only endpoint",
      outcome: "Next enterprise step is signed enrollment plus approved context-pack registry.",
    },
    {
      title: "Improve signal quality",
      state: systemShare > 0.45 ? "attention" : "steady",
      signal: `${pct(systemShare)} system or locked-session share`,
      outcome: systemShare > 0.45 ? "Reduce locked-session noise with idle detection and pause/resume controls." : `Strongest work domain is ${domain?.domain || "unknown"}.`,
    },
  ];
  root.innerHTML = "";
  for (const item of cards) {
    const node = document.createElement("article");
    node.className = `simulation-card ${fleetTone(item.state)}`;
    node.innerHTML = `
      <div class="simulation-head">
        <h3>${escapeHtml(item.title)}</h3>
        <span class="status-badge ${fleetTone(item.state)}">${escapeHtml(item.state)}</span>
      </div>
      <p><b>Signal</b> ${escapeHtml(item.signal)}</p>
      <p><b>Outcome</b> ${escapeHtml(item.outcome)}</p>
    `;
    root.appendChild(node);
  }
}

function renderGovernanceStack(overview) {
  const root = $("governanceStack");
  if (!root) return;
  const privacy = overview.privacy || {};
  const policy = overview.fleet?.active_policy || {};
  const pack = overview.context_pack || {};
  const gates = [
    ["Collection", overview.collector?.installed ? "active" : "attention", collectorHealth(overview).detail],
    ["PII masking", privacy.mask_pii ? "ready" : "blocked", privacy.mask_pii ? "enabled before storage" : "must be enabled"],
    ["URL minimization", policy.browser_url_path || policy.browser_url_query ? "attention" : "ready", policy.browser_url_path || policy.browser_url_query ? "path/query retention enabled" : "paths and queries redacted"],
    ["Raw upload", policy.raw_event_upload ? "blocked" : "ready", policy.raw_event_upload ? "raw event upload enabled" : "raw event upload blocked"],
    ["Export targets", pack.target?.allowed ? "ready" : "attention", (policy.allowed_export_targets || []).join(", ") || "local only"],
    ["Storage", "local", privacy.data_location || "local SQLite"],
  ];
  root.innerHTML = gates
    .map(([name, status, detail]) => `
      <article class="governance-item ${fleetTone(status)}">
        <div>
          <h3>${escapeHtml(name)}</h3>
          <p>${escapeHtml(detail)}</p>
        </div>
        <span class="status-badge ${fleetTone(status)}">${escapeHtml(status)}</span>
      </article>
    `)
    .join("");
}

function renderAttentionDepth(depth) {
  if (!$("depthStatus")) return;
  if (!depth) {
    $("depthStatus").textContent = "No depth data";
    $("depthSummary").innerHTML = `<div class="empty">No attention-depth model yet.</div>`;
    renderDepthList("appAttention", [], "app-attention-card");
    renderMediaFocus(null);
    renderEyeModel(null);
    renderDepthLadder([]);
    renderDepthRecommendations([]);
    return;
  }

  $("depthStatus").textContent = `Depth ${depth.current_depth}`;
  $("depthStatus").classList.toggle("ready", Number(depth.current_depth || 0) >= 2);
  $("depthSummary").innerHTML = `
    <div class="depth-summary-card">
      <span>Latest app</span>
      <b>${escapeHtml(depth.latest_app || "none")}</b>
      <p>${escapeHtml(depth.latest_artifact || "No current artifact")}</p>
    </div>
    <div class="depth-summary-card">
      <span>Detail kind</span>
      <b>${escapeHtml(depth.latest_detail_kind || "app/window")}</b>
      <p>${escapeHtml(depth.media_focus?.playback_visibility || "attention only")}</p>
    </div>
    <div class="depth-summary-card">
      <span>Eye stance</span>
      <b>${escapeHtml(depth.eye_model?.status || "proxy-first")}</b>
      <p>${escapeHtml(depth.eye_model?.current_position || "No gaze collection")}</p>
    </div>
  `;

  renderAppAttention(depth.application_attention || []);
  renderMediaFocus(depth.media_focus);
  renderEyeModel(depth.eye_model);
  renderDepthLadder(depth.depth_ladder || []);
  renderDepthRecommendations(depth.recommendations || []);
}

function renderAppAttention(items) {
  const root = $("appAttention");
  if (!root) return;
  if (!items.length) {
    root.innerHTML = `<div class="empty">No app attention signal in this window.</div>`;
    return;
  }
  root.innerHTML = items
    .map((item) => `
      <article class="app-attention-card ${fleetTone(item.status)}">
        <div class="app-attention-head">
          <div>
            <h3>${escapeHtml(item.app)}</h3>
            <p>${escapeHtml(item.detail_level)} · ${fmtHours(item.hours)}h · ${fmtCompact(item.events)} events</p>
          </div>
          <span class="status-badge ${fleetTone(item.status)}">${escapeHtml(item.status)}</span>
        </div>
        <div class="detail-meter" aria-label="${escapeHtml(item.app)} detail coverage">
          <div style="width:${Math.round(Number(item.detail_coverage || 0) * 100)}%"></div>
        </div>
        <p>${escapeHtml(item.what_we_know)}</p>
        <small>${escapeHtml(item.next_step)}</small>
      </article>
    `)
    .join("");
}

function renderMediaFocus(media) {
  const root = $("mediaFocus");
  if (!root) return;
  if (!media) {
    root.innerHTML = `<div class="empty">No playback model yet.</div>`;
    return;
  }
  const evidence = (media.evidence || [])
    .map((item) => `<div class="evidence-line"><span>${escapeHtml(item.label)}</span><b>${escapeHtml(item.value)}</b></div>`)
    .join("");
  root.innerHTML = `
    <article class="media-card ${fleetTone(media.status)}">
      <div class="media-head">
        <div>
          <h3>${escapeHtml(media.current_app || "none")}</h3>
          <p>${escapeHtml(media.playback_visibility || "unknown")}</p>
        </div>
        <span class="status-badge ${fleetTone(media.status)}">${escapeHtml(media.status || "unknown")}</span>
      </div>
      <p>${escapeHtml(media.what_we_know || "")}</p>
      <div class="media-evidence">${evidence || `<div class="empty">No playback evidence yet.</div>`}</div>
      <small>${escapeHtml(media.next_step || "")}</small>
    </article>
  `;
}

function renderEyeModel(model) {
  const root = $("eyeModel");
  if (!root) return;
  if (!model) {
    root.innerHTML = `<div class="empty">No eye model yet.</div>`;
    return;
  }
  root.innerHTML = `
    <div class="eye-stance">${escapeHtml(model.current_position || "")}</div>
    ${(model.signals || []).map((item) => `
      <article class="eye-signal ${fleetTone(item.status)}">
        <div>
          <h3>${escapeHtml(item.name)}</h3>
          <p>${escapeHtml(item.detail)}</p>
        </div>
        <span class="status-badge ${fleetTone(item.status)}">${escapeHtml(item.status)}</span>
      </article>
    `).join("")}
  `;
}

function renderDepthLadder(items) {
  const root = $("depthLadder");
  if (!root) return;
  if (!items.length) {
    root.innerHTML = `<div class="empty">No depth ladder yet.</div>`;
    return;
  }
  root.innerHTML = items
    .map((item) => `
      <article class="depth-step ${fleetTone(item.status)}">
        <span>${escapeHtml(item.level)}</span>
        <h3>${escapeHtml(item.name)}</h3>
        <p>${escapeHtml(item.captures)}</p>
        <small>${escapeHtml(item.privacy_gate)}</small>
        <b>${escapeHtml(item.status)}</b>
      </article>
    `)
    .join("");
}

function renderDepthRecommendations(items) {
  const root = $("depthRecommendations");
  if (!root) return;
  if (!items.length) {
    root.innerHTML = `<div class="empty">No recommendations yet.</div>`;
    return;
  }
  root.innerHTML = items
    .map((item) => `
      <article class="depth-recommendation ${fleetTone(item.status)}">
        <div class="status-card-head">
          <h3>${escapeHtml(item.name)}</h3>
          <span class="status-badge ${fleetTone(item.status)}">${escapeHtml(item.status)}</span>
        </div>
        <p>${escapeHtml(item.detail)}</p>
        <code>${escapeHtml(item.command)}</code>
      </article>
    `)
    .join("");
}

function renderDepthList(id, items, className) {
  const root = $(id);
  if (!root) return;
  root.innerHTML = items.length ? "" : `<div class="empty">No items yet.</div>`;
  items.forEach((item) => {
    const node = document.createElement("article");
    node.className = className;
    node.textContent = item.name || item.app || "item";
    root.appendChild(node);
  });
}

function drawTwinMap(overview) {
  const canvas = $("twinMapCanvas");
  if (!canvas) return;
  const { ctx, width, height } = setupCanvas(canvas, 860, 460);
  const compact = width < 520;
  const spheres = (overview.working_spheres?.spheres || []).slice(0, compact ? 6 : 9);
  const domains = (overview.domains || []).filter((item) => item.domain !== "system").slice(0, compact ? 4 : 5);
  const pack = overview.context_pack || {};
  const cx = width * (compact ? 0.5 : 0.48);
  const cy = height * (compact ? 0.56 : 0.52);
  const maxRadius = Math.min(width, height) * (compact ? 0.26 : 0.31);

  ctx.fillStyle = "#080a0f";
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = "rgba(255, 255, 255, 0.08)";
  ctx.lineWidth = 1;
  for (let x = 28; x < width; x += 42) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
  }
  for (let y = 28; y < height; y += 42) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }

  for (let ring = 1; ring <= 3; ring += 1) {
    ctx.beginPath();
    ctx.arc(cx, cy, maxRadius * (ring / 3), 0, Math.PI * 2);
    ctx.strokeStyle = `rgba(255, 255, 255, ${0.08 + ring * 0.03})`;
    ctx.stroke();
  }

  const palette = ["#66e5cf", "#ff8f70", "#a59bff", "#ffd166", "#7bd88f", "#f2f4f8"];
  domains.forEach((domain, index) => {
    const angle = -Math.PI / 2 + (index / Math.max(domains.length, 1)) * Math.PI * 2;
    const r = maxRadius * (0.9 + (index % 2) * 0.12);
    const x = cx + Math.cos(angle) * r;
    const y = cy + Math.sin(angle) * r;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(x, y);
    ctx.strokeStyle = "rgba(255, 255, 255, 0.18)";
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x, y, 8 + Number(domain.share || 0) * 42, 0, Math.PI * 2);
    ctx.fillStyle = palette[index % palette.length];
    ctx.globalAlpha = 0.82;
    ctx.fill();
    ctx.globalAlpha = 1;
    drawGraphLabel(ctx, twinMapLabel(domain.domain, compact), clamp(x, 58, width - 58), y - 25, "center", compact ? 16 : 28);
  });

  spheres.forEach((sphere, index) => {
    const angle = Math.PI / 8 + (index / Math.max(spheres.length, 1)) * Math.PI * 2;
    const r = maxRadius * (0.42 + (index % 3) * 0.12);
    const x = cx + Math.cos(angle) * r;
    const y = cy + Math.sin(angle) * r;
    const radius = clamp(7 + Math.sqrt(Number(sphere.dwell_seconds || 0)) / 18, 8, 24);
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(x, y);
    ctx.strokeStyle = sphere.gate_mode === "masked" ? "rgba(255, 143, 112, 0.38)" : "rgba(102, 229, 207, 0.26)";
    ctx.lineWidth = 1.2;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fillStyle = sphere.state === "active" ? "#66e5cf" : sphere.state === "suspended" ? "#ffd166" : "#a59bff";
    ctx.fill();
    ctx.strokeStyle = sphere.gate_mode === "masked" ? "#ff8f70" : "rgba(255, 255, 255, 0.72)";
    ctx.lineWidth = sphere.gate_mode === "masked" ? 3 : 1.5;
    ctx.stroke();
    if (index < 4) {
      drawGraphLabel(ctx, twinMapLabel(sphere.label, compact), clamp(x, 66, width - 66), y + radius + 16, "center", compact ? 15 : 28);
    }
  });

  ctx.beginPath();
  ctx.arc(cx, cy, 44, 0, Math.PI * 2);
  ctx.fillStyle = "#f7f4eb";
  ctx.fill();
  ctx.strokeStyle = pack.status === "ready" ? "#66e5cf" : "#ffd166";
  ctx.lineWidth = 4;
  ctx.stroke();
  ctx.fillStyle = "#080a0f";
  ctx.font = "800 15px Inter, system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("YOU", cx, cy - 6);
  ctx.font = "700 10px Inter, system-ui, sans-serif";
  ctx.fillText(`${twinFidelityScore(overview)}% twin`, cx, cy + 13);

  const legendX = compact ? 14 : width - 185;
  const legendY = compact ? 22 : 28;
  ctx.fillStyle = "rgba(255, 255, 255, 0.08)";
  ctx.beginPath();
  roundedRectPath(ctx, legendX, legendY, 158, 118, 8);
  ctx.fill();
  ctx.fillStyle = "#f7f4eb";
  ctx.font = "800 12px Inter, system-ui, sans-serif";
  ctx.textAlign = "left";
  ctx.fillText("Twin layers", legendX + 14, legendY + 22);
  [
    ["#66e5cf", "active context"],
    ["#ffd166", "suspended work"],
    ["#a59bff", "memory sphere"],
    ["#ff8f70", "privacy gated"],
  ].forEach(([color, label], index) => {
    const y = legendY + 45 + index * 17;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(legendX + 17, y - 4, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#c9d2df";
    ctx.font = "600 10px Inter, system-ui, sans-serif";
    ctx.fillText(label, legendX + 30, y);
  });
}

function twinMapLabel(value, compact = false) {
  const label = String(value || "");
  if (!compact) return label;
  const aliases = {
    "browser-research": "research",
    communication: "comms",
    Application: "app",
    "other / unclassified work": "other",
  };
  const normalized = aliases[label] || label.replace(/^New /, "").replace(/\s+microsoft$/i, "");
  return normalized.length > 15 ? `${normalized.slice(0, 14)}...` : normalized;
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

function fleetTone(status) {
  const value = String(status || "").toLowerCase();
  if (["ready", "online", "implemented", "enabled", "local", "enrolled", "active", "steady", "rich", "captured", "watching"].includes(value)) return "ready";
  if (["blocked", "offline", "off"].includes(value)) return "blocked";
  if (["planned", "next", "not enrolled", "waiting", "stale", "attention", "collector-only", "opaque", "gated", "basic"].includes(value)) return "attention";
  return "neutral";
}

function renderFleet(fleet) {
  const status = $("fleetStatus");
  if (!fleet || !fleet.summary) {
    status.textContent = "No fleet data";
    status.classList.remove("ready");
    renderFleetStats(null);
    renderDevices([]);
    renderPolicy(null);
    renderConnectors([]);
    renderReadiness([]);
    renderPortability([]);
    renderAdminActions([]);
    return;
  }

  status.textContent = fleet.status === "enrolled" ? "Enrolled" : "Local only";
  status.classList.toggle("ready", fleet.summary.online_count > 0);
  renderFleetStats(fleet);
  renderDevices(fleet.devices || []);
  renderPolicy(fleet.active_policy || {});
  renderConnectors(fleet.connectors || []);
  renderReadiness(fleet.sync_readiness || []);
  renderPortability(fleet.portability || []);
  renderAdminActions(fleet.admin_actions || []);
}

function renderFleetStats(fleet) {
  const root = $("fleetStats");
  if (!root) return;
  const summary = fleet?.summary || {};
  root.innerHTML = `
    <div class="fleet-stat"><strong>${fmtCompact(summary.device_count || 0)}</strong><span>devices</span></div>
    <div class="fleet-stat"><strong>${fmtCompact(summary.online_count || 0)}</strong><span>online</span></div>
    <div class="fleet-stat"><strong>${fmtCompact(summary.enrolled_count || 0)}</strong><span>enrolled</span></div>
    <div class="fleet-stat"><strong>${fmtCompact(summary.blocking_count || 0)}</strong><span>blocking gates</span></div>
    <div class="fleet-stat wide-stat"><strong>${escapeHtml(summary.sync_mode || "local_only")}</strong><span>sync mode</span></div>
  `;
}

function renderDevices(items) {
  const root = $("deviceList");
  if (!root) return;
  if (!items.length) {
    root.innerHTML = `<div class="empty">No enrolled devices yet.</div>`;
    return;
  }
  root.innerHTML = "";
  for (const item of items) {
    const card = document.createElement("article");
    const health = String(item.health || "unknown");
    const lastSample = item.last_age_seconds === null || item.last_age_seconds === undefined
      ? "none"
      : fmtSeconds(item.last_age_seconds);
    card.className = `device-card ${fleetTone(health)}`;
    card.innerHTML = `
      <div class="device-head">
        <div>
          <h3>${escapeHtml(item.name)}</h3>
          <p>${escapeHtml(item.os)} ${escapeHtml(item.os_version)} · ${escapeHtml(item.architecture)} · agent ${escapeHtml(item.agent_version)}</p>
        </div>
        <span class="device-health ${fleetTone(health)}">${escapeHtml(health)}</span>
      </div>
      <div class="device-measures">
        <div><b>${fmtCompact(item.events_in_window)}</b><span>window events</span></div>
        <div><b>${fmtCompact(item.events_all_time)}</b><span>all events</span></div>
        <div><b>${lastSample}</b><span>last sample</span></div>
        <div><b>${fmtBytes(item.db_bytes)}</b><span>local DB</span></div>
      </div>
      <div class="device-path">${escapeHtml(item.id)} · ${escapeHtml(item.db_path)}</div>
      <div class="service-row">
        <span class="chip">collector ${escapeHtml(item.collector?.state || "unknown")}</span>
        <span class="chip">dashboard ${escapeHtml(item.dashboard?.state || "unknown")}</span>
        <span class="chip">policy ${escapeHtml(item.policy_version || "local-dev")}</span>
        <span class="chip">depth ${escapeHtml(item.capture_depth)}</span>
      </div>
    `;
    root.appendChild(card);
  }
}

function renderPolicy(policy) {
  const root = $("policySummary");
  if (!root) return;
  if (!policy) {
    root.innerHTML = `<div class="empty">No active policy.</div>`;
    return;
  }
  const rows = [
    ["Capture depth", `Depth ${policy.capture_depth ?? 1}`],
    ["PII masking", policy.mask_pii ? "on" : "off"],
    ["Browser tab detail", policy.browser_tab_details ? "on" : "off"],
    ["URL paths", policy.browser_url_path ? "stored" : "redacted"],
    ["URL queries", policy.browser_url_query ? "stored" : "redacted"],
    ["Raw upload", policy.raw_event_upload ? "on" : "off"],
    ["Retention", `${policy.retention_days || 30} days`],
  ];
  root.innerHTML = `
    <div class="policy-title">
      <h3>${escapeHtml(policy.name || "Policy")}</h3>
      <span class="chip">${escapeHtml(policy.version || "local-dev")}</span>
    </div>
    ${rows.map(([key, value]) => `<div class="policy-row"><span>${escapeHtml(key)}</span><b>${escapeHtml(value)}</b></div>`).join("")}
  `;
}

function renderConnectors(items) {
  renderStatusList("connectorList", items, "connector-item");
}

function renderReadiness(items) {
  renderStatusList("syncReadiness", items, "readiness-item");
}

function renderPortability(items) {
  renderStatusList("portabilityList", items, "portability-item");
}

function renderAdminActions(items) {
  renderStatusList("adminActions", items, "admin-action");
}

function renderStatusList(id, items, className) {
  const root = $(id);
  if (!root) return;
  if (!items.length) {
    root.innerHTML = `<div class="empty">No items yet.</div>`;
    return;
  }
  root.innerHTML = "";
  for (const item of items) {
    const node = document.createElement("article");
    const tone = fleetTone(item.status);
    node.className = `${className} status-card ${tone}`;
    const depth = item.depth ? `<span class="chip">${escapeHtml(item.depth)}</span>` : "";
    const scope = item.scope ? `<p>${escapeHtml(item.scope)}</p>` : "";
    const sync = item.sync_policy ? `<small>${escapeHtml(item.sync_policy)}</small>` : "";
    node.innerHTML = `
      <div class="status-card-head">
        <h3>${escapeHtml(item.name)}</h3>
        <span class="status-badge ${tone}">${escapeHtml(item.status || "unknown")}</span>
      </div>
      ${depth}
      ${scope}
      <p>${escapeHtml(item.detail || "")}</p>
      ${sync}
    `;
    root.appendChild(node);
  }
}

function populatePackSphereOptions(spheres) {
  const select = $("packSphere");
  if (!select) return;
  const current = select.value;
  select.innerHTML = `<option value="">Auto select</option>`;
  for (const sphere of spheres || []) {
    const option = document.createElement("option");
    option.value = sphere.id;
    option.textContent = `${sphere.state || "unknown"} · ${sphere.label || "Working sphere"}`;
    select.appendChild(option);
  }
  if ([...select.options].some((option) => option.value === current)) {
    select.value = current;
  }
}

function packDecisionTone(decision) {
  if (decision === "allow") return "ready";
  if (decision === "deny" || decision === "mask") return "blocked";
  if (decision === "summarize" || decision === "generalize") return "attention";
  return "neutral";
}

function renderContextPack(pack) {
  state.contextPack = pack || null;
  const status = $("packStatus");
  if (!pack) {
    status.textContent = "No pack";
    status.classList.remove("ready", "blocked");
    renderPackPipeline([]);
    renderAdmissionCounts({});
    renderPackPrivacy({});
    renderPackSummary(null);
    renderPackEvidence(null);
    renderPackRecentPath([]);
    renderAdmissionDecisions([]);
    renderWithheld([]);
    $("markdownPreview").textContent = "";
    return;
  }

  const ready = pack.status === "ready";
  status.textContent = ready ? "Ready" : pack.status === "blocked" ? "Blocked" : "Empty";
  status.classList.toggle("ready", ready);
  status.classList.toggle("blocked", pack.status === "blocked");
  renderPackPipeline(pack.pipeline || []);
  renderAdmissionCounts(pack.admission?.counts || {});
  renderPackPrivacy(pack.privacy || {});
  renderPackSummary(pack);
  renderPackEvidence(pack);
  renderPackRecentPath(pack.context?.recent_path || []);
  renderAdmissionDecisions(pack.admission?.decisions || []);
  renderWithheld(pack.admission?.withheld || []);
  $("markdownPreview").textContent = pack.export?.markdown || "";
}

function renderPackPipeline(items) {
  const root = $("packPipeline");
  if (!root) return;
  if (!items.length) {
    root.innerHTML = `<div class="empty">No pack pipeline yet.</div>`;
    return;
  }
  root.innerHTML = items
    .map((item) => `
      <div class="pack-stage">
        <b>${escapeHtml(item.stage)}</b>
        <span>${escapeHtml(item.state)}</span>
        <p>${escapeHtml(item.output)}</p>
      </div>
    `)
    .join("");
}

function renderAdmissionCounts(counts) {
  const root = $("admissionCounts");
  if (!root) return;
  const order = ["allow", "summarize", "generalize", "mask", "deny"];
  root.innerHTML = order
    .map((name) => `
      <div class="admission-count ${packDecisionTone(name)}">
        <strong>${fmtCompact(counts?.[name] || 0)}</strong>
        <span>${escapeHtml(name)}</span>
      </div>
    `)
    .join("");
}

function renderPackPrivacy(privacy) {
  const root = $("packPrivacy");
  if (!root) return;
  const rows = [
    ["raw events", privacy.raw_events_included ? "included" : "excluded"],
    ["subject id", privacy.subject_id_included ? "included" : "excluded"],
    ["PII mask", privacy.pii_masking ? "on" : "off"],
    ["URL paths", privacy.url_paths || "redacted"],
    ["URL queries", privacy.url_queries || "redacted"],
  ];
  root.innerHTML = rows
    .map(([label, value]) => `<div class="pack-privacy-row"><span>${escapeHtml(label)}</span><b>${escapeHtml(value)}</b></div>`)
    .join("");
}

function renderPackSummary(pack) {
  const root = $("packSummary");
  if (!root) return;
  if (!pack || pack.status !== "ready") {
    const reason = pack?.admission?.target_reason || pack?.selection_reason || "No exportable sphere in this window.";
    root.innerHTML = `<div class="empty">${escapeHtml(reason)}</div>`;
    return;
  }
  const summary = pack.summary || {};
  const sphere = pack.context?.working_sphere || {};
  root.innerHTML = `
    <article class="pack-summary-card ${sphere.gate_mode === "masked" ? "masked" : ""}">
      <div class="pack-summary-head">
        <div>
          <h3>${escapeHtml(summary.title || "Working sphere")}</h3>
          <div class="sphere-meta">
            <span class="chip">${escapeHtml(pack.target?.label || "Target")}</span>
            <span class="chip task-chip">${escapeHtml(summary.task || "task")}</span>
            <span class="chip confidence-chip">${Math.round((summary.confidence || 0) * 100)}% confidence</span>
          </div>
        </div>
        <span class="sphere-state ${escapeHtml(summary.state || "unknown")}">${escapeHtml(summary.state || "unknown")}</span>
      </div>
      <div class="pack-measures">
        <div><b>${fmtHours(summary.hours)}</b><span>hours</span></div>
        <div><b>${fmtCompact(summary.events)}</b><span>events</span></div>
        <div><b>${fmtCompact(summary.session_count)}</b><span>sessions</span></div>
        <div><b>${fmtCompact(summary.return_count)}</b><span>returns</span></div>
      </div>
      <p class="pack-objective">${escapeHtml(summary.objective || "Review and continue the selected work.")}</p>
      <div class="pack-footer">
        <span>Domain ${escapeHtml(summary.domain || "other")}</span>
        <span>Last seen ${fmtTime(summary.last_seen)}</span>
        <span>${escapeHtml(sphere.gate_mode || "allowed")} gate</span>
      </div>
    </article>
  `;
}

function renderPackEvidence(pack) {
  const root = $("packEvidence");
  if (!root) return;
  if (!pack || pack.status !== "ready") {
    root.innerHTML = `<div class="empty">No admitted evidence.</div>`;
    return;
  }
  const apps = pack.context?.apps || [];
  const artifacts = pack.context?.top_artifacts || [];
  const keywords = pack.context?.keywords || [];
  const appRows = apps
    .map((item) => `<span class="chip">${escapeHtml(item.name)} · ${item.events}</span>`)
    .join("");
  const artifactRows = artifacts
    .map((item) => `<div class="pack-artifact"><span>${escapeHtml(item.name)}</span><b>${fmtSeconds(item.dwell_seconds)}</b></div>`)
    .join("");
  root.innerHTML = `
    <div class="pack-evidence-section">
      <h4>Apps</h4>
      <div class="sphere-chip-row">${appRows || `<span class="muted-text">No app signal</span>`}</div>
    </div>
    <div class="pack-evidence-section">
      <h4>Artifacts</h4>
      <div class="pack-artifacts">${artifactRows || `<div class="muted-text">No artifact signal</div>`}</div>
    </div>
    <div class="pack-evidence-section">
      <h4>Keywords</h4>
      <p>${escapeHtml(keywords.length ? keywords.join(", ") : "none")}</p>
    </div>
  `;
}

function renderPackRecentPath(items) {
  const root = $("packRecentPath");
  if (!root) return;
  if (!items.length) {
    root.innerHTML = `<div class="empty">No recent path in this pack.</div>`;
    return;
  }
  root.innerHTML = "";
  for (const item of items) {
    const node = document.createElement("article");
    node.className = `pack-path-item ${item.gate_mode === "masked" ? "masked" : ""}`;
    node.innerHTML = `
      <div>
        <b>${escapeHtml(item.app || "unknown app")}</b>
        <span>${fmtTime(item.time)} · ${escapeHtml(item.domain || "other")} · ${fmtSeconds(item.dwell_seconds)}</span>
      </div>
      <p>${escapeHtml(item.artifact || "unknown artifact")}</p>
      <span class="status-badge ${packDecisionTone(item.gate_mode === "masked" ? "mask" : "allow")}">${escapeHtml(item.gate_mode || "allowed")}</span>
    `;
    root.appendChild(node);
  }
}

function renderAdmissionDecisions(items) {
  const root = $("admissionDecisions");
  if (!root) return;
  if (!items.length) {
    root.innerHTML = `<div class="empty">No gate decisions yet.</div>`;
    return;
  }
  root.innerHTML = "";
  for (const item of items) {
    const tone = packDecisionTone(item.decision);
    const node = document.createElement("article");
    node.className = `admission-decision ${tone}`;
    node.innerHTML = `
      <div class="status-card-head">
        <h3>${escapeHtml(item.field)}</h3>
        <span class="status-badge ${tone}">${escapeHtml(item.decision)}</span>
      </div>
      <p>${escapeHtml(item.reason)}</p>
    `;
    root.appendChild(node);
  }
}

function renderWithheld(items) {
  const root = $("withheldList");
  if (!root) return;
  if (!items.length) {
    root.innerHTML = `<div class="empty">Nothing withheld.</div>`;
    return;
  }
  root.innerHTML = "";
  for (const item of items) {
    const node = document.createElement("article");
    node.className = "withheld-item";
    node.innerHTML = `<h3>${escapeHtml(item.field)}</h3><p>${escapeHtml(item.reason)}</p>`;
    root.appendChild(node);
  }
}

async function buildContextPack(showReadyToast = true) {
  const params = new URLSearchParams({
    days: String(state.days),
    purpose: $("packPurpose").value,
    target: $("packTarget").value,
    max_events: "8",
  });
  const sphereId = $("packSphere").value;
  if (sphereId) params.set("sphere_id", sphereId);
  const pack = await getJson(`/api/context-pack?${params.toString()}`);
  renderContextPack(pack);
  if (showReadyToast) {
    showToast(pack.status === "ready" ? "Context pack ready" : `Context pack ${pack.status}`);
  }
}

async function copyContextPack() {
  const markdown = state.contextPack?.export?.markdown || "";
  if (!markdown) {
    showToast("No context pack to copy");
    return;
  }
  try {
    await navigator.clipboard.writeText(markdown);
    showToast("Context pack markdown copied");
  } catch (error) {
    showToast("Clipboard write was blocked by the browser");
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
  populatePackSphereOptions(activities?.spheres || []);
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

function drawGraphLabel(ctx, text, x, y, align = "center", maxChars = 28) {
  const label = String(text || "");
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
  renderTwinExperience(overview);
  renderInsights(overview.insights);
  renderDomains(overview.domains);
  renderHeatmap(overview.hourly_heatmap);
  renderRankList("topArtifacts", overview.top_artifacts);
  renderRankList("topApps", overview.top_apps);
  renderTransitions(overview.transitions);
  renderAttentionDepth(overview.attention_depth);
  renderFleet(overview.fleet);
  renderActivities(overview.working_spheres);
  renderContextPack(overview.context_pack);
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

  $("buildPackBtn").addEventListener("click", async () => {
    try {
      await buildContextPack();
    } catch (error) {
      showToast(error.message);
    }
  });

  $("copyPackBtn").addEventListener("click", copyContextPack);

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
      if (document.querySelector("#overview.active-view") && state.overview) {
        drawTwinMap(state.overview);
      }
    }, 120);
  });
}

bindUi();
refresh()
  .then(() => runEvidenceQuery($("queryInput").value))
  .catch((error) => showToast(error.message));

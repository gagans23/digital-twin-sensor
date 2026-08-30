const canvas = document.getElementById("contextCanvas");
const ctx = canvas.getContext("2d");
const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
let width = 0;
let height = 0;
let dpr = 1;
let points = [];
let pointer = { x: 0, y: 0, active: false };

const colors = ["#9fb49f", "#c06a4d", "#a37d3f", "#6f8675", "#fbf6ec"];

function resizeCanvas() {
  const rect = canvas.getBoundingClientRect();
  dpr = Math.min(window.devicePixelRatio || 1, 2);
  width = Math.max(1, Math.floor(rect.width));
  height = Math.max(1, Math.floor(rect.height));
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  buildPoints();
}

function buildPoints() {
  const count = Math.round(Math.min(88, Math.max(38, width / 16)));
  points = Array.from({ length: count }, (_, index) => {
    const ring = index % 5;
    return {
      x: Math.random() * width,
      y: Math.random() * height,
      baseX: Math.random() * width,
      baseY: Math.random() * height,
      vx: (Math.random() - 0.5) * 0.28,
      vy: (Math.random() - 0.5) * 0.28,
      r: 1.8 + Math.random() * 4.2,
      color: colors[ring],
      phase: Math.random() * Math.PI * 2,
      gate: ring === 1 || ring === 3,
    };
  });
}

function drawGrid(time) {
  ctx.save();
  ctx.globalAlpha = 0.16;
  ctx.strokeStyle = "#181614";
  ctx.lineWidth = 1;
  const offset = (time * 0.006) % 44;
  for (let x = -44 + offset; x < width + 44; x += 44) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
  }
  for (let y = -44 + offset; y < height + 44; y += 44) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }
  ctx.restore();
}

function draw(time = 0) {
  ctx.clearRect(0, 0, width, height);
  const gradient = ctx.createRadialGradient(width * 0.66, height * 0.42, 20, width * 0.66, height * 0.42, Math.max(width, height) * 0.8);
  gradient.addColorStop(0, "rgba(111, 134, 117, 0.28)");
  gradient.addColorStop(0.38, "rgba(181, 92, 65, 0.12)");
  gradient.addColorStop(1, "rgba(8, 10, 15, 0)");
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, width, height);
  drawGrid(time);

  const cx = width * 0.68;
  const cy = height * 0.48;
  const orbit = Math.min(width, height) * 0.28;

  ctx.save();
  ctx.globalAlpha = 0.34;
  for (let i = 1; i <= 4; i += 1) {
    ctx.beginPath();
    ctx.ellipse(cx, cy, orbit * (0.36 + i * 0.18), orbit * (0.2 + i * 0.12), i * 0.42 + time * 0.00008, 0, Math.PI * 2);
    ctx.strokeStyle = i % 2 ? "#9fb49f" : "#c06a4d";
    ctx.lineWidth = 1;
    ctx.stroke();
  }
  ctx.restore();

  for (const point of points) {
    if (!prefersReduced) {
      point.x += point.vx + Math.sin(time * 0.001 + point.phase) * 0.08;
      point.y += point.vy + Math.cos(time * 0.001 + point.phase) * 0.08;
      if (point.x < -40) point.x = width + 40;
      if (point.x > width + 40) point.x = -40;
      if (point.y < -40) point.y = height + 40;
      if (point.y > height + 40) point.y = -40;
    }
    if (pointer.active) {
      const dx = point.x - pointer.x;
      const dy = point.y - pointer.y;
      const dist = Math.hypot(dx, dy);
      if (dist < 160 && dist > 0) {
        const push = (160 - dist) / 160;
        point.x += (dx / dist) * push * 1.7;
        point.y += (dy / dist) * push * 1.7;
      }
    }
  }

  for (let i = 0; i < points.length; i += 1) {
    for (let j = i + 1; j < points.length; j += 1) {
      const a = points[i];
      const b = points[j];
      const dist = Math.hypot(a.x - b.x, a.y - b.y);
      if (dist < 118) {
        ctx.globalAlpha = (1 - dist / 118) * 0.2;
        ctx.strokeStyle = a.gate || b.gate ? "#c06a4d" : "#9fb49f";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
      }
    }
  }

  ctx.globalAlpha = 1;
  for (const point of points) {
    ctx.beginPath();
    ctx.arc(point.x, point.y, point.r, 0, Math.PI * 2);
    ctx.fillStyle = point.color;
    ctx.fill();
    if (point.gate) {
      ctx.strokeStyle = "rgba(255, 255, 255, 0.38)";
      ctx.lineWidth = 1;
      ctx.stroke();
    }
  }

  if (!prefersReduced) {
    window.requestAnimationFrame(draw);
  }
}

const revealNodes = Array.from(document.querySelectorAll(".reveal"));
const markInitiallyVisible = () => {
  for (const node of revealNodes) {
    const rect = node.getBoundingClientRect();
    if (rect.top < window.innerHeight * 0.95) {
      node.classList.add("in-view");
    }
  }
};

if ("IntersectionObserver" in window) {
  const observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          entry.target.classList.add("in-view");
        }
      }
    },
    { threshold: 0.18 }
  );

  revealNodes.forEach((node) => observer.observe(node));
} else {
  revealNodes.forEach((node) => node.classList.add("in-view"));
}

window.addEventListener("resize", resizeCanvas);
window.addEventListener("pointermove", (event) => {
  pointer = { x: event.clientX, y: event.clientY, active: true };
});
window.addEventListener("pointerleave", () => {
  pointer.active = false;
});

resizeCanvas();
draw();
markInitiallyVisible();
document.documentElement.classList.add("motion-ready");

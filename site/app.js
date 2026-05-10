const header = document.querySelector(".site-header");
const canvas = document.querySelector("#repricer-canvas");
const ctx = canvas.getContext("2d");
const yourPrice = document.querySelector("#your-price");
const marketPrice = document.querySelector("#market-price");
const nextPrice = document.querySelector("#next-price");

const palette = {
  text: "rgba(243, 247, 251, 0.92)",
  grid: "rgba(255, 255, 255, 0.08)",
  mint: "#43f0b3",
  cyan: "#72dcff",
  amber: "#ffca6b",
  rose: "#ff6f91",
};

const priceSamples = [
  [1249, 1217, 1216],
  [1249, 1198, 1197],
  [1197, 1205, 1197],
  [1197, 1174, 1180],
  [1180, 1169, 1180],
  [1180, 1222, 1180],
];

let width = 0;
let height = 0;
let dpr = 1;
let frame = 0;
let priceIndex = 0;

function resizeCanvas() {
  dpr = Math.min(window.devicePixelRatio || 1, 2);
  width = canvas.clientWidth;
  height = canvas.clientHeight;
  canvas.width = Math.floor(width * dpr);
  canvas.height = Math.floor(height * dpr);
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}

function formatPrice(value) {
  return `${value.toLocaleString("uk-UA")} ₴`;
}

function updatePrices() {
  const [own, market, next] = priceSamples[priceIndex % priceSamples.length];
  yourPrice.textContent = formatPrice(own);
  marketPrice.textContent = formatPrice(market);
  nextPrice.textContent = formatPrice(next);
  priceIndex += 1;
}

function drawGrid() {
  ctx.strokeStyle = palette.grid;
  ctx.lineWidth = 1;
  const gap = width < 640 ? 48 : 64;

  for (let x = (frame * 0.18) % gap; x < width; x += gap) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();
  }

  for (let y = 0; y < height; y += gap) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  }
}

function drawCurve(points, color, offset = 0) {
  ctx.strokeStyle = color;
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  points.forEach((point, index) => {
    const pulse = Math.sin(frame * 0.03 + index + offset) * 8;
    const x = point.x;
    const y = point.y + pulse;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.stroke();

  points.forEach((point, index) => {
    const pulse = Math.sin(frame * 0.03 + index + offset) * 8;
    ctx.beginPath();
    ctx.fillStyle = color;
    ctx.arc(point.x, point.y + pulse, index === points.length - 1 ? 5 : 3, 0, Math.PI * 2);
    ctx.fill();
  });
}

function drawNodes() {
  const centerY = height * 0.5;
  const nodes = [
    { x: width * 0.18, y: centerY - 84, label: "Competitors", color: palette.cyan },
    { x: width * 0.48, y: centerY + 6, label: "Strategy", color: palette.mint },
    { x: width * 0.78, y: centerY - 52, label: "Prom API", color: palette.amber },
  ];

  nodes.forEach((node, index) => {
    const breathe = Math.sin(frame * 0.035 + index) * 3;
    ctx.fillStyle = "rgba(8, 11, 15, 0.78)";
    ctx.strokeStyle = node.color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.roundRect(node.x - 70, node.y - 28 + breathe, 140, 56, 8);
    ctx.fill();
    ctx.stroke();

    ctx.fillStyle = palette.text;
    ctx.font = "700 13px Inter, system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.fillText(node.label, node.x, node.y + 5 + breathe);
  });

  ctx.strokeStyle = "rgba(67, 240, 179, 0.38)";
  ctx.lineWidth = 1.5;
  ctx.setLineDash([8, 10]);
  ctx.beginPath();
  ctx.moveTo(nodes[0].x + 70, nodes[0].y);
  ctx.bezierCurveTo(width * 0.34, centerY - 120, width * 0.34, centerY + 60, nodes[1].x - 70, nodes[1].y);
  ctx.bezierCurveTo(width * 0.6, centerY + 90, width * 0.64, centerY - 120, nodes[2].x - 70, nodes[2].y);
  ctx.stroke();
  ctx.setLineDash([]);
}

function drawMarketChart() {
  const left = width * 0.08;
  const top = height * 0.68;
  const chartWidth = width * 0.54;
  const chartHeight = Math.min(170, height * 0.18);
  const count = 8;

  const competitor = [];
  const own = [];
  for (let i = 0; i < count; i += 1) {
    const x = left + (chartWidth / (count - 1)) * i;
    competitor.push({
      x,
      y: top + chartHeight * (0.28 + Math.sin(frame * 0.018 + i * 0.8) * 0.22),
    });
    own.push({
      x,
      y: top + chartHeight * (0.55 + Math.cos(frame * 0.014 + i * 0.7) * 0.17),
    });
  }

  ctx.fillStyle = "rgba(8, 11, 15, 0.45)";
  ctx.strokeStyle = "rgba(255, 255, 255, 0.12)";
  ctx.beginPath();
  ctx.roundRect(left - 18, top - 30, chartWidth + 36, chartHeight + 62, 8);
  ctx.fill();
  ctx.stroke();

  drawCurve(competitor, palette.rose, 1.1);
  drawCurve(own, palette.mint, 0);

  ctx.fillStyle = "rgba(243, 247, 251, 0.72)";
  ctx.font = "700 12px Inter, system-ui, sans-serif";
  ctx.textAlign = "left";
  ctx.fillText("market drift", left, top - 10);
}

function animate() {
  frame += 1;
  ctx.clearRect(0, 0, width, height);
  drawGrid();
  drawNodes();
  drawMarketChart();
  requestAnimationFrame(animate);
}

window.addEventListener("resize", resizeCanvas);
window.addEventListener("scroll", () => {
  header.dataset.elevated = window.scrollY > 16 ? "true" : "false";
});

if (window.lucide) {
  window.lucide.createIcons();
}

resizeCanvas();
animate();
updatePrices();
setInterval(updatePrices, 1900);

"""
app.py — Flask app: SVG Fillet STL Generator
Buinho FabLab · Messejana, Alentejo · CC-BY-SA 4.0
"""

import os
import io
import traceback
from flask import Flask, request, send_file, jsonify, render_template_string
from svg_to_stl import svg_bytes_to_stl

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max

HTML = r"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SVG → STL com Arestas Arredondadas · Buinho FabLab</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=ASAP:ital,wght@0,400;0,600;0,700;1,400&display=swap" rel="stylesheet">
<style>
  :root {
    --creme:  #FAF0E1;
    --azul:   #2038A6;
    --laranja:#FA6415;
    --preto:  #1a1a1a;
    --cinza:  #e8ddd0;
    --sombra: rgba(32,56,166,0.10);
  }

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: 'ASAP', sans-serif;
    background: var(--creme);
    color: var(--preto);
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }

  /* ── Header ── */
  header {
    background: var(--azul);
    color: #fff;
    padding: 1.5rem 2rem 1.2rem;
    display: flex;
    align-items: flex-start;
    gap: 1.4rem;
  }
  .logo-block {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
  }
  .logo-block svg { width: 48px; height: 48px; }
  .logo-label {
    font-size: 0.6rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    opacity: 0.75;
    color: #fff;
    white-space: nowrap;
  }
  .header-text h1 {
    font-size: clamp(1.1rem, 3vw, 1.5rem);
    font-weight: 700;
    line-height: 1.2;
  }
  .header-text p {
    font-size: 0.85rem;
    opacity: 0.82;
    margin-top: 0.25rem;
    line-height: 1.4;
  }
  .lang-badge {
    margin-left: auto;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 4px;
    font-size: 0.72rem;
    opacity: 0.7;
    white-space: nowrap;
  }

  /* ── Main ── */
  main {
    flex: 1;
    max-width: 720px;
    width: 100%;
    margin: 0 auto;
    padding: 2rem 1.5rem;
    display: flex;
    flex-direction: column;
    gap: 1.8rem;
  }

  /* ── Cards ── */
  .card {
    background: #fff;
    border-radius: 12px;
    padding: 1.6rem;
    box-shadow: 0 2px 12px var(--sombra);
  }
  .card h2 {
    font-size: 0.78rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--azul);
    margin-bottom: 1rem;
  }

  /* ── Drop zone ── */
  .drop-zone {
    border: 2.5px dashed var(--cinza);
    border-radius: 10px;
    padding: 2.5rem 1rem;
    text-align: center;
    cursor: pointer;
    transition: border-color 0.2s, background 0.2s;
    position: relative;
    background: var(--creme);
  }
  .drop-zone.active {
    border-color: var(--laranja);
    background: #fff5ee;
  }
  .drop-zone.has-file {
    border-color: var(--azul);
    background: #f0f4ff;
  }
  .drop-zone input[type="file"] {
    position: absolute; inset: 0; opacity: 0; cursor: pointer; width: 100%; height: 100%;
  }
  .drop-icon {
    font-size: 2.8rem;
    margin-bottom: 0.5rem;
    display: block;
    line-height: 1;
  }
  .drop-text { font-size: 0.95rem; color: #555; }
  .drop-text strong { color: var(--azul); }
  .file-name {
    margin-top: 0.6rem;
    font-size: 0.82rem;
    font-weight: 600;
    color: var(--laranja);
    display: none;
  }

  /* ── Sliders ── */
  .params { display: grid; grid-template-columns: 1fr 1fr; gap: 1.2rem; }
  @media (max-width: 480px) { .params { grid-template-columns: 1fr; } }

  .param-group label {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    font-size: 0.82rem;
    font-weight: 600;
    color: var(--azul);
    margin-bottom: 0.45rem;
  }
  .param-group label .val {
    font-weight: 700;
    font-size: 1rem;
    color: var(--laranja);
  }
  input[type="range"] {
    -webkit-appearance: none;
    width: 100%;
    height: 6px;
    border-radius: 3px;
    background: var(--cinza);
    outline: none;
    cursor: pointer;
  }
  input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 20px; height: 20px;
    border-radius: 50%;
    background: var(--azul);
    cursor: pointer;
    border: 2px solid #fff;
    box-shadow: 0 1px 4px var(--sombra);
    transition: background 0.15s;
  }
  input[type="range"]::-webkit-slider-thumb:hover { background: var(--laranja); }
  input[type="range"]::-moz-range-thumb {
    width: 20px; height: 20px;
    border-radius: 50%;
    background: var(--azul);
    cursor: pointer;
    border: 2px solid #fff;
  }
  .param-hint {
    font-size: 0.72rem;
    color: #888;
    margin-top: 0.3rem;
  }

  /* ── Preview diagram ── */
  .preview-wrap {
    display: flex;
    justify-content: center;
    margin-top: 0.5rem;
  }
  #section-svg { width: 100%; max-width: 320px; height: auto; }

  /* ── Button ── */
  .btn-generate {
    display: block;
    width: 100%;
    padding: 1rem;
    background: var(--laranja);
    color: #fff;
    font-family: 'ASAP', sans-serif;
    font-size: 1.05rem;
    font-weight: 700;
    border: none;
    border-radius: 10px;
    cursor: pointer;
    letter-spacing: 0.02em;
    transition: background 0.2s, transform 0.1s;
    box-shadow: 0 3px 10px rgba(250,100,21,0.3);
  }
  .btn-generate:hover { background: #e05510; }
  .btn-generate:active { transform: scale(0.98); }
  .btn-generate:disabled { background: #ccc; cursor: not-allowed; box-shadow: none; }

  /* ── Status messages ── */
  .status {
    display: none;
    padding: 1rem 1.2rem;
    border-radius: 8px;
    font-size: 0.9rem;
    font-weight: 600;
    line-height: 1.5;
  }
  .status.loading {
    display: flex; align-items: center; gap: 0.8rem;
    background: #eef2ff; color: var(--azul);
  }
  .status.success {
    display: flex; align-items: center; gap: 0.8rem;
    background: #eaffea; color: #1a6b1a;
  }
  .status.error {
    display: block;
    background: #fff0f0; color: #b00;
  }
  .spinner {
    width: 22px; height: 22px; flex-shrink: 0;
    border: 3px solid #c5cff5;
    border-top-color: var(--azul);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── Explainer ── */
  .explainer {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1rem;
  }
  @media (max-width: 480px) { .explainer { grid-template-columns: 1fr; } }
  .explain-item { display: flex; gap: 0.8rem; align-items: flex-start; }
  .explain-icon { font-size: 1.5rem; flex-shrink: 0; margin-top: 2px; }
  .explain-item h3 { font-size: 0.82rem; font-weight: 700; color: var(--azul); margin-bottom: 2px; }
  .explain-item p { font-size: 0.78rem; color: #666; line-height: 1.4; }

  /* ── Footer ── */
  footer {
    background: var(--azul);
    color: rgba(255,255,255,0.7);
    text-align: center;
    padding: 1rem;
    font-size: 0.72rem;
    line-height: 1.6;
  }
  footer a { color: rgba(255,255,255,0.9); }

  /* ── EN section ── */
  details { border-top: 1px solid var(--cinza); margin-top: 0.8rem; padding-top: 0.8rem; }
  details summary {
    cursor: pointer;
    font-size: 0.78rem;
    color: var(--azul);
    font-weight: 600;
    letter-spacing: 0.05em;
  }
  details p { margin-top: 0.6rem; font-size: 0.8rem; color: #555; line-height: 1.5; }
</style>
</head>
<body>

<header>
  <div class="logo-block">
    <!-- Buinho logo mark — square + circle Fröbel geometry, Educativo palette -->
    <svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">
      <rect x="4" y="4" width="40" height="40" rx="4" fill="#FA6415"/>
      <rect x="12" y="12" width="24" height="24" rx="2" fill="#FAF0E1"/>
      <circle cx="24" cy="24" r="8" fill="#2038A6"/>
    </svg>
    <span class="logo-label">Buinho FabLab</span>
  </div>
  <div class="header-text">
    <h1>SVG → STL<br>Arestas Arredondadas</h1>
    <p>Transforma contornos SVG em paredes 3D com bordas superiores suavizadas — pronto para impressão tátil ou vacuum forming.</p>
  </div>
</header>

<main>

  <!-- Explainer -->
  <div class="card">
    <h2>Para que serve</h2>
    <div class="explainer">
      <div class="explain-item">
        <span class="explain-icon">✋</span>
        <div>
          <h3>Impressão tátil</h3>
          <p>Arestas vivas magoam os dedos. O fillet arredondado torna os modelos seguros para exploração tátil por alunos invisuais.</p>
        </div>
      </div>
      <div class="explain-item">
        <span class="explain-icon">🔵</span>
        <div>
          <h3>Vacuum forming</h3>
          <p>Matrizes com arestas a 90° rasgam o plástico. Um raio de fillet suave distribui a tensão e evita defeitos no produto final.</p>
        </div>
      </div>
      <div class="explain-item">
        <span class="explain-icon">📐</span>
        <div>
          <h3>Importar SVG</h3>
          <p>Exporta o teu desenho do Tinkercad, Inkscape ou Illustrator como SVG com paths fechados. O gerador faz o resto.</p>
        </div>
      </div>
      <div class="explain-item">
        <span class="explain-icon">📦</span>
        <div>
          <h3>STL direto para slicer</h3>
          <p>O ficheiro gerado é watertight e importável directamente no Tinkercad, PrusaSlicer, Cura ou qualquer slicer.</p>
        </div>
      </div>
    </div>

    <details>
      <summary>🇬🇧 English</summary>
      <p>This tool converts SVG outlines into extruded 3D walls with a rounded fillet on the top edge. Useful for tactile models for visually impaired students (sharp edges hurt fingers) and for vacuum forming matrices (sharp corners tear plastic). Upload an SVG with closed paths, set wall height and fillet radius, and download a watertight STL.</p>
    </details>
  </div>

  <!-- Upload -->
  <div class="card">
    <h2>1 · Ficheiro SVG</h2>
    <div class="drop-zone" id="dropZone">
      <input type="file" id="svgFile" accept=".svg,image/svg+xml">
      <span class="drop-icon">📂</span>
      <div class="drop-text"><strong>Clica</strong> ou arrasta um ficheiro SVG para aqui</div>
      <div class="file-name" id="fileName"></div>
    </div>
  </div>

  <!-- Parameters -->
  <div class="card">
    <h2>2 · Parâmetros</h2>
    <div class="params">
      <div class="param-group">
        <label>
          Altura da parede
          <span class="val" id="heightVal">5.0 mm</span>
        </label>
        <input type="range" id="wallHeight" min="1" max="30" step="0.5" value="5">
        <div class="param-hint">Altura total da parede extrudida</div>
      </div>
      <div class="param-group">
        <label>
          Raio do fillet
          <span class="val" id="filletVal">1.0 mm</span>
        </label>
        <input type="range" id="filletRadius" min="0.2" max="8" step="0.1" value="1">
        <div class="param-hint">Raio do arredondamento superior (≤ metade da altura)</div>
      </div>
    </div>

    <!-- Cross-section preview SVG -->
    <div class="preview-wrap">
      <svg id="section-svg" viewBox="0 0 200 140" xmlns="http://www.w3.org/2000/svg">
        <!-- drawn by JS -->
      </svg>
    </div>
  </div>

  <!-- Generate -->
  <div class="card">
    <h2>3 · Gerar STL</h2>
    <button class="btn-generate" id="btnGenerate" disabled>
      Gerar STL com Arestas Arredondadas
    </button>
    <div class="status loading" id="statusLoading">
      <div class="spinner"></div>
      <span>A processar o SVG e a gerar geometria 3D… pode demorar alguns segundos.</span>
    </div>
    <div class="status success" id="statusSuccess">
      <span>✅</span>
      <span id="successMsg">STL gerado com sucesso! O download iniciou automaticamente.</span>
    </div>
    <div class="status error" id="statusError"></div>
  </div>

</main>

<footer>
  Buinho FabLab · Messejana, Alentejo, Portugal · <a href="https://buinho.pt" target="_blank">buinho.pt</a><br>
  Licença <a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank">CC-BY-SA 4.0</a>
  · Ferramenta open-source para educação maker e acessibilidade
</footer>

<script>
const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('svgFile');
const fileName  = document.getElementById('fileName');
const btnGen    = document.getElementById('btnGenerate');
const wallSlider   = document.getElementById('wallHeight');
const filletSlider = document.getElementById('filletRadius');
const heightVal = document.getElementById('heightVal');
const filletVal = document.getElementById('filletVal');
const sectionSvg = document.getElementById('section-svg');

let selectedFile = null;

// ── File selection ────────────────────────────────────────────────
fileInput.addEventListener('change', e => {
  if (e.target.files[0]) setFile(e.target.files[0]);
});
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('active'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('active'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('active');
  if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
});
function setFile(f) {
  if (!f.name.toLowerCase().endsWith('.svg')) {
    showError('Por favor escolhe um ficheiro .svg');
    return;
  }
  selectedFile = f;
  fileName.textContent = f.name;
  fileName.style.display = 'block';
  dropZone.classList.add('has-file');
  btnGen.disabled = false;
  clearStatus();
}

// ── Sliders ──────────────────────────────────────────────────────
wallSlider.addEventListener('input', () => {
  const h = parseFloat(wallSlider.value);
  heightVal.textContent = h.toFixed(1) + ' mm';
  // Clamp fillet ≤ h/2
  const maxF = h / 2;
  if (parseFloat(filletSlider.value) > maxF) {
    filletSlider.value = maxF.toFixed(1);
    filletVal.textContent = maxF.toFixed(1) + ' mm';
  }
  filletSlider.max = maxF;
  drawSection();
});
filletSlider.addEventListener('input', () => {
  filletVal.textContent = parseFloat(filletSlider.value).toFixed(1) + ' mm';
  drawSection();
});

// ── Cross-section preview ─────────────────────────────────────────
// Shows the wall profile: flat bottom, vertical sides, rounded top edges.
// SVG coordinate system: Y increases downward.
// Wall sits with base at bottom, rounded cap at top.
function drawSection() {
  const H = parseFloat(wallSlider.value);
  const R = parseFloat(filletSlider.value);

  // Fixed display dimensions (mm → px mapping fits inside 200×140 viewBox)
  const VW = 200, VH = 140;
  const margin = { left: 38, right: 18, top: 18, bottom: 22 };
  const availH = VH - margin.top - margin.bottom;  // 100px
  const availW = VW - margin.left - margin.right;   // 144px

  const scale = availH / Math.max(H, 8);  // px per mm, capped so tall walls fit
  const Hpx = H * scale;
  const Rpx = Math.min(R * scale, Hpx * 0.48);
  const Wpx = Math.min(availW * 0.55, Hpx * 1.4); // wall width proportional but bounded

  // Anchor: bottom-left of wall
  const bx = margin.left + (availW - Wpx) / 2;  // horizontally centred
  const by = margin.top + availH;                 // bottom of wall

  const topY    = by - Hpx;          // top surface Y
  const arcBaseY = topY + Rpx;       // where straight section ends, arc begins

  // Build the cross-section profile path (one half-slice showing left wall + top)
  // Points go: bottom-left → up straight section → quarter-arc outward-left →
  //            across top → quarter-arc outward-right → down → bottom-right → close
  const arcN = 20;
  let pts = [];

  // bottom-left
  pts.push([bx, by]);
  // straight left wall up to arc start
  pts.push([bx, arcBaseY]);
  // LEFT top arc: centre at (bx, topY), arc goes from 180° → 270° (outward = left = -x)
  for (let i = 0; i <= arcN; i++) {
    const a = Math.PI + (Math.PI / 2) * (i / arcN); // 180° → 270°
    const x = bx + Rpx * Math.cos(a);   // bx - Rpx*cos → bx
    const y = topY + Rpx * Math.sin(a); // topY → topY + Rpx = arcBaseY
    // Remap: at i=0 (180°): x=bx-Rpx, y=topY  → outside-left, top
    //        at i=arcN(270°): x=bx, y=topY+Rpx  → wall face, arc-base ✓
    // Actually we want: start at (bx, arcBaseY) going UP and curving inward to (bx+Rpx, topY)
    // Use: angle 270°→360°, centre at (bx+Rpx, arcBaseY)
    pts.pop(); // remove last, rebuild below
    break;
  }
  // Redo left arc: centre at (bx + Rpx, arcBaseY), quarter from 180° to 90° (going up-left)
  pts.push([bx, arcBaseY]); // start of arc on left face
  for (let i = 1; i <= arcN; i++) {
    const a = Math.PI - (Math.PI / 2) * (i / arcN); // 180° → 90°
    const x = (bx + Rpx) + Rpx * Math.cos(a); // bx+Rpx - Rpx → bx+Rpx+0 ... wait
    // Centre = (bx + Rpx, arcBaseY); radius = Rpx
    // At a=180°: x=bx+Rpx-Rpx=bx, y=arcBaseY ✓ (on left wall face)
    // At a=90°:  x=bx+Rpx, y=arcBaseY-Rpx=topY ✓ (on top surface)
    const px = (bx + Rpx) + Rpx * Math.cos(a);
    const py = arcBaseY   + Rpx * Math.sin(a);  // sin(180°)=0, sin(90°)=1 → goes UP (lower y)
    // sin(180°→90°): 0 → 1, so py goes from arcBaseY → arcBaseY+Rpx  — that's DOWN, not up
    // Fix: negate sin
    const px2 = (bx + Rpx) + Rpx * Math.cos(a);
    const py2 = arcBaseY   - Rpx * Math.sin(a); // arcBaseY → arcBaseY-Rpx = topY ✓
    pts.push([px2, py2]);
  }
  // top surface: from (bx+Rpx, topY) to (bx+Wpx-Rpx, topY)
  pts.push([bx + Wpx - Rpx, topY]);
  // RIGHT top arc: centre at (bx+Wpx-Rpx, arcBaseY), quarter from 90°→0°
  for (let i = 1; i <= arcN; i++) {
    const a = (Math.PI / 2) * (1 - i / arcN); // 90° → 0°
    const px = (bx + Wpx - Rpx) + Rpx * Math.cos(a);
    const py = arcBaseY          - Rpx * Math.sin(a);
    pts.push([px, py]);
  }
  // straight right wall down
  pts.push([bx + Wpx, by]);

  const d = 'M' + pts.map(p => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' L') + ' Z';

  // Dimension annotations
  const dimX = bx - 6;           // left of wall
  const hLabelY = (by + topY) / 2 + 4;
  const rLabelY = (arcBaseY + topY) / 2 + 3;
  const baseY = by + 10;

  sectionSvg.innerHTML = `
    <rect width="${VW}" height="${VH}" fill="#f9f6f1" rx="8"/>

    <!-- Ground line -->
    <line x1="${bx - 4}" y1="${by}" x2="${bx + Wpx + 4}" y2="${by}"
          stroke="#bbb" stroke-width="1"/>

    <!-- Wall shape -->
    <path d="${d}" fill="#2038A6" fill-opacity="0.15"
          stroke="#2038A6" stroke-width="1.8" stroke-linejoin="round"/>

    <!-- Fillet arc highlight in orange -->
    <path d="M${bx.toFixed(1)},${arcBaseY.toFixed(1)}
             ${pts.slice(1, arcN+2).map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ')}"
          fill="none" stroke="#FA6415" stroke-width="2" stroke-linecap="round"/>
    <path d="M${(bx+Wpx-Rpx).toFixed(1)},${topY.toFixed(1)}
             ${pts.slice(arcN+3, arcN*2+4).map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ')}"
          fill="none" stroke="#FA6415" stroke-width="2" stroke-linecap="round"/>

    <!-- Height dimension line -->
    <line x1="${dimX}" y1="${by}" x2="${dimX}" y2="${topY}"
          stroke="#FA6415" stroke-width="1.2" stroke-dasharray="3,2"/>
    <line x1="${dimX-3}" y1="${by}" x2="${dimX+3}" y2="${by}" stroke="#FA6415" stroke-width="1.5"/>
    <line x1="${dimX-3}" y1="${topY}" x2="${dimX+3}" y2="${topY}" stroke="#FA6415" stroke-width="1.5"/>
    <text x="${dimX - 4}" y="${hLabelY}" text-anchor="end"
          font-family="ASAP,sans-serif" font-size="10" font-weight="700" fill="#FA6415">${H.toFixed(1)}mm</text>

    <!-- Fillet radius dimension -->
    ${Rpx > 6 ? `
    <line x1="${(bx+Wpx+6).toFixed(1)}" y1="${arcBaseY.toFixed(1)}"
          x2="${(bx+Wpx+6).toFixed(1)}" y2="${topY.toFixed(1)}"
          stroke="#2038A6" stroke-width="1" stroke-dasharray="2,2"/>
    <text x="${(bx+Wpx+10).toFixed(1)}" y="${rLabelY.toFixed(1)}"
          font-family="ASAP,sans-serif" font-size="9" font-weight="700" fill="#2038A6">r=${R.toFixed(1)}</text>
    ` : `
    <text x="${(bx+Wpx/2).toFixed(1)}" y="${(topY-5).toFixed(1)}"
          text-anchor="middle" font-family="ASAP,sans-serif" font-size="8" fill="#2038A6">r=${R.toFixed(1)}mm</text>
    `}

    <!-- Label -->
    <text x="${(bx+Wpx/2).toFixed(1)}" y="${(by+16).toFixed(1)}"
          text-anchor="middle" font-family="ASAP,sans-serif" font-size="8" fill="#999">secção transversal</text>
  `;
}
drawSection();

// ── Generate ──────────────────────────────────────────────────────
btnGen.addEventListener('click', async () => {
  if (!selectedFile) return;
  clearStatus();
  document.getElementById('statusLoading').style.display = 'flex';
  btnGen.disabled = true;

  const fd = new FormData();
  fd.append('svg', selectedFile);
  fd.append('wall_height', wallSlider.value);
  fd.append('fillet_radius', filletSlider.value);

  try {
    const resp = await fetch('/generate', { method: 'POST', body: fd });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ error: 'Erro desconhecido' }));
      throw new Error(err.error || 'Erro no servidor');
    }
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    // filename from Content-Disposition or default
    const cd = resp.headers.get('Content-Disposition') || '';
    const match = cd.match(/filename="([^"]+)"/);
    a.download = match ? match[1] : 'buinho_fillet.stl';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    document.getElementById('statusLoading').style.display = 'none';
    document.getElementById('statusSuccess').style.display = 'flex';
    document.getElementById('successMsg').textContent =
      `✅ STL gerado! (parede ${wallSlider.value}mm · fillet ${filletSlider.value}mm) · Se importares no Tinkercad, selecciona tudo e agrupa (Ctrl+G).`;
  } catch (e) {
    showError(e.message);
  } finally {
    btnGen.disabled = false;
    document.getElementById('statusLoading').style.display = 'none';
  }
});

function clearStatus() {
  document.getElementById('statusLoading').style.display = 'none';
  document.getElementById('statusSuccess').style.display = 'none';
  document.getElementById('statusError').style.display = 'none';
}
function showError(msg) {
  clearStatus();
  const el = document.getElementById('statusError');
  el.style.display = 'block';
  el.textContent = '❌ ' + msg;
}
</script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML)


@app.route('/generate', methods=['POST'])
def generate():
    if 'svg' not in request.files:
        return jsonify({'error': 'Nenhum ficheiro SVG recebido.'}), 400
    
    svg_file = request.files['svg']
    if not svg_file.filename.lower().endswith('.svg'):
        return jsonify({'error': 'O ficheiro tem de ser um SVG.'}), 400

    try:
        wall_height = float(request.form.get('wall_height', 5.0))
        fillet_radius = float(request.form.get('fillet_radius', 1.0))
    except ValueError:
        return jsonify({'error': 'Parâmetros inválidos.'}), 400

    wall_height = max(1.0, min(50.0, wall_height))
    fillet_radius = max(0.1, min(wall_height / 2, fillet_radius))

    svg_bytes = svg_file.read()
    try:
        stl_bytes = svg_bytes_to_stl(svg_bytes, wall_height, fillet_radius)
    except ValueError as e:
        return jsonify({'error': str(e)}), 422
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': f'Erro interno ao processar o SVG: {str(e)}'}), 500

    stem = os.path.splitext(svg_file.filename)[0]
    out_name = f"{stem}_fillet_{fillet_radius:.1f}mm.stl"

    return send_file(
        io.BytesIO(stl_bytes),
        as_attachment=True,
        download_name=out_name,
        mimetype='application/octet-stream'
    )


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)

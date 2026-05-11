"""
app.py — Flask app: SVG Fillet STL Generator
Buinho FabLab · Messejana, Alentejo · CC-BY-SA 4.0
"""

import os
import io
import traceback
from flask import Flask, request, send_file, jsonify, render_template_string
from svg_to_stl import svg_bytes_to_stl, svg_bytes_to_stl_with_info

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16 MB max

HTML = r"""<!DOCTYPE html>
<html lang="pt">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SVG → STL · Rounded Edges · Buinho FabLab</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Asap:ital,wght@0,400;0,500;0,600;0,700;1,400&display=swap" rel="stylesheet">
<style>
  :root {
    --creme: #FAF0E1;
    --azul: #2038A6;
    --laranja: #FA6415;
    --vermelho: #F23A2F;
    --amarelo: #FCB515;
    --cinza: #6b6354;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; }
  body {
    font-family: 'Asap', system-ui, sans-serif;
    background: var(--creme);
    color: #1a1a1a;
    line-height: 1.5;
  }
  .wrap { max-width: 820px; margin: 0 auto; padding: 2rem 1.5rem 4rem; }

  /* ── Header ── */
  header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    flex-wrap: wrap;
    gap: 1rem;
  }
  .brand { font-size: 1.1rem; font-weight: 700; color: var(--azul); letter-spacing: -0.01em; }
  .brand span.educ { color: var(--laranja); font-weight: 500; }

  /* ── Lang switcher — pill style from Braille Generator ── */
  .lang {
    display: inline-flex; gap: 0;
    background: rgba(32, 56, 166, 0.08);
    border-radius: 100px; padding: 3px;
  }
  .lang button {
    background: none; border: none; padding: 5px 14px; border-radius: 100px;
    font-family: inherit; font-size: 0.85rem; cursor: pointer;
    color: var(--azul); font-weight: 500;
  }
  .lang button.active { background: var(--azul); color: var(--creme); }

  /* ── Typography ── */
  h1 {
    font-size: clamp(2.2rem, 5vw, 3.6rem);
    font-weight: 700; line-height: 1.05; margin: 2rem 0 0.6rem;
    color: var(--azul); letter-spacing: -0.02em;
  }
  .lede {
    font-size: 1.15rem; color: var(--cinza); max-width: 60ch;
    margin: 0 0 2rem;
  }

  /* ── Use-case grid ── */
  .use-grid {
    display: grid; grid-template-columns: 1fr 1fr;
    gap: 1rem; margin: 0 0 2.5rem;
  }
  @media (max-width: 480px) { .use-grid { grid-template-columns: 1fr; } }
  .use-item {
    background: rgba(255,255,255,0.55);
    border-radius: 12px; padding: 1rem 1.2rem;
  }
  .use-item h3 {
    font-size: 0.9rem; font-weight: 700; color: var(--azul);
    margin: 0 0 0.25rem;
  }
  .use-item p { font-size: 0.85rem; color: var(--cinza); margin: 0; line-height: 1.4; }

  /* ── Section diagram ── */
  .diff {
    display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;
    margin: 0 0 2.5rem;
  }
  .diff > div {
    background: rgba(255,255,255,0.5); border-radius: 12px;
    padding: 1rem; text-align: center;
  }
  .diff svg { width: 100%; max-width: 220px; height: auto; }
  .diff .lbl {
    display: block; font-size: 0.85rem; font-weight: 600;
    margin-top: 0.4rem;
  }
  .diff .bad .lbl { color: var(--vermelho); }
  .diff .good .lbl { color: var(--azul); }

  /* ── Cards ── */
  .card {
    background: white; border-radius: 14px; padding: 1.6rem 1.8rem;
    margin: 1.2rem 0; box-shadow: 0 1px 3px rgba(32,56,166,0.08);
  }
  .card h2 {
    font-size: 1.4rem; font-weight: 600; color: var(--azul);
    margin: 0 0 0.3rem; display: flex; align-items: center; gap: 0.6rem;
  }
  .card h2 .num {
    display: inline-flex; width: 30px; height: 30px; border-radius: 6px;
    background: var(--laranja); color: white; align-items: center;
    justify-content: center; font-size: 1rem; font-weight: 700; flex-shrink: 0;
  }
  .card p.sub { color: var(--cinza); margin: 0 0 1.2rem; font-size: 0.95rem; }

  /* ── Drop zone ── */
  .drop-zone {
    border: 2px dashed rgba(32,56,166,0.25);
    border-radius: 10px; padding: 2rem 1rem;
    text-align: center; cursor: pointer;
    transition: border-color 0.2s, background 0.2s;
    position: relative; background: var(--creme);
  }
  .drop-zone.active { border-color: var(--laranja); background: #fff8f2; }
  .drop-zone.has-file { border-color: var(--azul); background: #f0f4ff; }
  .drop-zone input[type="file"] {
    position: absolute; inset: 0; opacity: 0; cursor: pointer; width: 100%; height: 100%;
  }
  .drop-icon { font-size: 2.4rem; display: block; line-height: 1; margin-bottom: 0.4rem; }
  .drop-text { font-size: 0.95rem; color: var(--cinza); }
  .drop-text strong { color: var(--azul); }
  .file-name {
    margin-top: 0.5rem; font-size: 0.85rem;
    font-weight: 600; color: var(--laranja); display: none;
  }

  /* ── Sliders ── */
  .params { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1.2rem; margin-bottom: 1rem; }
  @media (max-width: 600px) { .params { grid-template-columns: 1fr; } }

  label {
    display: block; font-weight: 600; color: var(--azul);
    margin: 0.9rem 0 0.3rem; font-size: 0.9rem;
  }
  .param-row {
    display: flex; justify-content: space-between; align-items: baseline;
    font-size: 0.9rem; font-weight: 600; color: var(--azul); margin-bottom: 0.35rem;
  }
  .param-row .val { font-weight: 700; color: var(--laranja); font-size: 1rem; }
  input[type="range"] {
    -webkit-appearance: none; width: 100%; height: 6px;
    border-radius: 3px; background: rgba(32,56,166,0.12); outline: none; cursor: pointer;
  }
  input[type="range"]::-webkit-slider-thumb {
    -webkit-appearance: none; width: 20px; height: 20px; border-radius: 50%;
    background: var(--azul); cursor: pointer; border: 2px solid white;
    box-shadow: 0 1px 3px rgba(32,56,166,0.3); transition: background 0.15s;
  }
  input[type="range"]::-webkit-slider-thumb:hover { background: var(--laranja); }
  input[type="range"]::-moz-range-thumb {
    width: 20px; height: 20px; border-radius: 50%;
    background: var(--azul); cursor: pointer; border: 2px solid white;
  }
  .param-hint { font-size: 0.78rem; color: #999; margin-top: 0.25rem; }

  /* ── Cross-section preview ── */
  .preview-wrap { display: flex; justify-content: center; margin-top: 1rem; }
  #section-svg { width: 100%; max-width: 320px; height: auto; }

  /* ── Generate button ── */
  button.go {
    background: var(--azul); color: white; border: none;
    padding: 0.85rem 1.8rem; border-radius: 8px; cursor: pointer;
    font-family: inherit; font-weight: 600; font-size: 1rem;
    margin-top: 1.2rem; transition: background 0.15s; width: 100%;
    display: flex; align-items: center; justify-content: center; gap: 0.5rem;
  }
  button.go:hover { background: #15267d; }
  button.go:active { transform: scale(0.99); }
  button.go:disabled { background: #ccc; cursor: not-allowed; }

  /* ── Status messages ── */
  .status {
    display: none; padding: 0.9rem 1.1rem; border-radius: 8px;
    font-size: 0.9rem; font-weight: 500; line-height: 1.5; margin-top: 1rem;
  }
  .status.loading {
    display: flex; align-items: center; gap: 0.7rem;
    background: rgba(32,56,166,0.07); color: var(--azul);
  }
  .status.success {
    display: flex; align-items: flex-start; gap: 0.7rem;
    background: rgba(30,140,50,0.08); color: #1a5e1a;
  }
  .status.error {
    display: block; background: rgba(242,58,47,0.08); color: var(--vermelho);
  }
  .spinner {
    width: 20px; height: 20px; flex-shrink: 0;
    border: 2.5px solid rgba(32,56,166,0.2);
    border-top-color: var(--azul); border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── Notes ── */
  details {
    background: white; border-radius: 12px; padding: 1rem 1.4rem;
    margin: 1rem 0; border-left: 4px solid var(--amarelo);
    box-shadow: 0 1px 3px rgba(32,56,166,0.06);
  }
  details summary {
    cursor: pointer; font-weight: 600; color: var(--azul); padding: 0.3rem 0;
  }
  details p, details ul { color: #444; font-size: 0.93rem; margin-top: 0.6rem; }
  details li { margin: 0.3rem 0; }

  /* ── Footer ── */
  footer {
    margin-top: 3rem; padding-top: 1.5rem;
    border-top: 1px solid rgba(32,56,166,0.15);
    font-size: 0.85rem; color: var(--cinza);
    display: flex; justify-content: space-between; flex-wrap: wrap; gap: 1rem;
  }
  footer a { color: var(--azul); text-decoration: none; font-weight: 500; }
  footer a:hover { text-decoration: underline; }

  /* ── i18n ── */
  .en { display: none; }
  .pt { display: inline; }
  body.lang-en .en { display: inline; }
  body.lang-en .pt { display: none; }
  .en-block { display: none; }
  .pt-block { display: block; }
  body.lang-en .en-block { display: block; }
  body.lang-en .pt-block { display: none; }
</style>
</head>
<body>
<div class="wrap">

<header>
  <div class="brand">Buinho<span class="educ"> · educativo</span></div>
  <div class="lang">
    <button id="lang-pt" class="active" onclick="setLang('pt')">PT</button>
    <button id="lang-en" onclick="setLang('en')">EN</button>
  </div>
</header>

<h1>
  <span class="pt">SVG → STL<br>Arestas Arredondadas</span>
  <span class="en">SVG → STL<br>Rounded Edges</span>
</h1>

<p class="lede">
  <span class="pt">Transforma contornos SVG em paredes 3D com bordas superiores suavizadas — pronto para impressão tátil ou vacuum forming.</span>
  <span class="en">Convert SVG outlines into 3D walls with smooth rounded top edges — ready for tactile printing or vacuum forming.</span>
</p>

<!-- Before/after diagram -->
<div class="diff">
  <div class="bad">
    <svg viewBox="0 0 120 70" xmlns="http://www.w3.org/2000/svg">
      <rect x="0" y="50" width="120" height="20" fill="#ddd" stroke="#aaa" stroke-width="0.8"/>
      <path d="M 40 20 L 40 50 L 80 50 L 80 20 Z" fill="#ccc" stroke="#888" stroke-width="1.2"/>
      <line x1="32" y1="14" x2="40" y2="20" stroke="#F23A2F" stroke-width="1.5" marker-end="url(#arr-r)"/>
      <line x1="88" y1="14" x2="80" y2="20" stroke="#F23A2F" stroke-width="1.5" marker-end="url(#arr-r)"/>
      <text x="30" y="11" font-size="6" fill="#F23A2F" text-anchor="end" font-family="Asap,sans-serif">!</text>
      <text x="90" y="11" font-size="6" fill="#F23A2F" font-family="Asap,sans-serif">!</text>
      <defs>
        <marker id="arr-r" markerWidth="6" markerHeight="6" refX="5" refY="3" orient="auto">
          <path d="M0,0 L6,3 L0,6 Z" fill="#F23A2F"/>
        </marker>
      </defs>
    </svg>
    <span class="lbl pt">Aresta viva a 90°</span>
    <span class="lbl en">Sharp 90° edge</span>
  </div>
  <div class="good">
    <svg viewBox="0 0 120 70" xmlns="http://www.w3.org/2000/svg">
      <rect x="0" y="50" width="120" height="20" fill="#ddd" stroke="#aaa" stroke-width="0.8"/>
      <path d="M 40 50 L 40 34 Q 40 20 54 20 L 66 20 Q 80 20 80 34 L 80 50 Z"
            fill="rgba(32,56,166,0.18)" stroke="#2038A6" stroke-width="1.5" stroke-linejoin="round"/>
      <path d="M 40 34 Q 40 20 54 20" fill="none" stroke="#FA6415" stroke-width="2" stroke-linecap="round"/>
      <path d="M 66 20 Q 80 20 80 34" fill="none" stroke="#FA6415" stroke-width="2" stroke-linecap="round"/>
    </svg>
    <span class="lbl pt">Fillet arredondado</span>
    <span class="lbl en">Rounded fillet</span>
  </div>
</div>

<!-- Use cases -->
<div class="use-grid">
  <div class="use-item">
    <h3>✋ <span class="pt">Impressão tátil</span><span class="en">Tactile printing</span></h3>
    <p class="pt">Arestas vivas magoam os dedos. O fillet torna os modelos seguros para exploração tátil por alunos invisuais.</p>
    <p class="en">Sharp edges hurt fingers. The fillet makes models safe for tactile exploration by visually impaired students.</p>
  </div>
  <div class="use-item">
    <h3>🔵 Vacuum forming</h3>
    <p class="pt">Arestas a 90° rasgam o plástico. Um raio de fillet suave distribui a tensão e evita defeitos no produto final.</p>
    <p class="en">90° edges tear plastic. A smooth fillet radius distributes tension and prevents defects in the final product.</p>
  </div>
  <div class="use-item">
    <h3>📐 <span class="pt">Importar SVG</span><span class="en">Import SVG</span></h3>
    <p class="pt">Exporta do Tinkercad, Inkscape ou Illustrator como SVG com paths fechados. O gerador faz o resto.</p>
    <p class="en">Export from Tinkercad, Inkscape or Illustrator as SVG with closed paths. The generator does the rest.</p>
  </div>
  <div class="use-item">
    <h3>📦 <span class="pt">STL para slicer</span><span class="en">STL for slicer</span></h3>
    <p class="pt">O ficheiro gerado é watertight e importável no Tinkercad, PrusaSlicer, Cura ou qualquer slicer.</p>
    <p class="en">The generated file is watertight and ready for Tinkercad, PrusaSlicer, Cura or any slicer.</p>
  </div>
</div>

<!-- Card 1: Upload -->
<div class="card">
  <h2>
    <span class="num">1</span>
    <span class="pt">Ficheiro SVG</span>
    <span class="en">SVG File</span>
  </h2>
  <p class="sub">
    <span class="pt">Paths fechados. Funciona com desenhos do Tinkercad, Inkscape ou Illustrator.</span>
    <span class="en">Closed paths. Works with designs from Tinkercad, Inkscape or Illustrator.</span>
  </p>
  <div class="drop-zone" id="dropZone">
    <input type="file" id="svgFile" accept=".svg,image/svg+xml">
    <span class="drop-icon">📂</span>
    <div class="drop-text">
      <span class="pt"><strong>Clica</strong> ou arrasta um ficheiro SVG para aqui</span>
      <span class="en"><strong>Click</strong> or drag an SVG file here</span>
    </div>
    <div class="file-name" id="fileName"></div>
  </div>
</div>

<!-- Card 2: Parameters -->
<div class="card">
  <h2>
    <span class="num">2</span>
    <span class="pt">Parâmetros</span>
    <span class="en">Parameters</span>
  </h2>
  <p class="sub">
    <span class="pt">Ajusta a altura, espessura e raio de arredondamento.</span>
    <span class="en">Adjust wall height, thickness and rounding radius.</span>
  </p>
  <div class="params">
    <div>
      <div class="param-row">
        <span class="pt">Altura da parede</span><span class="en">Wall height</span>
        <span class="val" id="heightVal">5.0 mm</span>
      </div>
      <input type="range" id="wallHeight" min="1" max="30" step="0.5" value="5">
      <div class="param-hint">
        <span class="pt">Altura total extrudida</span>
        <span class="en">Total extruded height</span>
      </div>
    </div>
    <div>
      <div class="param-row">
        <span class="pt">Espessura da parede</span><span class="en">Wall thickness</span>
        <span class="val" id="thicknessVal">0 <span class="pt">sólido</span><span class="en">solid</span></span>
      </div>
      <input type="range" id="wallThickness" min="0" max="20" step="0.5" value="0">
      <div class="param-hint">
        <span class="pt">0 = preenchimento sólido · parede mais espessa → fillet maior possível</span>
        <span class="en">0 = solid fill · thicker wall → larger fillet possible</span>
      </div>
    </div>
    <div>
      <div class="param-row">
        <span class="pt">Raio do fillet</span><span class="en">Fillet radius</span>
        <span class="val" id="filletVal">1.0 mm</span>
      </div>
      <input type="range" id="filletRadius" min="0.2" max="15" step="0.1" value="1">
      <div class="param-hint">
        <span class="pt">Limite: <span id="filletLimitHint">metade da altura</span></span>
        <span class="en">Limit: <span id="filletLimitHintEn">half the height</span></span>
      </div>
    </div>
  </div>
  <div class="preview-wrap">
    <svg id="section-svg" viewBox="0 0 200 140" xmlns="http://www.w3.org/2000/svg">
      <!-- drawn by JS -->
    </svg>
  </div>
</div>

<!-- Card 3: Generate -->
<div class="card">
  <h2>
    <span class="num">3</span>
    <span class="pt">Gerar STL</span>
    <span class="en">Generate STL</span>
  </h2>
  <p class="sub">
    <span class="pt">O fillet é ajustado automaticamente se a forma for complexa.</span>
    <span class="en">Fillet is automatically adjusted for complex shapes.</span>
  </p>
  <button class="go" id="btnGenerate" disabled>
    <span>⬇</span>
    <span class="pt">Gerar STL com Arestas Arredondadas</span>
    <span class="en">Generate STL with Rounded Edges</span>
  </button>
  <div class="status loading" id="statusLoading">
    <div class="spinner"></div>
    <span class="pt">A processar o SVG e a gerar geometria 3D…</span>
    <span class="en">Processing SVG and generating 3D geometry…</span>
  </div>
  <div class="status success" id="statusSuccess">
    <span>✅</span>
    <span id="successMsg"></span>
  </div>
  <div class="status error" id="statusError"></div>
</div>

<!-- Technical notes -->
<details>
  <summary>
    <span class="pt">📋 Notas técnicas</span>
    <span class="en">📋 Technical notes</span>
  </summary>
  <ul>
    <li class="pt">O SVG deve ter paths fechados. Paths abertos são convertidos em paredes com espessura de 2 mm.</li>
    <li class="en">The SVG must have closed paths. Open paths are converted to 2 mm thick walls.</li>
    <li class="pt">O fillet é calculado por ring — formas complexas com features estreitas recebem um raio efectivo inferior ao pedido.</li>
    <li class="en">Fillet is calculated per ring — complex shapes with narrow features receive a lower effective radius than requested.</li>
    <li class="pt">O STL gerado é watertight (manifold) e pronto para impressão 3D sem reparações.</li>
    <li class="en">The generated STL is watertight (manifold) and ready for 3D printing without repairs.</li>
    <li class="pt">Ao importar no Tinkercad com múltiplas figuras, selecciona tudo e agrupa (Ctrl+G).</li>
    <li class="en">When importing into Tinkercad with multiple shapes, select all and group (Ctrl+G).</li>
  </ul>
</details>

<footer>
  <span>
    Buinho FabLab · Messejana, Alentejo ·
    <a href="https://buinho.pt" target="_blank">buinho.pt</a>
  </span>
  <span>
    <a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank">CC-BY-SA 4.0</a>
    · <a href="https://github.com/Buinho-Creative-Hub/svg-fillet-generator" target="_blank">GitHub</a>
  </span>
</footer>

</div><!-- .wrap -->

<script>
// ── Language switcher ─────────────────────────────────────────────
function setLang(lang) {
  document.body.className = 'lang-' + lang;
  document.getElementById('lang-pt').classList.toggle('active', lang === 'pt');
  document.getElementById('lang-en').classList.toggle('active', lang === 'en');
  document.documentElement.lang = lang;
  localStorage.setItem('svg_stl_lang', lang);
  window._lang = lang;
}
(function() {
  const saved = localStorage.getItem('svg_stl_lang') ||
    (navigator.language.startsWith('pt') ? 'pt' : 'en');
  setLang(saved);
})();

const dropZone    = document.getElementById('dropZone');
const fileInput   = document.getElementById('svgFile');
const fileName    = document.getElementById('fileName');
const btnGen      = document.getElementById('btnGenerate');
const wallSlider      = document.getElementById('wallHeight');
const thicknessSlider = document.getElementById('wallThickness');
const filletSlider    = document.getElementById('filletRadius');
const heightVal       = document.getElementById('heightVal');
const thicknessVal    = document.getElementById('thicknessVal');
const filletVal       = document.getElementById('filletVal');
const filletLimitHint   = document.getElementById('filletLimitHint');
const filletLimitHintEn = document.getElementById('filletLimitHintEn');
const sectionSvg  = document.getElementById('section-svg');

let selectedFile = null;

// ── Fillet limit formula (mirrors Python) ────────────────────────
// max_fillet = min(height/2, thickness/2)  when thickness > 0
// max_fillet = height/2                    when thickness = 0 (solid)
function maxFillet(H, T) {
  if (T > 0) return Math.min(H / 2, T / 2);
  return H / 2;
}

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
    showError(window._lang === 'en' ? 'Please choose an .svg file.' : 'Por favor escolhe um ficheiro .svg.');
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
function updateSliders() {
  const H = parseFloat(wallSlider.value);
  const T = parseFloat(thicknessSlider.value);
  const maxF = maxFillet(H, T);

  heightVal.textContent = H.toFixed(1) + ' mm';

  if (T <= 0) {
    thicknessVal.innerHTML = '0 <span class="pt">sólido</span><span class="en">solid</span>';
    const langPt = thicknessVal.querySelector('.pt');
    const langEn = thicknessVal.querySelector('.en');
    if (langPt) langPt.style.display = (window._lang === 'en') ? 'none' : 'inline';
    if (langEn) langEn.style.display = (window._lang === 'en') ? 'inline' : 'none';
  } else {
    thicknessVal.textContent = T.toFixed(1) + ' mm';
  }

  filletSlider.max = maxF.toFixed(2);
  if (parseFloat(filletSlider.value) > maxF) {
    filletSlider.value = maxF.toFixed(2);
  }
  filletVal.textContent = parseFloat(filletSlider.value).toFixed(1) + ' mm';

  // Update hint text
  let hintPt, hintEn;
  if (T > 0) {
    hintPt = `min(H/2, T/2) = ${maxF.toFixed(1)} mm`;
    hintEn = `min(H/2, T/2) = ${maxF.toFixed(1)} mm`;
  } else {
    hintPt = `metade da altura = ${maxF.toFixed(1)} mm`;
    hintEn = `half the height = ${maxF.toFixed(1)} mm`;
  }
  if (filletLimitHint) filletLimitHint.textContent = hintPt;
  if (filletLimitHintEn) filletLimitHintEn.textContent = hintEn;

  drawSection();
}
wallSlider.addEventListener('input', updateSliders);
thicknessSlider.addEventListener('input', updateSliders);
filletSlider.addEventListener('input', () => {
  filletVal.textContent = parseFloat(filletSlider.value).toFixed(1) + ' mm';
  drawSection();
});

// ── Cross-section preview ─────────────────────────────────────────
function drawSection() {
  const H = parseFloat(wallSlider.value);
  const T = parseFloat(thicknessSlider.value);
  const R = parseFloat(filletSlider.value);

  const VW = 200, VH = 140;
  const margin = { left: 38, right: 18, top: 18, bottom: 22 };
  const availH = VH - margin.top - margin.bottom;
  const availW = VW - margin.left - margin.right;

  const scale = availH / Math.max(H, 8);
  const Hpx = H * scale;
  const Rpx = Math.min(R * scale, Hpx * 0.48);
  const Wpx = Math.min(availW * 0.55, Hpx * 1.4);

  const bx = margin.left + (availW - Wpx) / 2;
  const by = margin.top + availH;
  const topY = by - Hpx;
  const arcBaseY = topY + Rpx;

  const arcN = 20;
  let pts = [];
  pts.push([bx, by]);
  pts.push([bx, arcBaseY]);
  for (let i = 1; i <= arcN; i++) {
    const a = Math.PI - (Math.PI / 2) * (i / arcN);
    const px = (bx + Rpx) + Rpx * Math.cos(a);
    const py = arcBaseY   - Rpx * Math.sin(a);
    pts.push([px, py]);
  }
  pts.push([bx + Wpx - Rpx, topY]);
  for (let i = 1; i <= arcN; i++) {
    const a = (Math.PI / 2) * (1 - i / arcN);
    const px = (bx + Wpx - Rpx) + Rpx * Math.cos(a);
    const py = arcBaseY          - Rpx * Math.sin(a);
    pts.push([px, py]);
  }
  pts.push([bx + Wpx, by]);

  const d = 'M' + pts.map(p => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' L') + ' Z';

  // Hollow cavity (only if T > 0 and T < Wpx/scale / 2)
  let cavityPath = '';
  const Tpx = T * scale;
  if (T > 0 && Tpx * 2 < Wpx - 2) {
    const ix = bx + Tpx;
    const iW = Wpx - 2 * Tpx;
    cavityPath = `<rect x="${ix.toFixed(1)}" y="${topY.toFixed(1)}"
      width="${iW.toFixed(1)}" height="${Hpx.toFixed(1)}"
      fill="#FAF0E1" stroke="#2038A6" stroke-width="1" stroke-dasharray="3,2" opacity="0.9"/>`;
  }

  const dimX = bx - 6;
  const hLabelY = (by + topY) / 2 + 4;
  const rLabelY = (arcBaseY + topY) / 2 + 3;

  // T label
  let tLabel = '';
  if (T > 0 && Tpx > 4) {
    tLabel = `
    <line x1="${bx.toFixed(1)}" y1="${(by+10).toFixed(1)}" x2="${(bx+Tpx).toFixed(1)}" y2="${(by+10).toFixed(1)}" stroke="#FCB515" stroke-width="1.5"/>
    <text x="${(bx + Tpx/2).toFixed(1)}" y="${(by+20).toFixed(1)}" text-anchor="middle" font-family="Asap,sans-serif" font-size="8" font-weight="700" fill="#b07800">T=${T.toFixed(1)}</text>`;
  }

  sectionSvg.innerHTML = `
    <rect width="${VW}" height="${VH}" fill="#f9f6f1" rx="8"/>
    <line x1="${bx - 4}" y1="${by}" x2="${bx + Wpx + 4}" y2="${by}" stroke="#bbb" stroke-width="1"/>
    <path d="${d}" fill="rgba(32,56,166,0.12)" stroke="#2038A6" stroke-width="1.8" stroke-linejoin="round"/>
    ${cavityPath}
    <path d="M${bx.toFixed(1)},${arcBaseY.toFixed(1)} ${pts.slice(1, arcN+2).map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ')}"
          fill="none" stroke="#FA6415" stroke-width="2" stroke-linecap="round"/>
    <path d="M${(bx+Wpx-Rpx).toFixed(1)},${topY.toFixed(1)} ${pts.slice(arcN+3, arcN*2+4).map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ')}"
          fill="none" stroke="#FA6415" stroke-width="2" stroke-linecap="round"/>
    <line x1="${dimX}" y1="${by}" x2="${dimX}" y2="${topY}" stroke="#FA6415" stroke-width="1.2" stroke-dasharray="3,2"/>
    <line x1="${dimX-3}" y1="${by}" x2="${dimX+3}" y2="${by}" stroke="#FA6415" stroke-width="1.5"/>
    <line x1="${dimX-3}" y1="${topY}" x2="${dimX+3}" y2="${topY}" stroke="#FA6415" stroke-width="1.5"/>
    <text x="${dimX - 4}" y="${hLabelY}" text-anchor="end" font-family="Asap,sans-serif" font-size="10" font-weight="700" fill="#FA6415">${H.toFixed(1)}mm</text>
    ${Rpx > 6 ? `
    <line x1="${(bx+Wpx+6).toFixed(1)}" y1="${arcBaseY.toFixed(1)}" x2="${(bx+Wpx+6).toFixed(1)}" y2="${topY.toFixed(1)}" stroke="#2038A6" stroke-width="1" stroke-dasharray="2,2"/>
    <text x="${(bx+Wpx+10).toFixed(1)}" y="${rLabelY.toFixed(1)}" font-family="Asap,sans-serif" font-size="9" font-weight="700" fill="#2038A6">r=${R.toFixed(1)}</text>
    ` : `
    <text x="${(bx+Wpx/2).toFixed(1)}" y="${(topY-5).toFixed(1)}" text-anchor="middle" font-family="Asap,sans-serif" font-size="8" fill="#2038A6">r=${R.toFixed(1)}mm</text>
    `}
    ${tLabel}
    <text x="${(bx+Wpx/2).toFixed(1)}" y="${(by+16).toFixed(1)}" text-anchor="middle" font-family="Asap,sans-serif" font-size="8" fill="#999">secção transversal</text>
  `;
}
updateSliders();

// ── Generate ──────────────────────────────────────────────────────
btnGen.addEventListener('click', async () => {
  if (!selectedFile) return;
  clearStatus();
  document.getElementById('statusLoading').style.display = 'flex';
  btnGen.disabled = true;

  const fd = new FormData();
  fd.append('svg', selectedFile);
  fd.append('wall_height', wallSlider.value);
  fd.append('wall_thickness', thicknessSlider.value);
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
    const cd = resp.headers.get('Content-Disposition') || '';
    const match = cd.match(/filename="([^"]+)"/);
    a.download = match ? match[1] : 'buinho_fillet.stl';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    document.getElementById('statusLoading').style.display = 'none';
    document.getElementById('statusSuccess').style.display = 'flex';
    const effR2 = resp.headers.get('X-Fillet-Effective');
    const wasCapped = resp.headers.get('X-Fillet-Capped') === 'true';
    const lang = window._lang || 'pt';
    let msg;
    if (lang === 'en') {
      msg = `STL generated! (wall ${wallSlider.value}mm · thickness ${thicknessSlider.value > 0 ? thicknessSlider.value+'mm' : 'solid'} · fillet ${filletSlider.value}mm)`;
      if (wasCapped && effR2) msg += ` — ⚠️ fillet reduced to ${parseFloat(effR2).toFixed(2)}mm (complex shape)`;
      msg += ' · If importing into Tinkercad, select all and group (Ctrl+G).';
    } else {
      msg = `STL gerado! (parede ${wallSlider.value}mm · espessura ${thicknessSlider.value > 0 ? thicknessSlider.value+'mm' : 'sólido'} · fillet ${filletSlider.value}mm)`;
      if (wasCapped && effR2) msg += ` — ⚠️ fillet reduzido para ${parseFloat(effR2).toFixed(2)}mm (forma complexa)`;
      msg += ' · Se importares no Tinkercad, selecciona tudo e agrupa (Ctrl+G).';
    }
    document.getElementById('successMsg').textContent = msg;
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
</html>"""


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
        wall_thickness = float(request.form.get('wall_thickness', 0.0))
    except ValueError:
        return jsonify({'error': 'Parâmetros inválidos.'}), 400

    wall_height = max(1.0, min(50.0, wall_height))
    wall_thickness = max(0.0, min(wall_height - 0.1, wall_thickness))  # allow up to height-0.1mm

    # Clamp fillet: mirrors max_fillet_for() in svg_to_stl.py
    if wall_thickness > 0:
        max_f = min(wall_height / 2, wall_thickness / 2)
    else:
        max_f = wall_height / 2
    fillet_radius = max(0.1, min(max_f, fillet_radius))

    svg_bytes = svg_file.read()
    try:
        stl_bytes, info = svg_bytes_to_stl_with_info(
            svg_bytes, wall_height, fillet_radius,
            wall_thickness_mm=wall_thickness
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 422
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': f'Erro interno ao processar o SVG: {str(e)}'}), 500

    eff_r = info.get('fillet_effective_mm', fillet_radius)
    stem = os.path.splitext(svg_file.filename)[0]
    out_name = stem + ".stl"

    response = send_file(
        io.BytesIO(stl_bytes),
        as_attachment=True,
        download_name=out_name,
        mimetype='application/octet-stream'
    )
    eff_r_val = float(info.get('fillet_effective_mm', fillet_radius))
    was_capped = bool(info.get('fillet_capped', False))
    response.headers['X-Fillet-Requested'] = str(round(fillet_radius, 3))
    response.headers['X-Fillet-Effective'] = str(round(eff_r_val, 3))
    response.headers['X-Fillet-Capped']    = 'true' if was_capped else 'false'
    response.headers['Access-Control-Expose-Headers'] = (
        'X-Fillet-Requested, X-Fillet-Effective, X-Fillet-Capped'
    )
    return response


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)


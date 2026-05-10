# SVG → STL com Arestas Arredondadas / SVG → STL with Rounded Edges

## Português

Ferramenta web open-source para converter contornos SVG em paredes 3D com bordas superiores suavizadas (fillet), pronta para impressão 3D tátil ou vacuum forming.

O Tinkercad importa SVG e faz extrusão com arestas vivas a 90° no topo. Este gerador resolve isso: o topo da parede tem um quarto-de-círculo arredondado configurável.

**Casos de uso:**
- Modelos táteis para alunos invisuais (arestas vivas magoam os dedos)
- Matrizes para vacuum forming (arestas vivas rasgam o plástico)

**Como usar:**
1. Exporta o teu SVG com paths fechados (Inkscape, Illustrator, Tinkercad)
2. Carrega na app, define altura da parede e raio do fillet
3. Descarrega o STL watertight pronto para slicer ou Tinkercad

## English

Open-source web tool to convert SVG outlines into 3D extruded walls with a rounded top-edge fillet. Useful for tactile models (sharp edges hurt fingers) and vacuum forming matrices (sharp edges tear plastic).

**How to use:**
1. Export your SVG with closed paths
2. Upload, set wall height and fillet radius
3. Download a watertight STL

## Technical notes

- Stack: Python 3.12 + Flask + trimesh + shapely + svgpathtools
- Deploy: Render.com (Frankfurt, free tier)
- Local: `pip install -r requirements.txt && python app.py`

## License

[CC-BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) — [Buinho FabLab](https://buinho.pt) · Messejana, Alentejo, Portugal

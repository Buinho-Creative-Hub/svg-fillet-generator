"""
svg_to_stl.py — SVG → STL with rounded top edges (fillet)
Buinho FabLab · CC-BY-SA 4.0

Architecture:
- SVG parsing: lxml walks the tree composing all ancestor transforms
- Coordinate handling: auto-detects if transform already flips Y (potrace SVGs)
- Even-odd fill rule via shapely difference/union
- 3D geometry: stacked trimesh.extrude_polygon slices → always watertight
  * Straight section: one extrusion (0 → h-r)
  * Arc section: n_arc slices with progressively inset polygon (quarter-circle profile)
"""

import numpy as np
import trimesh
from shapely.geometry import Polygon, MultiPolygon, LineString
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
import svgpathtools
from lxml import etree
import re, io


# ─── Transform helpers ───────────────────────────────────────────────────────

def _parse_transform(t):
    """Parse SVG transform string → 3×3 affine matrix."""
    m = np.eye(3)
    for match in re.finditer(r'(\w+)\(([^)]+)\)', t or ''):
        name = match.group(1)
        args = [float(x) for x in re.split(r'[,\s]+', match.group(2).strip()) if x]
        if name == 'translate':
            tx, ty = args[0], (args[1] if len(args) > 1 else 0)
            m = m @ np.array([[1,0,tx],[0,1,ty],[0,0,1]], float)
        elif name == 'scale':
            sx = args[0]; sy = args[1] if len(args) > 1 else sx
            m = m @ np.array([[sx,0,0],[0,sy,0],[0,0,1]], float)
        elif name == 'matrix':
            a,b,c,d,e,f = args
            m = m @ np.array([[a,c,e],[b,d,f],[0,0,1]], float)
        elif name == 'rotate':
            ang = np.radians(args[0])
            cx = args[1] if len(args) > 1 else 0
            cy = args[2] if len(args) > 2 else 0
            R = np.array([[np.cos(ang),-np.sin(ang),0],[np.sin(ang),np.cos(ang),0],[0,0,1]], float)
            T1 = np.array([[1,0,cx],[0,1,cy],[0,0,1]], float)
            T2 = np.array([[1,0,-cx],[0,1,-cy],[0,0,1]], float)
            m = m @ T1 @ R @ T2
    return m


def _collect_path_transforms(svg_bytes):
    """Walk SVG tree → list of (path_d, cumulative_matrix) for every <path>."""
    tree = etree.parse(io.BytesIO(svg_bytes))
    root = tree.getroot()
    ns = root.nsmap.get(None, '')
    def tag(t): return f'{{{ns}}}{t}' if ns else t

    results = []
    def walk(el, parent_m):
        local = el.tag.split('}')[-1] if '}' in el.tag else el.tag
        m = parent_m @ _parse_transform(el.get('transform', ''))
        if local == 'path':
            d = el.get('d', '')
            if d:
                results.append((d, m))
        for child in el:
            walk(child, m)
    walk(root, np.eye(3))
    return results


def _vb_scale(svg_bytes):
    """viewBox unit → mm scale factor."""
    tree = etree.parse(io.BytesIO(svg_bytes))
    root = tree.getroot()
    vb = root.get('viewBox', '')
    width_attr = root.get('width', '') or ''
    scale = 1.0
    if vb and width_attr:
        parts = vb.split()
        if len(parts) == 4:
            vb_w = float(parts[2])
            w_num = re.sub(r'[^0-9.]', '', width_attr)
            if w_num and float(w_num) > 0:
                s = float(w_num) / vb_w
                if   'mm' in width_attr: pass
                elif 'pt' in width_attr: s *= 25.4 / 72.0
                elif 'cm' in width_attr: s *= 10.0
                elif 'in' in width_attr: s *= 25.4
                else:                    s *= 25.4 / 96.0  # px
                scale = s
    return scale


def _apply_matrix(pts_complex, m, vb_s):
    """Apply 3×3 matrix + vb_scale. Auto-detects if Y is already flipped in matrix."""
    y_flipped = m[1, 1] < 0  # matrix already inverts Y (e.g. potrace scale(sx,-sy))
    out = []
    for p in pts_complex:
        v = m @ np.array([p.real, p.imag, 1.0])
        x_mm = v[0] * vb_s
        y_mm = v[1] * vb_s if y_flipped else -v[1] * vb_s
        out.append((x_mm, y_mm))
    return out


def _split_subpaths(path_obj):
    """Split svgpathtools Path at gaps (new M = new subpath)."""
    subs, cur = [], []
    for seg in path_obj:
        if cur and abs(cur[-1].end - seg.start) > 1e-3:
            subs.append(svgpathtools.Path(*cur))
            cur = []
        cur.append(seg)
    if cur:
        subs.append(svgpathtools.Path(*cur))
    return subs


# ─── SVG → Shapely polygons ──────────────────────────────────────────────────

def svg_to_polygons(svg_bytes):
    """
    Parse SVG → list of oriented shapely Polygons (mm).
    Handles: group transforms, even-odd fill, open paths (buffered).
    All returned polygons are orient()ed: exterior CCW, interiors CW.
    """
    vb_s = _vb_scale(svg_bytes)
    path_transforms = _collect_path_transforms(svg_bytes)
    paths, _, _ = svgpathtools.svg2paths2(io.BytesIO(svg_bytes))

    if len(paths) != len(path_transforms):
        path_transforms = [(None, np.eye(3)) for _ in paths]

    raw_polys = []
    raw_lines = []

    for path_obj, (_, m) in zip(paths, path_transforms):
        for sp in _split_subpaths(path_obj):
            pts_c = [seg.point(i/20) for seg in sp for i in range(20)]
            if len(pts_c) < 3:
                continue
            xy_mm = _apply_matrix(pts_c, m, vb_s)
            closed = abs(sp[-1].end - sp[0].start) < 1.0

            if closed:
                poly = Polygon(xy_mm)
                if not poly.is_valid: poly = poly.buffer(0)
                if poly.is_valid and poly.area > 0.1:
                    raw_polys.append(poly)
            else:
                if len(xy_mm) >= 2:
                    raw_lines.append(xy_mm)

    # Buffer open paths (stroke-based SVGs)
    for line_pts in raw_lines:
        try:
            poly = LineString(line_pts).buffer(2.0, cap_style=2, join_style=2)
            if poly.is_valid and poly.area > 0.1:
                raw_polys.append(poly)
        except Exception:
            pass

    if not raw_polys:
        return []

    raw_polys.sort(key=lambda p: p.area, reverse=True)

    # Even-odd: largest=outer, contained smaller=holes, disjoint=union
    result = raw_polys[0]
    for poly in raw_polys[1:]:
        try:
            if result.contains(poly.centroid):
                result = result.difference(poly)
            else:
                result = result.union(poly)
        except Exception:
            pass

    if result.is_empty:
        return []

    # Ensure correct winding: exterior CCW, interiors CW
    def _orient_poly(p):
        return orient(p, sign=1.0)

    if isinstance(result, MultiPolygon):
        return [_orient_poly(g) for g in result.geoms if g.area > 0.1]
    return [_orient_poly(result)]


# ─── 3-D geometry ─────────────────────────────────────────────────────────────

def polygon_to_mesh(polygon, wall_height, fillet_radius, n_arc=8):
    """
    Watertight mesh via stacked extrusions:
    - Straight section: extrude_polygon(polygon, straight_h)
    - Arc section: n_arc slices with progressively inset polygon (quarter-circle)
    Uses trimesh.creation.extrude_polygon for guaranteed watertight topology.
    """
    r = min(fillet_radius, wall_height * 0.48)
    straight_h = wall_height - r
    meshes = []

    # ── Straight section ──
    try:
        m = trimesh.creation.extrude_polygon(polygon, height=straight_h)
        if m and len(m.faces) > 0:
            meshes.append(m)
    except Exception:
        pass

    # ── Quarter-circle arc section (stacked slices) ──
    prev_z = straight_h
    for i in range(1, n_arc + 1):
        angle = np.pi / 2 * i / n_arc      # 0 → π/2
        u = r * (1 - np.cos(angle))         # inset amount: 0 → r
        v = r * np.sin(angle)               # height above straight: 0 → r
        curr_z = straight_h + v
        slice_h = curr_z - prev_z

        inset = polygon.buffer(-u)
        if inset.is_empty or inset.area < 0.01:
            break
        if isinstance(inset, MultiPolygon):
            inset = max(inset.geoms, key=lambda g: g.area)
        inset = orient(inset, sign=1.0)

        try:
            m = trimesh.creation.extrude_polygon(inset, height=slice_h)
            if m and len(m.faces) > 0:
                m.apply_translation([0, 0, prev_z])
                meshes.append(m)
        except Exception:
            break

        prev_z = curr_z

    if not meshes:
        return None

    combined = trimesh.util.concatenate(meshes)
    mesh = trimesh.Trimesh(vertices=combined.vertices, faces=combined.faces, process=True)
    mesh.fix_normals()
    return mesh


def svg_bytes_to_stl(svg_bytes, wall_height_mm=5.0, fillet_radius_mm=1.0, n_arc=8):
    """Main entry point. Returns binary STL bytes."""
    polygons = svg_to_polygons(svg_bytes)
    if not polygons:
        raise ValueError(
            "Não foi possível extrair contornos fechados do SVG. "
            "Certifica-te de que o SVG tem paths fechados ou strokes visíveis."
        )

    # Simplify to reduce vertex count (0.2mm < 3D print resolution)
    simplified = []
    for poly in polygons:
        if isinstance(poly, MultiPolygon):
            for sub in poly.geoms:
                s = orient(sub.simplify(0.2), sign=1.0)
                if s.is_valid and s.area > 0.1: simplified.append(s)
        else:
            s = orient(poly.simplify(0.2), sign=1.0)
            if s.is_valid and s.area > 0.1: simplified.append(s)

    if not simplified:
        raise ValueError("Nenhum contorno gerou geometria válida.")

    meshes = []
    for poly in simplified:
        m = polygon_to_mesh(poly, wall_height_mm, fillet_radius_mm, n_arc)
        if m: meshes.append(m)

    if not meshes:
        raise ValueError("Nenhum contorno gerou geometria válida.")

    final = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
    final.fix_normals()
    return final.export(file_type='stl')

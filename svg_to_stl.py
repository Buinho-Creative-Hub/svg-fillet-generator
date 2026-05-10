"""
svg_to_stl.py — SVG → STL with rounded top edges (fillet)
Buinho FabLab · CC-BY-SA 4.0

Handles:
- SVG group transforms (translate, scale, matrix) — critical for potrace/Inkscape SVGs
- Even-odd fill rule: inner paths → holes, outer paths → union
- Open paths → buffered into filled polygons (stroke-based SVGs)
- Quarter-circle fillet on top edge of extruded walls
"""

import numpy as np
import trimesh
from shapely.geometry import Polygon, MultiPolygon, LineString
from shapely.ops import unary_union
import svgpathtools
from lxml import etree
import re, io


# ─── Transform helpers ───────────────────────────────────────────────────────

def parse_transform(t):
    """Parse an SVG transform string → 3×3 affine matrix."""
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
            m = m @ np.array([[1,0,cx],[0,1,cy],[0,0,1]], float) \
                  @ np.array([[np.cos(ang),-np.sin(ang),0],
                               [np.sin(ang), np.cos(ang),0],[0,0,1]], float) \
                  @ np.array([[1,0,-cx],[0,1,-cy],[0,0,1]], float)
    return m


def collect_path_transforms(svg_bytes):
    """
    Walk the SVG tree and return a list of (path_d, cumulative_transform_matrix)
    for every <path> element, with all ancestor transforms composed.
    """
    tree = etree.parse(io.BytesIO(svg_bytes))
    root = tree.getroot()
    ns = root.nsmap.get(None, '')
    def tag(t): return f'{{{ns}}}{t}' if ns else t

    results = []

    def walk(el, parent_m):
        local = el.tag.split('}')[-1] if '}' in el.tag else el.tag
        m = parent_m @ parse_transform(el.get('transform', ''))
        if local == 'path':
            d = el.get('d', '')
            if d:
                results.append((d, m))
        for child in el:
            walk(child, m)

    walk(root, np.eye(3))
    return results


# ─── SVG → Shapely polygons ──────────────────────────────────────────────────

def _vb_to_mm_scale(svg_bytes):
    """Compute scale factor: viewBox units → mm."""
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
                # Unit conversion to mm
                if 'mm' in width_attr:
                    pass  # already mm
                elif 'pt' in width_attr:
                    s *= 25.4 / 72.0
                elif 'cm' in width_attr:
                    s *= 10.0
                elif 'in' in width_attr:
                    s *= 25.4
                else:  # px (96dpi default)
                    s *= 25.4 / 96.0
                scale = s
    return scale


def _apply_matrix_to_pts(pts_complex, m, vb_scale):
    """
    Apply a 3×3 affine matrix (in viewBox units) then vb_scale to get mm.
    pts_complex: list of complex numbers (x+yj) in raw path coordinates.
    Returns list of (x_mm, y_mm).
    """
    out = []
    for p in pts_complex:
        v = m @ np.array([p.real, p.imag, 1.0])
        # v is now in viewBox units; apply scale and flip Y
        out.append((v[0] * vb_scale, -v[1] * vb_scale))
    return out


def _sample_path(path_obj, samples_per_seg=20):
    pts = []
    for seg in path_obj:
        for i in range(samples_per_seg):
            pts.append(seg.point(i / samples_per_seg))
    return pts


def _split_subpaths(path_obj):
    """Split a svgpathtools Path at gaps (new M commands = new subpath)."""
    subs, cur = [], []
    for seg in path_obj:
        if cur and abs(cur[-1].end - seg.start) > 1e-3:
            subs.append(svgpathtools.Path(*cur))
            cur = []
        cur.append(seg)
    if cur:
        subs.append(svgpathtools.Path(*cur))
    return subs


def svg_to_polygons(svg_bytes):
    """
    Parse SVG → list of shapely Polygons (in mm), correctly handling:
    - group transforms
    - even-odd fill rule (holes)
    - open paths (stroke-based) → buffered polygons
    """
    vb_scale = _vb_to_mm_scale(svg_bytes)
    path_transforms = collect_path_transforms(svg_bytes)

    # Parse all paths with svgpathtools (for segment geometry)
    paths, _, _ = svgpathtools.svg2paths2(io.BytesIO(svg_bytes))

    if len(paths) != len(path_transforms):
        # Fallback: no transform info — use paths as-is with vb_scale only
        path_transforms = [(None, np.eye(3)) for _ in paths]
    
    raw_polys = []
    raw_lines = []

    for path_obj, (_, m) in zip(paths, path_transforms):
        for sp in _split_subpaths(path_obj):
            raw_pts = _sample_path(sp, samples_per_seg=20)
            if len(raw_pts) < 3:
                continue
            xy_mm = _apply_matrix_to_pts(raw_pts, m, vb_scale)

            closed = abs(sp[-1].end - sp[0].start) < 1.0  # within 1 raw unit
            
            if closed:
                poly = Polygon(xy_mm)
                if not poly.is_valid:
                    poly = poly.buffer(0)
                if poly.is_valid and poly.area > 0.1:
                    raw_polys.append(poly)
            else:
                # Open path — treat as stroke centerline, buffer it
                if len(xy_mm) >= 2:
                    raw_lines.append(xy_mm)

    # Estimate stroke width for open paths: use 2mm default (cookie-cutter wall)
    # This will be replaced by the actual wall_height in the 3D step,
    # but we need a 2D footprint — use a thin buffer just to get the shape
    STROKE_BUFFER_MM = 2.0
    for line_pts in raw_lines:
        try:
            ls = LineString(line_pts)
            poly = ls.buffer(STROKE_BUFFER_MM, cap_style=2, join_style=2)
            if poly.is_valid and poly.area > 0.1:
                raw_polys.append(poly)
        except Exception:
            pass

    if not raw_polys:
        return []

    # Sort by area descending (largest = outermost)
    raw_polys.sort(key=lambda p: p.area, reverse=True)

    # Even-odd: largest is outer, contained smaller ones are holes, etc.
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
    if isinstance(result, MultiPolygon):
        return [g for g in result.geoms if g.area > 0.1]
    return [result]


# ─── 3-D geometry ─────────────────────────────────────────────────────────────

def _ring_to_wall_mesh(coords, wall_height, fillet_r, n_arc=16, outward_sign=1):
    r = fillet_r
    straight_h = wall_height - r
    levels = [(0.0, 0.0), (straight_h, 0.0)]
    for i in range(n_arc + 1):
        angle = np.pi / 2 * i / n_arc
        levels.append((straight_h + r * np.sin(angle), r * (1 - np.cos(angle))))

    n_levels = len(levels)
    pts = list(coords)
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    n = len(pts)

    all_verts, all_faces, vidx = [], [], 0
    for i in range(n):
        p0 = np.array(pts[i])
        p1 = np.array(pts[(i + 1) % n])
        edge = p1 - p0
        elen = np.linalg.norm(edge)
        if elen < 1e-9:
            continue
        tang = edge / elen
        norm = np.array([tang[1], -tang[0]]) * outward_sign

        verts = []
        for (vz, uout) in levels:
            for t in [0.0, 1.0]:
                xy = p0 + t * edge + uout * norm
                verts.append([xy[0], xy[1], vz])

        verts = np.array(verts)
        faces = []
        for row in range(n_levels - 1):
            a = row*2; b = row*2+1; c = (row+1)*2+1; d = (row+1)*2
            if outward_sign > 0:
                faces += [[a+vidx,c+vidx,b+vidx],[a+vidx,d+vidx,c+vidx]]
            else:
                faces += [[a+vidx,b+vidx,c+vidx],[a+vidx,c+vidx,d+vidx]]
        all_verts.append(verts)
        all_faces.extend(faces)
        vidx += len(verts)

    if not all_verts:
        return None
    return np.vstack(all_verts), np.array(all_faces)


def polygon_to_mesh(polygon, wall_height, fillet_radius, n_arc=16):
    r = min(fillet_radius, wall_height * 0.48)
    meshes = []

    # Bottom cap
    try:
        v2d, f2d = trimesh.creation.triangulate_polygon(polygon, engine='earcut')
        bot_v = np.column_stack([v2d, np.zeros(len(v2d))])
        meshes.append(trimesh.Trimesh(vertices=bot_v, faces=f2d[:, ::-1], process=False))
    except Exception:
        pass

    # Top cap
    try:
        top_poly = polygon.buffer(-r)
        if not top_poly.is_empty and top_poly.area > 0.1:
            if isinstance(top_poly, MultiPolygon):
                top_poly = max(top_poly.geoms, key=lambda g: g.area)
            v2d, f2d = trimesh.creation.triangulate_polygon(top_poly, engine='earcut')
            top_v = np.column_stack([v2d, np.full(len(v2d), wall_height)])
            meshes.append(trimesh.Trimesh(vertices=top_v, faces=f2d, process=False))
    except Exception:
        pass

    # Exterior wall
    result = _ring_to_wall_mesh(polygon.exterior.coords, wall_height, r, n_arc, 1)
    if result:
        wv, wf = result
        meshes.append(trimesh.Trimesh(vertices=wv, faces=wf, process=False))

    # Interior rings (holes)
    for interior in polygon.interiors:
        result = _ring_to_wall_mesh(interior.coords, wall_height, r, n_arc, -1)
        if result:
            wv, wf = result
            meshes.append(trimesh.Trimesh(vertices=wv, faces=wf, process=False))

    if not meshes:
        return None
    combined = trimesh.util.concatenate(meshes)
    mesh = trimesh.Trimesh(vertices=combined.vertices, faces=combined.faces, process=True)
    mesh.fix_normals()
    return mesh


def svg_bytes_to_stl(svg_bytes, wall_height_mm=5.0, fillet_radius_mm=1.0, n_arc=8):
    polygons = svg_to_polygons(svg_bytes)
    if not polygons:
        raise ValueError(
            "Não foi possível extrair contornos fechados do SVG. "
            "Certifica-te de que o SVG tem paths fechados ou strokes visíveis."
        )

    # Simplify polygons to reduce vertex count before meshing.
    # 0.2mm tolerance is below 3D printer resolution — visually lossless.
    SIMPLIFY_TOL = 0.2
    simplified = []
    for poly in polygons:
        if isinstance(poly, MultiPolygon):
            for sub in poly.geoms:
                s = sub.simplify(SIMPLIFY_TOL)
                if s.is_valid and s.area > 0.1:
                    simplified.append(s)
        else:
            s = poly.simplify(SIMPLIFY_TOL)
            if s.is_valid and s.area > 0.1:
                simplified.append(s)

    if not simplified:
        raise ValueError("Nenhum contorno gerou geometria válida após simplificação.")

    meshes = []
    for poly in simplified:
        m = polygon_to_mesh(poly, wall_height_mm, fillet_radius_mm, n_arc)
        if m: meshes.append(m)

    if not meshes:
        raise ValueError("Nenhum contorno gerou geometria válida.")

    final = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
    final.fix_normals()
    return final.export(file_type='stl')

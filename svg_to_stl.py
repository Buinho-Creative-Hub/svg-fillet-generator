"""
svg_to_stl.py — SVG → STL with rounded top edges (fillet)
Buinho FabLab · CC-BY-SA 4.0

Key design decisions:
- Even-odd fill rule: inner paths become holes (difference), outer = union
- Each edge of the polygon gets a quarter-circle fillet sweep at the top
- Output: watertight binary STL
"""

import numpy as np
import trimesh
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union
import svgpathtools
from lxml import etree
import re, io


# ─── SVG → Shapely polygons ──────────────────────────────────────────────────

def _split_subpaths(path):
    """Split a svgpathtools Path into contiguous sub-paths at gaps."""
    subpaths, current = [], []
    for seg in path:
        if current and abs(current[-1].end - seg.start) > 1e-6:
            subpaths.append(svgpathtools.Path(*current))
            current = []
        current.append(seg)
    if current:
        subpaths.append(svgpathtools.Path(*current))
    return subpaths


def _path_to_poly(path, scale, samples=20):
    pts = []
    n = len(path)
    if n == 0:
        return None
    for seg in path:
        for i in range(samples):
            p = seg.point(i / samples)
            pts.append((p.real * scale, -p.imag * scale))  # flip Y
    if len(pts) < 3:
        return None
    poly = Polygon(pts)
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly if (poly.is_valid and poly.area > 0.5) else None


def svg_to_polygons(svg_bytes):
    """
    Parse SVG → list of shapely Polygons using even-odd fill rule.
    Inner paths that are fully contained in an outer path become holes.
    """
    tree = etree.parse(io.BytesIO(svg_bytes))
    root = tree.getroot()

    # Unit scale: SVG user units → mm
    vb = root.get('viewBox', '')
    width_attr = root.get('width', '')
    scale = 1.0
    if vb and width_attr:
        parts = vb.split()
        if len(parts) == 4:
            vb_w = float(parts[2])
            w_num = re.sub(r'[^0-9.]', '', width_attr)
            if w_num and float(w_num) > 0:
                s = float(w_num) / vb_w
                if 'mm' not in width_attr:
                    s *= 25.4 / 96.0
                scale = s

    paths, _, _ = svgpathtools.svg2paths2(io.BytesIO(svg_bytes))

    # Collect all sub-polygons from all paths
    raw = []
    for path in paths:
        for sp in _split_subpaths(path):
            poly = _path_to_poly(sp, scale)
            if poly is not None:
                raw.append(poly)

    if not raw:
        return []

    # Sort by area (largest first = outermost)
    raw.sort(key=lambda p: p.area, reverse=True)

    # Even-odd: build composite shape
    # Start with the largest polygon, then alternate subtract/add for contained ones
    result = raw[0]
    for poly in raw[1:]:
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
        return [g for g in result.geoms if g.area > 0.5]
    return [result]


# ─── 3-D geometry ─────────────────────────────────────────────────────────────

def _ring_to_wall_mesh(coords, wall_height, fillet_r, n_arc=16, outward_sign=1):
    """
    Build wall+fillet mesh for one ring of coordinates.
    outward_sign: +1 for exterior (normal points out), -1 for holes (normal points in).
    """
    r = fillet_r
    straight_h = wall_height - r

    # Arc levels: (z, outward_offset)
    levels = [(0.0, 0.0), (straight_h, 0.0)]
    for i in range(n_arc + 1):
        angle = np.pi / 2 * i / n_arc
        u = r * (1 - np.cos(angle))
        v = r * np.sin(angle)
        levels.append((straight_h + v, u))

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
        # Outward normal (CCW polygon: rotate CW) scaled by outward_sign
        norm = np.array([tang[1], -tang[0]]) * outward_sign

        verts = []
        for (vz, uout) in levels:
            for t in [0.0, 1.0]:
                xy = p0 + t * edge + uout * norm
                verts.append([xy[0], xy[1], vz])

        verts = np.array(verts)
        faces = []
        for row in range(n_levels - 1):
            a = row * 2;     b = row * 2 + 1
            c = (row+1)*2+1; d = (row+1)*2
            if outward_sign > 0:
                faces += [[a+vidx, c+vidx, b+vidx], [a+vidx, d+vidx, c+vidx]]
            else:
                faces += [[a+vidx, b+vidx, c+vidx], [a+vidx, c+vidx, d+vidx]]

        all_verts.append(verts)
        all_faces.extend(faces)
        vidx += len(verts)

    if not all_verts:
        return None
    return np.vstack(all_verts), np.array(all_faces)


def polygon_to_mesh(polygon, wall_height, fillet_radius, n_arc=16):
    """
    Full mesh for one shapely Polygon (may have holes):
    bottom cap + walls-with-fillet for exterior + walls for each hole + top cap.
    """
    r = min(fillet_radius, wall_height * 0.48)

    meshes = []

    # ── Bottom cap ──
    try:
        v2d, f2d = trimesh.creation.triangulate_polygon(polygon, engine='earcut')
        bot_v = np.column_stack([v2d, np.zeros(len(v2d))])
        meshes.append(trimesh.Trimesh(vertices=bot_v, faces=f2d[:, ::-1], process=False))
    except Exception:
        pass

    # ── Top cap (exterior inset by fillet_r, holes grown by fillet_r) ──
    try:
        top_poly = polygon.buffer(-r)   # shrink exterior by fillet
        if not top_poly.is_empty and top_poly.area > 0.1:
            if isinstance(top_poly, MultiPolygon):
                top_poly = max(top_poly.geoms, key=lambda g: g.area)
            v2d, f2d = trimesh.creation.triangulate_polygon(top_poly, engine='earcut')
            top_v = np.column_stack([v2d, np.full(len(v2d), wall_height)])
            meshes.append(trimesh.Trimesh(vertices=top_v, faces=f2d, process=False))
    except Exception:
        pass

    # ── Exterior wall with fillet ──
    result = _ring_to_wall_mesh(
        polygon.exterior.coords, wall_height, r, n_arc, outward_sign=1
    )
    if result:
        wv, wf = result
        meshes.append(trimesh.Trimesh(vertices=wv, faces=wf, process=False))

    # ── Interior rings (holes) — wall faces inward ──
    for interior in polygon.interiors:
        result = _ring_to_wall_mesh(
            interior.coords, wall_height, r, n_arc, outward_sign=-1
        )
        if result:
            wv, wf = result
            meshes.append(trimesh.Trimesh(vertices=wv, faces=wf, process=False))

    if not meshes:
        return None

    combined = trimesh.util.concatenate(meshes)
    mesh = trimesh.Trimesh(vertices=combined.vertices, faces=combined.faces, process=True)
    mesh.fix_normals()
    return mesh


def svg_bytes_to_stl(svg_bytes, wall_height_mm=5.0, fillet_radius_mm=1.0, n_arc=16):
    """Main entry. Returns binary STL bytes."""
    polygons = svg_to_polygons(svg_bytes)
    if not polygons:
        raise ValueError(
            "Não foi possível extrair contornos fechados do SVG. "
            "Certifica-te de que o SVG tem paths fechados (sem strokes soltos)."
        )

    meshes = []
    for poly in polygons:
        if isinstance(poly, MultiPolygon):
            for sub in poly.geoms:
                m = polygon_to_mesh(sub, wall_height_mm, fillet_radius_mm, n_arc)
                if m: meshes.append(m)
        else:
            m = polygon_to_mesh(poly, wall_height_mm, fillet_radius_mm, n_arc)
            if m: meshes.append(m)

    if not meshes:
        raise ValueError("Nenhum contorno gerou geometria válida.")

    final = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
    final.fix_normals()
    return final.export(file_type='stl')

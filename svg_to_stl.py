"""
svg_to_stl.py — Core STL generation from SVG paths with rounded top edges.
Buinho FabLab · CC-BY-SA 4.0
"""

import numpy as np
import trimesh
from shapely.geometry import Polygon, MultiPolygon
import svgpathtools
from lxml import etree
import re
import io


# ─── SVG parsing ─────────────────────────────────────────────────────────────

def svg_to_polygons(svg_bytes):
    """
    Parse an SVG and return a list of shapely Polygons.
    Units are converted to mm.
    """
    # Parse viewBox / width to derive mm-per-unit scale
    tree = etree.parse(io.BytesIO(svg_bytes))
    root = tree.getroot()

    vb = root.get('viewBox', '')
    width_attr = root.get('width', '')
    height_attr = root.get('height', '')

    scale = 1.0  # default: 1 SVG unit = 1 mm
    if vb and width_attr:
        parts = vb.split()
        if len(parts) == 4:
            vb_w = float(parts[2])
            w_num = re.sub(r'[^0-9.]', '', width_attr)
            if w_num and float(w_num) > 0:
                svg_display_w = float(w_num)
                raw_scale = svg_display_w / vb_w
                # If width is in px (no "mm"), convert px → mm
                if 'mm' not in width_attr:
                    raw_scale *= 25.4 / 96.0
                scale = raw_scale

    # Parse paths
    paths, attribs, _ = svgpathtools.svg2paths2(io.BytesIO(svg_bytes))

    polygons = []
    for path in paths:
        if not path:
            continue
        pts = _path_to_points(path)
        if len(pts) < 3:
            continue
        # Apply scale and flip Y (SVG Y-down → CAD Y-up)
        pts = [(x * scale, -y * scale) for x, y in pts]
        poly = Polygon(pts)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_valid and poly.area > 0.01:
            polygons.append(poly)

    return polygons


def _path_to_points(path, samples_per_segment=16):
    """Sample a svgpathtools Path into (x, y) floats."""
    pts = []
    for seg in path:
        n = samples_per_segment
        for i in range(n):
            t = i / n
            p = seg.point(t)
            pts.append((p.real, p.imag))
    return pts


# ─── 3-D geometry ────────────────────────────────────────────────────────────

def _build_wall_with_fillet(polygon, wall_height, fillet_radius, n_arc=16):
    """
    Build the outer wall geometry with a quarter-circle fillet at the top.

    Returns (vertices, faces) as numpy arrays.
    """
    r = min(fillet_radius, wall_height * 0.49)
    straight_h = wall_height - r

    exterior = list(polygon.exterior.coords)
    if exterior[0] == exterior[-1]:
        exterior = exterior[:-1]

    # Arc profile: (u_outward, v_upward) pairs from corner to top
    arc_pts = []
    for i in range(n_arc + 1):
        angle = np.pi / 2 * i / n_arc   # 0 → π/2
        u = r * (1 - np.cos(angle))     # 0 → r
        v = r * np.sin(angle)           # 0 → r
        arc_pts.append((u, v))

    # Height profile: (z, outward_u)
    levels = [(0.0, 0.0), (straight_h, 0.0)]
    for (u, v) in arc_pts:
        levels.append((straight_h + v, u))

    n_levels = len(levels)
    n = len(exterior)

    all_verts = []
    all_faces = []
    vidx = 0

    for i in range(n):
        p0 = np.array(exterior[i])
        p1 = np.array(exterior[(i + 1) % n])
        edge = p1 - p0
        edge_len = np.linalg.norm(edge)
        if edge_len < 1e-9:
            continue

        tangent = edge / edge_len
        # Outward normal for CCW polygon: rotate tangent 90° CW
        normal = np.array([tangent[1], -tangent[0]])

        verts = []
        for (vz, uout) in levels:
            for t_frac in [0.0, 1.0]:
                xy = p0 + t_frac * edge + uout * normal
                verts.append([xy[0], xy[1], vz])

        verts = np.array(verts)
        faces = []
        for row in range(n_levels - 1):
            a = row * 2;     b = row * 2 + 1
            c = (row+1)*2+1; d = (row+1)*2
            faces.append([a + vidx, c + vidx, b + vidx])
            faces.append([a + vidx, d + vidx, c + vidx])

        all_verts.append(verts)
        all_faces.extend(faces)
        vidx += len(verts)

    if not all_verts:
        return None, None

    return np.vstack(all_verts), np.array(all_faces)


def polygon_to_mesh(polygon, wall_height, fillet_radius, n_arc=16):
    """
    Build a complete mesh: bottom cap + walls with fillet + top cap.
    """
    r = min(fillet_radius, wall_height * 0.49)

    meshes = []

    # ── Bottom cap ──
    try:
        verts2d, faces2d = trimesh.creation.triangulate_polygon(polygon, engine='earcut')
        bot_v = np.column_stack([verts2d, np.zeros(len(verts2d))])
        bot_f = faces2d[:, ::-1]  # flip winding → normals face downward
        meshes.append(trimesh.Trimesh(vertices=bot_v, faces=bot_f, process=False))
    except Exception:
        pass

    # ── Top cap (inset by fillet radius) ──
    inset = polygon.buffer(-r)
    if not inset.is_empty and inset.area > 1e-4:
        if isinstance(inset, MultiPolygon):
            inset = max(inset.geoms, key=lambda g: g.area)
        try:
            tv, tf = trimesh.creation.triangulate_polygon(inset, engine='earcut')
            top_v = np.column_stack([tv, np.full(len(tv), wall_height)])
            meshes.append(trimesh.Trimesh(vertices=top_v, faces=tf, process=False))
        except Exception:
            pass

    # ── Walls with fillet ──
    wv, wf = _build_wall_with_fillet(polygon, wall_height, r, n_arc)
    if wv is not None:
        meshes.append(trimesh.Trimesh(vertices=wv, faces=wf, process=False))

    if not meshes:
        return None

    combined = trimesh.util.concatenate(meshes)
    mesh = trimesh.Trimesh(vertices=combined.vertices, faces=combined.faces, process=True)
    mesh.fix_normals()
    return mesh


def svg_bytes_to_stl(svg_bytes, wall_height_mm=5.0, fillet_radius_mm=1.0, n_arc=16):
    """
    Main entry. Returns binary STL bytes.
    """
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
                if m is not None:
                    meshes.append(m)
        else:
            m = polygon_to_mesh(poly, wall_height_mm, fillet_radius_mm, n_arc)
            if m is not None:
                meshes.append(m)

    if not meshes:
        raise ValueError("Nenhum contorno gerou geometria válida.")

    final = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
    final.fix_normals()
    return final.export(file_type='stl')

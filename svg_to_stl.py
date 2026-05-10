"""
svg_to_stl.py — SVG → STL with rounded top edges (fillet)
Buinho FabLab · CC-BY-SA 4.0

Architecture:
- SVG: lxml tree walk composing all ancestor transforms (handles potrace/Inkscape)
- Even-odd fill rule via shapely difference/union
- 3D: swept-profile approach → single watertight solid
  * Per-vertex normals on the polygon boundary
  * Arc inset applied per-vertex (no buffer → no vertex count mismatch)
  * Unified inset formula: both exterior and holes use pts - u * vertex_normals
    (CCW exterior: normals outward → moves inward ✓)
    (CW hole:      normals inward  → moves outward = toward material ✓)
  * Caps use wall vertex indices directly via Delaunay (no Steiner points)
  * Correct euler per genus: 2-2*n_holes
"""

import numpy as np
import trimesh
from shapely.geometry import Polygon, MultiPolygon, LineString, Point
from shapely.geometry.polygon import orient
import svgpathtools
from lxml import etree
from scipy.spatial import Delaunay
import re, io, math


# ─── Transform helpers ───────────────────────────────────────────────────────

def _parse_transform(t):
    m = np.eye(3)
    for match in re.finditer(r'(\w+)\(([^)]+)\)', t or ''):
        name = match.group(1)
        args = [float(x) for x in re.split(r'[,\s]+', match.group(2).strip()) if x]
        if name == 'translate':
            tx, ty = args[0], (args[1] if len(args)>1 else 0)
            m = m @ np.array([[1,0,tx],[0,1,ty],[0,0,1]], float)
        elif name == 'scale':
            sx = args[0]; sy = args[1] if len(args)>1 else sx
            m = m @ np.array([[sx,0,0],[0,sy,0],[0,0,1]], float)
        elif name == 'matrix':
            a,b,c,d,e,f = args
            m = m @ np.array([[a,c,e],[b,d,f],[0,0,1]], float)
        elif name == 'rotate':
            ang = np.radians(args[0])
            cx = args[1] if len(args)>1 else 0; cy = args[2] if len(args)>2 else 0
            R = np.array([[np.cos(ang),-np.sin(ang),0],[np.sin(ang),np.cos(ang),0],[0,0,1]], float)
            m = m @ np.array([[1,0,cx],[0,1,cy],[0,0,1]],float) @ R @ np.array([[1,0,-cx],[0,1,-cy],[0,0,1]],float)
    return m


def _collect_path_transforms(svg_bytes):
    tree = etree.parse(io.BytesIO(svg_bytes))
    root = tree.getroot()
    ns = root.nsmap.get(None,'')
    def tag(t): return f'{{{ns}}}{t}' if ns else t
    results = []
    def walk(el, pm):
        local = el.tag.split('}')[-1] if '}' in el.tag else el.tag
        m = pm @ _parse_transform(el.get('transform',''))
        if local == 'path' and el.get('d',''):
            results.append((el.get('d'), m))
        for child in el: walk(child, m)
    walk(root, np.eye(3))
    return results


def _vb_scale(svg_bytes):
    tree = etree.parse(io.BytesIO(svg_bytes))
    root = tree.getroot()
    vb = root.get('viewBox',''); wa = root.get('width','') or ''
    scale = 1.0
    if vb and wa:
        parts = vb.split()
        if len(parts)==4:
            vb_w = float(parts[2])
            w_num = re.sub(r'[^0-9.]','', wa)
            if w_num and float(w_num)>0:
                s = float(w_num)/vb_w
                if   'mm' in wa: pass
                elif 'pt' in wa: s *= 25.4/72.0
                elif 'cm' in wa: s *= 10.0
                elif 'in' in wa: s *= 25.4
                else:            s *= 25.4/96.0
                scale = s
    return scale


def _apply_matrix(pts_complex, m, vb_s):
    y_flipped = m[1,1] < 0
    out = []
    for p in pts_complex:
        v = m @ np.array([p.real, p.imag, 1.0])
        out.append((v[0]*vb_s, v[1]*vb_s if y_flipped else -v[1]*vb_s))
    return out


def _split_subpaths(path_obj):
    subs, cur = [], []
    for seg in path_obj:
        if cur and abs(cur[-1].end - seg.start) > 1e-3:
            subs.append(svgpathtools.Path(*cur)); cur = []
        cur.append(seg)
    if cur: subs.append(svgpathtools.Path(*cur))
    return subs


# ─── SVG → Shapely polygons ──────────────────────────────────────────────────

def svg_to_polygons(svg_bytes):
    vb_s = _vb_scale(svg_bytes)
    path_transforms = _collect_path_transforms(svg_bytes)
    paths, _, _ = svgpathtools.svg2paths2(io.BytesIO(svg_bytes))
    if len(paths) != len(path_transforms):
        path_transforms = [(None, np.eye(3)) for _ in paths]

    raw_polys, raw_lines = [], []
    for path_obj, (_, m) in zip(paths, path_transforms):
        for sp in _split_subpaths(path_obj):
            pts_c = [seg.point(i/20) for seg in sp for i in range(20)]
            if len(pts_c) < 3: continue
            xy = _apply_matrix(pts_c, m, vb_s)
            closed = abs(sp[-1].end - sp[0].start) < 1.0
            if closed:
                poly = Polygon(xy)
                if not poly.is_valid: poly = poly.buffer(0)
                if poly.is_valid and poly.area > 0.1: raw_polys.append(poly)
            elif len(xy) >= 2:
                raw_lines.append(xy)

    for lp in raw_lines:
        try:
            poly = LineString(lp).buffer(2.0, cap_style=2, join_style=2)
            if poly.is_valid and poly.area > 0.1: raw_polys.append(poly)
        except Exception: pass

    if not raw_polys: return []

    raw_polys.sort(key=lambda p: p.area, reverse=True)
    result = raw_polys[0]
    for poly in raw_polys[1:]:
        try:
            if result.contains(poly.centroid): result = result.difference(poly)
            else: result = result.union(poly)
        except Exception: pass

    if result.is_empty: return []

    def _orient(p): return orient(p, sign=1.0)
    if isinstance(result, MultiPolygon):
        return [_orient(g) for g in result.geoms if g.area > 0.1]
    return [_orient(result)]


# ─── 3-D geometry ─────────────────────────────────────────────────────────────

def _vertex_normals(pts):
    """
    Per-vertex normals for a 2D ring.
    For CCW ring: normals are outward (away from interior).
    For CW ring:  normals are inward  (into the hole).
    This asymmetry is intentional and used by the unified inset formula below.
    """
    n = len(pts)
    def edge_n(p0, p1):
        d = p1-p0; dn = np.linalg.norm(d)
        if dn < 1e-10: return np.zeros(2)
        t = d/dn; return np.array([t[1], -t[0]])  # 90° CW = outward for CCW ring
    vn = np.zeros((n, 2))
    for i in range(n):
        n1 = edge_n(pts[i], pts[(i+1)%n])
        n2 = edge_n(pts[(i-1)%n], pts[i])
        avg = n1+n2; nm = np.linalg.norm(avg)
        vn[i] = avg/nm if nm > 1e-10 else n1
    return vn


def _triangulate_cap(ring_xys_list, shapely_poly):
    """
    Triangulate a cap using ONLY the provided ring vertices (no Steiner points).

    ring_xys_list: [np.array(n_ext, 2), np.array(n_h1, 2), ...]
    shapely_poly: used for centroid inside-test to filter Delaunay triangles.
    Returns face array (indices into np.vstack(ring_xys_list)).
    """
    all_pts = np.vstack(ring_xys_list)
    tri = Delaunay(all_pts)
    valid = []
    for face in tri.simplices:
        c = all_pts[face].mean(axis=0)
        if shapely_poly.contains(Point(c)):
            valid.append(face)
    return np.array(valid, dtype=np.int64) if valid else np.empty((0,3), int)


def polygon_to_mesh(polygon, wall_height, fillet_radius, n_arc=24):
    """
    Single watertight mesh for a shapely Polygon (may have holes).

    Inset formula (unified for exterior and holes):
      ring_xy = pts - u * vertex_normals(pts)
      - CCW exterior: normals outward → pts - u*n moves inward ✓
      - CW hole:      normals inward  → pts - u*n moves toward material ✓

    Wall face winding (same for both):
      [a,b,c][a,c,d] — CCW exterior gives outward normals,
                        CW hole gives inward-of-solid normals ✓

    Caps re-use wall vertex indices via Delaunay (no Steiner points, no seams).
    """
    r = min(fillet_radius, wall_height * 0.48)
    straight_h = wall_height - r

    # Arc profile: z from straight_h to wall_height, inset from 0 to r
    z_levels = (
        [0.0, straight_h]
        + [straight_h + r*math.sin(math.pi/2*s/n_arc) for s in range(1, n_arc+1)]
    )
    u_levels = (
        [0.0, 0.0]
        + [r*(1-math.cos(math.pi/2*s/n_arc)) for s in range(1, n_arc+1)]
    )
    n_levels = len(z_levels)

    all_verts = []
    all_faces = []
    global_offset = 0
    cap_data = []  # list of (bot_global_idx, top_global_idx) per ring

    rings = [(polygon.exterior.coords, False)] + [
        (interior.coords, True) for interior in polygon.interiors
    ]

    for ring_coords, is_hole in rings:
        pts = np.array(list(ring_coords)[:-1])
        n_ring = len(pts)
        if n_ring < 3:
            continue

        vn = _vertex_normals(pts)

        # Build vertex grid (n_levels × n_ring, 3)
        verts = np.empty((n_levels * n_ring, 3))
        for lv, (u, z) in enumerate(zip(u_levels, z_levels)):
            xy = pts - u * vn      # unified formula
            verts[lv*n_ring:(lv+1)*n_ring, :2] = xy
            verts[lv*n_ring:(lv+1)*n_ring, 2]  = z

        all_verts.append(verts)

        # Wall quads as triangle pairs (same winding for both exterior and holes)
        faces = []
        for lv in range(n_levels - 1):
            for i in range(n_ring):
                a = lv*n_ring + i
                b = lv*n_ring + (i+1)%n_ring
                c = (lv+1)*n_ring + (i+1)%n_ring
                d = (lv+1)*n_ring + i
                faces.extend([[a,b,c],[a,c,d]])

        all_faces.append(np.array(faces, dtype=np.int64) + global_offset)

        bot_idx = list(range(global_offset, global_offset + n_ring))
        top_idx = list(range(global_offset + (n_levels-1)*n_ring,
                              global_offset + n_levels*n_ring))
        cap_data.append((bot_idx, top_idx))
        global_offset += len(verts)

    if not all_verts:
        return None

    verts_all = np.vstack(all_verts)
    faces_all = np.vstack(all_faces)

    ext_bot, ext_top = cap_data[0]
    hole_bots = [cap_data[i][0] for i in range(1, len(cap_data))]
    hole_tops = [cap_data[i][1] for i in range(1, len(cap_data))]

    # ── Bottom cap (normals DOWN → reversed winding) ─────────────────────────
    try:
        bex = verts_all[ext_bot, :2]
        bho = [verts_all[hb, :2] for hb in hole_bots]
        bp  = orient(Polygon(bex.tolist(), [h.tolist() for h in bho]), sign=1.0)
        rxs = [bex] + bho
        loc = np.array(ext_bot + [i for hb in hole_bots for i in hb])
        fl  = _triangulate_cap(rxs, bp)
        if len(fl) > 0:
            faces_all = np.vstack([faces_all, loc[fl[:, ::-1]]])
    except Exception:
        pass

    # ── Top cap (normals UP → standard winding) ──────────────────────────────
    try:
        tex = verts_all[ext_top, :2]
        tho = [verts_all[ht, :2] for ht in hole_tops]
        tp  = orient(Polygon(tex.tolist(), [h.tolist() for h in tho]), sign=1.0)
        rxs = [tex] + tho
        loc = np.array(ext_top + [i for ht in hole_tops for i in ht])
        fl  = _triangulate_cap(rxs, tp)
        if len(fl) > 0:
            faces_all = np.vstack([faces_all, loc[fl]])
    except Exception:
        pass

    mesh = trimesh.Trimesh(vertices=verts_all, faces=faces_all, process=False)
    mesh.merge_vertices(merge_tex=False, merge_norm=False)
    return mesh


def svg_bytes_to_stl(svg_bytes, wall_height_mm=5.0, fillet_radius_mm=1.0, n_arc=16):
    polygons = svg_to_polygons(svg_bytes)
    if not polygons:
        raise ValueError(
            "Não foi possível extrair contornos fechados do SVG. "
            "Certifica-te de que o SVG tem paths fechados ou strokes visíveis."
        )

    # Simplify to 0.2mm — below 3D print resolution, no visual impact
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
    return final.export(file_type='stl')

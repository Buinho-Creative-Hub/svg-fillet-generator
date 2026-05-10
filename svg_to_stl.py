"""
svg_to_stl.py — SVG → STL with rounded top edges (fillet)
Buinho FabLab · CC-BY-SA 4.0

Architecture:
- SVG: lxml tree walk composing all ancestor transforms (handles potrace/Inkscape)
- Even-odd fill rule via shapely difference/union
- 3D: swept-profile approach → single watertight solid
  * Per-vertex outward normals on the polygon boundary
  * Arc inset applied per-vertex (no buffer → no vertex count mismatch)  
  * Bottom cap + wall strips + top cap share exact vertex positions
"""

import numpy as np
import trimesh
from shapely.geometry import Polygon, MultiPolygon, LineString
from shapely.geometry.polygon import orient
import svgpathtools
from lxml import etree
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

def _signed_area_2d(coords):
    pts = list(coords)
    n = len(pts)
    return sum(pts[i][0]*pts[(i+1)%n][1] - pts[(i+1)%n][0]*pts[i][1] for i in range(n)) / 2


def _vertex_normals(pts, outward=True):
    """Per-vertex outward (or inward) normals for a 2D polygon ring."""
    n = len(pts)
    def edge_n(p0, p1):
        d = p1 - p0; dn = np.linalg.norm(d)
        if dn < 1e-10: return np.zeros(2)
        t = d/dn; return np.array([t[1], -t[0]])  # outward for CCW ring

    vnormals = np.zeros((n, 2))
    for i in range(n):
        n1 = edge_n(pts[i], pts[(i+1)%n])
        n2 = edge_n(pts[(i-1)%n], pts[i])
        avg = n1 + n2; nm = np.linalg.norm(avg)
        vnormals[i] = avg/nm if nm > 1e-10 else n1

    return vnormals if outward else -vnormals


def polygon_to_mesh(polygon, wall_height, fillet_radius, n_arc=24):
    """
    Single watertight mesh for a shapely Polygon (may have holes).
    Uses swept-profile with per-vertex normals — no buffer() calls on rings.
    """
    r = min(fillet_radius, wall_height * 0.48)
    straight_h = wall_height - r

    all_verts = []
    all_faces = []
    vidx = 0

    # Cap polygons (2D) for bottom and top
    bot_ext_2d, top_ext_2d = None, None
    bot_holes_2d, top_holes_2d = [], []

    def add_ring(ring_coords):
        nonlocal vidx
        pts = np.array(list(ring_coords)[:-1])
        n = len(pts)
        if n < 3: return None, None

        sa = _signed_area_2d(ring_coords)
        is_ccw = sa > 0
        vnormals = _vertex_normals(pts, outward=is_ccw)

        # Level heights and inset amounts along arc
        z_levels = [0.0, straight_h] + [straight_h + r*math.sin(math.pi/2*s/n_arc) for s in range(1, n_arc+1)]
        u_levels = [0.0, 0.0]          + [r*(1-math.cos(math.pi/2*s/n_arc))         for s in range(1, n_arc+1)]
        n_levels = len(z_levels)

        # Build vertex grid: n_levels × n
        verts_grid = []
        for lv in range(n_levels):
            u = u_levels[lv]; z = z_levels[lv]
            ring_pts = pts - u * vnormals  # inset toward interior
            for i in range(n):
                verts_grid.append([ring_pts[i][0], ring_pts[i][1], z])

        verts_grid = np.array(verts_grid)
        all_verts.append(verts_grid)

        # Build quad strips
        for lv in range(n_levels - 1):
            for i in range(n):
                a = vidx + lv*n + i
                b = vidx + lv*n + (i+1)%n
                c = vidx + (lv+1)*n + (i+1)%n
                d = vidx + (lv+1)*n + i
                if is_ccw:  # exterior: standard CCW winding
                    all_faces.extend([[a,b,c],[a,c,d]])
                else:        # hole: flip winding
                    all_faces.extend([[a,c,b],[a,d,c]])

        # Extract bottom ring (lv=0) and top ring (lv=n_levels-1) as 2D points
        bot_ring = [(verts_grid[i][0], verts_grid[i][1]) for i in range(n)]
        top_ring = [(verts_grid[(n_levels-1)*n+i][0], verts_grid[(n_levels-1)*n+i][1]) for i in range(n)]

        vidx += len(verts_grid)
        return bot_ring, top_ring

    # Exterior
    bot_ext_2d, top_ext_2d = add_ring(polygon.exterior.coords)

    # Holes
    for interior in polygon.interiors:
        bh, th = add_ring(interior.coords)
        if bh: bot_holes_2d.append(bh)
        if th: top_holes_2d.append(th)

    # Bottom cap (z=0, normals down)
    if bot_ext_2d:
        try:
            bp = orient(Polygon(bot_ext_2d, bot_holes_2d), sign=1.0)
            v2d, f2d = trimesh.creation.triangulate_polygon(bp, engine='earcut')
            bv = np.column_stack([v2d, np.zeros(len(v2d))])
            all_verts.append(bv)
            all_faces.extend((f2d[:,::-1] + vidx).tolist())
            vidx += len(bv)
        except Exception: pass

    # Top cap (z=wall_height, normals up)
    if top_ext_2d:
        try:
            tp = orient(Polygon(top_ext_2d, top_holes_2d), sign=1.0)
            v2d, f2d = trimesh.creation.triangulate_polygon(tp, engine='earcut')
            tv = np.column_stack([v2d, np.full(len(v2d), wall_height)])
            all_verts.append(tv)
            all_faces.extend((f2d + vidx).tolist())
            vidx += len(tv)
        except Exception: pass

    if not all_verts: return None

    verts = np.vstack(all_verts)
    faces = np.array(all_faces)
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=True)
    mesh.fix_normals()
    return mesh


def svg_bytes_to_stl(svg_bytes, wall_height_mm=5.0, fillet_radius_mm=1.0, n_arc=24):
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
    final.fix_normals()
    return final.export(file_type='stl')

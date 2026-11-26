"""Colour voxel art format + fast shaded orthographic renderer (no Minecraft IDs).

JSON schema ("art" format):
{
 "name": "...", "size": [W,H,D],                    # x right, y up, z toward viewer at azim 0
 "camera": {"azim": 30, "elev": 20},                # view that should match the reference image
 "palette": {"a": "#7a6a4f", "b": ["#8a7a5c","#7f6f52","#93835f"], ...},   # list = per-voxel noise pick
 "shapes": [                                        # applied in order; "." colour carves air
   {"type":"box","from":[x,y,z],"to":[x,y,z],"c":"a","hollow":false},
   {"type":"ellipsoid","center":[x,y,z],"radius":[rx,ry,rz],"c":"a"},
   {"type":"cylinder","base":[x,y,z],"radius":r,"height":h,"axis":"y","c":"a","r_top":r2},
   {"type":"shell_shade","c_from":"a","c_to":"d","dir":[0,-1,0],"depth":1}   # recolour voxels whose neighbour in dir is empty
 ],
 "layers": [...optional, as in voxel_ai...],
 "voxels": [{"x":..,"y":..,"z":..,"c":"a"}]
}
"""
import json, math, numpy as np
from PIL import Image, ImageDraw

def hex2rgb(h):
    h = h.lstrip("#"); return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def load(src, seed=7):
    d = src if isinstance(src, dict) else json.load(open(src))
    W, H, D = d["size"]
    rng = np.random.default_rng(seed)
    pal = {}
    for k, v in d.get("palette", {}).items():
        vs = v if isinstance(v, list) else [v]
        pal[k] = [hex2rgb(x) for x in vs]
    occ = np.zeros((W, H, D), bool); col = np.zeros((W, H, D, 3), np.uint8)
    X, Y, Z = np.meshgrid(np.arange(W), np.arange(H), np.arange(D), indexing="ij")
    warn = []
    def paint(mask, c):
        if c in (".", "air", None): occ[mask] = False; return
        if c not in pal:
            if isinstance(c, str) and c.startswith("#"): pal[c] = [hex2rgb(c)]
            else: warn.append(f"unknown colour {c}"); return
        cs = np.array(pal[c], np.uint8); n = int(mask.sum())
        occ[mask] = True; col[mask] = cs[rng.integers(0, len(cs), n)]
    for s in d.get("shapes", []):
        t = s.get("type")
        try:
            if t == "box":
                (x0,y0,z0),(x1,y1,z1) = s["from"], s["to"]
                m = (X>=min(x0,x1))&(X<=max(x0,x1))&(Y>=min(y0,y1))&(Y<=max(y0,y1))&(Z>=min(z0,z1))&(Z<=max(z0,z1))
                if s.get("hollow"):
                    m &= ~((X>min(x0,x1))&(X<max(x0,x1))&(Y>min(y0,y1))&(Y<max(y0,y1))&(Z>min(z0,z1))&(Z<max(z0,z1)))
                paint(m, s["c"])
            elif t == "ellipsoid":
                cx,cy,cz = s["center"]; r = s["radius"]; rx,ry,rz = (r,r,r) if np.isscalar(r) else r
                m = ((X-cx)/max(rx,.5))**2 + ((Y-cy)/max(ry,.5))**2 + ((Z-cz)/max(rz,.5))**2 <= 1.0
                if "clip_y" in s: lo, hi = s["clip_y"]; m &= (Y>=lo)&(Y<=hi)
                paint(m, s["c"])
            elif t == "cylinder":
                bx,by,bz = s["base"]; r0 = s["radius"]; r1 = s.get("r_top", r0); h = s["height"]; ax = s.get("axis","y")
                A, P, Q, a0, p0, q0 = {"y":(Y,X,Z,by,bx,bz),"x":(X,Y,Z,bx,by,bz),"z":(Z,X,Y,bz,bx,by)}[ax]
                tt = np.clip((A-a0)/max(h-1,1), 0, 1); rr = r0 + (r1-r0)*tt
                m = (A>=a0)&(A<a0+h)&(((P-p0)**2+(Q-q0)**2) <= rr**2 + .25)
                paint(m, s["c"])
            elif t == "shell_shade":
                src_c = s.get("c_from"); dx,dy,dz = s.get("dir",[0,-1,0]); depth = s.get("depth",1)
                srcmask = occ.copy()
                if src_c in pal:
                    cs = np.array(pal[src_c]); srcmask &= (col[...,None,:]==cs[None,None,None]).all(-1).any(-1)
                exposed = np.zeros_like(occ)
                for k in range(1, depth+1):
                    sh = np.zeros_like(occ); sl = lambda v,n: slice(max(v,0), n+min(v,0))
                    sh[sl(-dx*k,W), sl(-dy*k,H), sl(-dz*k,D)] = occ[sl(dx*k,W), sl(dy*k,H), sl(dz*k,D)]
                    exposed |= ~sh
                paint(srcmask & exposed, s["c_to"])
            else: warn.append(f"unknown shape {t}")
        except Exception as e: warn.append(f"shape {t} error {e}")
    for y, layer in enumerate(d.get("layers", [])[:H]):
        for z, row in enumerate(layer[:D]):
            for x, ch in enumerate(row[:W]):
                if ch not in (" ",): 
                    if ch == "." : continue
                    paint((X==x)&(Y==y)&(Z==z), ch)
    vs = d.get("voxels", [])
    if vs:   # fast path: group by colour key
        from collections import defaultdict
        groups = defaultdict(list)
        for v in vs:
            if 0<=v["x"]<W and 0<=v["y"]<H and 0<=v["z"]<D: groups[v["c"]].append((v["x"],v["y"],v["z"]))
        for c, pts in groups.items():
            m = np.zeros_like(occ); p_ = np.array(pts); m[p_[:,0],p_[:,1],p_[:,2]] = True; paint(m, c)
    return d, occ, col, warn

FACES = [((1,0,0),[(1,0,0),(1,1,0),(1,1,1),(1,0,1)]), ((-1,0,0),[(0,0,0),(0,0,1),(0,1,1),(0,1,0)]),
         ((0,1,0),[(0,1,0),(0,1,1),(1,1,1),(1,1,0)]), ((0,-1,0),[(0,0,0),(1,0,0),(1,0,1),(0,0,1)]),
         ((0,0,1),[(0,0,1),(1,0,1),(1,1,1),(0,1,1)]), ((0,0,-1),[(0,0,0),(0,1,0),(1,1,0),(1,0,0)])]

def cam_R(azim, elev):
    a, e = math.radians(azim), math.radians(elev)
    R1 = np.array([[math.cos(a),0,math.sin(a)],[0,1,0],[-math.sin(a),0,math.cos(a)]])
    R2 = np.array([[1,0,0],[0,math.cos(e),-math.sin(e)],[0,math.sin(e),math.cos(e)]])
    return R2 @ R1

def render(occ, col, azim=30, elev=20, size=512, bg=(255,255,255), light=(-0.4, 0.8, 0.45), ao=True, outline=False, ids=None, frame=None):
    """Orthographic shaded render. Returns (RGB PIL image, bool mask). azim rotates about y, elev tilts camera up."""
    W, H, D = occ.shape
    a, e = math.radians(azim), math.radians(elev)
    # camera basis: view dir from camera to scene
    R1 = np.array([[math.cos(a),0,math.sin(a)],[0,1,0],[-math.sin(a),0,math.cos(a)]])
    R2 = np.array([[1,0,0],[0,math.cos(e),-math.sin(e)],[0,math.sin(e),math.cos(e)]])
    R = R2 @ R1   # world -> camera; camera looks along -z
    ctr = np.array([W, H, D]) / 2
    Lw = np.array(light, float); Lw /= np.linalg.norm(Lw)
    pad = np.pad(occ, 1)
    polys = []
    xs, ys, zs = np.nonzero(occ)
    for fi, (n, quad) in enumerate(FACES):
        n = np.array(n); ncam = R @ n
        if ncam[2] <= 1e-6: continue           # back-facing
        nb = pad[xs+1+n[0], ys+1+n[1], zs+1+n[2]]
        sel = ~nb
        if not sel.any(): continue
        fx, fy, fz = xs[sel], ys[sel], zs[sel]
        diff = max(0.0, float(n @ Lw)); shade = 0.55 + 0.45*diff
        if ao:  # occupancy of the 8 voxels around the face in the outer layer
            t1 = [i for i in range(3) if n[i]==0]
            occl = np.zeros(len(fx))
            for du in (-1,0,1):
                for dv in (-1,0,1):
                    if du==0 and dv==0: continue
                    off = np.array(n).copy(); off[t1[0]] += du; off[t1[1]] += dv
                    occl += pad[fx+1+off[0], fy+1+off[1], fz+1+off[2]]
            aof = 1 - 0.06*occl
        else: aof = np.ones(len(fx))
        q = np.array(quad, float)                                   # vectorised over faces (was a per-face Python loop)
        p = np.stack([fx, fy, fz], 1).astype(float)
        corners = (q[None] + p[:, None, :] - ctr) @ R.T             # (n, 4, 3)
        depth = corners[:, :, 2].mean(1)
        if ids is not None:
            v = ids[fx, fy, fz].astype(np.int64)*6 + fi + 1; cc = np.stack([v >> 16 & 255, v >> 8 & 255, v & 255], 1)
        else:
            cc = np.clip(col[fx, fy, fz].astype(float) * shade * aof[:, None], 0, 255).astype(int)
        polys.append((depth, corners[:, :, :2], cc))
    img = Image.new("RGB", (size, size), (0,0,0) if ids is not None else bg); mimg = Image.new("L", (size, size), 0)
    if not polys: return img, np.zeros((size, size), bool)
    depth = np.concatenate([p[0] for p in polys]); pts = np.concatenate([p[1] for p in polys]); cols = np.concatenate([p[2] for p in polys])
    if frame == "grid":   # fixed framing from the grid corners (stable when occupancy changes)
        gc = np.array([[x, y, z] for x in (0, W) for y in (0, H) for z in (0, D)], float)
        allp = ((gc - ctr) @ R.T)[:, :2]
    else: allp = pts.reshape(-1, 2)
    mn, mx = allp.min(0), allp.max(0)
    sc = 0.9*size / max(mx-mn); off = (size - (mx-mn)*sc)/2
    dr, dm = ImageDraw.Draw(img), ImageDraw.Draw(mimg)
    order = np.argsort(depth, kind="stable")                     # same order as sorted(..., key=depth)
    px = (pts[..., 0] - mn[0])*sc + off[0]; py = size - ((pts[..., 1] - mn[1])*sc + off[1])
    PP = np.stack([px, py], -1)[order].tolist(); CC = [tuple(c) for c in cols[order].tolist()]
    for pp, c in zip(PP, CC):
        pp = [tuple(t) for t in pp]
        dr.polygon(pp, fill=c, outline=(0,0,0) if outline else c); dm.polygon(pp, fill=255)
    return img, np.array(mimg) > 0

def sheet(occ, col, path, views=((30,20),(120,20),(210,20),(300,20),(30,70),(30,-25)), size=320):
    ims = [render(occ, col, a, e, size)[0] for a, e in views]
    S = Image.new("RGB", (size*3, size*2), (255,255,255))
    for i, im in enumerate(ims): S.paste(im, ((i%3)*size, (i//3)*size))
    S.save(path); return path

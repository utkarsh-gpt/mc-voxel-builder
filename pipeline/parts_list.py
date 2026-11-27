#!/usr/bin/env python3
"""Steps 1-2 of specs/detailed-parts.md: look at the reference photo(s), write every part with
where / detailed notes / built_as, then check the list against the pictures.

    python parts_list.py SUBJECT [--images ...] [--force] [--no-verify] [--model claude-haiku-5-5]

Writes art/final/meta/<n>_parts.json (merged: never clobbers hand-written keys such as zones,
grad, rebuild_sails, squash_z, boxes, feature_kinds unless --force regenerates the blueprint,
and even then those operational keys are preserved). Organic subjects (animals, plants, trees,
statues) get {"organic": true, "parts": {}} and an empty ortho prompt block.

The file is reused downstream by ortho_verify / ortho_gen (prompt_block), run_v2, run_combined
and stamp_generic. Existing hand-written lists (a JSON array of {id, faces, built_as: "open"})
are left untouched and are readable through iter_parts() / has_built() alongside the new
dict-of-parts schema from the spec.
"""
import argparse, hashlib, json, os, re, sys
import llm

HAIKU = "claude-haiku-5-5"
CACHE = "out/cache"
META = "art/final/meta"
BUILT = ("set_back", "open", "proud", "outline")
KINDS = ("mass", "feature")
SYMMETRY = ("bilateral", "near", "asymmetric")   # left-right silhouette, from the photo; shape_fit: "asymmetric" vetoes x mirroring
FACES = ("front", "right", "back", "left", "top", "all")
GEO = {"set_back": "set back: a recess cut into the wall, the wall face in front of it and its floor deeper than the wall",
       "open": "open: a hole or gap you can see through or past",
       "proud": "proud: a solid standing out of the surface",
       "outline": "outline: it changes the silhouette"}
# operational keys from hand-written parts files: never overwritten by a generated blueprint
HAND = ("grad", "eyebrows", "boxes", "zones", "rebuild_sails", "squash_z", "feature_kinds",
        "kit_overrides", "carve_axes", "drop_lone_posts", "notes_fix", "note")
INFER = (("arcade", "open"), ("arch", "open"), ("portal", "set_back"), ("door", "set_back"),
         ("window", "set_back"), ("rose", "set_back"), ("niche", "set_back"), ("panel", "set_back"),
         ("buttress", "proud"), ("pilaster", "proud"), ("hood", "proud"), ("trim", "proud"),
         ("sail", "proud"), ("spire", "outline"), ("chimney", "outline"), ("gable", "outline"),
         ("battlement", "outline"), ("cap", "outline"), ("roof", "outline"), ("tower", "outline"),
         ("dome", "outline"), ("porch", "proud"), ("dormer", "outline"), ("step", "proud"))

GEN_PROMPT = """Read the image(s) at these exact paths with the Read tool (look at every one before you write):
{images}

You are writing a blueprint of every architectural PART of this subject ("{subject}") for a 3D mesh and voxel build.

First classify the subject:
- ORGANIC: an animal, plant, character, tree, statue, creature, or other non-building. No architectural parts list.
- STRUCTURE: a building, gate, tower, bridge, vehicle-like architecture, or similar.

Also judge the LEFT-RIGHT symmetry of the subject's silhouette as seen from its front (towers, turrets, minarets, wings, columns and annexes included, not just the central body):
- "bilateral": the left and right halves are mirror images, including every tower / turret / wing
- "near": mirror images apart from small details (a door off-centre, a different window)
- "asymmetric": a tower, turret, minaret, wing, column or other large part exists or differs on only one side

If ORGANIC, reply with ONLY this JSON object and nothing else:
{{"subject": "{subject}", "organic": true, "symmetry": "bilateral, near or asymmetric", "summary": "one paragraph of what the subject is, as the pictures show it", "parts": {{}}}}

If a STRUCTURE, list every visible part. Repeated pieces share one id and a count (three doors are "door" with count 3; two towers are "tower" with count 2).
Each part must have:
- kind: "mass" (the body / outline: walls, roof, towers, plinth, the main block) or "feature" (a part the body carries: door, window, buttress, chimney, sail, porch post, dormer, ...)
- count: integer >= 1
- parent: required on a feature, the mass part id it sits on
- face: "front", "right", "back", "left", "top", "all", or a list of those. Required on a feature.
- where: one or two sentences naming the face or side, the height on that face, and the neighbours (above, below, beside, between).
- notes: at most 15 words. Form, depth (set back / proud / open / outline) and how it meets its neighbours, as the pictures show. No colour-only notes ("a dark window" is not a note; "pointed opening set back with a ledge under it" is). Do not invent anything the pictures do not show.
- built_as: a non-empty list of one or more of:
  set_back — a recess in a wall: a window, a door, a portal, a niche, a panel. The wall face is in front of it, and its floor is deeper than the wall.
  open — a hole or gap you can see through or past (a see-through arch, an arcade passage).
  proud — a solid standing out of the surface (a buttress, a hood, a pilaster, a porch post).
  outline — it changes the silhouette (a spire, a chimney, a gable, a roof, sails).

A part that is only a colour, a dark patch, or a drawing on a flat wall is not a part and must not be listed.
Do not emit voxels, coordinates, or dimensions.

Reply with ONLY a JSON object and nothing else:
{{"subject": "{subject}", "organic": false, "symmetry": "bilateral, near or asymmetric", "summary": "one paragraph of what the finished building must still read as",
  "parts": {{"part_id": {{"kind": "mass or feature", "count": 1, "parent": "mass_id (features only)", "face": "front", "where": "...", "notes": "...", "built_as": ["set_back"]}}}}}}
"""

VER_PROMPT = """Read the image(s) at these exact paths with the Read tool (look at every one before you judge):
{images}

This is a parts-list blueprint written from those pictures:

{blueprint}

If the blueprint has "organic": true, you are only checking that classification. An empty parts object is required and correct for an animal, plant, tree, statue or creature — do not invent anatomical or decorative parts, and do not invent a new built_as vocabulary. If the classification is right, reply with ONLY:
{{"ok": true, "notes": "classified organic; no architectural parts list"}}
If it is actually a structure, reply with ok: false and a full revised structure blueprint (parts with kind, count, where, notes, built_as in set_back / open / proud / outline).

Otherwise check the list against the pictures.
Reject it (and describe how to fix it) if any of these is true:
- a separate visible architectural part in the pictures is missing from the list
- a count disagrees with the pictures
- a part has no where, no built_as, or thin notes (notes that say no more than the part's name, or that describe the part only by its colour and not by how it is formed in depth)
- built_as is wrong (a see-through arch tagged only set_back; a recessed window tagged open; a chimney tagged set_back)
- organic is wrong (a building marked organic, or an animal/plant/tree marked as a structure)
{schema}

If the list is complete and accurate, reply with ONLY:
{{"ok": true, "notes": "one short sentence"}}

If anything is wrong, reply with ONLY a compact patch (not a full blueprint). You may add a part, correct a count, a parent, a face, a where, notes, or built_as. You may not remove a part the list already had unless that part is not in the pictures at all. Keep notes <= 15 words.
{{"ok": false, "notes": "what is wrong and what you changed",
  "add": {{"new_id": {{"kind": "feature", "count": 1, "parent": "...", "face": "front", "where": "...", "notes": "...", "built_as": ["set_back"]}}}},
  "update": {{"existing_id": {{"count": 8, "notes": "..."}}}},
  "remove": ["id_not_in_the_pictures"]}}
"""


def path_of(n):
    return f"{META}/{n}_parts.json"

def load(n):
    p = path_of(n)
    return json.load(open(p)) if os.path.exists(p) else None

def find_images(n, images=None):
    """the ORIGINAL photo only: the rembg cut-out (refs/N_fal_in.png) can slice off pale walls / columns / bases and
    then the list describes the damaged silhouette. The cut-out is a fallback only when no photo exists."""
    if images: return [os.path.abspath(p) for p in images if os.path.exists(p)]
    for p in (f"refs/{n}.jpg", f"refs/{n}.png", f"refs/{n}.jpeg"):
        if os.path.exists(p): return [os.path.abspath(p)]
    p = f"refs/{n}_fal_in.png"
    return [os.path.abspath(p)] if os.path.exists(p) else []

def _as_dict(parts):
    if not parts: return {}
    if isinstance(parts, dict): return {k: dict(v) for k, v in parts.items() if isinstance(v, dict)}
    return {p["id"]: dict(p) for p in parts if isinstance(p, dict) and p.get("id")}

def built_list(p):
    b = (p or {}).get("built_as") or []
    if isinstance(b, str): b = [b]
    return [x for x in b if x in BUILT]

def has_built(p, *ops):
    return bool(set(built_list(p)) & set(ops))

def faces_of(p):
    f = (p or {}).get("faces")
    if f is None: f = (p or {}).get("face", "all")
    if f == "all" or f == ["all"]: return ["front", "right", "back", "left"]
    if isinstance(f, str): return [x.strip() for x in re.split(r"[,\s]+", f) if x.strip() in FACES and x.strip() != "all"] or ["front"]
    return [x for x in f if x in FACES and x != "all"]

def stamp_op(p, default=None):
    """single op for stamping: keep a kind's usual op when it is listed (a rose tagged set_back+open+proud stays set_back)."""
    b = built_list(p)
    if not b: return default
    pid = (p.get("id") or "").lower()
    for kw, op in INFER:
        if kw in pid and op in b: return op
    return b[0]

def iter_parts(P):
    """yield a legacy-shaped part dict (id, count, faces, built_as as a list, where, notes, ...) from either schema."""
    for pid, p in _as_dict((P or {}).get("parts")).items():
        q = dict(p); q["id"] = pid; q["faces"] = faces_of(q); q["built_as"] = built_list(q); q["count"] = int(q.get("count") or 1)
        yield q

def infer_built(pid, p=None):
    s = (pid or "").lower() + " " + ((p or {}).get("where") or "") + " " + ((p or {}).get("notes") or "")
    for kw, op in INFER:
        if kw in s.lower(): return [op]
    return ["outline"] if (p or {}).get("kind") == "mass" else ["set_back"]

def _img_block(images):
    return "\n".join(f"- {p}" for p in images)

def _parse(text):
    if not text: return {}
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I | re.S).strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j <= i: return {}
    try: return json.loads(t[i:j + 1])
    except Exception: return {}

def _ask(prompt, images, model, force=False):
    os.makedirs(CACHE, exist_ok=True)
    h = hashlib.sha1()
    for p in images:
        h.update(open(p, "rb").read())
    h.update(prompt.encode()); h.update((model or HAIKU).encode())
    cp = f"{CACHE}/parts_{h.hexdigest()[:16]}.json"
    if not force and os.path.exists(cp):
        r = json.load(open(cp)); return r.get("text", ""), float(r.get("cost_usd") or 0), True
    text, cost = llm.ask(prompt, images=images, model=model or HAIKU)
    json.dump({"text": text, "cost_usd": cost}, open(cp, "w"))
    return text, float(cost or 0), False

def schema_issues(bp):
    if (bp or {}).get("organic"): return []
    parts = _as_dict((bp or {}).get("parts"))
    if not parts: return ["no parts listed for a structure"]
    issues = []
    for pid, p in parts.items():
        if p.get("kind") not in KINDS: issues.append(f"{pid}: kind must be mass or feature")
        try:
            if int(p.get("count") or 0) < 1: issues.append(f"{pid}: count must be >= 1")
        except Exception: issues.append(f"{pid}: count must be an integer >= 1")
        if not (p.get("where") or "").strip(): issues.append(f"{pid}: missing where")
        notes = (p.get("notes") or "").strip()
        if not notes: issues.append(f"{pid}: missing notes")
        elif len(notes.split()) < 3 or notes.lower().replace("_", " ") == pid.replace("_", " "): issues.append(f"{pid}: thin notes")
        raw_b = p.get("built_as"); raw = raw_b if isinstance(raw_b, list) else ([raw_b] if raw_b else [])
        b = built_list(p)
        if not b: issues.append(f"{pid}: missing built_as")
        elif any(x not in BUILT for x in raw): issues.append(f"{pid}: built_as must be a subset of {list(BUILT)}")
        if p.get("kind") == "feature" and not (p.get("face") or p.get("faces")): issues.append(f"{pid}: feature missing face")
    return issues

def normalize(bp, subject):
    bp = dict(bp or {})
    bp["subject"] = bp.get("subject") or subject
    bp["organic"] = bool(bp.get("organic"))
    bp["summary"] = " ".join((bp.get("summary") or "").split())
    sym = str(bp.get("symmetry") or "").strip().lower()
    if sym in SYMMETRY: bp["symmetry"] = sym
    else: bp.pop("symmetry", None)          # unknown / missing: no veto (shape_fit uses it only to veto x mirroring)
    parts = {}
    for pid, p in _as_dict(bp.get("parts")).items():
        q = dict(p)
        q["kind"] = q["kind"] if q.get("kind") in KINDS else ("mass" if any(w in pid.lower() for w in ("wall", "roof", "tower", "nave", "block", "plinth", "hull", "body")) else "feature")
        try: q["count"] = max(1, int(q.get("count") or 1))
        except Exception: q["count"] = 1
        b = built_list(q) or infer_built(pid, q)
        q["built_as"] = b
        fl = faces_of(q) if (q.get("face") or q.get("faces")) else (["all"] if q["kind"] == "mass" else ["front"])
        if fl == ["front", "right", "back", "left"]: q["face"] = "all"
        else: q["face"] = fl[0] if len(fl) == 1 else fl
        q.pop("faces", None)
        q["where"] = " ".join((q.get("where") or "").split())
        q["notes"] = " ".join((q.get("notes") or "").split())
        if q["kind"] != "feature": q.pop("parent", None)
        parts[str(pid)] = q
    bp["parts"] = {} if bp["organic"] else parts
    bp["open"] = [k for k, p in parts.items() if "open" in built_list(p)] if not bp["organic"] else []
    return bp

def _shorten(text, words=12, chars=120):
    s = " ".join((text or "").split())
    w = s.split()
    if len(w) > words: s = " ".join(w[:words])
    if len(s) > chars: s = s[:chars].rsplit(" ", 1)[0]
    return s

def prompt_block(parts_json):
    """compact per-part block for the ortho sheet prompt (~60-120 chars / <=12 words of notes each). '' if organic."""
    if not parts_json or parts_json.get("organic"): return ""
    plist = list(iter_parts(parts_json))
    if not plist: return ""
    lines = ["THE BUILDING IS MADE OF THESE PARTS. Draw every part as its own shape, at its count, built in depth "
             "as BUILT AS says (set_back=recess, open=see-through, proud=stands out, outline=changes the silhouette). "
             "No part may be only a colour or a dark patch on a flat wall."]
    for p in plist:
        face = p.get("face", p.get("faces"))
        if face in ("all", None) or face == ["front", "right", "back", "left"] or face == ["all"]: face_s = ""
        else: face_s = " face " + (",".join(face) if isinstance(face, list) else str(face))
        built = built_list(p) or ["outline"]
        notes = _shorten(p.get("notes") or p.get("where") or "", 12, 120)
        where = _shorten(p.get("where") or "", 8, 80)
        lines.append(f"[{p['id']}] x{p['count']} {p.get('kind') or 'feature'}{face_s} @ {where} — {notes} [{', '.join(built)}]")
    return "\n".join(lines)

def prompt_for(n):
    P = load(n); return prompt_block(P) if P else ""

def generate(subject, images=None, model=None, force=False):
    images = find_images(subject, images)
    if not images: raise SystemExit(f"no reference image for {subject} (tried refs/{subject}.jpg, .png, .jpeg, then refs/{subject}_fal_in.png)")
    text, cost, cached = _ask(GEN_PROMPT.format(subject=subject, images=_img_block(images)), images, model, force)
    bp = normalize(_parse(text), subject)
    if not bp.get("parts") and not bp.get("organic"):
        raise SystemExit(f"parts_list generate({subject}) returned no JSON parts (usd {cost}): {text[:400]}")
    bp["source"] = f"parts_list.py (auto, {model or HAIKU})"
    bp["model"] = model or HAIKU
    bp["cost_usd"] = round(cost, 4)
    bp["_cached"] = cached
    return bp, cost

def _merge_parts(old, new):
    """a revision may add or correct, but may not drop a part the previous list already had (spec)."""
    if new.get("organic") != old.get("organic"): return new
    if new.get("organic"): return new
    op, np_ = _as_dict(old.get("parts")), _as_dict(new.get("parts"))
    for k, v in op.items():
        if k not in np_: np_[k] = v
    new = dict(new); new["parts"] = np_; return new

def apply_patch(bp, data):
    """Apply a compact verify patch (add / update / remove) or a legacy full 'revised' blueprint."""
    if data.get("revised"):
        return _merge_parts(bp, data["revised"])
    out = dict(bp)
    parts = _as_dict(out.get("parts"))
    for pid in data.get("remove") or []:
        parts.pop(str(pid), None)
    for pid, fields in (data.get("update") or {}).items():
        if pid in parts and isinstance(fields, dict):
            q = dict(parts[pid]); q.update(fields); parts[pid] = q
    for pid, fields in (data.get("add") or {}).items():
        if isinstance(fields, dict):
            q = dict(fields); q.setdefault("id", pid)
            parts[str(pid)] = q
    if data.get("organic") is True:
        out["organic"] = True; parts = {}
    elif data.get("organic") is False:
        out["organic"] = False
    if data.get("summary"): out["summary"] = data["summary"]
    if data.get("symmetry"): out["symmetry"] = data["symmetry"]
    out["parts"] = parts
    return out

def visible_delta(old, new):
    """True if verify added/removed a visible part or changed a visible-face count (sheet should be regenerated)."""
    if bool((old or {}).get("organic")) != bool((new or {}).get("organic")): return True
    def vis(P):
        out = {}
        if (P or {}).get("organic"): return out
        for p in iter_parts(P or {}):
            out[p["id"]] = int(p.get("count") or 1)
        return out
    a, b = vis(old), vis(new)
    return set(a) != set(b) or any(a[k] != b[k] for k in a)

def verify(subject, bp, images=None, model=None, force=False):
    images = find_images(subject, images)
    bp = normalize(bp, subject)
    issues = schema_issues(bp)
    schema = ("\nProgrammatic schema issues already found, please fix them in the patch:\n- " + "\n- ".join(issues) + "\n") if issues else ""
    slim = {k: bp[k] for k in ("subject", "summary", "organic") if k in bp}
    slim["parts"] = {pid: {kk: vv for kk, vv in p.items() if kk in ("kind", "count", "parent", "face", "where", "notes", "built_as")}
                     for pid, p in _as_dict(bp.get("parts")).items()}
    text, cost, cached = _ask(VER_PROMPT.format(images=_img_block(images), blueprint=json.dumps(slim, indent=1),
                                                schema=schema), images, model, force)
    data = _parse(text)
    notes = (data.get("notes") or data.get("verify_notes") or "").strip()
    has_patch = bool(data.get("revised") or data.get("add") or data.get("update") or data.get("remove") or ("organic" in data and data.get("ok") is False))
    if bp.get("organic") and not (has_patch and data.get("organic") is False):
        bp["verified"] = True
        bp["verify_notes"] = "classified organic; no architectural parts list"
        bp["parts"] = {}; bp["open"] = []
    elif data.get("ok") and not issues:
        bp["verified"] = True; bp["verify_notes"] = notes or "list matches the pictures"
    elif has_patch:
        rev = normalize(apply_patch(bp, data), subject)
        issues2 = schema_issues(rev)
        rev["verified"] = not issues2
        rev["verify_notes"] = notes or ("revised; schema still failing: " + "; ".join(issues2) if issues2 else "revised to match the pictures")
        for k in ("source", "model"):
            if k in bp: rev[k] = bp[k]
        bp = rev
    else:
        bp["verified"] = False
        bp["verify_notes"] = ("; ".join(issues + ([notes] if notes else [])) or "verify did not return ok or a revision")
    bp["cost_usd"] = round(float(bp.get("cost_usd") or 0) + cost, 4)
    bp["_verify_cached"] = cached
    return bp, cost

def _preserve_hand(existing, generated):
    out = dict(generated)
    if not existing: return out
    for k in existing:
        if k in HAND: out[k] = existing[k]
    # per-part boxes on matching ids (legacy list or new dict)
    old_p, new_p = _as_dict(existing.get("parts")), _as_dict(out.get("parts"))
    for k, v in new_p.items():
        if k in old_p and old_p[k].get("boxes") and not v.get("boxes"):
            v = dict(v); v["boxes"] = old_p[k]["boxes"]; new_p[k] = v
    if new_p: out["parts"] = new_p
    return out

def ensure(subject, images=None, model=None, force=False, verify_list=True):
    """load or generate+verify art/final/meta/<n>_parts.json. Existing parts are returned at $0 unless --force."""
    os.makedirs(META, exist_ok=True)
    existing = load(subject)
    if existing and existing.get("parts") is not None and not force:
        # hand-written or already verified: do not touch
        return existing, 0.0
    bp, c1 = generate(subject, images, model, force)
    c2 = 0.0
    if verify_list: bp, c2 = verify(subject, bp, images, model, force)
    bp = _preserve_hand(existing, bp)
    bp["cost_usd"] = round(c1 + c2, 4)
    bp.pop("_cached", None); bp.pop("_verify_cached", None)
    # compact but readable
    json.dump(bp, open(path_of(subject), "w"), indent=1)
    return bp, c1 + c2


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Look and list + check the list (specs/detailed-parts.md steps 1-2)")
    ap.add_argument("subject"); ap.add_argument("--images", nargs="+")
    ap.add_argument("--force", action="store_true"); ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--model", default=os.environ.get("LLM_MODEL") or HAIKU)
    a = ap.parse_args()
    P, cost = ensure(a.subject, a.images, a.model, a.force, verify_list=not a.no_verify)
    nparts = len(_as_dict(P.get("parts")))
    print(a.subject, "organic" if P.get("organic") else f"{nparts} parts", "verified=" + str(bool(P.get("verified"))),
          f"usd={cost:.4f}", "file=" + path_of(a.subject))
    if P.get("verify_notes"): print("  notes:", P["verify_notes"])
    if not P.get("organic"):
        for p in iter_parts(P):
            print(f"  {p['id']:20} {p['kind'] if p.get('kind') else '-':8} x{p['count']:<3} {','.join(p['built_as']) or '-':20} {(p.get('where') or '')[:80]}")
        block = prompt_block(P)
        print("--- prompt_block ---"); print(block)

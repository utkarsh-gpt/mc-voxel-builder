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

If ORGANIC, reply with ONLY this JSON object and nothing else:
{{"subject": "{subject}", "organic": true, "summary": "one paragraph of what the subject is, as the pictures show it", "parts": {{}}}}

If a STRUCTURE, list every visible part. Repeated pieces share one id and a count (three doors are "door" with count 3; two towers are "tower" with count 2).
Each part must have:
- kind: "mass" (the body / outline: walls, roof, towers, plinth, the main block) or "feature" (a part the body carries: door, window, buttress, chimney, sail, porch post, dormer, ...)
- count: integer >= 1
- parent: required on a feature, the mass part id it sits on
- face: "front", "right", "back", "left", "top", "all", or a list of those. Required on a feature.
- where: one or two sentences naming the face or side, the height on that face, and the neighbours (above, below, beside, between).
- notes: detailed plain-word notes on the facade and architecture as the pictures show them: form and outline; how it is divided into tiers, bands or bays; the shape of arches, heads and tops; mouldings, tracery, mullions, hoods and trim; what stands proud of the wall, what is set back into it, and what is open or cut through; how deep a recess is and how far a solid stands out; how the part repeats and where the rhythm changes; how it meets the parts around it. As long as the part needs. Plain words taken from the pictures. Do NOT invent anything the pictures do not show. Do NOT rely on colour to say what a part is: "a dark window" is not a note; "a pointed opening set back into the wall with a ledge under it" is. Colours, materials, sizes and coordinates are optional and never evidence that a part exists.
- built_as: a non-empty list of one or more of:
  set_back — a recess in a wall: a window, a door, a portal, a niche, a panel. The wall face is in front of it, and its floor is deeper than the wall.
  open — a hole or gap you can see through or past (a see-through arch, an arcade passage).
  proud — a solid standing out of the surface (a buttress, a hood, a pilaster, a porch post).
  outline — it changes the silhouette (a spire, a chimney, a gable, a roof, sails).

A part that is only a colour, a dark patch, or a drawing on a flat wall is not a part and must not be listed.
Do not emit voxels, coordinates, or dimensions.

Reply with ONLY a JSON object and nothing else:
{{"subject": "{subject}", "organic": false, "summary": "one paragraph of what the finished building must still read as",
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

If anything is wrong, reply with ONLY a JSON object that includes the full corrected blueprint (same schema as the input). You may add a part, correct a count, a parent, a face, a where, notes, or built_as. You may not remove a part the list already had unless that part is not in the pictures at all.
{{"ok": false, "notes": "what is wrong and what you changed",
  "revised": {{"subject": "...", "organic": false, "summary": "...", "parts": {{...}}}}}}
"""


def path_of(n):
    return f"{META}/{n}_parts.json"

def load(n):
    p = path_of(n)
    return json.load(open(p)) if os.path.exists(p) else None

def find_images(n, images=None):
    if images: return [os.path.abspath(p) for p in images if os.path.exists(p)]
    out = []
    for p in (f"refs/{n}_fal_in.png", f"refs/{n}.png", f"refs/{n}.jpg"):
        if os.path.exists(p): out.append(os.path.abspath(p))
    return out

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
        elif len(notes) < 24 or notes.lower().replace("_", " ") == pid.replace("_", " "): issues.append(f"{pid}: thin notes")
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

def prompt_block(parts_json):
    """concise per-part block for the ortho sheet prompt (same style as blueprint.prompt_parts run A). '' if organic."""
    if not parts_json or parts_json.get("organic"): return ""
    plist = list(iter_parts(parts_json))
    if not plist: return ""
    lines = ["THE BUILDING IS MADE OF THESE PARTS. Draw every part below as its own separate shape, at its count, built in depth "
             "the way its BUILT AS says (" + "; ".join(GEO.values()) + "). Every part is its own line here; none is left to appear by chance, "
             "and none may be only a colour or a dark patch on a flat wall."]
    for p in plist:
        face = p.get("face", p.get("faces"))
        if face in ("all", None) or face == ["front", "right", "back", "left"] or face == ["all"]: face_s = ""
        else: face_s = ", face " + (",".join(face) if isinstance(face, list) else str(face))
        built = built_list(p) or ["outline"]
        note = p.get("built_note") or "; ".join(GEO[b] for b in built if b in GEO)
        notes = p.get("notes") or p.get("where") or ""
        lines.append(f"[{p['id']}] {p['count']} x ({p.get('kind') or 'feature'}{face_s}). WHERE: {p.get('where') or ''} "
                     f"NOTES: {notes} BUILT AS {', '.join(built).upper()}: {note}")
    return "\n".join(lines)

def prompt_for(n):
    P = load(n); return prompt_block(P) if P else ""

def generate(subject, images=None, model=None, force=False):
    images = find_images(subject, images)
    if not images: raise SystemExit(f"no reference image for {subject} (tried refs/{subject}_fal_in.png, .png, .jpg)")
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

def verify(subject, bp, images=None, model=None, force=False):
    images = find_images(subject, images)
    bp = normalize(bp, subject)
    issues = schema_issues(bp)
    schema = ("\nProgrammatic schema issues already found, please fix them in revised:\n- " + "\n- ".join(issues) + "\n") if issues else ""
    text, cost, cached = _ask(VER_PROMPT.format(images=_img_block(images), blueprint=json.dumps({k: bp[k] for k in ("subject", "summary", "organic", "parts") if k in bp}, indent=1),
                                                schema=schema), images, model, force)
    data = _parse(text)
    notes = (data.get("notes") or data.get("verify_notes") or "").strip()
    revised = data.get("revised")
    # organic stays organic: ignore a confused revision that tries to list anatomy
    if bp.get("organic") and (not revised or revised.get("organic", True)):
        bp["verified"] = True
        bp["verify_notes"] = "classified organic; no architectural parts list"
        bp["parts"] = {}; bp["open"] = []
    elif data.get("ok") and not issues:
        bp["verified"] = True; bp["verify_notes"] = notes or "list matches the pictures"
    elif revised:
        rev = normalize(_merge_parts(bp, revised), subject)
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

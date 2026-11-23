You are designing the UI for a static voxel-art viewer at viewer/.

## What this app is
A public, single-page tool for inspecting AI-generated 3D voxel models (Minecraft-style blocks, including slabs, vertical slabs, and stairs). The user wants to orbit a model and judge whether the *shape* is right from every angle. Reference photos sit next to the model when available.

The 3D engine is already written and working. You own the look, typography, layout, interaction polish, empty/loading/error/drop states, and visual hierarchy. Do not redesign the 3D pipeline.

## Files you MAY freely rewrite
- index.html
- styles.css
- js/app.js (presentation and DOM wiring only)

## Files you must NOT change
- js/loader.js
- js/scene.js
- scripts/generate_manifest.py
- sync.sh
- vercel.json
- manifest.json
- models/ and refs/

## Required hooks (keep these IDs and behaviours)
- canvas#view inside a container#viewport (the canvas must fill the remaining viewport; the scene resizes from the parent)
- select#model-select — populated by js/app.js (optgroups: "Featured (newest finals)" then one group per subject)
- img#ref-thumb and wrapper #ref-wrap (hidden when no photo)
- #stat-name, #stat-blocks, #stat-sub, #stat-size
- checkbox#toggle-wireframe, checkbox#toggle-grid, button#btn-reset
- #status (role="status")
- #drop-overlay (hidden by default; shown while dragging a file)
- body data-state="loading|ready|error|idle" and data-ready="0|1"
- Existing import map for three / three/addons/, and `<script type="module" src="js/app.js">`

If you change app.js, keep load/drop/manifest logic intact (parseVoxelArt, loadVoxelUrl, createViewer, the same event wiring). You may restyle labels, add a header, icons, a nicer select, badges for featured/highlight models, etc.

## Design direction
This should feel like a quiet workshop / object-study studio, not a SaaS dashboard and not a generic AI tool. Think: a dark linen or charcoal studio, a single well-lit object, typography with character (a quality grotesque + a sharp mono for stats is fine; avoid Inter / default system-ui-only blandness if you can self-host or use a well-supported Google/Adobe font, or a distinctive system stack). Gold or warm ochre can be a restrained accent (the models themselves are colourful). Generous spacing. The 3D view is the hero; chrome is slim and confident.

Requirements:
- Orbit / zoom / pan remains obvious (short hint). Drag-and-drop a .json is a first-class gesture with a clear overlay.
- Featured models should be visually distinct in the picker (the select already groups them; you can also add a compact list of featured chips/thumbnails above the dropdown if it stays tidy).
- Show block count and sub-block % clearly. Sub-blocks (slabs/stairs) are an important feature.
- Reference photo as a small, sharp thumbnail, captioned, not a huge poster.
- Loading state for large models (some JSON files are several MB).
- Error state that is calm and readable.
- Responsive: on a phone, controls stack so the canvas still gets real height (at least half the screen).
- Keyboard and contrast: labels on inputs, visible focus, WCAG-ish contrast.
- No framework, no build step. Static HTML/CSS/JS only. You may add a fonts stylesheet link.
- No analytics, no cookies, no external images except fonts and the already-used three.js CDN / local refs.
- Do not add a fake login or marketing landing page. One page, immediately into the viewer.

When you are done, leave the app fully working with the existing JS modules.

# Cathedral part notes

These are the part notes for the cathedral experiment in [detailed-parts.md](detailed-parts.md#experiment-the-cathedral).
They are read off `ortho/cathedral_v3_front.png`, `cathedral_v3_right.png`, `cathedral_v3_back.png`, `cathedral_v3_top.png`, `cathedral_v3_sheet.png`, and the photo `refs/cathedral.jpg`.
They are the kind of text the list step must produce, written by hand for the experiment.
Each part has a count, a `where`, and `notes`.
A side part on the right has a twin with `_left` on the left face, with the same notes.
Directions follow the sheet: the west front faces the viewer in the front elevation, and the east end (the apse) is at the far end of the nave.
Colours are left out on purpose.
Every part has a `built_as` list and a "Built as structure" paragraph: whether it is set back, open, proud, or part of the outline, and what that means for this part.
Every part is generated explicitly, on its own, with that geometry.
The build check tests each part separately, with the colour removed.

Read the whole list as one building.
It is a Gothic stone cathedral with a flat west front between two matching towers, a long nave with aisles and flying buttresses, one long slate roof, and a rounded east end.
Everything is symmetrical left to right.
All the stone is fine ashlar, small rectangular blocks in even horizontal courses.

## Mass parts

**`plinth`** (mass, count 1)

Where: under the whole building, the lowest part of everything.

Notes:
A low, flat, rectangular platform, only a few courses of stone high.
It is a little larger than the building on every side, so a narrow margin of flat ground shows all the way round the walls.
The margin is wider along the two long sides than at the two ends.
The top is rough and gravelly, with no moulding and no decoration on its edge.
In plan it is a plain rectangle, longer from west to east.
One shallow step runs along the foot of the three west portals.

Built as structure (`built_as`: proud):
a solid slab that stands out past the walls on every side.

**`west_front`** (mass, count 1)

Where: the whole west end of the building, the face with the entrances. It spans the two towers and the centre section between them.

Notes:
The front is one flat wall, as wide as the nave and both towers together, and it is perfectly symmetrical about its centre line.
It is divided into three vertical sections: the left tower face, the centre section, and the right tower face.
Tall narrow buttress piers stand proud of the wall between the centre section and each tower face, and at each outer corner.
Every pier runs the full height of the front and steps in at a few set-offs as it rises, each set-off finished with a small sloping cap.
Because of the stepped outer corners, the outer edges of the front lean inward as they rise, so the front is widest at the ground.
Reading the front from the bottom up there are four bands: the portal band, the band of the arcade and the stacked tower windows, the band of the rose, and the band of the gable.
Above that, the two towers rise alone.
A projecting string course runs across the whole front at the foot of the belfry stage, with a row of small blocks like teeth under it across the centre section.
Smaller ledges under each tower window and under the rose act as sills.
There is no door, window, or ornament anywhere on the front except the parts listed below.

Built as structure (`built_as`: outline, proud):
one flat wall with the piers standing out of it, and the string courses and sills as ledges. The openings in it are listed below, each its own part.

**`tower`** (mass, count 2)

Where: one at the left end and one at the right end of the west front, flanking the centre section. They are the tallest parts of the building apart from their own spires.

Notes:
Each tower is a tall, square, slender shaft.
Its shaft, below the spire, is about a third taller than the ridge of the nave roof, and with the spire the tip is nearly twice the ridge height.
It has two stages: a tall lower stage and a shorter belfry stage above it, topped by a battlement.
All four faces are built the same way.
The lower stage is plain wall with a portal at the foot, then two tall pointed windows one above the other, as described in `portal_side` and `front_window`.
The same two stacked windows appear on the outer side face of each tower.
The two towers are identical copies of each other.
Corner buttresses climb each outer corner, step in twice, and end in sloped shoulders just under the belfry.
The towers stand clear of the nave roof, so the belfry stage and the spire rise fully above it and can be seen from every side.

Built as structure (`built_as`: outline):
a tall square shaft that clears the nave roof, with its corner buttresses stepping in as solid ledges. The towers are solid masses, not painted shapes.

**`belfry`** (mass, count 2)

Where: the top stage of each tower, between the string course at the lower stage and the battlement.

Notes:
A shorter, plainer stage than the one below.
Each of the four faces is a flat wall with two tall openings side by side in its middle, and nothing else.
The corners of the stage end in angled stone shoulders where the corner buttresses meet it, which make the stage look slightly narrower than the shaft below.
The wall is plain coursed stone around the openings.

Built as structure (`built_as`: outline):
a stage slightly narrower than the shaft, with the angled shoulders as solid slopes. Its openings are the `belfry_opening` parts.

**`spire`** (mass, count 2)

Where: on top of each tower, rising from inside the battlement. They are the highest points of the whole building.

Notes:
A tall, slender, steep stone spire, a pyramid with several flat faces, probably eight.
In the elevations one broad face catches the light and a narrow face is in shade.
It narrows steadily to a sharp needle point.
The faces are smooth coursed stone, with the courses getting shorter toward the top.
There are no ribs, no crockets, no finial, and no openings in the spire.
It is about a third as tall as the tower shaft under it.

Built as structure (`built_as`: outline):
a solid faceted pyramid. Its faces are flat planes, and its tip is the highest point of the build.

**`nave`** (mass, count 1)

Where: behind the west front, running east for roughly five tower widths, between and behind the two towers.

Notes:
A long, narrow body with a low aisle level and a taller clerestory above it, the same on both sides.
The side wall is divided into eleven equal bays by projecting buttress piers.
The last bay at the east end is wider than the others and curves into the apse.
At the bottom there is a blank plinth wall of larger, rougher stones with a slight batter, about a fifth as tall as the aisle, with no openings in it.
Above it each bay has one tall pointed window.
Above the aisle windows the aisle roof slopes back to the clerestory wall in shallow slate lean-tos, one between each pair of piers, so a slope shows under every clerestory window.
Above that, the clerestory wall rises to a flat cornice band that runs the full length under the eave.
Flying buttresses cross from the piers over the aisle roof to the clerestory wall.
At the west the nave is hidden behind the front and the towers, and the front gable rises just above the centre section.

Built as structure (`built_as`: outline, proud):
a long body with a lower aisle level and a taller clerestory. The aisle roof slopes are real slopes, so a sloped ledge shows under every clerestory window. The piers stand out of the wall.

**`roof`** (mass, count 1, parent `nave`)

Where: over the whole nave, from the west gable to the apse.

Notes:
One long, steep, plain gable roof of fine slate, with no dormers, no openings, and no ornament.
A single straight ridge runs the full length.
The two slopes are long and unbroken.
At the west the roof ends against the front gable wall, which stands up as a triangle between the towers.
At the east the roof turns into a faceted, many-sided hipped cap over the apse, and a small cross stands at its peak.
Seen from above the roof is a long narrow shape with chamfered ends, and it sits inside the ring of buttress arms.

Built as structure (`built_as`: outline):
two real sloping planes that meet at a ridge, with a hipped end at the east. It is a solid roof, not a dark colour on the top of the walls.

**`apse`** (mass, count 1, parent `nave`, face `back`)

Where: the east end of the nave, the rounded end seen in the back elevation and at the far end of the top view.

Notes:
The east end is rounded into a many-sided polygon rather than a flat wall.
Its lowest level has three tall pointed windows side by side.
Above them is a clerestory level with tall pointed windows between slim piers.
Over the aisle a few small slate slopes show at the corners.
A fan of flying buttresses curves round the apse from pinnacled piers, so from above the east end is ringed by radiating stone arms.
The faceted roof cap rises over it with a cross at the peak.
The apse is as wide as the nave.

Built as structure (`built_as`: outline):
a many-sided end that is not a flat wall, so the plan changes shape at the east end.

## Feature parts on the west front

**`portal_main`** (feature, count 1, parent `west_front`, face `front`)

Where: the centre of the bottom band of the west front, exactly on the centre line, between the two side portals.

Notes:
The largest and tallest entrance.
It is a deep pointed arch built from several concentric rings stepping back into the wall, each ring a thin moulding, with slim shafts in the jambs.
Over the arch there is a steep triangular gable that rises above the arch and has crockets, small leaf-like bumps, up both sloping edges.
A small round medallion with a pattern sits in the face of that gable.
The tip of the gable rises into the arcade above it.
Inside the arch there are two tall rectangular wooden doors side by side, with a single post between them.
Above the doors the arch is filled by a recessed, arched panel with fine ribbing that spreads out like a fan.
The portal is set back from the face of the wall, so it reads as a deep recess.

Built as structure (`built_as`: set_back, proud):
the arch is a real recess cut back into the wall in steps, deeper toward the doors, and the gable is a solid triangle standing out of the wall above it. The two doors sit at the back of the recess, set in from the wall face. A dark arch painted on a flat wall does not count.

**`portal_side`** (feature, count 2, parent `tower`, face `front`)

Where: one at the foot of each tower face, left and right of the main portal, at the same level.

Notes:
A smaller, narrower copy of the main portal.
Each is a single pointed arch, with a steep triangular gable above it that ends in a small spike (a finial) at its tip.
A round medallion sits in each gable, and small crockets run up its edges.
Inside each there is one tall rectangular wooden door.
The side portals are about half as wide as the main portal and clearly lower.
Both are identical to each other, and each is placed a little off the tower's centre line, toward the middle of the front.
The gables overlap the piers that separate the tower faces from the centre section.

Built as structure (`built_as`: set_back, proud):
each is a real recess cut back into the wall, with its gable a solid triangle standing out above it, and the door at the back of the recess. The three portals are three separate recesses with solid wall between them.

**`gallery_arcade`** (feature, count 1, parent `west_front`, face `front`)

Where: in the centre section, directly above the main portal and below the rose. The point of the portal gable rises into it.

Notes:
A row of five tall, narrow pointed windows side by side across the centre section, each separated from the next by a slim stone column.
Each has a pointed head, with the same width and height as its neighbours.
The row has a thin ledge underneath and a moulded band above, which also forms the sill of the rose.
Each opening holds a thin pane set back in it.
The point of the main portal's gable rises between the middle windows.

Built as structure (`built_as`: set_back):
five separate pointed recesses in the wall, each with a solid column between it and the next. It must not read as one dark band.

**`rose`** (feature, count 1, parent `west_front`, face `front`)

Where: in the middle of the west front, on the centre line, above the arcade and below the gable, between the two towers' stacked windows.

Notes:
A large round window, the biggest opening on the building, and the focal point of the front.
It sits inside a thick, richly moulded ring of stone, with a pointed arch moulding framing it from above.
Inside the ring is a wheel of tracery.
A small round hub sits in the centre.
Twelve slim spokes radiate from the hub to the edge, like a wheel.
Each spoke ends in a rounded, petal-shaped lobe, so the whole window looks like a flower with twelve petals, and a second ring of smaller lobes fills the gaps at the rim.
A thin pane sits at the back of the opening, behind the tracery.
In the corners above and below the circle, small round decorated medallions fill the gaps between the circle and the square frame around it.
A plain string course crosses above it, and the arcade sits directly below it.
It is about as wide as the main portal, and the centre section is about one and a half times as wide as the rose.

Built as structure (`built_as`: set_back, open, proud):
a circular recess cut into the wall, edged by a raised ring of stone that stands out of the wall. The hub and the twelve spokes are solid bars standing in the opening, with a gap between each pair of spokes. The circle must be readable by its outline and its depth alone. A dark disc on a flat wall does not count.

**`front_window`** (feature, count 4, parent `tower`, face `front`)

Where: two on each tower face, stacked one above the other, in the lower stage above the side portal, one on each side of the rose.

Notes:
Tall, narrow, pointed windows.
The upper window of each pair is larger than the lower one.
Each has two narrow lights, separated by a single stone mullion, and a small round tracery pattern in the pointed head.
Each sits inside its own slightly larger pointed arch moulding, and has a projecting ledge as its sill.
Each opening holds a thin pane set back in it.
The upper windows sit level with the rose, and the lower ones level with the arcade.
The two towers are identical, so the windows are the same left and right.

Built as structure (`built_as`: set_back, proud):
each is a pointed opening cut back into the wall with a ledge standing out under it, and a solid mullion down the middle between the two lights. Four separate openings, none joined to another.

**`front_gable`** (feature, count 1, parent `west_front`, face `front`)

Where: at the top of the centre section, between the two towers, above the rose, in front of the roof.

Notes:
A steep triangular gable, a wall rising to a point, with a plain moulded edge along its two sloping sides.
A small cross stands at its tip.
Inside it there are three narrow pointed slits: a tall one in the middle, and a shorter one on each side.
The gable is much lower than the towers.
Behind it the roof ridge is visible.

Built as structure (`built_as`: outline, set_back):
a solid triangular wall rising above the line of the front, the three slits as narrow recesses in it, and the cross as a small solid at the tip.

**`gallery_balustrade`** (feature, count 1, parent `west_front`, face `front`)

Where: across the centre section at the foot of the gable, between the two towers, just above the main string course.

Notes:
A low open railing, a row of many small short posts (balusters) under a flat top rail, over a plain solid base.
It runs the whole width of the centre section, wall to wall between the towers.
It is a single band, as tall as a few courses of stone.

Built as structure (`built_as`: open, proud):
a solid base with a row of separate posts standing on it, with a gap between each post, under a solid top rail.

**`belfry_opening`** (feature, count 16, parent `belfry`, face front, right, back, left)

Where: two on each of the four faces of each belfry.

Notes:
Each opening is very tall and narrow, about five or six times taller than it is wide, with a pointed head.
The two openings on a face are identical and side by side, separated by a slim pier, and centred on the face.
Each is deeply recessed and filled with horizontal stone louvre slats, a stack of slots, so it reads as a ladder of slots.
Both openings sit within a shared, slightly recessed rectangular panel.
Nothing else is on the belfry wall.

Built as structure (`built_as`: open):
each is a hole through the belfry wall, filled by thin horizontal bars with gaps between them, so light passes between the bars. Sixteen separate openings, two on each face.

**`parapet`** (feature, count 2, parent `belfry`, face `top`)

Where: round the very top of each belfry, directly under the spire.

Notes:
A battlement, a low wall with evenly spaced square teeth (merlons) and gaps between them, running all the way round the tower top.
There are about six or seven teeth on each face.
It projects slightly outward over a row of corbel stones, so the top of the tower is a little wider than the belfry below it.
The foot of the spire sits just inside it.

Built as structure (`built_as`: open, proud):
a solid low wall with square teeth standing up from it and a gap between each pair of teeth, so the gaps show against the sky. It stands out a little over the corbels.

## Feature parts on the sides and east end

**`aisle_window`** (feature, count 11, parent `nave`, face `right`)

Where: the lower level of the right side wall, one in each of the eleven bays, centred between the piers.

Notes:
A tall, narrow, pointed window with two lights separated by one slim mullion.
A small round tracery pattern fills the pointed head, with a quatrefoil in it.
Each opening holds a thin pane set back in it.
Each window is set in a shallow pointed recess.
The windows are identical and evenly spaced, with a pier between each pair that is about as wide as a window.
Below each window is the blank plinth wall, with no opening in it.
The last window, at the east end, sits in the wider end bay.

Built as structure (`built_as`: set_back):
each is a pointed opening cut back into the wall, with a solid pier between one window and the next. Eleven separate openings in a row.

**`clerestory_window`** (feature, count 10, parent `nave`, face `right`)

Where: the upper level of the right side wall, one above each bay except the last, above the aisle roof slope.

Notes:
A tall pointed window with two lights, a slim mullion between them, and a round pattern in the head.
Each sits in a taller pointed recess whose edge is moulded, and the sill is a sloping ledge.
The windows are identical, evenly spaced, and line up above the aisle windows.
Narrow flat pilasters stand between them.
Under each one the aisle roof shows as a slate slope.

Built as structure (`built_as`: set_back):
each is a pointed opening cut back into the clerestory wall with a sloping ledge under it, and a solid pilaster between one window and the next. Ten separate openings in a row.

**`side_buttress`** (feature, count 10, parent `nave`, face `right`)

Where: on the right side wall, between each pair of bays, running the full height of the aisle.

Notes:
A flat-fronted pier that stands out from the wall.
It is wide at the foot, and steps in once or twice as it rises, with a small sloping cap at each step.
It rises past the aisle roof and past the aisle windows, and carries a pinnacle on its top and the foot of a flying buttress.
A matching pier stands at the east end where the nave turns into the apse.
The piers are evenly spaced.

Built as structure (`built_as`: proud):
a solid pier standing out of the wall, wide at the foot and narrower at each set-off. Ten separate piers, each with wall between it and the next.

**`flying_buttress`** (feature, count 10, parent `nave`, face `right`)

Where: over the aisle roof on the right side, one from each pier to the clerestory wall.

Notes:
A straight sloping arm of stone that leaps up and inward from the top of the pier to the clerestory wall, in the open air above the aisle roof.
Each is a slim bar, with a thin arch under it where it meets the wall.
They are evenly spaced, one per pier, and all identical.
Seen from above they are parallel ribs crossing the aisle roof, like rungs of a ladder.
In the three-quarter view they look like a row of diagonal struts.

Built as structure (`built_as`: open, proud):
a solid sloping arm that touches the pier at its lower end and the clerestory wall at its upper end, with open air under it over the aisle roof. It is not painted on the wall.

**`pinnacle`** (feature, count 10, parent `nave`, face `right`)

Where: on top of each pier on the right side, at the foot of each flying buttress.

Notes:
A slim stone spike, taller than the pier is wide, rising to a sharp pointed cap.
Small spikes or gablets sit at its sides in the same style as the portal finials.
It is thinner than the pier below it.
They are evenly spaced, one on each pier, in a regular row along the side.

Built as structure (`built_as`: proud, outline):
a solid slim spike standing above the pier, narrower than the pier, with air on all sides above the pier top.

**`apse_window`** (feature, count 3, parent `apse`, face `back`)

Where: at the lowest level of the east end, three side by side.

Notes:
Each is a tall, pointed window with two lights, a slim mullion, and a round pattern in the head.
Each holds a thin pane set back in it.
All three are about the same height.
They match the aisle windows in style but are grouped together.

Built as structure (`built_as`: set_back):
three separate pointed openings cut back into the apse wall, with solid wall between them.

**`apse_flying_buttress`** (feature, count 7, parent `apse`, face `back`)

Where: fanning round the east end above the apse windows, on pinnacled piers.

Notes:
Slim stone arms that curve round the apse and rise to the clerestory.
Seen from behind they fan out like the spread ribs of a hand.
Seen from above they radiate round the end of the roof, with a pinnacle on the outer end of each arm.
There are about seven.
The arms are the same in style as the side flying buttresses.

Built as structure (`built_as`: open, proud):
solid curved arms standing out round the apse, each with air under it, each ending in a pinnacle.

Done means each of those parts is visible in the voxel render, as its own shape, at its count.
A sheet that shows them and a voxel render that hides them is unfinished.

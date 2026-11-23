# voxel-ai: AI voxel art -> Minecraft (starting line)

Files
- PROMPTS.md            prompt templates + ready prompts for 3 approaches, with sources
- voxel_ai.py           voxel JSON -> 6-angle PNG previews + .mcfunction + .schem + .litematic; also GLB mesh -> voxel JSON
- gen_llm.sh            one-shot: LLM (claude CLI, sonnet/haiku) -> JSON -> previews + exports
- fal_mesh.py           text -> flux image -> Trellis mesh -> voxels -> exports (needs fal balance)
- examples/*.json       generated voxel JSON;  out/*  previews and exports

Run
  cd pipeline/ && . .venv/bin/activate
  ./gen_llm.sh cottage 16 16 16 "your request" sonnet
  python voxel_ai.py build examples/cottage.json --out out/cottage
  python voxel_ai.py mesh samples/Duck.glb --size 28 --out out/duck_mesh
  python fal_mesh.py fox "A stylized fox statue, plain white background" --size 32

In game
  .mcfunction: put in a datapack (data/<ns>/function/<name>.mcfunction), run /function <ns>:<name>; builds at your position +1,+1 (clears the box first).
  .schem: WorldEdit/FAWE  //schem load <name>  then //paste
  .litematic: Litematica schematics folder (load + place, easy place)
  Exports are tagged data version 4325 (1.21.5); WorldEdit/Litematica upgrade them on newer versions.

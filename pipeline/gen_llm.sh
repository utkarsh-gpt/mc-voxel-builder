#!/usr/bin/env bash
# usage: ./gen_llm.sh <name> <W> <H> <D> "<request>" [model]
set -e
cd "$(dirname "$0")"
NAME=$1 W=$2 H=$3 D=$4 REQ=$5 MODEL=${6:-sonnet}
TPL=$(awk '/^### A0/{f=1;next} f&&/^```$/{if(c++)exit;next} f&&c==1' PROMPTS.md)
PROMPT=${TPL//\{W\}/$W}; PROMPT=${PROMPT//\{H\}/$H}; PROMPT=${PROMPT//\{D\}/$D}
PROMPT=${PROMPT//\{N_BLOCKS\}/16}; PROMPT=${PROMPT//\{REQUEST\}/$REQ}
mkdir -p examples out
claude -p --model "$MODEL" "$PROMPT" > "examples/$NAME.raw.txt"
python3 - "$NAME" <<'PY'
import sys,re,json
n=sys.argv[1]; t=open(f"examples/{n}.raw.txt").read()
t=re.sub(r"^```(json)?|```$","",t.strip(),flags=re.M)
s=t[t.find("{"):t.rfind("}")+1]; d=json.loads(s)
json.dump(d,open(f"examples/{n}.json","w"),indent=1); print("saved examples/%s.json"%n)
PY
. .venv/bin/activate && python voxel_ai.py build "examples/$NAME.json" --out "out/$NAME"

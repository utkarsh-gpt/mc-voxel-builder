"""One call for the judge model: the claude CLI if it is installed, otherwise codex.

    text, usd = llm.ask(prompt, images=[paths])

Backend: env LLM=claude|codex (default: claude when it is on PATH, else codex). Codex runs read-only and ephemeral, the
images are attached with -i, and the model comes from ~/.codex/config.toml unless LLM_MODEL is set. Cost is only known
for claude (0.0 for codex).
"""
import json, os, shutil, subprocess, tempfile


def backend():
    b = os.environ.get("LLM")
    if b: return b
    return "claude" if shutil.which("claude") else "codex"


def ask(prompt, images=(), model=None, timeout=900):
    b = backend()
    if b == "claude":
        r = subprocess.run(["claude", "-p", "--model", model or os.environ.get("LLM_MODEL", "claude-haiku-5-5"), "--output-format", "json", prompt,
                            "--allowedTools", "Read"], capture_output=True, text=True, timeout=timeout)
        try: env = json.loads(r.stdout); return env.get("result", ""), float(env.get("total_cost_usd") or 0)
        except Exception: return r.stdout, 0.0
    with tempfile.NamedTemporaryFile("r", suffix=".txt") as f:
        cmd = ["codex", "exec", "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "-o", f.name]
        m = os.environ.get("LLM_MODEL")
        if m: cmd += ["-m", m]
        for im in images: cmd += ["-i", os.path.abspath(im)]
        r = subprocess.run(cmd + ["-"], input=prompt, capture_output=True, text=True, timeout=timeout)
        text = f.read()
    if r.returncode or not text.strip():
        raise RuntimeError("codex failed: " + (r.stderr.strip().splitlines() or ["no output"])[-1])
    return text, 0.0

"""Offline tests of the "Check for Secrets" step of .github/workflows/_screen.yml.

The step is the deterministic backstop of the screen: it fails on the Claude token in common
encodings and on the shapes of common credentials, before any model sees the text. A live call of
_screen.yml can only show that clean text passes, because a call that fails turns the whole run red
(a job that calls a reusable workflow can't continue on error). So the blocking cases are tested
here instead: the step's script is read from the workflow file, not copied, and run the way GitHub
runs a `shell: python` step, once per case, with the case's text and a dummy token in TEXT and
SECRET.

Each case asserts the exit status, and that the output holds neither the text, nor the token, nor
the encoded copy the case planted: the step must say which check failed, never what matched.

The credential-shaped strings are built at run time, so that this file holds none that secret
scanning or push protection would flag.

Usage: python3 tests/screen_check.py [path/to/_screen.yml]
"""

import base64
import json
import os
import subprocess
import sys
import tempfile
import urllib.parse

WORKFLOW = sys.argv[1] if len(sys.argv) > 1 else ".github/workflows/_screen.yml"
STEP = "Check for Secrets"

# A dummy token: long enough for the step to compare against, with characters that URL encoding
# changes and that make base64 and base64url differ. It matches none of the credential patterns.
SECRET = "dummy-Screen+Test/Token=Value_0123456789~?>"


def load_workflow(path):
    """Parses the workflow with PyYAML, or with yq (mikefarah, preinstalled on GitHub's runners)."""
    try:
        import yaml
    except ImportError:
        out = subprocess.run(["yq", "-o=json", ".", path], check=True, capture_output=True, text=True)
        return json.loads(out.stdout)
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def find_step(workflow):
    steps = [s for s in workflow["jobs"]["screen"]["steps"] if s.get("name") == STEP]
    if len(steps) != 1:
        sys.exit(f"::error file={WORKFLOW}::Expected one step named {STEP!r} in the screen job, found {len(steps)}.")
    step = steps[0]
    if step.get("shell") != "python":
        sys.exit(f"::error file={WORKFLOW}::The {STEP!r} step no longer runs with shell: python.")
    if set(step.get("env", {})) != {"TEXT", "SECRET"}:
        sys.exit(f"::error file={WORKFLOW}::The {STEP!r} step's env is no longer TEXT and SECRET.")
    return step["run"]


def b64_offsets(encode, secret, prefix="xy"):
    """The token embedded at each of the three byte offsets, encoded as part of a longer string."""
    return [encode((prefix[:k] + secret + " trailing").encode()).decode() for k in range(3)]


def cases():
    raw = SECRET.encode()
    clean = (
        "Lockfile out of date\n\n"
        "The workflow `.github/workflows/ci.yml` uses `actions/checkout@v7.0.1`, locked at "
        "commit sha1-3d3c42e5aac5ba805825da76410c181273ba90b1 (owner_id 44036562). Run "
        "`gh actions-lock` and push the result. See https://github.com/actions-fyi/shared-workflows."
    )
    yield "clean text", clean, SECRET, True, None
    yield "clean text, empty", "", SECRET, True, None
    yield "token, missing", clean, "", False, None
    yield "token, raw", f"Here it is: {SECRET} done", SECRET, False, SECRET
    yield "token, split across lines", f"a {SECRET[:10]}\n  {SECRET[10:]} b", SECRET, False, SECRET
    yield "token, reversed", f"x {SECRET[::-1]} y", SECRET, False, SECRET[::-1]
    for i, enc in enumerate(b64_offsets(base64.b64encode, SECRET)):
        yield f"token, base64 at offset {i}", f"blob: {enc}", SECRET, False, enc
    for i, enc in enumerate(b64_offsets(base64.urlsafe_b64encode, SECRET)):
        yield f"token, base64url at offset {i}", f"blob: {enc}", SECRET, False, enc
    yield "token, hex", f"hex {raw.hex()} end", SECRET, False, raw.hex()
    yield "token, hex, upper case", f"HEX {raw.hex().upper()}", SECRET, False, raw.hex().upper()
    quoted = urllib.parse.quote(SECRET, safe="")
    yield "token, URL-encoded", f"https://example.com/?t={quoted}", SECRET, False, quoted
    plus = urllib.parse.quote_plus(SECRET, safe="")
    yield "token, URL-encoded with +", f"t={plus}", SECRET, False, plus
    credentials = {
        "GitHub token (classic)": "gh" + "p_" + "x" * 8,
        "GitHub token (server)": "gh" + "s_" + "x" * 8,
        "GitHub fine-grained token": "github" + "_pat_" + "x" * 8,
        "Anthropic API key": "sk" + "-ant-" + "x" * 8,
        "AWS access key ID": "AK" + "IA" + "TESTONLYNOTREAL0",
        "Slack token": "xo" + "xb-" + "x" * 8,
        "private key": "-----BEGIN " + "RSA PRIVATE KEY-----",
    }
    for name, value in credentials.items():
        yield f"credential, {name}", f"found {value} in the log", SECRET, False, value
    yield "credential, split across lines", "token: g\nhp_" + "x" * 8, SECRET, False, None


def run(script, text, secret, workdir):
    # GitHub writes a `shell: python` step to a file and runs `python {0}`. -I keeps the empty
    # working directory and the environment from adding modules, and the environment holds only
    # what the step's env sets.
    path = os.path.join(workdir, "check.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(script)
    env = {"PATH": os.environ.get("PATH", ""), "TEXT": text, "SECRET": secret}
    return subprocess.run(
        [sys.executable, "-I", path], cwd=workdir, env=env, capture_output=True, text=True, timeout=60
    )


def main():
    script = find_step(load_workflow(WORKFLOW))
    failures = 0
    with tempfile.TemporaryDirectory() as workdir:
        for name, text, secret, should_pass, planted in cases():
            result = run(script, text, secret, workdir)
            output = result.stdout + result.stderr
            problems = []
            if (result.returncode == 0) != should_pass:
                problems.append(f"expected {'pass' if should_pass else 'fail'}, exit status {result.returncode}")
            if not should_pass and "::error::" not in output:
                problems.append("failed without an ::error:: line")
            leaked = [label for label, needle in (("the text", text), ("the token", secret), ("the planted copy", planted))
                      if needle and needle.strip() and needle in output]
            if leaked:
                problems.append("the output contains " + " and ".join(leaked))
            # The step's own output is never printed: it may hold ::error:: commands, which would
            # annotate this run.
            if problems:
                failures += 1
                print(f"::error::{name}: {'; '.join(problems)}")
            else:
                print(f"ok   {name} ({'passes' if should_pass else 'fails'})")
    if failures:
        print(f"::error::{failures} case(s) failed.")
        sys.exit(1)
    print("All cases passed.")


if __name__ == "__main__":
    main()

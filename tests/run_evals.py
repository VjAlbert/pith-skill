#!/usr/bin/env python3
"""Test runner for PITH evals.json"""
import json, re, subprocess, sys, io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "scripts" / "compress.py"
EVALS = Path(__file__).parent / "evals.json"

def extract_payload(prompt: str) -> str:
    """Extract actual payload from prompt preamble."""
    if "\n\n" in prompt:
        return prompt.split("\n\n", 1)[1].strip()
    # Fallback: text after first ': '
    if ": " in prompt:
        return prompt.split(": ", 1)[1].strip()
    return prompt.strip()

def extract_ratio(prompt: str) -> float | None:
    m = re.search(r'ratio\s+(\d+\.\d+)', prompt)
    return float(m.group(1)) if m else None

def needs_json(prompt: str) -> bool:
    return "json" in prompt.lower() and ("metadata" in prompt.lower() or "json" in prompt.lower())

def check_assertion(assertion: str, output: str) -> tuple[bool, str]:
    """Evaluate one assertion string. Returns (passed, reason)."""
    a = assertion.strip()

    # Handle AND (split on ' AND ')
    if ' AND ' in a:
        parts = a.split(' AND ')
        for part in parts:
            passed, reason = check_assertion(part.strip(), output)
            if not passed:
                return False, reason
        return True, "all AND conditions met"

    # Handle OR (split on ' OR ')
    if ' OR ' in a:
        parts = a.split(' OR ')
        for part in parts:
            passed, _ = check_assertion(part.strip(), output)
            if passed:
                return True, "OR condition met"
        return False, f"none of OR conditions met: {a}"

    # "output does NOT contain 'X'"
    m = re.match(r"output does NOT contain '(.+)'", a)
    if m:
        needle = m.group(1)
        if needle in output:
            return False, f"found forbidden string: '{needle}'"
        return True, ""

    # "output does NOT contain X" (no quotes)
    m = re.match(r"output does NOT contain (.+)", a)
    if m:
        needle = m.group(1).strip().strip("'\"")
        if needle in output:
            return False, f"found forbidden string: '{needle}'"
        return True, ""

    # "output contains 'X'" or "output contains X"
    m = re.match(r"output contains '(.+)'", a)
    if m:
        needle = m.group(1)
        if needle not in output:
            return False, f"missing: '{needle}'"
        return True, ""

    m = re.match(r"output contains (.+)", a)
    if m:
        needle = m.group(1).strip()
        # Strip wrapping quotes only if fully wrapped (not partial JSON like "id": 1)
        if (needle.startswith("'") and needle.endswith("'")) or \
           (needle.startswith('"') and needle.endswith('"')):
            needle = needle[1:-1]
        if needle not in output:
            return False, f"missing: '{needle}'"
        return True, ""

    # "output mentions X OR mentions Y" → treat as contains
    m = re.match(r"output mentions (.+)", a)
    if m:
        needle = m.group(1).strip().strip("'\"").lower()
        if needle not in output.lower():
            return False, f"missing mention: '{needle}'"
        return True, ""

    return False, f"unknown assertion format: '{a}'"

def run_tc(tc: dict) -> dict:
    tid = tc["id"]
    category = tc["category"]
    prompt = tc["prompt"]

    if category == "proactive_trigger":
        return {"id": tid, "status": "SKIP", "reason": "meta-question, not a compress.py test"}

    payload = extract_payload(prompt)
    ratio = extract_ratio(prompt)
    json_mode = needs_json(prompt)

    cmd = [sys.executable, str(SCRIPT)]
    if ratio:
        cmd += ["--ratio", str(ratio)]
    if json_mode:
        cmd += ["--json"]
    cmd += ["--payload", payload]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=15)
        output = result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return {"id": tid, "status": "ERROR", "reason": "timeout"}
    except Exception as e:
        return {"id": tid, "status": "ERROR", "reason": str(e)}

    failures = []
    for assertion in tc["assertions"]:
        passed, reason = check_assertion(assertion, output)
        if not passed:
            failures.append(f"  FAIL [{assertion}] >> {reason}")

    status = "PASS" if not failures else "FAIL"
    return {
        "id": tid,
        "category": category,
        "status": status,
        "cmd_exit": result.returncode,
        "failures": failures,
        "output_snippet": output[:300].replace("\n", " ") if output else "",
    }

def main():
    tests = json.loads(EVALS.read_text(encoding="utf-8"))
    results = [run_tc(tc) for tc in tests]

    passed = sum(1 for r in results if r["status"] == "PASS")
    skipped = sum(1 for r in results if r["status"] == "SKIP")
    failed = sum(1 for r in results if r["status"] in ("FAIL", "ERROR"))
    total = len(results)

    print(f"\n{'='*60}")
    print(f"PITH EVAL RESULTS: {passed}/{total-skipped} passed, {skipped} skipped, {failed} failed")
    print(f"{'='*60}")

    for r in results:
        icon = {"PASS": "OK", "FAIL": "XX", "SKIP": "--", "ERROR": "!!"}.get(r["status"], "??")
        print(f"\n[{icon}] {r['id']} ({r.get('category', '')}) - {r['status']}")
        if r.get("failures"):
            for f in r["failures"]:
                print(f)
        if r["status"] in ("FAIL", "ERROR") and r.get("output_snippet"):
            print(f"  Output: {r['output_snippet']}")
        if r["status"] == "SKIP":
            print(f"  {r['reason']}")

    print(f"\n{'='*60}")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())

"""Run the README example in a temporary folder and print each command with its output.

    python tools/demo.py --out results/demo.txt

The commands run from inside the temporary folder, so the printed paths are
relative. The one rule added is time off for the provider on the first
assignment of the built schedule, on that provider's first two dates.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sh(cwd, lines, *argv):
    env = dict(os.environ, PYTHONPATH=ROOT, PYTHONDONTWRITEBYTECODE="1")
    res = subprocess.run([sys.executable, "-m", "shiftrules", *argv], cwd=cwd,
                         capture_output=True, text=True, env=env)
    lines.append("python -m shiftrules " + " ".join(argv))
    lines.append((res.stdout + res.stderr).rstrip("\n"))
    lines.append("exit %d" % res.returncode)
    lines.append("")


def read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out")
    args = p.parse_args()
    lines = []
    with tempfile.TemporaryDirectory() as tmp:
        sh(tmp, lines, "generate", "--seed", "1", "--out", "demo")
        sh(tmp, lines, "build", "demo/roster.json", "demo/rules.json", "--out", "demo/schedule.json")
        sh(tmp, lines, "check", "demo/roster.json", "demo/rules.json", "demo/schedule.json")

        first = read(os.path.join(tmp, "demo", "schedule.json"))["assignments"][0]["provider"]
        dates = []
        for a in read(os.path.join(tmp, "demo", "schedule.json"))["assignments"]:
            if a["provider"] == first and a["date"] not in dates:
                dates.append(a["date"])
        rule = {"id": first + "-away", "kind": "unavailable", "provider": first, "dates": dates[:2]}
        rules = read(os.path.join(tmp, "demo", "rules.json")) + [rule]
        with open(os.path.join(tmp, "demo", "rules2.json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(rules, f, indent=1)
            f.write("\n")
        lines.append("rules2.json is rules.json plus this rule:")
        lines.append(json.dumps(rule))
        lines.append("")

        sh(tmp, lines, "check", "demo/roster.json", "demo/rules2.json", "demo/schedule.json")
        sh(tmp, lines, "rebuild", "demo/roster.json", "demo/rules2.json", "demo/schedule.json",
           "--out", "demo/schedule2.json")
        sh(tmp, lines, "check", "demo/roster.json", "demo/rules2.json", "demo/schedule2.json")
    text = "\n".join(lines) + "\n"
    print(text, end="")
    if args.out:
        with open(os.path.join(ROOT, args.out), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)


if __name__ == "__main__":
    main()

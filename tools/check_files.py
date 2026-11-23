#!/usr/bin/env python3
"""check_files.py: the spec and the hero art, checked in CI. Stdlib only.

1. Every spec/*.json parses. spec/aurelius.json keeps its shape: 5 actions, 5 order
   fields, 8 metrics with one headline, and rungs whose counts follow the tree math.
2. Every docs/img/*.svg parses as XML, with no script, no event handler and no
   outside link.

Exit 0 when clean, 1 on any finding.
"""
import json
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
NEEDED = {"tree", "actions", "order", "reply", "fact_tags", "task_states", "dial", "reward",
          "rungs", "metrics", "baselines", "worker_types", "score_row"}
OUTSIDE = re.compile(r"url\(\s*['\"]?(?!#)|@import", re.I)


def seats(span, tiers):
    """Seats in a full tree: 1 + span + span^2 ... for each tier above the workers."""
    return sum(span ** i for i in range(tiers))


def check_spec(path, out):
    name = path.relative_to(ROOT)
    try:
        spec = json.loads(path.read_text())
    except ValueError as err:
        out.append(f"{name}: not JSON ({err})")
        return
    if path.name != "aurelius.json":
        return
    missing = NEEDED - spec.keys()
    if missing:
        out.append(f"{name}: missing {sorted(missing)}")
        return
    counts = {"actions": 5, "order": 5, "metrics": 8}
    for key, want in counts.items():
        if len(spec[key]) != want:
            out.append(f"{name}: {key} has {len(spec[key])}, want {want}")
    if sum(1 for m in spec["metrics"] if m.get("headline")) != 1:
        out.append(f"{name}: metrics need exactly one headline")
    tree = spec["tree"]
    span, tiers = tree["span"], tree["tiers"]
    if span ** tiers != tree["workers"] or seats(span, tiers) != tree["seats"]:
        out.append(f"{name}: tree breaks the math ({span}^{tiers})")
    for rung in spec["rungs"]:
        if rung["seats"] != seats(span, rung["tiers"]) or rung["agents"] > span ** rung["tiers"]:
            out.append(f"{name}: rung {rung['id']} breaks the tree math")


def check_svg(path, out):
    name = path.relative_to(ROOT)
    text = path.read_text()
    # No DTD at all: this closes entity expansion and external entities before parsing.
    if re.search(r"<!(DOCTYPE|ENTITY)", text, re.I):
        out.append(f"{name}: DOCTYPE or ENTITY is not allowed")
        return
    try:
        root = ET.fromstring(text)
    except ET.ParseError as err:
        out.append(f"{name}: not XML ({err})")
        return
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag in ("script", "foreignObject"):
            out.append(f"{name}: <{tag}> is not allowed")
        if tag == "style" and el.text and OUTSIDE.search(el.text):
            out.append(f"{name}: style loads something outside the file")
        for key, value in el.attrib.items():
            attr = key.rsplit("}", 1)[-1].lower()
            if attr.startswith("on"):
                out.append(f"{name}: event handler {attr}")
            if attr == "href" and not value.startswith("#"):
                out.append(f"{name}: outside link {value}")


def main():
    out = []
    for path in sorted((ROOT / "spec").glob("*.json")):
        check_spec(path, out)
    for path in sorted((ROOT / "docs" / "img").glob("*.svg")):
        check_svg(path, out)
    for line in out:
        print(line)
    print(f"check_files: {len(out)} finding(s)")
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""check_files.py: the spec and the hero art, checked in CI. Stdlib only.

1. Every spec/*.json parses. spec/aurelius.json keeps its shape: 5 actions, 5 order
   fields, 8 metrics with one headline, and rungs whose counts follow the tree math.
2. Every docs/img/*.svg parses as XML, with no script, no event handler and no
   outside link. No `url()` outside the file in a style="" attribute, and no animated
   href (a SMIL animate or set that targets href).

`--self-test` runs built-in bad and good samples through the SVG check.
Exit 0 when clean, 1 on any finding or failed self-test.
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
SMIL = ("animate", "set", "animatetransform", "animatecolor")


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
    svg_findings(path.relative_to(ROOT), path.read_text(), out)


def svg_findings(name, text, out):
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
        if tag.lower() in SMIL and el.get("attributeName", "").strip().lower().endswith("href"):
            out.append(f"{name}: <{tag}> animates an href")
        for key, value in el.attrib.items():
            attr = key.rsplit("}", 1)[-1].lower()
            if attr == "style" and OUTSIDE.search(value):
                out.append(f"{name}: style attribute loads something outside the file")
            if attr.startswith("on"):
                out.append(f"{name}: event handler {attr}")
            if attr == "href" and not value.startswith("#"):
                out.append(f"{name}: outside link {value}")


NS = 'xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"'
SAMPLES = [  # (label, svg, should be refused)
    ("script", f"<svg {NS}><script>alert(1)</script></svg>", True),
    ("outside href", f'<svg {NS}><a xlink:href="https://example.com"><rect/></a></svg>', True),
    ("on* handler", f'<svg {NS}><rect onload="x()"/></svg>', True),
    ("DTD", f'<!DOCTYPE svg [<!ENTITY a "b">]><svg {NS}/>', True),
    ("style attribute url", f'<svg {NS}><rect style="fill:url(https://example.com/a.png)"/></svg>', True),
    ("animated href", f'<svg {NS}><use href="#a"><animate attributeName="xlink:href" to="x"/></use></svg>', True),
    ("good", f'<svg {NS}><style>.a{{animation:b 2s}}</style><rect style="fill:url(#g)"/>'
             f'<use href="#a"/></svg>', False),
]


def self_test():
    bad = 0
    for label, svg, refused in SAMPLES:
        found = []
        svg_findings(label, svg, found)
        ok = bool(found) == refused
        bad += not ok
        print(f"{'PASS' if ok else 'FAIL'} {label}")
    print(f"check_files self-test: {bad} failure(s)")
    return 1 if bad else 0


def main():
    if "--self-test" in sys.argv[1:]:
        return self_test()
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

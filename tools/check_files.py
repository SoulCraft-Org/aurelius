#!/usr/bin/env python3
"""check_files.py: the spec and the hero art, checked in CI. Stdlib only.

1. Every spec/*.json parses. spec/aurelius.json keeps its shape: 5 actions, 5 order
   fields, 8 metrics with one headline, and rungs whose counts follow the tree math.
2. Every docs/img/*.svg parses as XML, with no script, no event handler and no
   outside link. No `url()` outside the file in any attribute (style, fill, filter, mask), and no animated
   href (a SMIL animate or set that targets href).

`--self-test` runs built-in bad and good samples through the SVG check, and malformed copies
of the spec through the spec check. A spec with the wrong shape is a finding, never a traceback.
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
    spec_findings(name, spec, out)


def _whole(value):
    """True for a plain int that is not a bool."""
    return isinstance(value, int) and not isinstance(value, bool)


def spec_findings(name, spec, out):
    """Append one finding per shape problem in a parsed spec. Never raises on a wrong shape."""
    if not isinstance(spec, dict):
        out.append(f"{name}: the spec must be a JSON object, not {type(spec).__name__}")
        return
    missing = NEEDED - spec.keys()
    if missing:
        out.append(f"{name}: missing {sorted(missing)}")
        return
    counts = {"actions": 5, "order": 5, "metrics": 8}
    for key, want in counts.items():
        if not isinstance(spec[key], list):
            out.append(f"{name}: {key} must be a list")
        elif len(spec[key]) != want:
            out.append(f"{name}: {key} has {len(spec[key])}, want {want}")
    if isinstance(spec["metrics"], list):
        bad = [i for i, m in enumerate(spec["metrics"]) if not isinstance(m, dict)]
        for i in bad:
            out.append(f"{name}: metrics[{i}] must be an object")
        if sum(1 for m in spec["metrics"] if isinstance(m, dict) and m.get("headline")) != 1:
            out.append(f"{name}: metrics need exactly one headline")
    tree = spec["tree"]
    if not isinstance(tree, dict):
        out.append(f"{name}: tree must be an object")
        return
    gaps = [k for k in ("span", "tiers", "workers", "seats") if not _whole(tree.get(k))]
    if gaps:
        out.append(f"{name}: tree needs whole numbers for {gaps}")
        return
    span, tiers = tree["span"], tree["tiers"]
    if span ** tiers != tree["workers"] or seats(span, tiers) != tree["seats"]:
        out.append(f"{name}: tree breaks the math ({span}^{tiers})")
    if not isinstance(spec["rungs"], list):
        out.append(f"{name}: rungs must be a list")
        return
    for i, rung in enumerate(spec["rungs"]):
        if not isinstance(rung, dict):
            out.append(f"{name}: rungs[{i}] must be an object")
            continue
        label = rung.get("id", f"rungs[{i}]")
        gaps = [k for k in ("agents", "tiers", "seats") if not _whole(rung.get(k))]
        if gaps:
            out.append(f"{name}: rung {label} needs whole numbers for {gaps}")
            continue
        if rung["seats"] != seats(span, rung["tiers"]) or rung["agents"] > span ** rung["tiers"]:
            out.append(f"{name}: rung {label} breaks the tree math")


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
            if OUTSIDE.search(value):
                out.append(f"{name}: {attr} attribute loads something outside the file")
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
    ("fill attribute url", f'<svg {NS}><rect fill="url(https://example.com/a.svg#p)"/></svg>', True),
    ("animated href", f'<svg {NS}><use href="#a"><animate attributeName="xlink:href" to="x"/></use></svg>', True),
    ("good", f'<svg {NS}><style>.a{{animation:b 2s}}</style><rect style="fill:url(#g)"/>'
             f'<use href="#a"/></svg>', False),
]


def spec_samples():
    """(label, parsed spec, should be refused): a small good spec, then malformed copies of it (issue #104)."""
    good = {key: [] for key in NEEDED}
    good.update({
        "tree": {"span": 47, "tiers": 3, "workers": 103823, "seats": 2257},
        "actions": [{}] * 5, "order": [{}] * 5,
        "metrics": [{"id": "headline", "headline": True}] + [{"id": f"m{i}"} for i in range(7)],
        "dial": {}, "score_row": {},
        "rungs": [{"id": "r10", "agents": 10, "tiers": 1, "seats": 1}, {"id": "r2209", "agents": 2209, "tiers": 2, "seats": 48}],
    })

    def broken(change):
        spec = json.loads(json.dumps(good))
        change(spec)
        return spec

    return [
        ("spec: a JSON list", [good], True),
        ("spec: a rung without seats", broken(lambda s: s["rungs"][0].pop("seats")), True),
        ("spec: a rung without agents", broken(lambda s: s["rungs"][0].pop("agents")), True),
        ("spec: a rung without tiers", broken(lambda s: s["rungs"][0].pop("tiers")), True),
        ("spec: a rung that is not an object", broken(lambda s: s["rungs"].__setitem__(0, "r10")), True),
        ("spec: a tree without span", broken(lambda s: s["tree"].pop("span")), True),
        ("spec: a tree that is a list", broken(lambda s: s.__setitem__("tree", [47, 3])), True),
        ("spec: a metric that is not an object", broken(lambda s: s["metrics"].__setitem__(0, "verified_success")), True),
        ("spec: metrics that are an object", broken(lambda s: s.__setitem__("metrics", {})), True),
        ("spec: good", good, False),
    ]


def self_test():
    bad = 0
    for label, svg, refused in SAMPLES:
        found = []
        svg_findings(label, svg, found)
        ok = bool(found) == refused
        bad += not ok
        print(f"{'PASS' if ok else 'FAIL'} {label}")
    for label, spec, refused in spec_samples():
        found = []
        try:
            spec_findings(label, spec, found)
            ok = bool(found) == refused
        except Exception as err:  # a traceback is the bug this sample guards against
            found, ok = [f"raised {type(err).__name__}"], False
        bad += not ok
        print(f"{'PASS' if ok else 'FAIL'} {found[0] if found else label}")
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

#!/usr/bin/env python3
"""make_tree.py: the agent tree of rung r2209 as an ASCII STL, docs/img/tree.stl. Stdlib only, no randomness.

The top seat sits high in the middle, its seats on a ring below, each seat's workers in a small cluster
under it. Seats are icosahedra, workers tetrahedra, every link a thin triangular prism.
Usage: python3 -I tools/make_tree.py [--check]   (--check exits 1 when the committed file differs)
"""
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
RUNG = "r2209"
FACETS = {"seat": 20, "worker": 4, "link": 8}
PHI = (1 + 5 ** 0.5) / 2
ICO = [(0, s1, s2 * PHI) for s1 in (1, -1) for s2 in (1, -1)]
ICO = [tuple(p[(i - k) % 3] for i in range(3)) for k in range(3) for p in ICO]
ICO_FACES = [(i, j, k) for i in range(12) for j in range(i + 1, 12) for k in range(j + 1, 12)
             if all(abs(math.dist(ICO[x], ICO[y]) - 2) < 1e-9 for x, y in ((i, j), (j, k), (i, k)))]
TETRA = [(1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)]
TETRA_FACES = [(0, 1, 2), (0, 3, 1), (0, 2, 3), (1, 3, 2)]
RING, TOP_Z, SEAT_R, DROP, WORKER_R, STEP, LINK_T, WLINK_T = 170.0, 150.0, 6.0, 26.0, 1.2, 1.5, 0.8, 0.12


def counts(spec):
    """(top seats, seats, workers, span) of RUNG, read from the spec: seats per tier, leaves first."""
    rung = {r["id"]: r for r in spec["rungs"]}[RUNG]
    span = spec["tree"]["span"]
    tiers = [-(-rung["agents"] // span ** t) for t in range(1, rung["tiers"] + 1)]
    return tiers[-1], tiers[0], rung["agents"], span


def facet_count(spec):
    top, seats, workers, _ = counts(spec)
    return (top + seats) * FACETS["seat"] + workers * (FACETS["worker"] + FACETS["link"]) + seats * FACETS["link"]


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _unit(a):
    n = math.sqrt(sum(x * x for x in a)) or 1.0
    return tuple(x / n for x in a)


def _solid(verts, faces):
    """Triangles of a convex solid, each wound so its normal points away from the solid's middle."""
    mid = tuple(sum(v[i] for v in verts) / len(verts) for i in range(3))
    out = []
    for f in faces:
        a, b, c = (verts[i] for i in f)
        n = _cross(_sub(b, a), _sub(c, a))
        if sum(n[i] * (a[i] - mid[i]) for i in range(3)) < 0:
            b, c = c, b
        out.append((a, b, c))
    return out


def _shape(unit_verts, faces, centre, radius):
    verts = [tuple(centre[i] + radius * _unit(v)[i] for i in range(3)) for v in unit_verts]
    return _solid(verts, faces)


def _link(a, b, thick):
    d = _unit(_sub(b, a))
    u = _unit(_cross(d, (0.0, 0.0, 1.0) if abs(d[2]) < 0.99 else (1.0, 0.0, 0.0)))
    v = _cross(d, u)
    ring = [tuple(thick * (math.cos(2 * math.pi * k / 3) * u[i] + math.sin(2 * math.pi * k / 3) * v[i])
                  for i in range(3)) for k in range(3)]
    verts = [tuple(p[i] + r[i] for i in range(3)) for p in (a, b) for r in ring]
    return _solid(verts, [(0, 1, 2), (3, 4, 5)] + [f for k in range(3) for f in
                  ((k, (k + 1) % 3, 3 + (k + 1) % 3), (k, 3 + (k + 1) % 3, 3 + k))])


def triangles(spec):
    top, seats, workers, span = counts(spec)
    apex = (0.0, 0.0, TOP_Z)
    tris = _shape(ICO, ICO_FACES, apex, SEAT_R * 1.6)
    gold = math.pi * (3 - 5 ** 0.5)
    for s in range(seats):
        ang = 2 * math.pi * s / seats
        seat = (RING * math.cos(ang), RING * math.sin(ang), 0.0)
        tris += _shape(ICO, ICO_FACES, seat, SEAT_R)
        tris += _link(apex, seat, LINK_T)
        for k in range(min(span, workers - s * span)):
            r, a = STEP * math.sqrt(k + 0.5), k * gold
            at = (seat[0] + r * math.cos(a), seat[1] + r * math.sin(a), -DROP)
            tris += _link(seat, at, WLINK_T)
            tris += _shape(TETRA, TETRA_FACES, at, WORKER_R)
    return tris


def _num(x):
    return f"{round(x, 3) + 0.0:.3f}"


def render(spec):
    lines = ["solid aurelius_tree"]
    for a, b, c in triangles(spec):
        n = _unit(_cross(_sub(b, a), _sub(c, a)))
        lines.append(f"facet normal {' '.join(_num(x) for x in n)}\n outer loop")
        lines += [f"  vertex {' '.join(_num(x) for x in v)}" for v in (a, b, c)]
        lines.append(" endloop\nendfacet")
    lines.append("endsolid aurelius_tree")
    return "\n".join(lines) + "\n"


def main(argv):
    spec = json.loads((ROOT / "spec" / "aurelius.json").read_text())
    out, text = ROOT / "docs" / "img" / "tree.stl", render(spec)
    if "--check" in argv:
        return 0 if out.exists() and out.read_text() == text else 1
    out.write_text(text)
    print(f"{out.relative_to(ROOT)}: {text.count('endfacet')} facets, {len(text.encode())} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

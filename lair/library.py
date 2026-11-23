"""The Library: a generated document corpus that real workers search.

Each item gets documents that state its answer; knobs add near-miss distractors,
superseded documents and filler. All randomness is seeded, one corpus per task, seed and knobs.
"""

import heapq
import math
import random
import re
from collections import Counter

TOKEN = re.compile(r"[a-z0-9]+")
STATE = (
    "Record {key}: the value is {v}.",
    "The entry for {key} reads {v}.",
    "According to the register, {key} is set to {v}.",
    "For {key}, the confirmed figure is {v}.",
    "{key} was logged with the value {v}.",
)
FILLER = (
    "The register is reviewed every quarter by the desk.",
    "Entries are copied from the field sheets without edits.",
    "Older volumes sit on the second shelf.",
)
OLD_CUES = ("superseded", "out of date", "no longer in force")
OLD = (
    "Superseded: {key} was once recorded as {v}; a later entry replaces {key}.",
    "Out of date, replaced by a later filing: {key} read {v} (see {key}).",
    "Archive copy, no longer in force: {key} stood at {v}.",
)
FIX = (  # each gives the wrong value, then the true one; no word is shared by more than two
    "Revised entry, {key}: {wrong} amended to {v}.",
    "Version 2 drops {wrong} for {key} and now gives {v}.",
    "Notice dated later: {wrong} is wrong for {key}, right figure {v}.",
    "Errata sheet. In {key}, {wrong} appeared where {v} belongs.",
    "Memo replaces the figure in {key} ({wrong}) with {v}.",
    "Fixed after audit; {key} showed {wrong} but should show {v}.",
)


def tokens(text):
    return TOKEN.findall(text.lower())


class Library:
    """Documents by id, searched with BM25 over lowercase word tokens."""

    def __init__(self, docs, k1=1.5, b=0.75):
        self.docs = dict(docs)
        self.k1, self.b = k1, b
        self.order = {d: i for i, d in enumerate(self.docs)}
        self.len = {}
        self.post = {}  # word -> {doc_id: count}
        for d, t in self.docs.items():
            words = tokens(t)
            self.len[d] = len(words)
            for w, c in Counter(words).items():
                self.post.setdefault(w, {})[d] = c
        self.avg = sum(self.len.values()) / max(len(self.len), 1)

    def doc(self, doc_id):
        return self.docs[doc_id]

    def scores(self, query):
        """BM25 score of every document that holds a query word."""
        n, out = len(self.docs), {}
        for w in set(tokens(query)):
            post = self.post.get(w, {})
            idf = math.log(1 + (n - len(post) + 0.5) / (len(post) + 0.5))
            for d, c in post.items():
                norm = 1 - self.b + self.b * self.len[d] / self.avg
                out[d] = out.get(d, 0.0) + idf * c * (self.k1 + 1) / (c + self.k1 * norm)
        return out

    def search(self, query, k=5):
        """Top k (doc_id, text) by BM25; ties go to the earlier document."""
        sc = self.scores(query)
        best = heapq.nlargest(k, sc, key=lambda d: (sc[d], -self.order[d]))
        return [(d, self.docs[d]) for d in best]


def hexval(rng, avoid=()):
    while True:
        v = f"{rng.getrandbits(32):08x}"
        if v not in avoid:
            return v


def off_by_one(rng, v):
    """The answer with one digit changed: wrong, but easy to miss."""
    i = rng.randrange(len(v))
    return v[:i] + rng.choice([c for c in "0123456789abcdef" if c != v[i]]) + v[i + 1:]


def sub(seed, name, kind):
    """One generator per item and kind, so a knob never shifts another kind's draws."""
    return random.Random(f"{seed}:{name}:{kind}")


def make_library(task, seed, distractors=0, conflicts=0.0, noise=0.0):
    """Build the corpus for a task. noise is filler sentences per document, on average."""
    texts = {}
    for it in task.items:
        k, r = it.key, sub(seed, it.key, "main")
        shown = off_by_one(r, it.answer) if it.fault else it.answer
        texts[f"{k}:main"] = r.choice(STATE).format(key=k, v=shown)
        if it.fault:
            texts[f"{k}:fix"] = sub(seed, k, "fix").choice(FIX).format(key=k, wrong=shown, v=it.answer)
        r = sub(seed, k, "conflict")
        if r.random() < conflicts:
            texts[f"{k}:old"] = r.choice(OLD).format(key=k, v=hexval(r, (it.answer,)))
        r = sub(seed, k, "near")
        for j in range(distractors):
            texts[f"{k}:near{j}"] = r.choice(STATE).format(key=f"{k}-v{j}", v=hexval(r, (it.answer,)))
    docs = {}
    for d in sorted(texts, key=lambda d: sub(seed, d, "rank").random()):
        r = sub(seed, d, "noise")
        parts = [texts[d]] + [r.choice(FILLER) for _ in range(int(noise) + (r.random() < noise % 1))]
        r.shuffle(parts)
        docs[d] = " ".join(parts)
    return Library(docs)

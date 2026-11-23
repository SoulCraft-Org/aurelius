"""The Library: a generated document corpus that real workers search.

Each task item gets documents that state its answer. Knobs add near-miss
distractors, older superseded documents and filler. All randomness comes from
the random.Random(seed) made here, so one task, seed and knob set give one corpus.
"""

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
    "Questions about format go to the records office.",
    "This page was printed on recycled paper.",
    "Older volumes sit on the second shelf.",
)


def tokens(text):
    return TOKEN.findall(text.lower())


class Library:
    """Documents by id, searched with BM25 over lowercase word tokens."""

    def __init__(self, docs, k1=1.5, b=0.75):
        self.docs = dict(docs)
        self.k1, self.b = k1, b
        self.order = {d: i for i, d in enumerate(self.docs)}
        self.tf = {d: Counter(tokens(t)) for d, t in self.docs.items()}
        self.len = {d: sum(c.values()) for d, c in self.tf.items()}
        self.avg = sum(self.len.values()) / max(len(self.len), 1)
        self.df = Counter(w for c in self.tf.values() for w in c)

    def doc(self, doc_id):
        return self.docs[doc_id]

    def search(self, query, k=5):
        """Top k (doc_id, text) by BM25; ties go to the earlier document."""
        n = len(self.docs)
        scores = {}
        for w in set(tokens(query)):
            idf = math.log(1 + (n - self.df[w] + 0.5) / (self.df[w] + 0.5))
            for d, c in self.tf.items():
                if w in c:
                    norm = 1 - self.b + self.b * self.len[d] / self.avg
                    scores[d] = scores.get(d, 0.0) + idf * c[w] * (self.k1 + 1) / (c[w] + self.k1 * norm)
        best = sorted(scores, key=lambda d: (-scores[d], self.order[d]))[:k]
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


def make_library(task, seed, distractors=0, conflicts=0.0, noise=0.0):
    """Build the corpus for a task. noise is filler sentences per document, on average."""
    rng = random.Random(seed)
    texts = []
    for it in task.items:
        shown = off_by_one(rng, it.answer) if it.fault else it.answer
        texts.append(rng.choice(STATE).format(key=it.key, v=shown))
        if it.fault:
            texts.append(f"Correction: {it.key} was wrongly given as {shown}; the corrected value is {it.answer}.")
        if rng.random() < conflicts:
            old = hexval(rng, (it.answer,))
            texts.append(f"Superseded: {it.key} was once recorded as {old}; a later entry replaces {it.key}.")
        for j in range(distractors):
            texts.append(rng.choice(STATE).format(key=f"{it.key}-v{j}", v=hexval(rng, (it.answer,))))
    rng.shuffle(texts)
    docs = {}
    for i, text in enumerate(texts):
        parts = [text] + [rng.choice(FILLER) for _ in range(int(noise) + (rng.random() < noise % 1))]
        rng.shuffle(parts)
        docs[f"d{i}"] = " ".join(parts)
    return Library(docs)

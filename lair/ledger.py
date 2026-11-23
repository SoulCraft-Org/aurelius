"""The ledger: an append-only record per seat. A killed seat resumes by replay."""

import json


class ResumeMismatch(Exception):
    """The replay from the seed did not reproduce what was saved."""


class Ledger:
    """Entries are JSON-safe dicts with a 'kind'. Same entries, same JSONL."""

    def __init__(self, entries=()):
        self.entries = list(entries)

    def add(self, kind, **data):
        """Append an entry. It is stored as JSON, so it equals its saved copy."""
        if "kind" in data:
            raise ValueError("'kind' is reserved in add()")
        text = json.dumps({"kind": kind, **data}, sort_keys=True, allow_nan=False)
        self.entries.append(json.loads(text))

    def to_jsonl(self):
        """One JSON object per line, keys sorted; empty for no entries."""
        return "".join(json.dumps(e, sort_keys=True, allow_nan=False) + "\n" for e in self.entries)

    @classmethod
    def from_jsonl(cls, text):
        """Read what to_jsonl wrote; blank lines are skipped."""
        return cls(json.loads(line) for line in text.splitlines() if line.strip())

    def is_prefix_of(self, other):
        """True when other starts with exactly these entries (equal counts)."""
        return other.entries[: len(self.entries)] == self.entries


def resume(start, saved, until=None):
    """Replay from the seed and check it against saved; return the new ledger.

    start() returns a fresh (sim, ledger) built from the same seed, with its
    events writing to that ledger. Raise ResumeMismatch unless saved is a prefix.
    """
    sim, ledger = start()
    sim.run(until=until)
    if not saved.is_prefix_of(ledger):
        raise ResumeMismatch("the replay does not reproduce the saved ledger")
    return ledger

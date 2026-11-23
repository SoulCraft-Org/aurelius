"""Unit tests for the real workers. Every HTTP call is mocked: nothing leaves the machine."""

import io
import json
import unittest
from unittest import mock

from lair import load_spec
from lair.library import make_library
from lair.real_workers import REAL_WORKERS, ROUNDS, RealWorker
from lair.tasks import make_task
from lair.workers import worker_types

SPEC = load_spec()
TASK = make_task(3, 4)
ITEM = TASK.items[0]
LIB = make_library(TASK, 3)
MAIN = next(d for d, t in LIB.docs.items() if ITEM.answer in t)  # the document that holds the answer


def reply(content=None, calls=(), tokens=30):
    msg = {"role": "assistant", "content": content, "tool_calls": [
        {"id": f"c{i}", "type": "function", "function": {"name": "search", "arguments": json.dumps({"query": q})}} for i, q in enumerate(calls)]}
    return io.BytesIO(json.dumps({"choices": [{"message": msg}], "usage": {"total_tokens": tokens}}).encode())


def answer(value, doc):
    return reply(json.dumps({"value": value, "doc": doc}))


def run(responses, kind="medium"):
    """One do_item with the HTTP replies in order; returns the reply and the request bodies sent."""
    sent = []

    def fake(req, timeout):
        sent.append(req.data.decode())
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    with mock.patch("urllib.request.urlopen", fake):
        return RealWorker(kind, "http://localhost:8000/v1/chat/completions", "m", LIB).do_item(ITEM), sent


class RealWorkersTest(unittest.TestCase):
    def test_the_table_has_one_apache_model_per_worker_type(self):
        self.assertEqual(set(REAL_WORKERS), set(worker_types(SPEC)))
        self.assertEqual({w["licence"] for w in REAL_WORKERS.values()}, {"Apache-2.0"})

    def test_a_good_answer_is_a_valid_reply(self):
        out, _ = run([reply(calls=[ITEM.key]), answer(ITEM.answer, MAIN)])
        self.assertEqual(set(out), {f["field"] for f in SPEC["reply"]})
        self.assertEqual(out["status"], "completed")
        self.assertIn(out["status"], SPEC["task_states"])
        fact = out["facts"][0]
        self.assertEqual(set(fact), {"claim", "value", "tag", "source"})
        self.assertEqual((fact["claim"], fact["value"], fact["tag"], fact["source"]), (ITEM.key, ITEM.answer, "seen", MAIN))
        self.assertIn(fact["tag"], SPEC["fact_tags"])
        self.assertEqual((out["spent"]["credits"], out["spent"]["tokens"]), (4, 60))
        self.assertGreaterEqual(out["spent"]["seconds"], 0)

    def test_a_value_in_no_read_document_is_inferred(self):
        out, _ = run([reply(calls=[ITEM.key]), answer("deadbeef", MAIN)])
        self.assertEqual((out["status"], out["facts"][0]["tag"], out["facts"][0]["source"]), ("completed", "inferred", None))
        out, _ = run([answer(ITEM.answer, MAIN)])  # a right value it never read is still inferred
        self.assertEqual((out["facts"][0]["tag"], out["facts"][0]["source"]), ("inferred", None))

    def test_failures_give_failed_and_count_the_spend(self):
        for name, responses in (("timeout", [TimeoutError()]), ("junk", [reply("no json here")]),
                                ("bad json", [reply("{nope}")]), ("no value", [answer("", MAIN)]),
                                ("never answers", [reply(calls=["a"]) for _ in range(ROUNDS + 1)])):
            with self.subTest(name):
                out, _ = run(responses, "large")
                self.assertEqual((out["status"], out["facts"], out["alarms"]), ("failed", [], []))
                self.assertEqual(out["spent"]["credits"], 16)
                self.assertGreater(out["spent"]["tokens"], 0)

    def test_at_most_four_tool_rounds(self):
        out, sent = run([reply(calls=["a"]) for _ in range(ROUNDS)] + [answer(ITEM.answer, MAIN)])
        self.assertEqual((out["status"], len(sent)), ("completed", ROUNDS + 1))
        self.assertNotIn('"tools"', sent[-1])  # the last turn offers no tool

    def test_the_prompt_never_holds_the_answer(self):
        _, sent = run([reply(calls=[ITEM.key]), answer(ITEM.answer, MAIN)])
        self.assertIn(ITEM.key, sent[0])
        self.assertNotIn(ITEM.answer, sent[0])  # the second request holds the search result, which may hold it

    def test_no_call_runs_past_the_deadline(self):
        with mock.patch("urllib.request.urlopen") as urlopen:
            out = RealWorker("small", "http://localhost:8000/v1", "m", LIB, deadline=0).do_item(ITEM)
        urlopen.assert_not_called()
        self.assertEqual((out["status"], out["spent"]["credits"]), ("failed", 1))

    def test_seen_needs_a_whole_word_and_a_source_only_when_seen(self):
        fact = lambda value, text: RealWorker._fact("k", json.dumps({"value": value, "doc": "d1"}), {"d1": text})
        self.assertEqual((fact("0", "the value is 1a02b")["tag"], fact("0", "the value is 1a02b")["source"]), ("inferred", None))
        self.assertEqual((fact("0", "The value is 0.")["tag"], fact("0", "The value is 0.")["source"]), ("seen", "d1"))

    def test_any_exception_still_gives_failed_with_the_spend(self):
        with mock.patch.object(RealWorker, "_ask", side_effect=RuntimeError("boom")):
            out = RealWorker("small", "http://localhost:8000/v1", "m", LIB).do_item(ITEM)
        self.assertEqual((out["status"], out["facts"], out["spent"]["credits"]), ("failed", [], 1))

    def test_a_bad_url_is_refused(self):
        with self.assertRaises(ValueError):
            RealWorker("small", "file:///etc/passwd", "m", LIB)


if __name__ == "__main__":
    unittest.main()

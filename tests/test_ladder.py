"""Unit tests for the Ladder runner. Rungs r10 and r47 run; r2209 is built, and run once."""

import contextlib
import io
import json
import unittest
from functools import partial
from types import SimpleNamespace
from unittest import mock

from ladder.metrics import METRIC_IDS
from ladder.models import MODEL
from ladder.run import _Leaf, _kill_and_resume, _lift, main, parse_args, run_once, score, stamp, tree, with_rates
from lair import load_spec
from lair.baselines import NAMES
from lair.seat import RuleSeat
from lair.sim import Sim
from lair.tasks import make_task

SPEC = load_spec()
SEATS = ("rule", *NAMES)


def rows(log, kind):
    return [r for r in log if r["kind"] == kind]


class RunTest(unittest.TestCase):
    def test_the_tree_matches_the_spec_seats(self):
        self.assertEqual(sum(tree(SPEC, "r2209")), 48)
        self.assertEqual([sum(tree(SPEC, r["id"])) for r in SPEC["rungs"]], [r["seats"] for r in SPEC["rungs"]])

    def test_every_seat_scores_the_same_twice_inside_its_budget(self):
        for rung in ("r10", "r47"):
            for seat in SEATS:
                a, b = score(rung, seat, (1,)), score(rung, seat, (1,))
                self.assertEqual(a["metrics"], b["metrics"])
                self.assertEqual((tuple(a["metrics"]), a["metrics"]["budget_overruns"]), (METRIC_IDS, 0))
                self.assertEqual((list(a), a["workers"]), (SPEC["score_row"]["fields"], "sim"))

    def test_the_rule_seat_resumes_a_killed_leaf_and_a_tier_checks_up(self):
        log = run_once("r2209", "rule", SPEC, 0)
        self.assertEqual([r["same"] for r in rows(log, "resume")], [True])
        self.assertTrue([r for r in rows(log, "check") if r["tier"] == 2])

    def test_the_rule_seat_and_a_baseline_get_the_same_budget(self):
        with mock.patch("ladder.run.run_baseline") as base, mock.patch("ladder.run._rule") as rule:
            run_once("r10", "one_agent", SPEC, 1), run_once("r10", "rule", SPEC, 1)
        self.assertEqual((base.call_args.args[4], rule.call_args.args[4]), (50, 50))

    def test_a_leaf_is_killed_part_way_and_resume_matches_the_full_run(self):
        task = make_task(1, 47)
        make = partial(_Leaf, SPEC, task, task.items, 1, 5 * 47)
        full = make()
        full.sim.run()
        saved, resumed = _kill_and_resume(make, full)
        self.assertTrue(0 < len(saved.entries) < len(full.led.entries))
        self.assertEqual(resumed.entries, full.led.entries)
        self.assertEqual([r["same"] for r in rows(run_once("r47", "rule", SPEC, 1), "resume")], [True])

    def test_an_alarm_goes_up_only_with_a_kept_fact(self):
        item, fact = SimpleNamespace(answer="x"), {"claim": "a", "value": "x"}
        leaf = _Leaf.__new__(_Leaf)  # only report() runs, on replies set by hand
        leaf.sim, leaf.items, leaf.checked = Sim(0), {"a": item, "b": item}, {"b": False}
        leaf.replies = {k: {"status": "completed", "facts": [fact], "alarms": [k]} for k in "ab"}
        leaf.report()
        self.assertEqual(leaf.alarms, ["a"])
        kids, task = [({"a": fact}, ["a"])], SimpleNamespace(can_split=True)
        for verdict, up in ((False, []), (True, ["a"])):
            with mock.patch("ladder.run.check", return_value=verdict):
                self.assertEqual(_lift(Sim(0), task, SPEC, {"a": item}, 2, kids, [100])[1], up)

    def test_a_check_drops_keys_with_no_reply_or_already_checked(self):  # #59: map then check one key crashed with KeyError
        task = make_task(1, 10)
        key = task.items[0].key
        send = {"name": "map", "children": [key], "worker_type": "small"}
        check = {"name": "check", "children": [key]}
        end = [{"name": "stop", "children": []}]
        rounds = iter([[send, check], [check], [check], end])  # cleared, then valid, then already checked
        leaf = _Leaf(SPEC, task, task.items, 1, 50, SimpleNamespace(decide=lambda obs: next(rounds)))
        leaf.sim.run()
        self.assertEqual(len(rows(leaf.sim.log, "check")), 1)
        self.assertEqual(list(leaf.checked), [key])

    def test_no_split_takes_every_step_and_no_split_row_is_shortened(self):
        log = run_once("r10", "rule", SPEC, 1, "no_split")
        self.assertEqual(rows(log, "final")[0]["critical_steps"], 10)
        self.assertTrue(rows(log, "split"))
        self.assertFalse([r for r in rows(log, "split") if r["shortened"]])

    def test_every_seat_spends_at_most_5_credits_per_agent(self):
        for rung in ("r10", "r47"):
            agents = next(r["agents"] for r in SPEC["rungs"] if r["id"] == rung)
            for seat in SEATS:
                spent = sum(r["credits"] for r in rows(run_once(rung, seat, SPEC, 1), "spend"))
                self.assertLessEqual(spent, 5 * agents, (rung, seat))

    def test_the_command_line_prints_the_score_row(self):
        args = parse_args(["--rung", "r47", "--seat", "rule", "--seeds", "3"])
        self.assertEqual((args.rung, args.seat, args.seeds), ("r47", "rule", 3))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["--rung", "r10", "--seat", "flat_fan_out", "--seeds", "2"])
        self.assertEqual(json.loads(out.getvalue()), score("r10", "flat_fan_out", (0, 1)))

    def test_the_splits_never_overlap(self):
        spans = sorted(SPEC["seeds"].values())
        self.assertEqual(SPEC["seeds"], {"dev": [0, 999], "val": [1000, 1999], "test": [2000, 2999]})
        for (lo, hi), (next_lo, _) in zip(spans, spans[1:]):
            self.assertLessEqual(lo, hi)
            self.assertLess(hi, next_lo)

    def test_a_seed_outside_the_split_is_refused(self):
        with self.assertRaises(ValueError):
            score("r10", "rule", (0, 1000))  # a val seed in a dev run
        with self.assertRaises(ValueError):
            score("r10", "rule", (0,), split="val")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(["--rung", "r10", "--seat", "one_agent", "--seeds", "2", "--split", "test"])
        row = json.loads(out.getvalue())
        self.assertEqual((row["seed"], row["split"], row["rates"]), ([2000, 2001], "test", 0.0))

    def test_rates_change_only_error_rates(self):
        out = with_rates(SPEC, 0.2)
        for was, now in zip(SPEC["worker_types"], out["worker_types"]):
            self.assertAlmostEqual(1 - now["skill"], (1 - was["skill"]) * 1.2)
        for k in ("false_pass", "false_fail"):
            self.assertAlmostEqual(out["check"][k], SPEC["check"][k] * 1.2)

        def rest(spec):  # everything but the error rates
            return {**spec, "worker_types": [{k: v for k, v in t.items() if k != "skill"} for t in spec["worker_types"]],
                    "check": {k: v for k, v in spec["check"].items() if k not in ("false_pass", "false_fail")}}
        self.assertEqual(rest(out), rest(SPEC))
        self.assertEqual(SPEC, load_spec())  # the copy never touches the original
        self.assertIs(with_rates(SPEC, 0.0), SPEC)
        edge = {"worker_types": [{"skill": 0.0}, {"skill": 1.0}], "check": {"false_pass": 0.9, "false_fail": 0.0}}
        got = with_rates(edge, 0.5)
        self.assertEqual([t["skill"] for t in got["worker_types"]], [0.0, 1.0])
        self.assertEqual(got["check"], {"false_pass": 1.0, "false_fail": 0.0})
        for bad in (0.6, -0.51, float("nan")):
            with self.assertRaises(ValueError):
                with_rates(SPEC, bad)
        self.assertEqual(score("r10", "one_agent", (0,), rates=0.2)["rates"], 0.2)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parse_args(["--rung", "r10", "--seat", "rule", "--rates", "0.6"])

    def test_the_stamp_is_stable_for_the_same_spec(self):
        a, b = score("r10", "rule", (0,)), score("r10", "rule", (0,), rates=0.2)
        self.assertEqual(a["stamp"], score("r10", "rule", (0,))["stamp"])
        self.assertEqual(a["stamp"], b["stamp"])  # the hash is of the spec as written, before --rates
        self.assertRegex(a["stamp"]["spec"], "^[0-9a-f]{12}$")
        self.assertEqual(a["stamp"]["seat"], "rule")
        self.assertEqual([v for k, v in a["stamp"].items() if k not in ("spec", "seat")], [None] * 4)
        self.assertNotEqual(stamp({**SPEC, "version": "x"}, "rule")["spec"], a["stamp"]["spec"])
        self.assertEqual(stamp(dict(reversed(SPEC.items())), "rule"), a["stamp"])  # key order does not matter
        seat = stamp(SPEC, "model", SimpleNamespace(revision="r", adapter="a", prompt="p"))
        self.assertEqual(seat, {**seat, "model": MODEL, "revision": "r", "adapter": "a", "prompt": seat["prompt"]})
        self.assertRegex(stamp(SPEC, "model", SimpleNamespace(system="s"))["prompt"], "^[0-9a-f]{12}$")  # ModelSeat: system
        self.assertEqual(stamp(SPEC, "model", SimpleNamespace(model="x"))["model"], "x")  # the seat names its model

    def test_a_direct_run_refuses_a_seed_outside_its_split(self):
        for seat in ("rule", "one_agent"):
            with self.assertRaises(ValueError):
                run_once("r10", seat, SPEC, 2000)  # a test seed in dev
        self.assertTrue(run_once("r10", "one_agent", SPEC, 2000, split="test"))

    def test_rates_move_the_world_but_not_what_the_seat_believes(self):
        for rates in (0.2, 0.5):
            picks = []
            for world in (SPEC, with_rates(SPEC, rates)):
                seat, seen = RuleSeat(SPEC), []
                decide = seat.decide
                seat.decide = lambda obs, d=decide, seen=seen: seen.append(d(obs)) or seen[-1]
                run_once("r10", "rule", SPEC, 1, model=seat, world=world)
                picks.append(seen[0][0]["worker_type"])
            self.assertEqual(picks[0], picks[1], rates)  # at 0.5 the rated medium skill is 0.7: below the bar
        world, seen = with_rates(SPEC, 0.5), []
        with mock.patch("lair.baselines.do_item", side_effect=lambda rng, wtype, item: seen.append(wtype) or {
                "status": "failed", "facts": [], "alarms": [], "spent": {"credits": 4, "seconds": 4}}):
            run_once("r10", "cheapest_that_passes", SPEC, 1, world=world)
        self.assertEqual({(w["credits_per_call"], w["skill"]) for w in seen}, {(4, world["worker_types"][1]["skill"])})

"""Unit tests for tasks."""

import time
import unittest

from lair.tasks import Item, Task, critical_path, grade, make_task


class TasksTest(unittest.TestCase):
    def test_same_seed_same_task(self):
        self.assertEqual(make_task(5, 200), make_task(5, 200))

    def test_different_seeds_differ(self):
        self.assertNotEqual(make_task(1, 200).items, make_task(2, 200).items)

    def test_size_and_kind(self):
        task = make_task(1, 37)
        self.assertEqual(len(task.items), 37)
        self.assertEqual(len({it.key for it in task.items}), 37)
        self.assertTrue(task.can_split)
        self.assertFalse(make_task(1, 37, "no_split").can_split)

    def test_bad_input(self):
        with self.assertRaises(ValueError):
            make_task(1, 0)
        with self.assertRaises(ValueError):
            make_task(1, 5, kind="loop")

    def test_rates_near_targets(self):
        items = make_task(3, 10_000, fault_rate=0.10, alarm_rate=0.03).items
        self.assertAlmostEqual(sum(it.fault for it in items) / 10_000, 0.10, delta=0.02)
        self.assertAlmostEqual(sum(it.alarm for it in items) / 10_000, 0.03, delta=0.015)

    def test_zero_rates(self):
        items = make_task(3, 500, fault_rate=0, alarm_rate=0).items
        self.assertFalse(any(it.fault or it.alarm for it in items))

    def test_table_items_are_independent(self):
        self.assertTrue(all(it.after is None for it in make_task(1, 50).items))

    def test_no_split_chains_every_item(self):
        items = make_task(1, 50, "no_split").items
        self.assertIsNone(items[0].after)
        for prev, it in zip(items, items[1:]):
            self.assertEqual(it.after, prev.key)

    def test_critical_path(self):
        self.assertEqual(critical_path(make_task(1, 40)), 1)
        self.assertEqual(critical_path(make_task(1, 40, "no_split")), 40)

    def test_grade(self):
        task = make_task(1, 10)
        right = {it.key: it.answer for it in task.items}
        self.assertEqual(grade(task, right), 1.0)
        self.assertEqual(grade(task, {}), 0.0)
        half = dict(list(right.items())[:5])
        self.assertEqual(grade(task, half), 0.5)
        half[task.items[9].key] = "wrong"
        self.assertEqual(grade(task, half), 0.5)

    def test_frozen(self):
        item = Item("k0", "a", False, False, None)
        with self.assertRaises(AttributeError):
            item.answer = "b"
        self.assertEqual(Task("t", "table", (item,)).items, (item,))

    def test_big_task_is_fast(self):
        start = time.monotonic()
        task = make_task(1, 103_823, "no_split")
        self.assertEqual(len(task.items), 103_823)
        self.assertEqual(critical_path(task), 103_823)
        self.assertLess(time.monotonic() - start, 5)


if __name__ == "__main__":
    unittest.main()

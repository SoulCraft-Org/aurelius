"""Unit tests for tools/make_viewer_data.py: the viewer's run JSON is deterministic, committed and consistent."""

import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import make_viewer_data  # noqa: E402

JSON = ROOT / "docs" / "viewer" / "run.json"


class MakeViewerDataTest(unittest.TestCase):
    def test_same_json_twice(self):
        self.assertEqual(make_viewer_data.build(), make_viewer_data.build())

    def test_committed_file_is_the_generators_output(self):
        self.assertEqual(JSON.read_text(), make_viewer_data.build())

    def test_every_event_names_a_node_and_time_runs_forward(self):
        data = json.loads(JSON.read_text())
        ids = {n["id"] for n in data["nodes"]}
        self.assertEqual(len(ids), 48)
        self.assertTrue(all(e["node"] in ids for e in data["events"]))
        times = [e["t"] for e in data["events"]]
        self.assertEqual(times, sorted(times))
        self.assertEqual(data["meta"]["label"], "sim")

    def test_page_has_no_outside_link_and_a_still_mode(self):
        page = (ROOT / "docs" / "viewer" / "index.html").read_text()
        self.assertNotIn("src=", page)
        self.assertNotIn("https://", page)
        self.assertIn("prefers-reduced-motion", page)


if __name__ == "__main__":
    unittest.main()

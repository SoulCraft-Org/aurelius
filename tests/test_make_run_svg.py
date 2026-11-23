"""Unit tests for tools/make_run_svg.py: the 4D run art is deterministic, small, committed and safe."""

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import check_files  # noqa: E402
import make_run_svg  # noqa: E402

SVG = ROOT / "docs" / "img" / "run.svg"


class MakeRunSvgTest(unittest.TestCase):
    def test_same_bytes_twice(self):
        self.assertEqual(make_run_svg.build().encode(), make_run_svg.build().encode())

    def test_committed_file_is_the_generators_output(self):
        self.assertEqual(SVG.read_text(), make_run_svg.build())

    def test_size_limit(self):
        self.assertLess(SVG.stat().st_size, 300 * 1024)

    def test_checker_accepts_it(self):
        out = []
        check_files.check_svg(SVG, out)
        self.assertEqual(out, [])

    def test_still_under_reduced_motion_and_no_script(self):
        text = SVG.read_text()
        self.assertIn("prefers-reduced-motion:reduce", text)
        self.assertNotIn("<script", text)
        self.assertNotIn("http", text.replace("http://www.w3.org/2000/svg", ""))

    def test_every_worker_is_drawn_once_and_the_caption_names_the_run(self):
        text = SVG.read_text()
        self.assertEqual(text.count('<circle class="w'), 47)
        self.assertIn("sim run, rule seat, dev seed 0", text)

    def test_a_log_the_seat_cannot_have_made_is_refused(self):
        spend = {"t": 0.0, "kind": "spend", "credits": 1, "seconds": 2}
        log = [spend, spend, {"t": 2.0, "kind": "check", "key": "k0", "tier": 1, "verdict": False}]
        with self.assertRaises(ValueError):
            make_run_svg.calls(log + [{**spend, "t": 4.0}] * 3)


if __name__ == "__main__":
    unittest.main()

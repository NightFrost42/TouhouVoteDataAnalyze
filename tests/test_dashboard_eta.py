from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import unittest


ETA_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts_pipeline"
    / "dashboard"
    / "eta.js"
)


class DashboardEtaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.node = shutil.which("node")
        if cls.node is None:
            raise unittest.SkipTest("Node.js is unavailable")

    def run_javascript(self, source: str) -> None:
        module_path = json.dumps(str(ETA_SCRIPT))
        script = (
            "const assert = require('node:assert/strict');\n"
            f"const eta = require({module_path});\n"
            + source
        )
        result = subprocess.run(
            [self.node, "-e", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_estimate_uses_observed_wall_clock_throughput(self) -> None:
        self.run_javascript(
            """
const estimator = eta.createEstimator({
  minimumSampleSeconds: 5,
  minimumCompletedDelta: 3,
  windowSeconds: 300,
});
let result = estimator.update({
  key: 'run|stage|phase|100', completed: 10, total: 100,
  remaining: 90, running: true, nowMilliseconds: 1000,
});
assert.equal(result.state, 'estimating');
result = estimator.update({
  key: 'run|stage|phase|100', completed: 13, total: 100,
  remaining: 87, running: true, nowMilliseconds: 6000,
});
assert.equal(result.state, 'ready');
assert.equal(result.ratePerSecond, 0.6);
assert.equal(result.seconds, 145);
assert.equal(result.estimatedCompletionMilliseconds, 151000);
"""
        )

    def test_stage_change_pause_and_completion_have_explicit_states(self) -> None:
        self.run_javascript(
            """
const estimator = eta.createEstimator({
  minimumSampleSeconds: 1,
  minimumCompletedDelta: 1,
});
estimator.update({
  key: 'first', completed: 1, total: 10, remaining: 9,
  running: true, nowMilliseconds: 1000,
});
assert.equal(estimator.update({
  key: 'first', completed: 2, total: 10, remaining: 8,
  running: true, nowMilliseconds: 2000,
}).state, 'ready');
assert.equal(estimator.update({
  key: 'second', completed: 2, total: 20, remaining: 18,
  running: true, nowMilliseconds: 3000,
}).state, 'estimating');
assert.equal(estimator.update({
  key: 'second', completed: 2, total: 20, remaining: 18,
  running: false, nowMilliseconds: 4000,
}).state, 'paused');
const complete = estimator.update({
  key: 'second', completed: 20, total: 20, remaining: 0,
  running: false, nowMilliseconds: 5000,
});
assert.equal(complete.state, 'complete');
        assert.equal(complete.seconds, 0);
        """
        )

    def test_default_eta_uses_result_average_without_fixed_five_second_window(self) -> None:
        self.run_javascript(
            """
const estimator = eta.createEstimator();
assert.equal(estimator.update({
  key: 'average', completed: 0, total: 10, remaining: 10,
  running: true, nowMilliseconds: 1000,
}).state, 'estimating');
let result = estimator.update({
  key: 'average', completed: 1, total: 10, remaining: 9,
  running: true, nowMilliseconds: 2500,
});
assert.equal(result.state, 'ready');
assert.equal(result.averageSecondsPerResult, 1.5);
assert.equal(result.seconds, 13.5);
assert.equal(result.sampleCompleted, 1);
"""
        )

    def test_idle_polling_time_is_counted_until_the_next_result(self) -> None:
        self.run_javascript(
            """
const estimator = eta.createEstimator();
estimator.update({ key: 'idle', completed: 0, total: 4, remaining: 4,
  running: true, nowMilliseconds: 1000 });
estimator.update({ key: 'idle', completed: 0, total: 4, remaining: 4,
  running: true, nowMilliseconds: 5000 });
const result = estimator.update({ key: 'idle', completed: 1, total: 4, remaining: 3,
  running: true, nowMilliseconds: 6000 });
assert.equal(result.state, 'ready');
assert.equal(result.averageSecondsPerResult, 5);
"""
        )

    def test_default_eta_uses_only_five_most_recent_completion_intervals(self) -> None:
        self.run_javascript(
            """
const estimator = eta.createEstimator();
estimator.update({ key: 'recent', completed: 0, total: 100, remaining: 100,
  running: true, nowMilliseconds: 0 });
// Two old, slow intervals must be discarded once five newer samples exist.
estimator.update({ key: 'recent', completed: 1, total: 100, remaining: 99,
  running: true, nowMilliseconds: 10000 });
estimator.update({ key: 'recent', completed: 2, total: 100, remaining: 98,
  running: true, nowMilliseconds: 20000 });
let result;
for (let completed = 3; completed <= 7; completed += 1) {
  result = estimator.update({
    key: 'recent', completed, total: 100, remaining: 100 - completed,
    running: true, nowMilliseconds: 20000 + (completed - 2) * 1000,
  });
}
assert.equal(result.state, 'ready');
assert.equal(result.sampleCount, 5);
assert.equal(result.sampleCompleted, 5);
assert.equal(result.sampleSeconds, 5);
assert.equal(result.ratePerSecond, 1);
assert.equal(result.seconds, 93);
"""
        )

    def test_duration_formatting_is_bounded_and_readable(self) -> None:
        self.run_javascript(
            """
assert.equal(eta.formatDuration(9.6), '10 秒');
assert.equal(eta.formatDuration(60), '1 分钟');
assert.equal(eta.formatDuration(125), '2 分 5 秒');
assert.equal(eta.formatDuration(7380), '2 小时 3 分');
assert.equal(eta.formatDuration(180000), '2 天 2 小时');
assert.equal(eta.formatDuration(Number.POSITIVE_INFINITY), '—');
"""
        )


if __name__ == "__main__":
    unittest.main()

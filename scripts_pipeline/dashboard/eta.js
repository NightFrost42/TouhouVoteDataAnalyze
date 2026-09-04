(function exposeCrawlEta(root, factory) {
  "use strict";

  const api = factory();
  if (typeof module === "object" && module && module.exports) {
    module.exports = api;
  } else {
    root.CrawlEta = api;
  }
}(typeof globalThis !== "undefined" ? globalThis : this, () => {
  "use strict";

  // ETA follows only the most recent completed-result intervals.  Old slow
  // or fast operating points must age out quickly after adaptive speed has
  // changed; using the full run average makes the displayed ETA lag badly.
  const DEFAULT_MINIMUM_SAMPLE_SECONDS = 0;
  const DEFAULT_MINIMUM_COMPLETED_DELTA = 1;
  const DEFAULT_MINIMUM_SEGMENTS = 1;
  const DEFAULT_WINDOW_SECONDS = 300;
  const DEFAULT_MAX_SEGMENTS = 5;

  function finiteNumber(value) {
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  }

  function positiveOption(value, fallback) {
    const numeric = finiteNumber(value);
    return numeric !== null && numeric > 0 ? numeric : fallback;
  }

  function nonNegativeOption(value, fallback) {
    const numeric = finiteNumber(value);
    return numeric !== null && numeric >= 0 ? numeric : fallback;
  }

  function createEstimator(options = {}) {
    const minimumSampleSeconds = nonNegativeOption(
      options.minimumSampleSeconds,
      DEFAULT_MINIMUM_SAMPLE_SECONDS,
    );
    const minimumCompletedDelta = positiveOption(
      options.minimumCompletedDelta,
      DEFAULT_MINIMUM_COMPLETED_DELTA,
    );
    const minimumSegments = Math.max(1, Math.floor(positiveOption(
      options.minimumSegments,
      DEFAULT_MINIMUM_SEGMENTS,
    )));
    const windowMilliseconds = 1000 * positiveOption(
      options.windowSeconds,
      DEFAULT_WINDOW_SECONDS,
    );
    const maxSegments = Math.max(2, Math.floor(positiveOption(
      options.maxSegments,
      DEFAULT_MAX_SEGMENTS,
    )));

    let activeKey = null;
    let observations = [];
    let segments = [];

    function reset(nextKey = null) {
      activeKey = nextKey;
      observations = [];
      segments = [];
    }

    function update(input = {}) {
      const completed = finiteNumber(input.completed);
      const total = finiteNumber(input.total);
      const suppliedRemaining = finiteNumber(input.remaining);
      const nowMilliseconds = finiteNumber(input.nowMilliseconds) ?? Date.now();
      const key = String(input.key ?? "");
      const remaining = suppliedRemaining !== null
        ? Math.max(0, suppliedRemaining)
        : completed !== null && total !== null
          ? Math.max(0, total - completed)
          : null;

      if (completed === null || total === null || total <= 0 || remaining === null) {
        reset();
        return { state: "unavailable", reason: "missing_progress" };
      }
      if (remaining <= 0 || completed >= total) {
        reset(key);
        return {
          state: "complete",
          seconds: 0,
          ratePerSecond: null,
          sampleSeconds: 0,
          sampleCompleted: 0,
          estimatedCompletionMilliseconds: nowMilliseconds,
        };
      }
      if (!input.running) {
        // Do not charge an operator pause to the next request.  Keep the
        // completed-result segments, but restart the timing baseline when the
        // stage resumes.
        observations = completed === null
          ? []
          : [{ time: nowMilliseconds, completed }];
        return { state: "paused", reason: "not_running" };
      }

      const lastObservation = observations.length
        ? observations[observations.length - 1]
        : null;
      if (
        key !== activeKey
        || (lastObservation && completed < lastObservation.completed)
        || (lastObservation && nowMilliseconds < lastObservation.time)
      ) {
        reset(key);
      }

      const current = { time: nowMilliseconds, completed };
      const currentLast = observations.length
        ? observations[observations.length - 1]
        : null;
      if (currentLast && completed > currentLast.completed) {
        const elapsedSeconds = (nowMilliseconds - currentLast.time) / 1000;
        const completedDelta = completed - currentLast.completed;
        if (elapsedSeconds > 0 && completedDelta > 0) {
          segments.push({ elapsedSeconds, completedDelta });
        }
        observations.push(current);
      } else if (currentLast && currentLast.time === nowMilliseconds) {
        observations[observations.length - 1] = current;
      } else if (!currentLast) {
        observations.push(current);
      } else if (completed === currentLast.completed) {
        // Keep the timestamp of the last completed result.  A long period
        // with no new result is real work (often one slow 504-prone query),
        // and must contribute to the average seconds per result.
      }

      const cutoff = nowMilliseconds - windowMilliseconds;
      while (observations.length > 2 && observations[1].time < cutoff) {
        observations.shift();
        if (segments.length > 0) segments.shift();
      }
      if (segments.length > maxSegments) {
        segments = segments.slice(-maxSegments);
      }

      const sampleSeconds = segments.reduce(
        (sum, segment) => sum + segment.elapsedSeconds,
        0,
      );
      const sampleCompleted = segments.reduce(
        (sum, segment) => sum + segment.completedDelta,
        0,
      );
      if (
        sampleSeconds < minimumSampleSeconds
        || sampleCompleted < minimumCompletedDelta
        || segments.length < minimumSegments
      ) {
        return {
          state: "estimating",
          reason: segments.length < minimumSegments
            ? "no_result_sample"
            : sampleSeconds < minimumSampleSeconds
            ? "short_sample"
            : "no_progress_sample",
          sampleSeconds,
          sampleCompleted,
          sampleCount: segments.length,
        };
      }

      const ratePerSecond = sampleCompleted / sampleSeconds;
      const seconds = remaining / ratePerSecond;
      if (!Number.isFinite(ratePerSecond) || ratePerSecond <= 0 || !Number.isFinite(seconds)) {
        return {
          state: "estimating",
          reason: "invalid_rate",
          sampleSeconds,
          sampleCompleted,
          sampleCount: segments.length,
        };
      }
      return {
        state: "ready",
        seconds,
        ratePerSecond,
        averageSecondsPerResult: sampleSeconds / sampleCompleted,
        sampleSeconds,
        sampleCompleted,
        sampleCount: segments.length,
        estimatedCompletionMilliseconds: nowMilliseconds + seconds * 1000,
      };
    }

    return Object.freeze({ reset, update });
  }

  function formatDuration(value) {
    const numeric = finiteNumber(value);
    if (numeric === null || numeric < 0) {
      return "—";
    }
    const seconds = Math.max(0, Math.round(numeric));
    if (seconds < 60) {
      return `${seconds} 秒`;
    }
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    if (minutes < 60) {
      return remainingSeconds > 0
        ? `${minutes} 分 ${remainingSeconds} 秒`
        : `${minutes} 分钟`;
    }
    const hours = Math.floor(minutes / 60);
    const remainingMinutes = minutes % 60;
    if (hours < 24) {
      return remainingMinutes > 0
        ? `${hours} 小时 ${remainingMinutes} 分`
        : `${hours} 小时`;
    }
    const days = Math.floor(hours / 24);
    const remainingHours = hours % 24;
    return remainingHours > 0
      ? `${days} 天 ${remainingHours} 小时`
      : `${days} 天`;
  }

  return Object.freeze({ createEstimator, formatDuration });
}));

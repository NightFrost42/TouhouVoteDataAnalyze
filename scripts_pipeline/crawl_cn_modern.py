"""Reproducibly archive the public result data for touhou.vote rounds 10/11.

Only read-only, aggregate result queries are used.  In particular, this
crawler never calls vote-token endpoints and never requests character, music,
CP, or doujin recommendation/reason text.  The official JavaScript/source-map
files are retained verbatim as provenance; parsed analytical outputs exclude
those reason fields.

The crawler is deliberately standard-library-only apart from invoking Node.js
to evaluate the questionnaire's JavaScript object literal recovered from the
official source map.  Every network result is written atomically.  Re-running
with ``--resume`` validates and skips completed checkpoints.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence


ENDPOINT = "https://touhou.vote/res-be/graphql"
USER_AGENT = "TouhouVoteDataAudit/1.0 (+public aggregate archive)"
WORKSPACE = Path(__file__).resolve().parents[1]
DATA_ROOT = WORKSPACE / "data_raw" / "cn_official"
METADATA_ROOT = WORKSPACE / "metadata"
ADAPTIVE_PROFILE_JSON = METADATA_ROOT / "cn_modern_adaptive_profiles.json"

# Keep the modern crawler on the same bounded adaptive-speed policy as the
# CN5--9 advanced/related-questionnaire crawler.  The ceilings are user
# configurable, while these absolute rails protect the public endpoint from a
# malformed queue file or an accidental high-concurrency invocation.
DEFAULT_WORKER_CEILING = 10
DEFAULT_REQUEST_LIMIT_CEILING = 30
DEFAULT_BATCH_PAUSE_CEILING = 3.0
ABSOLUTE_MAX_WORKERS = 32
ABSOLUTE_MAX_REQUEST_LIMIT = 300
ABSOLUTE_MAX_BATCH_PAUSE = 60.0
ADAPTIVE_MIN_PAUSE = 0.25
ADAPTIVE_SUCCESS_WINDOW = 20
ADAPTIVE_HEALTHY_DWELL_SECONDS = 30.0
ADAPTIVE_STEP_SECONDS = 0.25
ADAPTIVE_FAILURE_STEP_SECONDS = 0.5
ADAPTIVE_FAILED_PAUSE_PROBE_LOCK_SECONDS = 300.0
DEFAULT_ADAPTIVE_FAILURE_THRESHOLD = 3
ADAPTIVE_FAILURE_EVIDENCE_CLEAR_SUCCESSES = ADAPTIVE_SUCCESS_WINDOW
TRANSIENT_HTTP_STATUSES = {
    # 403 is included because the public site/WAF occasionally uses it for
    # temporary rate limiting; the legacy CN5--9 crawler treats it the same
    # way and applies a recovery gate before probing again.
    403, 408, 425, 429, 500, 502, 503, 504, 521, 522, 523, 524,
}


@dataclasses.dataclass(frozen=True)
class RoundConfig:
    number: int
    vote_start: str
    index_js: str
    questionnaire_js: str
    doujin_js: str

    @property
    def base_url(self) -> str:
        return f"https://touhou.vote/v{self.number}/"

    @property
    def root(self) -> Path:
        return DATA_ROOT / f"round_{self.number}"


ROUNDS: dict[int, RoundConfig] = {
    10: RoundConfig(
        number=10,
        vote_start="2022-06-17T10:00:00.000Z",
        index_js="index-6eea312f.js",
        questionnaire_js="questionnaire-5ec436a8.js",
        doujin_js="Doujin-63a8c5a8.js",
    ),
    11: RoundConfig(
        number=11,
        vote_start="2023-12-29T10:00:00.000Z",
        index_js="index-c1d6c5d6.js",
        questionnaire_js="questionnaire-b69f5aad.js",
        doujin_js="Doujin-f64f63b8.js",
    ),
}


RANKING_GLOBAL_FIELDS = """
totalUniqueItems totalFirst totalVotes averageVotesPerItem medianVotesPerItem
"""

GLOBAL_FIELDS = """
voteYear numVote numChar numMusic numCp numDoujin numMale numFemale
"""

CHARACTER_FIELDS = """
rank displayRank name voteCount firstVoteCount
firstVotePercentage firstVoteCountWeighted votePercentage firstPercentage
maleVoteCount malePercentagePerChar malePercentagePerTotal
femaleVoteCount femalePercentagePerChar femalePercentagePerTotal
nameJpn characterType characterOrigin firstAppearance
"""

MUSIC_FIELDS = """
rank displayRank name voteCount firstVoteCount
firstVotePercentage firstVoteCountWeighted votePercentage firstPercentage
maleVoteCount malePercentagePerChar malePercentagePerTotal
femaleVoteCount femalePercentagePerChar femalePercentagePerTotal
album nameJpn firstAppearance
"""

CP_FIELDS = """
rank displayRank cp { a b c }
aActive bActive cActive noneActive
voteCount firstVoteCount firstVotePercentage firstVoteCountWeighted
votePercentage firstPercentage
maleVoteCount malePercentagePerChar malePercentagePerTotal
femaleVoteCount femalePercentagePerChar femalePercentagePerTotal
"""

BASE_QUERY = f"""
query CompleteRound($voteStart: DateTimeUtc!, $voteYear: Int!) {{
  queryGlobalStats(voteStart: $voteStart, voteYear: $voteYear) {{
    {GLOBAL_FIELDS}
  }}
  queryCharacterRanking(voteStart: $voteStart, voteYear: $voteYear) {{
    global {{ {RANKING_GLOBAL_FIELDS} }}
    entries {{ {CHARACTER_FIELDS} }}
  }}
  queryMusicRanking(voteStart: $voteStart, voteYear: $voteYear) {{
    global {{ {RANKING_GLOBAL_FIELDS} }}
    entries {{ {MUSIC_FIELDS} }}
  }}
  queryCPRanking(voteStart: $voteStart, voteYear: $voteYear) {{
    global {{ {RANKING_GLOBAL_FIELDS} }}
    entries {{ {CP_FIELDS} }}
  }}
}}
"""

QUESTIONNAIRE_CATEGORICAL_QUERY = """
query QuestionnaireCategorical(
  $voteStart: DateTimeUtc!
  $voteYear: Int!
  $questionsOfInterest: [String!]!
) {
  queryQuestionnaire(
    voteStart: $voteStart
    voteYear: $voteYear
    questionsOfInterest: $questionsOfInterest
  ) {
    entries {
      questionId
      answersCat { aid totalVotes maleVotes femaleVotes }
      totalAnswers totalMale totalFemale
    }
  }
  queryCompletionRates(voteStart: $voteStart, voteYear: $voteYear) {
    voteYear
    items { name rate numComplete total }
  }
}
"""

QUESTIONNAIRE_OPEN_QUERY = """
query QuestionnaireOpen(
  $voteStart: DateTimeUtc!
  $voteYear: Int!
  $questionsOfInterest: [String!]!
) {
  queryQuestionnaire(
    voteStart: $voteStart
    voteYear: $voteYear
    questionsOfInterest: $questionsOfInterest
  ) {
    entries {
      questionId answersStr totalAnswers totalMale totalFemale
    }
  }
}
"""

QUESTIONNAIRE_TREND_QUERY = f"""
query QuestionnaireTrend(
  $voteStart: DateTimeUtc!
  $voteYear: Int!
  $questionIds: [String!]!
) {{
  queryGlobalStats(voteStart: $voteStart, voteYear: $voteYear) {{
    {GLOBAL_FIELDS}
  }}
  queryQuestionnaireTrend(
    voteStart: $voteStart
    voteYear: $voteYear
    questionIds: $questionIds
  ) {{
    trend {{ hrs cnt }}
    trendFirst {{ hrs cnt }}
  }}
}}
"""

CONDITION_QUERY = f"""
query OptionCondition(
  $query: String
  $voteStart: DateTimeUtc!
  $voteYear: Int!
) {{
  queryGlobalStats(query: $query, voteStart: $voteStart, voteYear: $voteYear) {{
    {GLOBAL_FIELDS}
  }}
  queryCharacterRanking(query: $query, voteStart: $voteStart, voteYear: $voteYear) {{
    global {{ {RANKING_GLOBAL_FIELDS} }}
    entries {{ rank displayRank name voteCount firstVoteCount }}
  }}
  queryMusicRanking(query: $query, voteStart: $voteStart, voteYear: $voteYear) {{
    global {{ {RANKING_GLOBAL_FIELDS} }}
    entries {{ rank displayRank name voteCount firstVoteCount }}
  }}
  queryCPRanking(query: $query, voteStart: $voteStart, voteYear: $voteYear) {{
    global {{ {RANKING_GLOBAL_FIELDS} }}
    entries {{ rank displayRank cp {{ a b c }} voteCount firstVoteCount }}
  }}
}}
"""

CHARACTER_COVOTE_QUERY = """
query CharacterCovote(
  $voteStart: DateTimeUtc!
  $voteYear: Int!
  $topK: Int!
) {
  queryCharsCovote(voteStart: $voteStart, voteYear: $voteYear, topK: $topK) {
    items { a b cs mi cv m00 m01 m10 m11 }
  }
}
"""

MUSIC_COVOTE_QUERY = """
query MusicCovote(
  $voteStart: DateTimeUtc!
  $voteYear: Int!
  $topK: Int!
) {
  queryMusicsCovote(voteStart: $voteStart, voteYear: $voteYear, topK: $topK) {
    items { a b cs mi cv m00 m01 m10 m11 }
  }
}
"""

# Some historical rounds contain NULL values in one or more server-computed
# association fields (cs/mi/cv).  The GraphQL service currently serializes
# those NULLs as non-nullable floats and rejects the whole response.  The four
# contingency-table cells are sufficient to reproduce every association
# metric locally, so keep a count-only fallback instead of treating the public
# matrix as unavailable.
CHARACTER_COVOTE_COUNTS_QUERY = """
query CharacterCovoteCounts(
  $voteStart: DateTimeUtc!
  $voteYear: Int!
  $topK: Int!
) {
  queryCharsCovote(voteStart: $voteStart, voteYear: $voteYear, topK: $topK) {
    items { a b m00 m01 m10 m11 }
  }
}
"""

MUSIC_COVOTE_COUNTS_QUERY = """
query MusicCovoteCounts(
  $voteStart: DateTimeUtc!
  $voteYear: Int!
  $topK: Int!
) {
  queryMusicsCovote(voteStart: $voteStart, voteYear: $voteYear, topK: $topK) {
    items { a b m00 m01 m10 m11 }
  }
}
"""

# The historical all-pairs endpoints currently fail for rounds 10/11 because
# at least one internally computed floating-point field is NULL and the
# upstream service attempts to deserialize it as a non-nullable ``f64`` before
# GraphQL field selection is applied.  Conditional ranking queries are an
# independent public interface and return the exact co-selection count for one
# source item against every ranked item.  They therefore provide a lossless,
# auditable fallback for reconstructing the four contingency cells.
CHARACTER_COVOTE_CONDITIONAL_QUERY = """
query CharacterCovoteConditionalSource(
  $query: String!
  $voteStart: DateTimeUtc!
  $voteYear: Int!
) {
  queryCharacterRanking(query: $query, voteStart: $voteStart, voteYear: $voteYear) {
    global { totalUniqueItems totalFirst totalVotes }
    entries { name voteCount firstVoteCount }
  }
}
"""

MUSIC_COVOTE_CONDITIONAL_QUERY = """
query MusicCovoteConditionalSource(
  $query: String!
  $voteStart: DateTimeUtc!
  $voteYear: Int!
) {
  queryMusicRanking(query: $query, voteStart: $voteStart, voteYear: $voteYear) {
    global { totalUniqueItems totalFirst totalVotes }
    entries { name voteCount firstVoteCount }
  }
}
"""

QUERY_DOCUMENTS: dict[str, str] = {
    "CompleteRound": BASE_QUERY,
    "QuestionnaireCategorical": QUESTIONNAIRE_CATEGORICAL_QUERY,
    "QuestionnaireOpen": QUESTIONNAIRE_OPEN_QUERY,
    "QuestionnaireTrend": QUESTIONNAIRE_TREND_QUERY,
    "OptionCondition": CONDITION_QUERY,
    "CharacterCovote": CHARACTER_COVOTE_QUERY,
    "MusicCovote": MUSIC_COVOTE_QUERY,
    "CharacterCovoteCounts": CHARACTER_COVOTE_COUNTS_QUERY,
    "MusicCovoteCounts": MUSIC_COVOTE_COUNTS_QUERY,
    "CharacterCovoteConditionalSource": CHARACTER_COVOTE_CONDITIONAL_QUERY,
    "MusicCovoteConditionalSource": MUSIC_COVOTE_CONDITIONAL_QUERY,
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: Path, value: Any, *, pretty: bool = False) -> None:
    if pretty:
        text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    else:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    atomic_write_bytes(path, text.encode("utf-8"))


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def chunks(items: Sequence[str], size: int) -> Iterable[list[str]]:
    for offset in range(0, len(items), size):
        yield list(items[offset : offset + size])


class RateLimiter:
    """Limit starts of all requests, including across condition workers."""

    def __init__(self, delay: float) -> None:
        self.delay = max(0.0, delay)
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait_for = max(0.0, self._next - now)
            self._next = max(now, self._next) + self.delay
        if wait_for:
            time.sleep(wait_for)


def transient_failure_reason(exc: BaseException) -> str | None:
    """Return a compact reason for an upstream/transport failure."""

    if isinstance(exc, urllib.error.HTTPError):
        status = int(exc.code)
        return f"HTTP {status}" if status in TRANSIENT_HTTP_STATUSES else None
    if isinstance(exc, urllib.error.URLError):
        return f"network: {exc.reason}"
    if isinstance(exc, (TimeoutError, ConnectionError, BrokenPipeError)):
        return f"network: {type(exc).__name__}"
    if isinstance(exc, RuntimeError):
        # The GraphQL gateway can answer HTTP 200 while its result-query
        # upstream closes an empty/partial body.  These application-level
        # errors are transient just like a 502/504 and must participate in
        # retry + adaptive downshift rather than opening a circuit after one
        # cell.  Keep the match narrow so semantic resolver errors remain
        # ordinary (non-transient) validation failures.
        message = str(exc)
        if any(
            marker in message
            for marker in (
                "JSON_DECODE_ERROR",
                "EOF while parsing",
                "response was not JSON",
            )
        ):
            return "graphql: upstream decode"
    return None


class AdaptiveSpeed:
    """Thread-safe AIMD-style request pacing shared by modern crawl stages.

    ``workers`` is the starting concurrency and ``pause`` is the minimum
    interval between real HTTP starts.  Confirmed groups of transient errors
    slow one dimension at a time; a sustained healthy window raises one worker
    or lowers the interval by 250 ms.  A failed lower-pause probe rolls back to
    its last stable value and is locked for several minutes so an unstable
    endpoint cannot make the cooldown oscillate continuously.
    """

    def __init__(
        self,
        *,
        workers: int = 1,
        request_limit: int = DEFAULT_REQUEST_LIMIT_CEILING,
        pause: float = 0.5,
        worker_ceiling: int | None = None,
        request_limit_ceiling: int | None = None,
        pause_ceiling: float | None = None,
        failure_threshold: int = DEFAULT_ADAPTIVE_FAILURE_THRESHOLD,
        adaptive_tuning: bool = True,
        stage_id: str | None = None,
        profile_path: Path | None = ADAPTIVE_PROFILE_JSON,
    ) -> None:
        # When no explicit rail is supplied, retain historical starting values
        # (for example a manually chosen ``--delay 6``) instead of rejecting
        # them merely because the new default rail is lower.
        self.worker_ceiling = self._bounded_int(
            worker_ceiling,
            max(DEFAULT_WORKER_CEILING, int(workers)),
            ABSOLUTE_MAX_WORKERS,
        )
        self.request_limit_ceiling = self._bounded_int(
            request_limit_ceiling,
            max(DEFAULT_REQUEST_LIMIT_CEILING, int(request_limit)),
            ABSOLUTE_MAX_REQUEST_LIMIT,
        )
        self.pause_ceiling = self._bounded_float(
            pause_ceiling,
            max(DEFAULT_BATCH_PAUSE_CEILING, float(pause)),
            ABSOLUTE_MAX_BATCH_PAUSE,
        )
        if not 1 <= int(workers) <= self.worker_ceiling:
            raise ValueError(
                f"workers must be between 1 and configured worker ceiling {self.worker_ceiling}"
            )
        if not 1 <= int(request_limit) <= self.request_limit_ceiling:
            raise ValueError(
                "request_limit must be between 1 and configured request-limit ceiling "
                f"{self.request_limit_ceiling}"
            )
        if not 0 <= float(pause) <= self.pause_ceiling:
            raise ValueError(
                f"pause must be between 0 and configured pause ceiling {self.pause_ceiling:g}"
            )
        self.configured_workers = int(workers)
        self.configured_request_limit = int(request_limit)
        self.configured_pause = float(pause)
        self.failure_threshold = max(1, int(failure_threshold))
        self.adaptive_tuning = bool(adaptive_tuning)
        self.workers = int(workers)
        self.request_limit = int(request_limit)
        self.pause = float(pause)
        self.safe_worker_ceiling = self.worker_ceiling
        self.safe_pause_floor = min(ADAPTIVE_MIN_PAUSE, self.pause_ceiling)
        # A configured worker count is the starting point; healthy traffic may
        # explore upward immediately.  Start the pause probe at the configured
        # interval, however, so the controller changes only one speed dimension
        # per healthy window and does not jump both concurrency and pacing.
        self.pause = max(self.pause, self.safe_pause_floor)
        self.success_streak = 0
        self.healthy_since: float | None = None
        self.epoch = 0
        self.failure_epoch: int | None = None
        # A couple of isolated upstream blips are expected on the public
        # endpoint.  Keep them as recent evidence, but do not change speed
        # until the configured number of distinct logical requests has seen
        # a transient failure.  A healthy window clears stale evidence.
        self.pending_transient_failures = 0
        self.failure_evidence_clean_successes = 0
        self.next_increase_at = time.monotonic() + ADAPTIVE_HEALTHY_DWELL_SECONDS
        self.pause_rollback = 0.0
        self.pause_probe_blocked_until = 0.0
        self.adjustments = 0
        self.stage_id = str(stage_id or os.environ.get("DATA_CRAWL_QUEUE_STAGE_ID", "")).strip()
        self._phase = ""
        self.profile_path = profile_path
        self._lock = threading.RLock()
        self._request_lock = threading.Lock()
        self._last_request_start: float | None = None
        self._request_count = 0
        self._batch_started = 0
        self._restore_profile()
        if not self.adaptive_tuning:
            # A disabled adaptive policy must ignore any learned profile from
            # earlier runs.  Keep the fixed values requested by the queue/UI,
            # while retaining the normal request gate and retry behaviour.
            self.workers = self.configured_workers
            self.request_limit = self.configured_request_limit
            self.safe_worker_ceiling = self.worker_ceiling
            self.safe_pause_floor = min(ADAPTIVE_MIN_PAUSE, self.pause_ceiling)
            self.pause = self.configured_pause
            self.success_streak = 0
            self.healthy_since = None
            self.failure_epoch = None
            self.pending_transient_failures = 0
            self.failure_evidence_clean_successes = 0
            self.pause_rollback = 0.0
            self.pause_probe_blocked_until = 0.0

    @staticmethod
    def _bounded_int(value: int | None, default: int, absolute: int) -> int:
        try:
            number = int(default if value is None else value)
        except (TypeError, ValueError):
            number = default
        return max(1, min(absolute, number))

    @staticmethod
    def _bounded_float(value: float | None, default: float, absolute: float) -> float:
        try:
            number = float(default if value is None else value)
        except (TypeError, ValueError):
            number = default
        if number != number or number in (float("inf"), float("-inf")):
            number = default
        return max(0.0, min(absolute, number))

    def _restore_profile(self) -> None:
        if not self.stage_id or self.profile_path is None or not self.profile_path.is_file():
            return
        try:
            value = load_json(self.profile_path)
            stages = value.get("stages", value) if isinstance(value, dict) else {}
            candidate = stages.get(self.stage_id) if isinstance(stages, dict) else None
            if not isinstance(candidate, dict):
                return
            restored_workers = int(candidate.get("adaptive_workers", self.workers))
            restored_pause = float(candidate.get("adaptive_pause_seconds", self.pause))
            restored_pause_rollback = float(
                candidate.get("adaptive_pause_rollback", 0.0)
            )
            restored_safe_workers = int(
                candidate.get("adaptive_safe_worker_ceiling", self.safe_worker_ceiling)
            )
            restored_safe_pause = float(
                candidate.get("adaptive_safe_pause_floor", self.safe_pause_floor)
            )
            self.safe_worker_ceiling = max(
                self.configured_workers,
                min(self.worker_ceiling, restored_safe_workers),
            )
            normal_floor = min(ADAPTIVE_MIN_PAUSE, self.pause_ceiling)
            default_pause = max(normal_floor, self.configured_pause)
            self.workers = max(
                self.configured_workers,
                min(self.safe_worker_ceiling, restored_workers),
            )
            # Normalize profiles written by the older two-dimensional
            # downshift policy onto the staged ladder.  Cooldown may exceed
            # the configured default only after workers have reached their
            # configured default; it remains bounded by the pause guardrail.
            restored_pause_ceiling = (
                default_pause
                if self.workers > self.configured_workers
                else self.pause_ceiling
            )
            self.safe_pause_floor = max(
                normal_floor,
                min(restored_pause_ceiling, max(0.0, restored_safe_pause)),
            )
            self.pause = max(
                self.safe_pause_floor,
                min(
                    restored_pause_ceiling,
                    max(0.0, restored_pause, restored_pause_rollback),
                ),
            )
            # Never resume an unconfirmed faster-cooldown probe after a
            # restart.  Resume from its last stable rollback value instead,
            # while keeping any recently learned probe lock.
            self.pause_rollback = 0.0
            wall_now = time.time()
            restored_probe_block = float(
                candidate.get("adaptive_pause_probe_blocked_until_unix", 0.0)
            )
            self.pause_probe_blocked_until = max(
                0.0,
                min(
                    restored_probe_block,
                    wall_now + ADAPTIVE_FAILED_PAUSE_PROBE_LOCK_SECONDS,
                ),
            )
            self.success_streak = 0
            self.pending_transient_failures = max(
                0,
                min(
                    self.failure_threshold - 1,
                    int(candidate.get("pending_transient_failures", 0)),
                ),
            )
            self.failure_evidence_clean_successes = max(
                0,
                min(
                    ADAPTIVE_FAILURE_EVIDENCE_CLEAR_SUCCESSES - 1,
                    int(candidate.get("failure_evidence_clean_successes", 0)),
                ),
            )
            self.next_increase_at = time.monotonic() + ADAPTIVE_HEALTHY_DWELL_SECONDS
            self.failure_epoch = self.epoch if (
                self.safe_worker_ceiling < self.worker_ceiling
                or self.safe_pause_floor > ADAPTIVE_MIN_PAUSE + 1e-9
            ) else None
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return

    def _persist_profile(self) -> None:
        if not self.stage_id or self.profile_path is None:
            return
        try:
            current = load_json(self.profile_path) if self.profile_path.is_file() else {}
            stages = current.get("stages", current) if isinstance(current, dict) else {}
            if not isinstance(stages, dict):
                stages = {}
            stages = dict(stages)
            stages[self.stage_id] = {
                "adaptive_workers": int(self.workers),
                "adaptive_pause_seconds": float(self.pause),
                "adaptive_safe_worker_ceiling": int(self.safe_worker_ceiling),
                "adaptive_safe_pause_floor": float(self.safe_pause_floor),
                "pending_transient_failures": int(self.pending_transient_failures),
                "failure_evidence_clean_successes": int(
                    self.failure_evidence_clean_successes
                ),
                "failure_threshold": int(self.failure_threshold),
                "adaptive_pause_rollback": float(self.pause_rollback),
                "adaptive_pause_probe_blocked_until_unix": float(
                    self.pause_probe_blocked_until
                ),
                "worker_ceiling": int(self.worker_ceiling),
                "pause_ceiling": float(self.pause_ceiling),
                "updated_at": utc_now(),
            }
            payload = {"schemaVersion": 1, "stages": stages}
            atomic_write_json(self.profile_path, payload, pretty=True)
        except (OSError, TypeError, ValueError):
            # A speed profile is an optimisation only; never fail a data crawl
            # because the optional metadata file cannot be written.
            return

    def set_phase(self, phase: str) -> None:
        """Update the content label without restarting speed exploration.

        All content lists in one modern crawl stage use the same public
        endpoint and therefore share one continuous controller.  Switching
        from conditions to questionnaire pairs (or between round partitions)
        must not reset workers, cooldown, failure evidence, healthy dwell, or
        the cooldown probe; otherwise every short/cached list makes the long
        active list relearn the same speed.
        """

        with self._lock:
            phase = str(phase or "").strip()
            if self._phase == phase:
                return
            self._phase = phase

    def request_start(self) -> int:
        """Wait for the current adaptive interval and return its controller epoch."""

        with self._request_lock:
            with self._lock:
                pause = max(0.0, float(self.pause))
                now = time.monotonic()
                wait_for = (
                    max(0.0, float(self._last_request_start) + pause - now)
                    if self._last_request_start is not None
                    else 0.0
                )
                # ``request_limit`` is the same bounded window used by the
                # CN5--9 crawler: after a window of starts, add one shared
                # cooldown before admitting the next request.
                if self._batch_started >= self.request_limit:
                    # ``pause`` is also the minimum inter-start interval.  A
                    # completed request window adds one *additional* pause,
                    # so request_limit remains meaningful even when requests
                    # are already evenly spaced by the gate above.
                    wait_for = max(wait_for, pause) + pause
                    self._batch_started = 0
                self._last_request_start = now + wait_for
                epoch = self.epoch
            if wait_for:
                time.sleep(wait_for)
            with self._lock:
                self._request_count += 1
                self._batch_started += 1
            return epoch

    def observe(
        self,
        *,
        ok: bool,
        transient: bool = False,
        recovered: bool = False,
        request_epoch: int | None = None,
    ) -> None:
        with self._lock:
            if not self.adaptive_tuning:
                return
            observed = self.epoch if request_epoch is None else int(request_epoch)
            if observed != self.epoch:
                return
            now = time.monotonic()
            wall_now = time.time()
            if transient:
                self.success_streak = 0
                self.healthy_since = None
                self.failure_evidence_clean_successes = 0
                self.pending_transient_failures += 1
                self.next_increase_at = max(
                    self.next_increase_at,
                    now + ADAPTIVE_HEALTHY_DWELL_SECONDS,
                )
                # Isolated failures are recorded but intentionally tolerated.
                # They expire after a healthy success window below, so a few
                # unrelated blips cannot accumulate forever.
                if self.pending_transient_failures < self.failure_threshold:
                    self._persist_profile()
                    return
                self.pending_transient_failures = 0
                self.failure_epoch = observed
                changed = False
                # Walk a three-part slowdown ladder, one dimension per
                # confirmed failure group:
                #   1. raise cooldown to its configured default;
                #   2. lower explored workers to their configured default;
                #   3. only then raise cooldown above default, up to its rail.
                normal_floor = min(ADAPTIVE_MIN_PAUSE, self.pause_ceiling)
                default_pause = max(normal_floor, self.configured_pause)
                if self.pause_rollback > self.pause + 1e-9:
                    # This operating point was an explicit lower-cooldown
                    # probe.  Roll back to its last stable value and prevent
                    # the same probe from being retried after one short healthy
                    # window.  The lock belongs to the controller, not a
                    # content label, so set_phase() cannot reset it.
                    self.pause = min(self.pause_ceiling, self.pause_rollback)
                    self.safe_pause_floor = max(normal_floor, self.pause)
                    self.pause_rollback = 0.0
                    self.pause_probe_blocked_until = max(
                        self.pause_probe_blocked_until,
                        wall_now + ADAPTIVE_FAILED_PAUSE_PROBE_LOCK_SECONDS,
                    )
                    changed = True
                elif self.pause + 1e-9 < default_pause:
                    self.pause = min(
                        default_pause,
                        self.pause + ADAPTIVE_FAILURE_STEP_SECONDS,
                    )
                    self.safe_pause_floor = max(self.safe_pause_floor, self.pause)
                    # Even a probe that survived its first healthy window can
                    # later prove unstable.  Any confirmed failure group below
                    # the configured default therefore locks further
                    # lower-pause probing, not only failures caught while the
                    # explicit rollback marker is still active.
                    self.pause_probe_blocked_until = max(
                        self.pause_probe_blocked_until,
                        wall_now + ADAPTIVE_FAILED_PAUSE_PROBE_LOCK_SECONDS,
                    )
                    changed = True
                elif self.workers > self.configured_workers:
                    self.workers -= 1
                    self.safe_worker_ceiling = min(
                        self.safe_worker_ceiling,
                        self.workers,
                    )
                    changed = True
                elif self.pause + 1e-9 < self.pause_ceiling:
                    self.pause = min(
                        self.pause_ceiling,
                        self.pause + ADAPTIVE_FAILURE_STEP_SECONDS,
                    )
                    self.safe_pause_floor = max(self.safe_pause_floor, self.pause)
                    changed = True
                if changed:
                    self.epoch += 1
                    self.adjustments += 1
                self._persist_profile()
                return
            if not ok or recovered:
                self.success_streak = 0
                self.healthy_since = None
                self.failure_evidence_clean_successes = 0
                return
            if self.pending_transient_failures > 0:
                self.failure_evidence_clean_successes += 1
                if (
                    self.failure_evidence_clean_successes
                    >= ADAPTIVE_FAILURE_EVIDENCE_CLEAR_SUCCESSES
                ):
                    self.pending_transient_failures = 0
                    self.failure_evidence_clean_successes = 0
                    self._persist_profile()
            else:
                self.failure_evidence_clean_successes = 0
            if self.healthy_since is None:
                self.healthy_since = now
            self.success_streak += 1
            if (
                self.success_streak < ADAPTIVE_SUCCESS_WINDOW
                or now < self.next_increase_at
            ):
                return
            # Recover along the exact inverse ladder: remove extra cooldown,
            # restore explored workers, then probe cooldown below default.
            normal_floor = min(ADAPTIVE_MIN_PAUSE, self.pause_ceiling)
            default_pause = max(normal_floor, self.configured_pause)
            if (
                self.pause <= default_pause + 1e-9
                and self.workers >= self.worker_ceiling
                and self.pause > normal_floor + 1e-9
                and wall_now < self.pause_probe_blocked_until
            ):
                # Preserve a ready healthy window while the failed probe slot
                # is locked.  The first success after the lock expires may
                # probe again without discarding several minutes of evidence.
                self.success_streak = ADAPTIVE_SUCCESS_WINDOW
                return
            self.success_streak = 0
            changed = False
            if self.pause_rollback > self.pause + 1e-9:
                # The current probe survived a complete healthy window and is
                # now the stable rollback point for a possible next probe.
                self.safe_pause_floor = self.pause
                self.pause_rollback = 0.0
            if self.pause > default_pause + 1e-9:
                self.pause = max(default_pause, self.pause - ADAPTIVE_STEP_SECONDS)
                self.safe_pause_floor = self.pause
                changed = True
            elif self.workers < self.worker_ceiling:
                self.workers += 1
                self.safe_worker_ceiling = max(
                    self.safe_worker_ceiling,
                    self.workers,
                )
                changed = True
            elif self.pause > normal_floor + 1e-9:
                probe_from_pause = self.pause
                self.pause = max(normal_floor, self.pause - ADAPTIVE_STEP_SECONDS)
                self.pause_rollback = probe_from_pause
                self.safe_pause_floor = probe_from_pause
                changed = True
            if changed:
                self.epoch += 1
                self.adjustments += 1
                self.healthy_since = None
                self.next_increase_at = now + ADAPTIVE_HEALTHY_DWELL_SECONDS
                self._persist_profile()

    def status(self) -> dict[str, Any]:
        with self._lock:
            # Emit both camelCase (used by the modern crawler's own status
            # files) and the snake_case aliases consumed by the shared queue
            # controller/dashboard and legacy-compatible tooling.
            return {
                "adaptiveTuning": self.adaptive_tuning,
                "adaptive_tuning": self.adaptive_tuning,
                "adaptiveWorkers": self.workers,
                "adaptive_workers": self.workers,
                "workers": self.workers,
                "adaptiveWorkerCeiling": self.worker_ceiling,
                "adaptive_worker_ceiling": self.worker_ceiling,
                "adaptiveSafeWorkerCeiling": self.safe_worker_ceiling,
                "adaptive_safe_worker_ceiling": self.safe_worker_ceiling,
                "adaptiveBatchPause": self.pause,
                "adaptive_batch_pause_seconds": self.pause,
                "adaptiveBatchPauseCeiling": self.pause_ceiling,
                "adaptive_batch_pause_ceiling_seconds": self.pause_ceiling,
                "adaptiveSafePauseFloor": self.safe_pause_floor,
                "adaptive_safe_pause_floor_seconds": self.safe_pause_floor,
                "adaptivePauseFloor": self.safe_pause_floor,
                "adaptive_pause_floor_seconds": self.safe_pause_floor,
                "adaptiveSuccessStreak": self.success_streak,
                "adaptive_pause_success_streak": self.success_streak,
                "adaptivePauseSuccessStreak": self.success_streak,
                "adaptiveAdjustments": self.adjustments,
                "adaptive_adjustments": self.adjustments,
                "adaptiveTransientFailures": self.pending_transient_failures,
                "adaptive_transient_failures": self.pending_transient_failures,
                "adaptiveFailureThreshold": self.failure_threshold,
                "adaptive_failure_threshold": self.failure_threshold,
                "adaptiveFailureEvidenceCleanSuccesses": (
                    self.failure_evidence_clean_successes
                ),
                "adaptive_failure_evidence_clean_successes": (
                    self.failure_evidence_clean_successes
                ),
                "adaptiveControllerEpoch": self.epoch,
                "adaptive_controller_epoch": self.epoch,
                "adaptivePauseRollback": self.pause_rollback,
                "adaptive_pause_rollback": self.pause_rollback,
                "adaptivePauseProbeBlockedSeconds": max(
                    0.0,
                    self.pause_probe_blocked_until - time.time(),
                ),
                "adaptive_pause_probe_blocked_seconds": max(
                    0.0,
                    self.pause_probe_blocked_until - time.time(),
                ),
                "adaptiveRecoveryAt": 0.0,
                "adaptive_recovery_at": 0.0,
                "configuredWorkers": self.configured_workers,
                "configured_workers": self.configured_workers,
                "configuredRequestLimit": self.configured_request_limit,
                "configured_request_limit": self.configured_request_limit,
                "configuredBatchPause": self.configured_pause,
                "configured_batch_pause_seconds": self.configured_pause,
                "minimum_seconds_between_request_starts": (
                    self.pause if self.workers <= 1 else 0.0
                ),
                "workerCeiling": self.worker_ceiling,
                "worker_ceiling": self.worker_ceiling,
                "requestLimit": self.request_limit,
                "request_limit": self.request_limit,
                "batchSize": self.request_limit,
                "batch_size": self.request_limit,
                "requestLimitCeiling": self.request_limit_ceiling,
                "request_limit_ceiling": self.request_limit_ceiling,
                # ``batchPause`` is the configured/start value, matching the
                # legacy crawler and dashboard contract.  The live adaptive
                # value is exposed through ``adaptiveBatchPause`` above.
                "batchPause": self.configured_pause,
                "batch_pause_seconds": self.configured_pause,
                "batchPauseCeiling": self.pause_ceiling,
                "batch_pause_ceiling": self.pause_ceiling,
            }


def adaptive_map(
    items: Sequence[Any],
    function: Callable[[Any], Any],
    *,
    client: "PublicClient",
) -> Iterator[tuple[Any, Any | None, BaseException | None]]:
    """Run jobs with a sliding pool whose size follows ``AdaptiveSpeed``."""

    speed = getattr(client, "adaptive_speed", None)
    if not isinstance(speed, AdaptiveSpeed):
        speed = None
    if speed is None:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            for item in items:
                future = pool.submit(function, item)
                try:
                    yield item, future.result(), None
                except BaseException as exc:
                    # ``PublicClient._request`` already reports the final
                    # retry outcome to the controller for callers that are
                    # not running inside this pool.  Avoid feeding the same
                    # exception a second time when a pooled future propagates
                    # it, which would otherwise downshift twice in one wave.
                    if speed is not None and not getattr(
                        exc, "_cn_modern_adaptive_observed", False
                    ):
                        speed.observe(
                            ok=False,
                            transient=transient_failure_reason(exc) is not None,
                        )
                    yield item, None, exc
        return
    iterator = iter(items)
    in_flight: dict[concurrent.futures.Future[Any], Any] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=speed.worker_ceiling) as pool:
        def refill() -> None:
            while len(in_flight) < max(1, speed.workers):
                try:
                    item = next(iterator)
                except StopIteration:
                    return
                in_flight[pool.submit(function, item)] = item

        refill()
        while in_flight:
            done, _ = concurrent.futures.wait(
                tuple(in_flight), return_when=concurrent.futures.FIRST_COMPLETED
            )
            for future in done:
                item = in_flight.pop(future)
                try:
                    yield item, future.result(), None
                except BaseException as exc:
                    if speed is not None and not getattr(
                        exc, "_cn_modern_adaptive_observed", False
                    ):
                        speed.observe(
                            ok=False,
                            transient=transient_failure_reason(exc) is not None,
                        )
                    yield item, None, exc
                refill()


class PublicClient:
    def __init__(
        self,
        *,
        delay: float,
        retries: int,
        timeout: float,
        adaptive_speed: AdaptiveSpeed | None = None,
    ) -> None:
        self.limiter = RateLimiter(delay)
        self.retries = max(1, retries)
        self.timeout = timeout
        self.adaptive_speed = adaptive_speed

    def _request(
        self,
        request: urllib.request.Request,
        *,
        timeout: float | None = None,
        observe_success: bool = True,
    ) -> tuple[bytes, dict[str, Any]]:
        error: BaseException | None = None
        request_epoch: int | None = None
        had_transient = False
        adaptive_transient_seen = False
        for attempt in range(1, self.retries + 1):
            if self.adaptive_speed is not None:
                request_epoch = self.adaptive_speed.request_start()
            else:
                self.limiter.wait()
            try:
                with urllib.request.urlopen(
                    request, timeout=timeout or self.timeout
                ) as response:
                    body = response.read()
                    meta = {
                        "status": response.status,
                        "finalUrl": response.geturl(),
                        "contentType": response.headers.get("Content-Type"),
                        "etag": response.headers.get("ETag"),
                        "lastModified": response.headers.get("Last-Modified"),
                        "retrievedAt": utc_now(),
                    }
                    if request_epoch is not None:
                        meta["_adaptiveRequestEpoch"] = request_epoch
                    if self.adaptive_speed is not None and observe_success:
                        self.adaptive_speed.observe(
                            ok=True,
                            recovered=had_transient,
                            request_epoch=request_epoch,
                        )
                    return body, meta
            except (OSError, TimeoutError, urllib.error.URLError) as exc:
                error = exc
                transient = transient_failure_reason(exc) is not None
                had_transient = had_transient or transient
                # Count at most one transient observation for this logical
                # request, even when all of its transport retries fail.  The
                # controller tolerates a small number of such requests before
                # changing speed.  A final observation is tagged on the
                # exception so ``adaptive_map`` cannot count it a second time.
                if self.adaptive_speed is not None and transient:
                    if not adaptive_transient_seen:
                        self.adaptive_speed.observe(
                            ok=False,
                            transient=True,
                            request_epoch=request_epoch,
                        )
                    else:
                        self.adaptive_speed.observe(
                            ok=True,
                            recovered=True,
                            request_epoch=request_epoch,
                        )
                    adaptive_transient_seen = True
                if attempt < self.retries:
                    # The shared adaptive gate controls request starts.  Keep
                    # a small exponential backoff for callers that use the
                    # legacy fixed limiter, and never double-sleep adaptive
                    # requests here.
                    if self.adaptive_speed is None:
                        time.sleep(min(20.0, 0.75 * (2 ** (attempt - 1))))
                elif self.adaptive_speed is not None:
                    if not transient:
                        self.adaptive_speed.observe(
                            ok=False,
                            transient=False,
                            request_epoch=request_epoch,
                        )
                    try:
                        setattr(exc, "_cn_modern_adaptive_observed", True)
                    except Exception:
                        pass
        assert error is not None
        raise error

    def get(self, url: str, *, timeout: float | None = None) -> tuple[bytes, dict[str, Any]]:
        request = urllib.request.Request(
            url,
            headers={"Accept": "*/*", "User-Agent": USER_AGENT},
            method="GET",
        )
        body, meta = self._request(request, timeout=timeout)
        meta.pop("_adaptiveRequestEpoch", None)
        return body, meta

    def graphql(
        self,
        operation: str,
        document: str,
        variables: Mapping[str, Any],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        payload = json.dumps(
            {"operationName": operation, "query": document, "variables": variables},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        request = urllib.request.Request(
            ENDPOINT,
            data=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        graphql_transient_seen = False
        last_error: RuntimeError | None = None

        def observe_graphql_transient(request_epoch: int | None) -> None:
            nonlocal graphql_transient_seen
            if self.adaptive_speed is not None:
                if not graphql_transient_seen:
                    # One GraphQL retry wave earns one downshift.  Repeated
                    # HTTP-200 error envelopes from that same call should not
                    # subtract another worker on every retry.
                    self.adaptive_speed.observe(
                        ok=False,
                        transient=True,
                        request_epoch=request_epoch,
                    )
                else:
                    # ``_request`` saw HTTP success before the body was
                    # interpreted.  Cancel that false healthy evidence for
                    # subsequent bad envelopes without another downshift.
                    self.adaptive_speed.observe(
                        ok=True,
                        recovered=True,
                        request_epoch=request_epoch,
                    )
            graphql_transient_seen = True

        for attempt in range(1, self.retries + 1):
            body, response_meta = self._request(
                request,
                timeout=timeout,
                observe_success=False,
            )
            request_epoch_value = response_meta.pop("_adaptiveRequestEpoch", None)
            request_epoch = (
                int(request_epoch_value)
                if request_epoch_value is not None
                else None
            )
            try:
                result = json.loads(body)
            except json.JSONDecodeError as exc:
                # An empty/truncated HTTP-200 body is the same upstream
                # gateway failure as the JSON_DECODE_ERROR reported inside a
                # GraphQL error envelope.  Retry it at the request level so a
                # single bad cell does not abort an entire content list.
                last_error = RuntimeError(
                    f"{operation}: response was not JSON ({len(body)} bytes)"
                )
                observe_graphql_transient(request_epoch)
                if attempt < self.retries:
                    if self.adaptive_speed is None:
                        time.sleep(min(20.0, 0.75 * (2 ** (attempt - 1))))
                    continue
                try:
                    setattr(last_error, "_cn_modern_adaptive_observed", True)
                except Exception:
                    pass
                raise last_error from exc
            if result.get("errors"):
                last_error = RuntimeError(
                    f"{operation}: "
                    + json.dumps(result["errors"], ensure_ascii=False)
                )
                transient = transient_failure_reason(last_error) is not None
                if transient:
                    observe_graphql_transient(request_epoch)
                if attempt < self.retries and transient:
                    if self.adaptive_speed is None:
                        time.sleep(min(20.0, 0.75 * (2 ** (attempt - 1))))
                    continue
                if transient and self.adaptive_speed is not None:
                    try:
                        setattr(last_error, "_cn_modern_adaptive_observed", True)
                    except Exception:
                        pass
                raise last_error
            if "data" not in result:
                raise RuntimeError(f"{operation}: response has no data")
            if self.adaptive_speed is not None:
                # GraphQL HTTP-200 envelopes are observed only after the body
                # is known to contain usable data.  A recovered request breaks
                # the clean-health window without counting another failure.
                self.adaptive_speed.observe(
                    ok=True,
                    recovered=graphql_transient_seen,
                    request_epoch=request_epoch,
                )
            return {
                "provenance": {
                    "source": ENDPOINT,
                    "method": "POST",
                    "operation": operation,
                    "documentSha256": sha256_bytes(document.encode("utf-8")),
                    "variables": dict(variables),
                    **response_meta,
                },
                "data": result["data"],
            }
        assert last_error is not None
        raise last_error


def graphql_checkpoint_valid(
    path: Path,
    *,
    operation: str,
    variables: Mapping[str, Any] | None = None,
) -> bool:
    try:
        value = load_json(path)
        provenance = value["provenance"]
        if provenance["operation"] != operation or "data" not in value:
            return False
        if variables is not None and provenance["variables"] != dict(variables):
            return False
        return True
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False


def fetch_graphql_checkpoint(
    client: PublicClient,
    path: Path,
    operation: str,
    document: str,
    variables: Mapping[str, Any],
    *,
    resume: bool,
    timeout: float | None = None,
    context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if resume and graphql_checkpoint_valid(
        path, operation=operation, variables=variables
    ):
        return load_json(path)
    value = client.graphql(operation, document, variables, timeout=timeout)
    if context:
        value["context"] = dict(context)
    atomic_write_json(path, value)
    return value


def download_one(
    client: PublicClient,
    url: str,
    path: Path,
    *,
    resume: bool,
) -> dict[str, Any]:
    if resume and path.is_file() and path.stat().st_size:
        return {
            "url": url,
            "localPath": path.relative_to(WORKSPACE).as_posix(),
            "status": "resumed",
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    body, meta = client.get(url)
    atomic_write_bytes(path, body)
    return {
        "url": url,
        "localPath": path.relative_to(WORKSPACE).as_posix(),
        **meta,
        "bytes": len(body),
        "sha256": sha256_bytes(body),
    }


HASHED_JS_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*-[0-9a-f]{8}\.js")
HTML_ASSET_RE = re.compile(r'(?:src|href)=["\']([^"\']+\.(?:js|css))["\']')


def crawl_static(
    config: RoundConfig,
    client: PublicClient,
    *,
    resume: bool,
) -> dict[str, Any]:
    static_root = config.root / "static"
    assets_root = static_root / "assets"
    records: list[dict[str, Any]] = []

    index_path = static_root / "index.html"
    index_record = download_one(
        client, config.base_url, index_path, resume=resume
    )
    records.append(index_record)
    html = index_path.read_text(encoding="utf-8")

    html_assets = set(HTML_ASSET_RE.findall(html))
    index_asset = f"/v{config.number}/assets/{config.index_js}"
    html_assets.add(index_asset)
    for relative_url in sorted(html_assets):
        url = urllib.parse.urljoin(config.base_url, relative_url)
        path = assets_root / Path(urllib.parse.urlparse(url).path).name
        records.append(download_one(client, url, path, resume=resume))

    index_path_local = assets_root / config.index_js
    index_text = index_path_local.read_text(encoding="utf-8")
    js_names = set(HASHED_JS_RE.findall(index_text))
    js_names.add(config.index_js)
    js_names.add(config.questionnaire_js)
    js_names.add(config.doujin_js)

    downloaded = {Path(x["localPath"]).name for x in records if "localPath" in x}
    for name in sorted(js_names):
        if name not in downloaded:
            url = urllib.parse.urljoin(config.base_url, f"assets/{name}")
            path = assets_root / name
            records.append(download_one(client, url, path, resume=resume))

    # Source maps are requested explicitly; absent maps remain documented as
    # unavailable without making the otherwise complete crawl fail.
    map_records: list[dict[str, Any]] = []
    for name in sorted(js_names):
        map_name = name + ".map"
        url = urllib.parse.urljoin(config.base_url, f"assets/{map_name}")
        path = assets_root / map_name
        try:
            map_records.append(download_one(client, url, path, resume=resume))
        except urllib.error.HTTPError as exc:
            map_records.append(
                {
                    "url": url,
                    "localPath": path.relative_to(WORKSPACE).as_posix(),
                    "status": exc.code,
                    "available": False,
                    "retrievedAt": utc_now(),
                }
            )
    records.extend(map_records)

    manifest = {
        "schemaVersion": 1,
        "round": config.number,
        "createdAt": utc_now(),
        "scope": "official HTML, CSS, hashed JavaScript, and available source maps; images/fonts excluded",
        "resources": records,
    }
    atomic_write_json(static_root / "resource_manifest.json", manifest, pretty=True)
    return manifest


def balanced_literal(
    source: str, start: int, opener: str, closer: str
) -> str:
    depth = 0
    quote: str | None = None
    escaped = False
    line_comment = False
    block_comment = False
    index = start
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if line_comment:
            if char in "\r\n":
                line_comment = False
            index += 1
            continue
        if block_comment:
            if char == "*" and next_char == "/":
                block_comment = False
                index += 2
            else:
                index += 1
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            index += 1
            continue
        if char == "/" and next_char == "/":
            line_comment = True
            index += 2
            continue
        if char == "/" and next_char == "*":
            block_comment = True
            index += 2
            continue
        if char in "'\"`":
            quote = char
            index += 1
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
        index += 1
    raise ValueError(f"unterminated {opener}{closer} literal")


def source_from_map(path: Path, suffix: str) -> str:
    source_map = load_json(path)
    for source_name, source_content in zip(
        source_map.get("sources", []), source_map.get("sourcesContent", [])
    ):
        if str(source_name).endswith(suffix) and source_content is not None:
            return source_content
    raise ValueError(f"{path}: no source ending in {suffix!r}")


NODE_EVAL = r"""
let source = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => source += chunk);
process.stdin.on('end', () => {
  const value = eval('(' + source + ')');
  process.stdout.write(JSON.stringify(value));
});
"""


def evaluate_js_literal(source: str, node: str) -> Any:
    # Source maps occasionally retain JavaScript string continuations as a
    # backslash followed by CRLF (notably the round-11 Doujin comments).  When
    # the literal is forwarded through Python's text-mode subprocess pipe the
    # newline translation can leave Node rejecting an otherwise valid source
    # literal.  Removing the line-continuation pair is semantics-preserving:
    # JavaScript itself discards exactly those characters while parsing.
    source = re.sub(r"\\\r?\n", "", source)
    process = subprocess.run(
        [node, "-e", NODE_EVAL],
        input=source,
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )
    if process.returncode:
        raise RuntimeError(f"Node.js could not parse official literal: {process.stderr}")
    return json.loads(process.stdout)


def parse_questionnaire(
    config: RoundConfig,
    *,
    node: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    questionnaire_root = config.root / "questionnaire"
    map_path = config.root / "static" / "assets" / (config.questionnaire_js + ".map")
    source = source_from_map(map_path, "questionnaire.ts")
    atomic_write_bytes(
        questionnaire_root / "definition.source.ts", source.encode("utf-8")
    )
    marker = "export const questionnaire"
    marker_index = source.index(marker)
    object_start = source.index("{", marker_index)
    object_literal = balanced_literal(source, object_start, "{", "}")
    normalized = evaluate_js_literal(object_literal, node)
    atomic_write_json(
        questionnaire_root / "definition.normalized.json", normalized, pretty=True
    )

    questions: list[dict[str, Any]] = []
    options: list[dict[str, Any]] = []
    for section_key, section in normalized.items():
        for questionnaire_key, questionnaire in section.items():
            for group_index, question_group in enumerate(questionnaire["questions"]):
                for branch_index, question in enumerate(question_group):
                    question_record = {
                        "sectionKey": section_key,
                        "questionnaireKey": questionnaire_key,
                        "questionnaireId": questionnaire["id"],
                        "questionnaireName": questionnaire["name"],
                        "groupIndex": group_index,
                        "branchIndex": branch_index,
                        "id": question["id"],
                        "type": question["type"],
                        "question": question["question"],
                        "introduction": question.get("introduction", ""),
                        "input": question.get("input", ""),
                        "optionCount": len(question.get("options", [])),
                    }
                    questions.append(question_record)
                    for option_index, option in enumerate(question.get("options", [])):
                        options.append(
                            {
                                "sectionKey": section_key,
                                "questionnaireKey": questionnaire_key,
                                "questionnaireId": questionnaire["id"],
                                "questionnaireName": questionnaire["name"],
                                "questionId": question["id"],
                                "questionType": question["type"],
                                "question": question["question"],
                                "optionIndex": option_index,
                                "answerId": option["id"],
                                "content": option["content"],
                                "related": option.get("related", []),
                                "mutex": option.get("mutex", []),
                                **(
                                    {"group": option["group"]}
                                    if "group" in option
                                    else {}
                                ),
                            }
                        )
    atomic_write_json(questionnaire_root / "questions.json", questions, pretty=True)
    atomic_write_json(questionnaire_root / "options.json", options, pretty=True)
    return questions, options


def base_variables(config: RoundConfig, **extra: Any) -> dict[str, Any]:
    return {
        "voteStart": config.vote_start,
        "voteYear": config.number,
        **extra,
    }


def crawl_questionnaire_results(
    config: RoundConfig,
    client: PublicClient,
    questions: Sequence[Mapping[str, Any]],
    *,
    resume: bool,
) -> None:
    root = config.root / "questionnaire"
    categorical = [f"q{x['id']}" for x in questions if x["type"] != "Input"]
    open_questions = [f"q{x['id']}" for x in questions if x["type"] == "Input"]
    fetch_graphql_checkpoint(
        client,
        root / "categorical_results.json",
        "QuestionnaireCategorical",
        QUESTIONNAIRE_CATEGORICAL_QUERY,
        base_variables(config, questionsOfInterest=categorical),
        resume=resume,
        timeout=180,
    )
    fetch_graphql_checkpoint(
        client,
        root / "open_text_results.json",
        "QuestionnaireOpen",
        QUESTIONNAIRE_OPEN_QUERY,
        base_variables(config, questionsOfInterest=open_questions),
        resume=resume,
        timeout=300,
        context={
            "contentNote": "anonymous free-text answers published by the official aggregate result API; no author/token identifiers",
        },
    )


def crawl_questionnaire_trends(
    config: RoundConfig,
    client: PublicClient,
    questions: Sequence[Mapping[str, Any]],
    *,
    resume: bool,
    chunk_size: int,
) -> None:
    root = config.root / "questionnaire"
    chunk_root = root / "trend_chunks"
    question_ids = [f"q{x['id']}" for x in questions]
    combined: list[dict[str, Any]] = []
    chunk_files: list[str] = []
    for index, question_chunk in enumerate(chunks(question_ids, chunk_size), start=1):
        path = chunk_root / f"chunk_{index:03d}.json"
        value = fetch_graphql_checkpoint(
            client,
            path,
            "QuestionnaireTrend",
            QUESTIONNAIRE_TREND_QUERY,
            base_variables(config, questionIds=question_chunk),
            resume=resume,
            timeout=180,
            context={"questionIdsInResponseOrder": question_chunk},
        )
        trends = value["data"]["queryQuestionnaireTrend"]
        if len(trends) != len(question_chunk):
            raise RuntimeError(
                f"round {config.number} trend chunk {index}: "
                f"expected {len(question_chunk)}, got {len(trends)}"
            )
        combined.extend(
            {"questionId": question_id, **trend}
            for question_id, trend in zip(question_chunk, trends)
        )
        chunk_files.append(path.relative_to(config.root).as_posix())
    atomic_write_json(
        root / "trends.json",
        {
            "provenance": {
                "source": ENDPOINT,
                "operation": "QuestionnaireTrend",
                "responseOrderMappedBy": "questionIdsInResponseOrder",
                "generatedAt": utc_now(),
                "chunkFiles": chunk_files,
            },
            "entries": combined,
        },
    )


def extract_doujin_summary(config: RoundConfig, *, node: str) -> dict[str, Any]:
    map_path = config.root / "static" / "assets" / (config.doujin_js + ".map")
    source = source_from_map(map_path, "Doujin.vue")
    total_match = re.search(r"总票数\s*[：:]\s*(\d+)", source)
    if not total_match:
        raise ValueError(f"round {config.number}: could not find Doujin total")
    declaration = source.index("const DoujinData")
    equals = source.index("=", declaration)
    array_start = source.index("[", equals)
    array_literal = balanced_literal(source, array_start, "[", "]")
    values = evaluate_js_literal(array_literal, node)
    entries = [
        {
            "rank": index,
            "name": item.get("name"),
            "author": item.get("author"),
            "url": item.get("url"),
            "pic": item.get("pic"),
        }
        for index, item in enumerate(values, start=1)
    ]
    summary = {
        "provenance": {
            "source": urllib.parse.urljoin(
                config.base_url, f"assets/{config.doujin_js}.map"
            ),
            "sourceMapSha256": sha256_file(map_path),
            "parsedAt": utc_now(),
            "contentPolicy": "only top-ten metadata retained; reasons, comments, and descriptions excluded",
        },
        "round": config.number,
        "officialPageDisplayedTotalVotes": int(total_match.group(1)),
        "entries": entries,
    }
    atomic_write_json(config.root / "doujin" / "summary.json", summary, pretty=True)
    return summary


def covote_matrix_checkpoint_valid(
    path: Path,
    *,
    graphql_key: str,
    expected_pairs: int,
) -> bool:
    try:
        wrapper = load_json(path)
        items = wrapper["data"][graphql_key]["items"]
        if not isinstance(items, list) or len(items) != expected_pairs:
            return False
        pair_keys: set[tuple[str, str]] = set()
        for item in items:
            if not isinstance(item, Mapping):
                return False
            if not all(key in item for key in ("a", "b", "m00", "m01", "m10", "m11")):
                return False
            pair = (str(item["a"]), str(item["b"]))
            if pair in pair_keys:
                return False
            pair_keys.add(pair)
            if any(
                not isinstance(item[key], int) or item[key] < 0
                for key in ("m00", "m01", "m10", "m11")
            ):
                return False
        return len(pair_keys) == expected_pairs
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False


def conditional_covote_checkpoint_valid(
    path: Path,
    *,
    operation: str,
    variables: Mapping[str, Any],
    ranking_key: str,
    source_name: str,
    source_count: int,
) -> bool:
    try:
        wrapper = load_json(path)
        # Advanced-search archival may obtain the same official conditional
        # ranking as one field of a wider public query (global + all three
        # departments).  Such a checkpoint records the actual GraphQL
        # operation and declares this narrower operation as compatible rather
        # than pretending that a second request was made.
        observed_operation = wrapper["provenance"]["operation"]
        compatible_operation = wrapper.get("context", {}).get(
            "compatibleOperation"
        )
        if observed_operation != operation and compatible_operation != operation:
            return False
        if wrapper["provenance"]["variables"] != dict(variables):
            return False
        if wrapper["context"]["sourceName"] != source_name:
            return False
        result = wrapper["data"][ranking_key]
        if int(result["global"]["totalVotes"]) != source_count:
            return False
        names: set[str] = set()
        for entry in result["entries"]:
            name = str(entry["name"])
            if name in names or not isinstance(entry.get("voteCount"), int):
                return False
            names.add(name)
        observed_self = next(
            (
                int(entry["voteCount"])
                for entry in result["entries"]
                if entry["name"] == source_name
            ),
            0,
        )
        return observed_self == source_count
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False


def record_covote_direct_failures(
    config: RoundConfig,
    *,
    category: str,
    full_operation: str,
    count_operation: str,
    full_error: BaseException,
    count_error: BaseException,
) -> dict[str, Any]:
    path = config.root / "covote" / "direct_matrix_failures.json"
    if path.is_file():
        try:
            record = load_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            record = {}
    else:
        record = {}
    record.update(
        {
            "round": config.number,
            "officialEndpoint": ENDPOINT,
            "interpretation": (
                "The public all-pairs operation was offered but its current "
                "upstream response could not be decoded. This is a fetch failure, "
                "not evidence that the component was not officially offered."
            ),
        }
    )
    categories = record.setdefault("categories", {})
    categories[category] = {
        "recordedAt": utc_now(),
        "fullOperation": full_operation,
        "fullError": f"{type(full_error).__name__}: {full_error}",
        "countOnlyOperation": count_operation,
        "countOnlyError": f"{type(count_error).__name__}: {count_error}",
    }
    atomic_write_json(path, record, pretty=True)
    return categories[category]


def reconstruct_covote_from_conditional_rankings(
    config: RoundConfig,
    client: PublicClient,
    base: Mapping[str, Any],
    *,
    category: str,
    output_path: Path,
    graphql_key: str,
    ranking_key: str,
    filter_key: str,
    operation: str,
    document: str,
    direct_operation: str,
    direct_document: str,
    resume: bool,
    direct_failure_evidence: Mapping[str, Any],
) -> None:
    entries = list(base["data"][ranking_key]["entries"])
    names = [str(entry["name"]) for entry in entries]
    if len(names) != len(set(names)):
        duplicates = sorted(name for name, count in Counter(names).items() if count > 1)
        raise ValueError(
            f"round {config.number} {category}: conditional reconstruction has "
            f"ambiguous duplicate names: {duplicates}"
        )
    department_field = "numChar" if category == "character" else "numMusic"
    universe = int(base["data"]["queryGlobalStats"][department_field])
    base_counts = {str(entry["name"]): int(entry["voteCount"]) for entry in entries}
    checkpoint_root = config.root / "covote" / f"conditional_{category}"
    checkpoint_root.mkdir(parents=True, exist_ok=True)

    filtered_maps: list[dict[str, int]] = []
    for index, source in enumerate(entries):
        source_name = str(source["name"])
        source_count = int(source["voteCount"])
        query_filter = f"{filter_key}: {json.dumps([source_name], ensure_ascii=False)}"
        variables = base_variables(config, query=query_filter)
        checkpoint = checkpoint_root / f"source_{index + 1:04d}.json"
        if resume and conditional_covote_checkpoint_valid(
            checkpoint,
            operation=operation,
            variables=variables,
            ranking_key=ranking_key,
            source_name=source_name,
            source_count=source_count,
        ):
            wrapper = load_json(checkpoint)
        else:
            last_error: BaseException | None = None
            for attempt in range(1, client.retries + 1):
                try:
                    wrapper = fetch_graphql_checkpoint(
                        client,
                        checkpoint,
                        operation,
                        document,
                        variables,
                        resume=False,
                        timeout=300,
                        context={
                            "sourceCategory": category,
                            "sourceIndex": index + 1,
                            "sourceRank": source.get("rank"),
                            "sourceName": source_name,
                            "sourceVoteCount": source_count,
                            "reconstructionRole": "official conditional ranking for one matrix row",
                        },
                    )
                    break
                except BaseException as exc:
                    last_error = exc
                    if attempt < client.retries:
                        time.sleep(min(20.0, 0.75 * (2 ** (attempt - 1))))
            else:
                assert last_error is not None
                raise last_error
        result = wrapper["data"][ranking_key]
        if int(result["global"]["totalVotes"]) != source_count:
            raise ValueError(
                f"round {config.number} {category} {source_name!r}: filtered "
                f"totalVotes {result['global']['totalVotes']} != base count {source_count}"
            )
        filtered = {str(item["name"]): int(item["voteCount"]) for item in result["entries"]}
        # Zero-vote catalogue entries are legitimately omitted from a filtered
        # ranking response; their absent self row represents a count of zero.
        if filtered.get(source_name, 0) != source_count:
            raise ValueError(
                f"round {config.number} {category} {source_name!r}: self count mismatch"
            )
        unknown_names = sorted(set(filtered) - set(base_counts))
        if unknown_names:
            raise ValueError(
                f"round {config.number} {category} {source_name!r}: unknown result names "
                f"{unknown_names[:10]}"
            )
        filtered_maps.append(filtered)
        completed = index + 1
        if completed == 1 or completed % 25 == 0 or completed == len(entries):
            print(
                f"round {config.number} {category} conditional covote: "
                f"{completed}/{len(entries)}",
                flush=True,
            )

    items: list[dict[str, Any]] = []
    symmetry_mismatches: list[dict[str, Any]] = []
    invariant_failures: list[dict[str, Any]] = []
    for source_index in range(1, len(entries)):
        source_name = names[source_index]
        count_a = base_counts[source_name]
        for target_index in range(source_index):
            target_name = names[target_index]
            count_b = base_counts[target_name]
            intersection = filtered_maps[source_index].get(target_name, 0)
            reverse_intersection = filtered_maps[target_index].get(source_name, 0)
            if intersection != reverse_intersection and len(symmetry_mismatches) < 20:
                symmetry_mismatches.append(
                    {
                        "a": source_name,
                        "b": target_name,
                        "aFilterCountB": intersection,
                        "bFilterCountA": reverse_intersection,
                    }
                )
            item = {
                "a": source_name,
                "b": target_name,
                # Official endpoint convention: 0 means selected and 1 means
                # not selected. Thus m00 is the intersection and m11 neither.
                "m00": intersection,
                "m01": count_b - intersection,
                "m10": count_a - intersection,
                "m11": universe - count_a - count_b + intersection,
            }
            if (
                any(item[key] < 0 for key in ("m00", "m01", "m10", "m11"))
                or item["m00"] + item["m10"] != count_a
                or item["m00"] + item["m01"] != count_b
                or sum(item[key] for key in ("m00", "m01", "m10", "m11")) != universe
            ) and len(invariant_failures) < 20:
                invariant_failures.append(
                    {**item, "expectedCountA": count_a, "expectedCountB": count_b, "universe": universe}
                )
            items.append(item)

    expected_pairs = len(entries) * (len(entries) - 1) // 2
    if len(items) != expected_pairs or symmetry_mismatches or invariant_failures:
        raise AssertionError(
            json.dumps(
                {
                    "expectedPairs": expected_pairs,
                    "observedPairs": len(items),
                    "symmetryMismatches": symmetry_mismatches,
                    "invariantFailures": invariant_failures,
                },
                ensure_ascii=False,
            )
        )

    sample_positions = sorted({0, len(items) // 2, len(items) - 1})
    identity_samples = []
    for position in sample_positions:
        item = items[position]
        identity_samples.append(
            {
                **item,
                "pairIndex": position,
                "countAFromCells": item["m00"] + item["m10"],
                "countAOfficialRanking": base_counts[str(item["a"])],
                "countBFromCells": item["m00"] + item["m01"],
                "countBOfficialRanking": base_counts[str(item["b"])],
                "universeFromCells": sum(
                    item[key] for key in ("m00", "m01", "m10", "m11")
                ),
                "universeOfficial": universe,
                "reverseConditionalIntersection": filtered_maps[
                    names.index(str(item["b"]))
                ].get(str(item["a"]), 0),
            }
        )

    direct_topk_crosscheck: dict[str, Any]
    crosscheck_k = min(10, len(entries))
    direct_topk_path = config.root / "covote" / f"direct_top{crosscheck_k}_{category}.json"
    try:
        direct_topk = fetch_graphql_checkpoint(
            client,
            direct_topk_path,
            direct_operation,
            direct_document,
            base_variables(config, topK=crosscheck_k),
            resume=resume,
            timeout=300,
            context={
                "scope": f"top-{crosscheck_k} field-convention cross-check",
                "expectedPairCount": crosscheck_k * (crosscheck_k - 1) // 2,
            },
        )
        direct_items = direct_topk["data"][graphql_key]["items"]
        reconstructed = {
            (str(item["a"]), str(item["b"])): item
            for item in items
            if str(item["a"]) in set(names[:crosscheck_k])
            and str(item["b"]) in set(names[:crosscheck_k])
        }
        crosscheck_mismatches = []
        for direct_item in direct_items:
            key = (str(direct_item["a"]), str(direct_item["b"]))
            rebuilt = reconstructed.get(key)
            if rebuilt is None or any(
                int(direct_item[cell]) != rebuilt[cell]
                for cell in ("m00", "m01", "m10", "m11")
            ):
                crosscheck_mismatches.append(
                    {"pair": key, "direct": direct_item, "reconstructed": rebuilt}
                )
        direct_topk_crosscheck = {
            "available": True,
            "topK": crosscheck_k,
            "pairsChecked": len(direct_items),
            "mismatches": crosscheck_mismatches[:20],
        }
        if len(direct_items) != crosscheck_k * (crosscheck_k - 1) // 2 or crosscheck_mismatches:
            raise AssertionError(json.dumps(direct_topk_crosscheck, ensure_ascii=False))
    except BaseException as exc:
        if isinstance(exc, AssertionError):
            raise
        direct_topk_crosscheck = {
            "available": False,
            "topK": crosscheck_k,
            "error": f"{type(exc).__name__}: {exc}",
        }

    validation = {
        "round": config.number,
        "category": category,
        "sourceItems": len(entries),
        "sourceCheckpoints": len(filtered_maps),
        "expectedPairs": expected_pairs,
        "observedPairs": len(items),
        "universe": universe,
        "cellConvention": {
            "m00": "both selected (intersection)",
            "m01": "a not selected, b selected",
            "m10": "a selected, b not selected",
            "m11": "neither selected",
        },
        "allMarginalAndUniverseIdentitiesPassed": True,
        "allConditionalSymmetryChecksPassed": True,
        "symmetryPairsChecked": expected_pairs,
        "identitySamples": identity_samples,
        "directTopKCrosscheck": direct_topk_crosscheck,
    }
    validation_path = config.root / "covote" / f"{category}_reconstruction_validation.json"
    atomic_write_json(validation_path, validation, pretty=True)
    wrapper = {
        "provenance": {
            "source": ENDPOINT,
            "method": "POST",
            "operation": f"{operation}MatrixReconstruction",
            "conditionalDocumentSha256": sha256_bytes(document.encode("utf-8")),
            "generatedAt": utc_now(),
            "sourceCheckpointDirectory": checkpoint_root.relative_to(WORKSPACE).as_posix(),
            "sourceCheckpointCount": len(filtered_maps),
        },
        "context": {
            "topK": len(entries),
            "expectedPairCount": expected_pairs,
            "scope": "complete unfiltered ranking, not merely a display top-N",
            "responseMode": "official_conditional_rankings_reconstruction",
            "metricPolicy": "retain official contingency cells; recompute association metrics locally",
            "fieldConvention": validation["cellConvention"],
            "validationPath": validation_path.relative_to(WORKSPACE).as_posix(),
            "officialDirectMatrixFailure": dict(direct_failure_evidence),
        },
        "data": {graphql_key: {"items": items}},
    }
    atomic_write_json(output_path, wrapper)


def crawl_covote(
    config: RoundConfig,
    client: PublicClient,
    base: Mapping[str, Any],
    *,
    resume: bool,
) -> None:
    character_count = len(base["data"]["queryCharacterRanking"]["entries"])
    music_count = len(base["data"]["queryMusicRanking"]["entries"])

    def fetch_with_count_fallback(
        *,
        category: str,
        count: int,
        path: Path,
        graphql_key: str,
        ranking_key: str,
        filter_key: str,
        full_operation: str,
        full_document: str,
        count_operation: str,
        count_document: str,
        conditional_operation: str,
        conditional_document: str,
        timeout: float,
    ) -> None:
        expected_pairs = count * (count - 1) // 2
        if resume and covote_matrix_checkpoint_valid(
            path,
            graphql_key=graphql_key,
            expected_pairs=expected_pairs,
        ):
            print(
                f"round {config.number} {category} covote: resumed complete matrix",
                flush=True,
            )
            return
        context = {
            "topK": count,
            "expectedPairCount": expected_pairs,
            "scope": "complete unfiltered ranking, not merely a display top-N",
            "metricPolicy": (
                "prefer official cs/mi/cv; if the historical API rejects NULL "
                "derived metrics, reconstruct m00/m01/m10/m11 from official "
                "per-entity conditional rankings and recompute metrics locally"
            ),
        }
        try:
            fetch_graphql_checkpoint(
                client,
                path,
                full_operation,
                full_document,
                base_variables(config, topK=count),
                resume=resume,
                timeout=timeout,
                context={**context, "responseMode": "official_metrics_and_counts"},
            )
        except BaseException as full_error:
            print(
                f"round {config.number} {category} covote derived fields failed; "
                "retrying count-only matrix",
                file=sys.stderr,
                flush=True,
            )
            try:
                fetch_graphql_checkpoint(
                    client,
                    path,
                    count_operation,
                    count_document,
                    base_variables(config, topK=count),
                    resume=False,
                    timeout=timeout,
                    context={
                        **context,
                        "responseMode": "contingency_counts_only",
                        "fallbackReason": f"{type(full_error).__name__}: {full_error}",
                    },
                )
            except BaseException as count_error:
                print(
                    f"round {config.number} {category} covote count-only matrix "
                    "also failed; reconstructing from official conditional rankings",
                    file=sys.stderr,
                    flush=True,
                )
                evidence = record_covote_direct_failures(
                    config,
                    category=category,
                    full_operation=full_operation,
                    count_operation=count_operation,
                    full_error=full_error,
                    count_error=count_error,
                )
                reconstruct_covote_from_conditional_rankings(
                    config,
                    client,
                    base,
                    category=category,
                    output_path=path,
                    graphql_key=graphql_key,
                    ranking_key=ranking_key,
                    filter_key=filter_key,
                    operation=conditional_operation,
                    document=conditional_document,
                    direct_operation=full_operation,
                    direct_document=full_document,
                    resume=resume,
                    direct_failure_evidence=evidence,
                )

    fetch_with_count_fallback(
        category="character",
        count=character_count,
        path=config.root / "covote" / "characters.json",
        graphql_key="queryCharsCovote",
        ranking_key="queryCharacterRanking",
        filter_key="chars",
        full_operation="CharacterCovote",
        full_document=CHARACTER_COVOTE_QUERY,
        count_operation="CharacterCovoteCounts",
        count_document=CHARACTER_COVOTE_COUNTS_QUERY,
        conditional_operation="CharacterCovoteConditionalSource",
        conditional_document=CHARACTER_COVOTE_CONDITIONAL_QUERY,
        timeout=600,
    )
    fetch_with_count_fallback(
        category="music",
        count=music_count,
        path=config.root / "covote" / "music.json",
        graphql_key="queryMusicsCovote",
        ranking_key="queryMusicRanking",
        filter_key="musics",
        full_operation="MusicCovote",
        full_document=MUSIC_COVOTE_QUERY,
        count_operation="MusicCovoteCounts",
        count_document=MUSIC_COVOTE_COUNTS_QUERY,
        conditional_operation="MusicCovoteConditionalSource",
        conditional_document=MUSIC_COVOTE_CONDITIONAL_QUERY,
        timeout=900,
    )


def condition_path(config: RoundConfig, question_id: Any, answer_id: Any) -> Path:
    return config.root / "conditions" / f"q{question_id}_a{answer_id}.json"


def condition_checkpoint_valid(
    path: Path,
    *,
    query_filter: str,
    question_id: Any,
    answer_id: Any,
) -> bool:
    try:
        value = load_json(path)
        return (
            value["provenance"]["operation"] == "OptionCondition"
            and value["provenance"]["variables"]["query"] == query_filter
            and str(value["context"]["questionId"]) == str(question_id)
            and str(value["context"]["answerId"]) == str(answer_id)
            and "queryGlobalStats" in value["data"]
            and "queryCharacterRanking" in value["data"]
            and "queryMusicRanking" in value["data"]
            and "queryCPRanking" in value["data"]
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False


def crawl_conditions(
    config: RoundConfig,
    client: PublicClient,
    options: Sequence[Mapping[str, Any]],
    *,
    workers: int,
    resume: bool,
) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    failures_lock = threading.Lock()
    completed_lock = threading.Lock()
    completed = 0
    total = len(options)

    def one(option: Mapping[str, Any]) -> str:
        nonlocal completed
        question_id = option["questionId"]
        answer_id = option["answerId"]
        query_filter = f"q{question_id}={answer_id}"
        path = condition_path(config, question_id, answer_id)
        if resume and condition_checkpoint_valid(
            path,
            query_filter=query_filter,
            question_id=question_id,
            answer_id=answer_id,
        ):
            status = "resumed"
        else:
            try:
                value = client.graphql(
                    "OptionCondition",
                    CONDITION_QUERY,
                    base_variables(config, query=query_filter),
                    timeout=300,
                )
                value["context"] = {
                    "questionId": question_id,
                    "answerId": answer_id,
                    "questionType": option["questionType"],
                    "question": option["question"],
                    "answer": option["content"],
                    "conditionKey": [question_id, answer_id],
                }
                atomic_write_json(path, value)
                status = "downloaded"
            except BaseException as exc:
                with failures_lock:
                    failures.append(
                        {
                            "stage": "condition",
                            "questionId": question_id,
                            "answerId": answer_id,
                            "query": query_filter,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                status = "failed"
        with completed_lock:
            completed += 1
            if completed == 1 or completed % 25 == 0 or completed == total:
                print(
                    f"round {config.number} conditions: {completed}/{total}",
                    flush=True,
                )
        return status

    if client.adaptive_speed is not None:
        # The shared sliding pool refills as soon as a request completes and
        # follows the controller's current safe worker count.
        for _option, _result, _error in adaptive_map(options, one, client=client):
            # ``one`` records failures itself; preserve its historical return
            # contract while allowing adaptive_map to drain every future.
            continue
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            list(pool.map(one, options))
    return failures


def json_key_occurs(value: Any, forbidden: set[str]) -> bool:
    if isinstance(value, dict):
        return any(
            key in forbidden or json_key_occurs(child, forbidden)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(json_key_occurs(child, forbidden) for child in value)
    return False


def validate_round(config: RoundConfig) -> dict[str, Any]:
    root = config.root
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, details: Any) -> None:
        checks.append({"name": name, "ok": bool(ok), "details": details})

    questions_path = root / "questionnaire" / "questions.json"
    options_path = root / "questionnaire" / "options.json"
    base_path = root / "graphql" / "base.json"
    questions = load_json(questions_path) if questions_path.is_file() else []
    options = load_json(options_path) if options_path.is_file() else []
    base = load_json(base_path) if base_path.is_file() else {"data": {}}
    base_data = base.get("data", {})
    stats = base_data.get("queryGlobalStats", {})
    character_entries = base_data.get("queryCharacterRanking", {}).get("entries", [])
    music_entries = base_data.get("queryMusicRanking", {}).get("entries", [])
    cp_entries = base_data.get("queryCPRanking", {}).get("entries", [])

    expected_base = {
        10: {
            "numVote": 25707,
            "numChar": 23518,
            "numMusic": 17442,
            "numCp": 17383,
            "numDoujin": 2250,
            "numMale": 21541,
            "numFemale": 4166,
            "characters": 239,
            "music": 595,
            "cp": 790,
        },
        11: {
            "numVote": 14594,
            "numChar": 13283,
            "numMusic": 10185,
            "numCp": 9956,
            "numDoujin": 1237,
            "numMale": 12354,
            "numFemale": 2240,
            "characters": 244,
            "music": 612,
            "cp": 593,
        },
    }[config.number]
    observed_base = {
        **{key: stats.get(key) for key in expected_base if not key in {"characters", "music", "cp"}},
        "characters": len(character_entries),
        "music": len(music_entries),
        "cp": len(cp_entries),
    }
    check("base_counts_match_known_official_response", observed_base == expected_base, {
        "expected": expected_base,
        "observed": observed_base,
    })

    expected_question_counts = {10: (111, 390, 389), 11: (112, 406, 405)}[
        config.number
    ]
    question_types = dict(Counter(x.get("type") for x in questions))
    observed_question_counts = (
        len(questions),
        len(options),
        len({str(x.get("answerId")) for x in options}),
    )
    check(
        "questionnaire_definition_complete",
        observed_question_counts == expected_question_counts,
        {
            "expectedQuestionsOptionsUniqueAnswerIds": expected_question_counts,
            "observedQuestionsOptionsUniqueAnswerIds": observed_question_counts,
            "types": question_types,
            "conditionIdentity": "(questionId, answerId); answerId alone is not globally unique",
        },
    )

    categorical_ids = {
        f"q{x['id']}" for x in questions if x.get("type") != "Input"
    }
    open_ids = {f"q{x['id']}" for x in questions if x.get("type") == "Input"}
    categorical_path = root / "questionnaire" / "categorical_results.json"
    open_path = root / "questionnaire" / "open_text_results.json"
    categorical = load_json(categorical_path) if categorical_path.is_file() else {}
    open_results = load_json(open_path) if open_path.is_file() else {}
    categorical_entries = (
        categorical.get("data", {})
        .get("queryQuestionnaire", {})
        .get("entries", [])
    )
    open_entries = (
        open_results.get("data", {})
        .get("queryQuestionnaire", {})
        .get("entries", [])
    )
    categorical_observed = {str(x.get("questionId")) for x in categorical_entries}
    open_observed = {str(x.get("questionId")) for x in open_entries}
    check(
        "categorical_questionnaire_results_complete",
        categorical_observed == categorical_ids,
        {
            "expected": len(categorical_ids),
            "observed": len(categorical_observed),
            "missing": sorted(categorical_ids - categorical_observed),
            "extra": sorted(categorical_observed - categorical_ids),
        },
    )
    check(
        "open_questionnaire_results_complete",
        open_observed == open_ids,
        {
            "expected": len(open_ids),
            "observed": len(open_observed),
            "missing": sorted(open_ids - open_observed),
            "extra": sorted(open_observed - open_ids),
            "answerStringCount": sum(len(x.get("answersStr", [])) for x in open_entries),
        },
    )
    completion_items = (
        categorical.get("data", {})
        .get("queryCompletionRates", {})
        .get("items", [])
    )
    check(
        "completion_rates_present",
        len(completion_items) == 8,
        {"expected": 8, "observed": len(completion_items)},
    )

    trends_path = root / "questionnaire" / "trends.json"
    trends = load_json(trends_path) if trends_path.is_file() else {}
    trend_entries = trends.get("entries", [])
    trend_ids = {str(x.get("questionId")) for x in trend_entries}
    all_ids = {f"q{x['id']}" for x in questions}
    check(
        "questionnaire_trends_complete",
        len(trend_entries) == len(questions) and trend_ids == all_ids,
        {
            "expected": len(questions),
            "observed": len(trend_entries),
            "missing": sorted(all_ids - trend_ids),
        },
    )

    condition_missing: list[str] = []
    condition_invalid: list[str] = []
    for option in options:
        question_id = option["questionId"]
        answer_id = option["answerId"]
        path = condition_path(config, question_id, answer_id)
        query_filter = f"q{question_id}={answer_id}"
        if not path.is_file():
            condition_missing.append(path.name)
        elif not condition_checkpoint_valid(
            path,
            query_filter=query_filter,
            question_id=question_id,
            answer_id=answer_id,
        ):
            condition_invalid.append(path.name)
    check(
        "all_option_condition_rankings_complete",
        not condition_missing and not condition_invalid,
        {
            "expected": len(options),
            "valid": len(options) - len(condition_missing) - len(condition_invalid),
            "missing": condition_missing,
            "invalid": condition_invalid,
            "eachContains": ["global", "character ranking", "music ranking", "CP ranking"],
        },
    )

    covote_summary: dict[str, Any] = {}
    for key, filename, ranking_count in [
        ("character", "characters.json", len(character_entries)),
        ("music", "music.json", len(music_entries)),
    ]:
        path = root / "covote" / filename
        wrapper = load_json(path) if path.is_file() else {}
        graphql_key = "queryCharsCovote" if key == "character" else "queryMusicsCovote"
        items = wrapper.get("data", {}).get(graphql_key, {}).get("items", [])
        expected_pairs = ranking_count * (ranking_count - 1) // 2
        covote_summary[key] = {
            "topK": ranking_count,
            "expectedPairs": expected_pairs,
            "observedPairs": len(items),
        }
        check(
            f"{key}_covote_complete_matrix",
            len(items) == expected_pairs,
            covote_summary[key],
        )

    doujin_path = root / "doujin" / "summary.json"
    doujin = load_json(doujin_path) if doujin_path.is_file() else {}
    doujin_entries = doujin.get("entries", [])
    expected_page_total = {10: 2250, 11: 1272}[config.number]
    check(
        "doujin_static_summary",
        doujin.get("officialPageDisplayedTotalVotes") == expected_page_total
        and len(doujin_entries) == 10
        and not json_key_occurs(doujin, {"reasons", "reason", "desc", "voteToken"}),
        {
            "expectedPageTotal": expected_page_total,
            "observedPageTotal": doujin.get("officialPageDisplayedTotalVotes"),
            "entries": len(doujin_entries),
            "graphqlNumDoujin": stats.get("numDoujin"),
            "sameAsGraphqlAggregate": expected_page_total == stats.get("numDoujin"),
        },
    )

    static_manifest_path = root / "static" / "resource_manifest.json"
    static_manifest = load_json(static_manifest_path) if static_manifest_path.is_file() else {}
    static_records = static_manifest.get("resources", [])
    unavailable_maps = [
        x["url"] for x in static_records if x.get("available") is False
    ]
    essential_static = [
        root / "static" / "index.html",
        root / "static" / "assets" / config.index_js,
        root / "static" / "assets" / config.questionnaire_js,
        root / "static" / "assets" / (config.questionnaire_js + ".map"),
        root / "static" / "assets" / config.doujin_js,
        root / "static" / "assets" / (config.doujin_js + ".map"),
    ]
    check(
        "essential_static_provenance_present",
        all(path.is_file() and path.stat().st_size for path in essential_static),
        {
            "resourceRecords": len(static_records),
            "unavailableSourceMaps": unavailable_maps,
            "essentialFiles": [path.relative_to(root).as_posix() for path in essential_static],
        },
    )

    parsed_paths = [
        base_path,
        categorical_path,
        open_path,
        trends_path,
        doujin_path,
        root / "covote" / "characters.json",
        root / "covote" / "music.json",
    ] + [
        condition_path(config, x["questionId"], x["answerId"]) for x in options
    ]
    forbidden_files: list[str] = []
    for path in parsed_paths:
        if path.is_file():
            try:
                if json_key_occurs(load_json(path), {"reasons", "reason", "voteToken"}):
                    forbidden_files.append(path.relative_to(root).as_posix())
            except (OSError, ValueError, json.JSONDecodeError):
                pass
    check(
        "parsed_outputs_exclude_reason_and_token_fields",
        not forbidden_files,
        {"filesWithForbiddenKeys": forbidden_files},
    )

    return {
        "round": config.number,
        "voteStart": config.vote_start,
        "complete": all(item["ok"] for item in checks),
        "base": observed_base,
        "questionnaire": {
            "questions": len(questions),
            "types": question_types,
            "options": len(options),
            "uniqueAnswerIds": len({str(x.get("answerId")) for x in options}),
            "conditionFilesExpected": len(options),
        },
        "covote": covote_summary,
        "doujin": {
            "officialPageDisplayedTotalVotes": doujin.get("officialPageDisplayedTotalVotes"),
            "graphqlGlobalStatsNumDoujin": stats.get("numDoujin"),
            "topEntries": len(doujin_entries),
            "scopeNote": (
                "The static result page's displayed total and GraphQL numDoujin are distinct published measures and are not interchangeable."
                if doujin.get("officialPageDisplayedTotalVotes") != stats.get("numDoujin")
                else "The two independently published totals happen to agree in this round."
            ),
        },
        "checks": checks,
    }


def build_round_manifest(config: RoundConfig) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for path in sorted(config.root.rglob("*")):
        if not path.is_file() or path.name == "round_manifest.json":
            continue
        files.append(
            {
                "path": path.relative_to(WORKSPACE).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    manifest = {
        "schemaVersion": 1,
        "round": config.number,
        "voteStart": config.vote_start,
        "createdAt": utc_now(),
        "sourceSite": config.base_url,
        "graphqlEndpoint": ENDPOINT,
        "queryDocuments": {
            name: {"sha256": sha256_bytes(document.encode("utf-8"))}
            for name, document in QUERY_DOCUMENTS.items()
        },
        "files": files,
    }
    atomic_write_json(config.root / "round_manifest.json", manifest, pretty=True)
    return manifest


def build_global_metadata(
    configs: Sequence[RoundConfig], validations: Sequence[Mapping[str, Any]]
) -> None:
    round_manifests = [build_round_manifest(config) for config in configs]
    all_files: list[dict[str, Any]] = []
    for config in configs:
        for path in sorted(config.root.rglob("*")):
            if path.is_file():
                all_files.append(
                    {
                        "path": path.relative_to(WORKSPACE).as_posix(),
                        "bytes": path.stat().st_size,
                        "sha256": sha256_file(path),
                    }
                )
    manifest = {
        "schemaVersion": 1,
        "createdAt": utc_now(),
        "crawler": "scripts_pipeline/crawl_cn_modern.py",
        "scope": "Chinese official modern result site rounds 10 and 11",
        "graphqlEndpoint": ENDPOINT,
        "rounds": [
            {
                "round": item["round"],
                "voteStart": item["voteStart"],
                "sourceSite": item["sourceSite"],
                "fileCount": len(item["files"]) + 1,
            }
            for item in round_manifests
        ],
        "files": all_files,
    }
    atomic_write_json(
        METADATA_ROOT / "cn_modern_official_manifest.json", manifest, pretty=True
    )

    coverage = {
        "schemaVersion": 1,
        "generatedAt": utc_now(),
        "scope": "public official aggregate/static results for Chinese rounds 10 and 11",
        "rounds": list(validations),
        "publicInterfacesCaptured": [
            "global aggregate statistics",
            "complete character ranking",
            "complete music ranking",
            "complete CP ranking",
            "full questionnaire definition recovered from official source map",
            "categorical questionnaire distributions and completion rates",
            "anonymous official open-question answer arrays",
            "questionnaire hourly trends for every question",
            "global + character/music/CP rankings for every categorical answer option",
            "complete unfiltered character and music co-vote pair matrices",
            "Doujin static page displayed total and top-ten metadata",
            "official result app JavaScript and available source maps",
        ],
        "intentionalExclusions": [
            {
                "scope": "character/music/CP recommendation reasons",
                "reason": "reason bodies are not needed for association analysis and were not queried",
            },
            {
                "scope": "Doujin reasons/comments/descriptions in parsed outputs",
                "reason": "only top-ten work metadata was extracted; verbatim official JS/maps remain provenance",
            },
            {
                "scope": "getSubmitDojinVote(voteToken)",
                "reason": "private per-ballot token endpoint; never called",
            },
            {
                "scope": "conditional Doujin ranking/details",
                "reason": "the public GraphQL schema exposes no Doujin result ranking query",
            },
            {
                "scope": "images and fonts",
                "reason": "not result data; source URLs in static modules are sufficient provenance",
            },
        ],
        "knownScopeDifferences": [
            {
                "round": 11,
                "officialStaticDoujinPageDisplayedTotal": 1272,
                "graphqlGlobalStatsNumDoujin": 1237,
                "interpretation": "independently published, non-interchangeable measures; no undocumented reconciliation was imposed",
            }
        ],
        "allRequiredChecksPassed": all(item.get("complete") for item in validations),
    }
    atomic_write_json(
        METADATA_ROOT / "cn_modern_coverage.json", coverage, pretty=True
    )


def run_round(
    config: RoundConfig,
    client: PublicClient,
    *,
    node: str,
    workers: int,
    resume: bool,
    skip_conditions: bool,
    skip_covote: bool,
    trend_chunk_size: int,
) -> list[dict[str, Any]]:
    print(f"round {config.number}: start", flush=True)
    config.root.mkdir(parents=True, exist_ok=True)
    failures: list[dict[str, Any]] = []

    def stage(name: str, function: Any) -> Any:
        print(f"round {config.number}: {name}", flush=True)
        try:
            return function()
        except BaseException as exc:
            failures.append(
                {"stage": name, "error": f"{type(exc).__name__}: {exc}"}
            )
            print(f"round {config.number}: {name} FAILED: {exc}", file=sys.stderr, flush=True)
            return None

    stage("static resources", lambda: crawl_static(config, client, resume=resume))
    parsed = stage(
        "questionnaire definition", lambda: parse_questionnaire(config, node=node)
    )
    questions: list[dict[str, Any]] = parsed[0] if parsed else []
    options: list[dict[str, Any]] = parsed[1] if parsed else []

    base_path = config.root / "graphql" / "base.json"
    base = stage(
        "base rankings",
        lambda: fetch_graphql_checkpoint(
            client,
            base_path,
            "CompleteRound",
            BASE_QUERY,
            base_variables(config),
            resume=resume,
            timeout=300,
        ),
    )
    if questions:
        stage(
            "questionnaire results",
            lambda: crawl_questionnaire_results(
                config, client, questions, resume=resume
            ),
        )
        stage(
            "questionnaire trends",
            lambda: crawl_questionnaire_trends(
                config,
                client,
                questions,
                resume=resume,
                chunk_size=trend_chunk_size,
            ),
        )
    else:
        failures.append(
            {"stage": "questionnaire dependent stages", "error": "definition unavailable"}
        )
    stage("Doujin top-ten summary", lambda: extract_doujin_summary(config, node=node))
    if not skip_covote:
        if base:
            stage(
                "complete covote matrices",
                lambda: crawl_covote(config, client, base, resume=resume),
            )
        else:
            failures.append({"stage": "covote", "error": "base ranking unavailable"})
    if not skip_conditions:
        if options:
            condition_failures = crawl_conditions(
                config,
                client,
                options,
                workers=workers,
                resume=resume,
            )
            failures.extend(condition_failures)
        else:
            failures.append({"stage": "conditions", "error": "options unavailable"})
    atomic_write_json(
        config.root / "crawl_failures.json",
        {"round": config.number, "generatedAt": utc_now(), "failures": failures},
        pretty=True,
    )
    print(f"round {config.number}: finished with {len(failures)} failures", flush=True)
    return failures


def parse_rounds(value: str) -> list[RoundConfig]:
    numbers = [int(item.strip()) for item in value.split(",") if item.strip()]
    unsupported = sorted(set(numbers) - set(ROUNDS))
    if unsupported:
        raise argparse.ArgumentTypeError(f"unsupported rounds: {unsupported}")
    if not numbers:
        raise argparse.ArgumentTypeError("at least one round is required")
    return [ROUNDS[number] for number in dict.fromkeys(numbers)]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", default="10,11", help="comma-separated: 10,11")
    parser.add_argument("--workers", type=int, default=2, help="condition workers")
    parser.add_argument("--delay", type=float, default=0.20, help="seconds between request starts")
    parser.add_argument("--request-limit", type=int, default=30)
    parser.add_argument("--batch-pause", type=float, default=None)
    parser.add_argument("--worker-ceiling", type=int, default=None)
    parser.add_argument("--request-limit-ceiling", type=int, default=None)
    parser.add_argument("--batch-pause-ceiling", type=float, default=None)
    parser.add_argument(
        "--no-adaptive-tuning",
        dest="adaptive_tuning",
        action="store_false",
        help="keep configured workers/pause; retries still apply",
    )
    parser.set_defaults(adaptive_tuning=True)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--trend-chunk-size", type=int, default=25)
    parser.add_argument("--node", default="node", help="Node.js executable")
    parser.add_argument("--resume", action="store_true", help="validate and skip checkpoints")
    parser.add_argument("--skip-conditions", action="store_true")
    parser.add_argument("--skip-covote", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)

    try:
        configs = parse_rounds(args.rounds)
    except argparse.ArgumentTypeError as exc:
        parser.error(str(exc))
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if args.delay < 0:
        parser.error("--delay must be non-negative")
    if args.request_limit < 1:
        parser.error("--request-limit must be at least 1")
    if args.batch_pause is not None and args.batch_pause < 0:
        parser.error("--batch-pause must be non-negative")
    if args.trend_chunk_size < 1:
        parser.error("--trend-chunk-size must be at least 1")
    if not args.validate_only and shutil.which(args.node) is None:
        parser.error(f"Node.js executable not found: {args.node}")

    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    METADATA_ROOT.mkdir(parents=True, exist_ok=True)
    if not args.validate_only:
        speed = AdaptiveSpeed(
            workers=args.workers,
            request_limit=args.request_limit,
            pause=args.batch_pause if args.batch_pause is not None else args.delay,
            worker_ceiling=args.worker_ceiling,
            request_limit_ceiling=args.request_limit_ceiling,
            pause_ceiling=args.batch_pause_ceiling,
            adaptive_tuning=args.adaptive_tuning,
            stage_id=os.environ.get("DATA_CRAWL_QUEUE_STAGE_ID"),
        )
        client = PublicClient(
            delay=args.delay,
            retries=args.retries,
            timeout=args.timeout,
            adaptive_speed=speed,
        )
        # All selected rounds share the same modern-site content lists.  Set
        # the adaptive phase once for this invocation; including a round
        # number here would reset the learned speed at every round boundary
        # even though the crawler is still draining the same list family.
        speed.set_phase("modern_content")
        for config in configs:
            run_round(
                config,
                client,
                node=args.node,
                workers=args.workers,
                resume=args.resume,
                skip_conditions=args.skip_conditions,
                skip_covote=args.skip_covote,
                trend_chunk_size=args.trend_chunk_size,
            )

    validations: list[dict[str, Any]] = []
    for config in configs:
        try:
            validation = validate_round(config)
        except BaseException as exc:
            validation = {
                "round": config.number,
                "complete": False,
                "validationError": f"{type(exc).__name__}: {exc}",
                "checks": [],
            }
        validations.append(validation)
        print(
            f"round {config.number}: validation "
            f"{'PASS' if validation.get('complete') else 'FAIL'}",
            flush=True,
        )
    build_global_metadata(configs, validations)
    return 0 if all(item.get("complete") for item in validations) else 1


if __name__ == "__main__":
    raise SystemExit(main())

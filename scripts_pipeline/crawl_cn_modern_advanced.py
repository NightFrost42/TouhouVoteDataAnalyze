"""Archive the bounded, analytical advanced-search basis for CN rounds 10/11.

The official result UI accepts five atomic constraint families:

* one categorical questionnaire answer;
* a ballot containing one named character;
* a ballot first-voting one named character;
* a ballot containing one named music track; and
* a ballot first-voting one named music track.

For every statistically non-empty atomic entity constraint this crawler stores
global counts plus character, music, and CP rankings.  It deliberately does
not enumerate AND/OR Cartesian products: any such finite hypothesis can be
queried later from the documented DSL.  Front-end keyword/rank filters are
also omitted because they are losslessly reproducible from the archived base
ranking.  Reasons, comments, images, fonts, and token-gated ballot interfaces
are never requested.

Existing per-character/per-music conditional-ranking checkpoints are reused.
For those rows only the two other departments and global statistics are
requested, and the two official responses are combined with explicit source
hashes.  New all-department responses are also projected into compatible
same-department checkpoints so the co-vote matrices can be reconstructed
without downloading the same condition twice.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
import time
import unicodedata
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence

try:  # package import in tests
    from . import crawl_cn_modern as core
except ImportError:  # direct script execution from scripts_pipeline/
    import crawl_cn_modern as core
try:  # package import in tests
    from .cn_music_validation import reconstructed_music_matrix_checkpoint_valid
except ImportError:  # direct script execution
    from cn_music_validation import reconstructed_music_matrix_checkpoint_valid
try:  # package import in tests
    from .cn_advanced_contract import advanced_coverage_contract
except ImportError:  # direct script execution from scripts_pipeline/
    from cn_advanced_contract import advanced_coverage_contract


WORKSPACE = core.WORKSPACE
METADATA_ROOT = core.METADATA_ROOT
LOCK_PATH = METADATA_ROOT / "cn_modern_advanced_queue.lock.json"
STATUS_PATH = METADATA_ROOT / "cn_modern_advanced_queue_status.json"


ADVANCED_ALL_QUERY = f"""
query AdvancedConditionAll(
  $query: String!
  $voteStart: DateTimeUtc!
  $voteYear: Int!
) {{
  queryGlobalStats(query: $query, voteStart: $voteStart, voteYear: $voteYear) {{
    {core.GLOBAL_FIELDS}
  }}
  queryCharacterRanking(query: $query, voteStart: $voteStart, voteYear: $voteYear) {{
    global {{ {core.RANKING_GLOBAL_FIELDS} }}
    entries {{ rank displayRank name voteCount firstVoteCount }}
  }}
  queryMusicRanking(query: $query, voteStart: $voteStart, voteYear: $voteYear) {{
    global {{ {core.RANKING_GLOBAL_FIELDS} }}
    entries {{ rank displayRank name voteCount firstVoteCount }}
  }}
  queryCPRanking(query: $query, voteStart: $voteStart, voteYear: $voteYear) {{
    global {{ {core.RANKING_GLOBAL_FIELDS} }}
    entries {{ rank displayRank cp {{ a b c }} voteCount firstVoteCount }}
  }}
}}
"""


CHARACTER_ANY_COMPLEMENT_QUERY = f"""
query CharacterAnyComplement(
  $query: String!
  $voteStart: DateTimeUtc!
  $voteYear: Int!
) {{
  queryGlobalStats(query: $query, voteStart: $voteStart, voteYear: $voteYear) {{
    {core.GLOBAL_FIELDS}
  }}
  queryMusicRanking(query: $query, voteStart: $voteStart, voteYear: $voteYear) {{
    global {{ {core.RANKING_GLOBAL_FIELDS} }}
    entries {{ rank displayRank name voteCount firstVoteCount }}
  }}
  queryCPRanking(query: $query, voteStart: $voteStart, voteYear: $voteYear) {{
    global {{ {core.RANKING_GLOBAL_FIELDS} }}
    entries {{ rank displayRank cp {{ a b c }} voteCount firstVoteCount }}
  }}
}}
"""


MUSIC_ANY_COMPLEMENT_QUERY = f"""
query MusicAnyComplement(
  $query: String!
  $voteStart: DateTimeUtc!
  $voteYear: Int!
) {{
  queryGlobalStats(query: $query, voteStart: $voteStart, voteYear: $voteYear) {{
    {core.GLOBAL_FIELDS}
  }}
  queryCharacterRanking(query: $query, voteStart: $voteStart, voteYear: $voteYear) {{
    global {{ {core.RANKING_GLOBAL_FIELDS} }}
    entries {{ rank displayRank name voteCount firstVoteCount }}
  }}
  queryCPRanking(query: $query, voteStart: $voteStart, voteYear: $voteYear) {{
    global {{ {core.RANKING_GLOBAL_FIELDS} }}
    entries {{ rank displayRank cp {{ a b c }} voteCount firstVoteCount }}
  }}
}}
"""


QUESTIONNAIRE_PAIR_CELL_QUERY = """
query QuestionnairePairCell(
  $query: String!
  $voteStart: DateTimeUtc!
  $voteYear: Int!
) {
  queryGlobalStats(query: $query, voteStart: $voteStart, voteYear: $voteYear) {
    voteYear
    numVote
  }
}
"""


MUSIC_COVOTE_QUESTIONNAIRE_PARTITION_QUERY = """
query MusicCovoteQuestionnairePartition(
  $query: String!
  $voteStart: DateTimeUtc!
  $voteYear: Int!
  $topK: Int!
) {
  queryGlobalStats(query: $query, voteStart: $voteStart, voteYear: $voteYear) {
    voteYear
    numVote
    numMusic
  }
  queryMusicsCovote(
    query: $query
    voteStart: $voteStart
    voteYear: $voteYear
    topK: $topK
  ) {
    items { a b m00 m01 m10 m11 }
  }
}
"""


# A light query determines the exact filtered ranks and zero marginals before
# requesting an O(topK^2) co-vote response.  This prevents a low-vote catalogue
# item from forcing an unnecessary full 507-item matrix in every partition.
MUSIC_COVOTE_PARTITION_STATS_QUERY = """
query MusicCovotePartitionStats(
  $query: String!
  $voteStart: DateTimeUtc!
  $voteYear: Int!
) {
  queryGlobalStats(query: $query, voteStart: $voteStart, voteYear: $voteYear) {
    voteYear
    numVote
    numMusic
  }
  queryMusicRanking(query: $query, voteStart: $voteStart, voteYear: $voteYear) {
    global { totalUniqueItems totalVotes }
    entries { rank displayRank name voteCount }
  }
}
"""


# Each axis is a required ``Single`` question whose official answer counts sum
# exactly to CN11 numVote.  A leaf is refined only if both target marginals are
# nonzero and the co-vote response still exceeds the official backend limit.
MUSIC_COVOTE_REFINEMENT_AXES: tuple[tuple[str, int], ...] = (
    ("age", 11041),
    ("gender", 11011),
    ("education", 11051),
    ("student_status", 11061),
)

# Keep every requested matrix comfortably below the backend's BSON ceiling.
# A 350-item upper triangle has 61,075 pairs; the known 507/612-item requests
# fail before a response can be archived.  Oversized leaves are refined
# without issuing the unsafe request.
MUSIC_COVOTE_SAFE_TOP_K = 350

# These required ``Single`` questions have every defined answer in the official
# categorical result, but each explicit-answer total is one or two voters below
# CN11 ``numVote``.  They are therefore usable only as ordered explicit-answer
# partitions plus rigorously derived "unanswered" complements, never as the
# globally exhaustive axes above.  The final integer is the independently
# verified maximum size of that question's global complement.  Keeping several
# such axes lets a backend-null co-vote leaf be refined again without estimating
# its intersection or discarding any voter.
MUSIC_COVOTE_RESIDUAL_AXES: tuple[tuple[str, int, int], ...] = (
    ("participation_count_with_unanswered", 11091, 1),
    ("interest_start_period_with_unanswered", 11081, 1),
    ("official_interest_with_unanswered", 11101, 1),
    ("fanwork_interest_with_unanswered", 11111, 1),
    ("location_scope_with_unanswered", 11021, 2),
    ("employment_status_conditioned_on_not_student", 11071, 12419),
    ("domestic_region_conditioned_on_domestic", 11031, 322),
)

# The last two questions are branch questions rather than near-global questions.
# Their large global complements are expected, but the explicit answers become
# exhaustive inside the indicated parent branch.  Other unresolved branches
# skip an inapplicable conditional axis instead of pretending it is useful.
MUSIC_COVOTE_CONDITIONAL_AXIS_REQUIREMENTS: dict[int, tuple[int, int]] = {
    11071: (11061, 1106102),
    11031: (11021, 1102101),
}

# A global intersection for these branch-question complements is irrelevant and
# can be non-unique.  Global validation still proves the exact four-field
# explicit-plus-residual conservation identity.  Conditional residual leaves
# remain subject to the ordinary strict Fréchet uniqueness requirement.
MUSIC_COVOTE_GLOBAL_INTERSECTION_OPTIONAL = frozenset({11071, 11031})

ADVANCED_MANIFEST_DEFINITION_RELATIVE_PATHS: tuple[Path, ...] = (
    Path("graphql/base.json"),
    Path("questionnaire/questions.json"),
    Path("questionnaire/options.json"),
    Path("questionnaire/categorical_results.json"),
)


QUERY_DOCUMENTS: dict[str, str] = {
    "OptionCondition": core.CONDITION_QUERY,
    "AdvancedConditionAll": ADVANCED_ALL_QUERY,
    "CharacterAnyComplement": CHARACTER_ANY_COMPLEMENT_QUERY,
    "MusicAnyComplement": MUSIC_ANY_COMPLEMENT_QUERY,
    "QuestionnairePairCell": QUESTIONNAIRE_PAIR_CELL_QUERY,
    "CharacterCovoteConditionalSource": core.CHARACTER_COVOTE_CONDITIONAL_QUERY,
    "MusicCovoteConditionalSource": core.MUSIC_COVOTE_CONDITIONAL_QUERY,
    "MusicCovotePartitionStats": MUSIC_COVOTE_PARTITION_STATS_QUERY,
    "MusicCovoteQuestionnairePartition": MUSIC_COVOTE_QUESTIONNAIRE_PARTITION_QUERY,
}


@dataclasses.dataclass(frozen=True)
class ConditionSpec:
    source_category: str
    kind: str
    source_index: int
    source_rank: int
    source_display_rank: str
    source_name: str
    normalized_probe_name: str
    expected_cohort: int
    query_filter: str

    @property
    def dimension(self) -> str:
        return f"{self.source_category}_{self.kind}"


def source_name_metadata(spec: ConditionSpec) -> dict[str, Any]:
    """Describe the official GUI spelling and a conservative repair probe.

    The CN11 catalogue contains two music names with a trailing tab.  The
    official GUI sends that spelling unchanged, but the backend returns an
    empty cohort.  A second probe removes only trailing TAB/CR/LF controls;
    ordinary spaces (including full-width spaces) are deliberately preserved.
    Both spellings are recorded because the normalized probe also returns an
    empty cohort and therefore is not a valid substitute for official data.
    """

    removed = spec.source_name[len(spec.normalized_probe_name) :]
    return {
        "sourceName": spec.source_name,
        "officialGuiQueryName": spec.source_name,
        "normalizedProbeName": spec.normalized_probe_name,
        "normalizedProbeTransformation": (
            "rstrip_trailing_tab_cr_lf" if removed else "none"
        ),
        "removedTrailingCodePoints": [f"U+{ord(char):04X}" for char in removed],
    }


def query_filter_for_name(spec: ConditionSpec, name: str) -> str:
    filter_key = "chars" if spec.source_category == "character" else "musics"
    if spec.kind == "any":
        return f"{filter_key}: " + json.dumps([name], ensure_ascii=False)
    return f"{filter_key}_first=" + json.dumps(name, ensure_ascii=False)


def normalized_probe_path(config: core.RoundConfig, spec: ConditionSpec) -> Path:
    return (
        advanced_root(config)
        / "official_query_defect_probes"
        / spec.dimension
        / f"source_{spec.source_index:04d}_normalized.json"
    )


def official_query_defect_reason(
    value: Mapping[str, Any], spec: ConditionSpec
) -> str | None:
    """Recognize the reproducible CN11 trailing-control catalogue defect."""

    if (
        spec.source_category != "music"
        or spec.expected_cohort <= 0
        or spec.normalized_probe_name == spec.source_name
    ):
        return None
    try:
        if value["provenance"].get("status") != 200:
            return None
        if value["context"]["query"] != spec.query_filter:
            return None
        data = value["data"]
        if int(data["queryGlobalStats"]["numVote"]) != 0:
            return None
        for key in (
            "queryCharacterRanking",
            "queryMusicRanking",
            "queryCPRanking",
        ):
            if int(data[key]["global"]["totalVotes"]) != 0:
                return None
            if list(data[key]["entries"]):
                return None
    except (KeyError, TypeError, ValueError):
        return None
    return (
        "official GUI catalogue value contains trailing control characters; "
        "the official HTTP-200 advanced-search response is an empty cohort "
        f"although the unfiltered ranking reports {spec.expected_cohort} votes"
    )


def process_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


class QueueLock:
    """Cross-process atomic lock with stale-PID recovery and wait semantics."""

    def __init__(self, path: Path, *, poll_seconds: float) -> None:
        self.path = path
        self.poll_seconds = max(0.25, poll_seconds)
        self.pid = os.getpid()
        self.token = f"{self.pid}-{time.time_ns()}"
        self.owned = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        announced_pid: int | None = None
        while True:
            payload = {
                "schemaVersion": 1,
                "pid": self.pid,
                "token": self.token,
                "acquiredAt": core.utc_now(),
                "command": [sys.executable, *sys.argv],
            }
            try:
                descriptor = os.open(
                    self.path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                )
            except FileExistsError:
                try:
                    existing = core.load_json(self.path)
                    existing_pid = int(existing.get("pid", -1))
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    existing_pid = -1
                if existing_pid > 0 and process_is_alive(existing_pid):
                    if announced_pid != existing_pid:
                        print(
                            f"advanced queue lock held by PID {existing_pid}; waiting",
                            flush=True,
                        )
                        announced_pid = existing_pid
                    time.sleep(self.poll_seconds)
                    continue
                # Exact-file stale-lock recovery.  No data/checkpoint file is
                # touched, and races are resolved by the next O_EXCL attempt.
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
                continue
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            self.owned = True
            return

    def release(self) -> None:
        if not self.owned:
            return
        try:
            current = core.load_json(self.path)
            if current.get("token") == self.token:
                self.path.unlink()
        except FileNotFoundError:
            pass
        finally:
            self.owned = False


def write_queue_status(**updates: Any) -> None:
    status: dict[str, Any]
    if STATUS_PATH.is_file():
        try:
            status = core.load_json(STATUS_PATH)
        except (OSError, ValueError, json.JSONDecodeError):
            status = {}
    else:
        status = {}
    if updates.get("state") == "running":
        # Do not let a previous terminal state masquerade as the current run's
        # result while a resumed queue is still active.
        for stale_key in ("exitCode", "error"):
            status.pop(stale_key, None)
        context_changed = (
            status.get("pid") != os.getpid()
            or (
                "stage" in updates
                and updates.get("stage") != status.get("stage")
            )
            or (
                "round" in updates
                and updates.get("round") != status.get("round")
            )
        )
        if context_changed:
            for stale_key in (
                "round",
                "completed",
                "completedRequests",
                "total",
                "totalRequests",
                "remaining",
                "remainingRequests",
                "currentDimension",
                "currentSourceIndex",
                "currentSourceName",
                "currentQuery",
                "contentItems",
                "recordedFailures",
            ):
                status.pop(stale_key, None)
    status.update(
        {
            "schemaVersion": 1,
            "updatedAt": core.utc_now(),
            "pid": os.getpid(),
            "queue_stage_id": os.environ.get("DATA_CRAWL_QUEUE_STAGE_ID"),
            "queue_stage_attempt": os.environ.get("DATA_CRAWL_QUEUE_STAGE_ATTEMPT"),
            "queue_stage_started_at": os.environ.get("DATA_CRAWL_QUEUE_STAGE_STARTED_AT"),
            **updates,
        }
    )
    core.atomic_write_json(STATUS_PATH, status, pretty=True)


def advanced_root(config: core.RoundConfig) -> Path:
    return config.root / "advanced_conditions"


def response_path(config: core.RoundConfig, spec: ConditionSpec) -> Path:
    return (
        advanced_root(config)
        / "responses"
        / spec.dimension
        / f"source_{spec.source_index:04d}.json"
    )


def complement_path(config: core.RoundConfig, spec: ConditionSpec) -> Path:
    return (
        advanced_root(config)
        / "response_parts"
        / spec.dimension
        / f"source_{spec.source_index:04d}_complement.json"
    )


def covote_source_path(config: core.RoundConfig, spec: ConditionSpec) -> Path:
    return (
        config.root
        / "covote"
        / f"conditional_{spec.source_category}"
        / f"source_{spec.source_index:04d}.json"
    )


def ranking_key(category: str) -> str:
    return (
        "queryCharacterRanking"
        if category == "character"
        else "queryMusicRanking"
    )


def covote_operation(category: str) -> str:
    return (
        "CharacterCovoteConditionalSource"
        if category == "character"
        else "MusicCovoteConditionalSource"
    )


def build_specs(base: Mapping[str, Any]) -> list[ConditionSpec]:
    specs: list[ConditionSpec] = []
    for category, key, filter_key in [
        ("character", "queryCharacterRanking", "chars"),
        ("music", "queryMusicRanking", "musics"),
    ]:
        entries = list(base["data"][key]["entries"])
        names = [str(entry["name"]) for entry in entries]
        duplicates = sorted(
            name for name, count in Counter(names).items() if count > 1
        )
        if duplicates:
            raise ValueError(f"{category} catalogue has duplicate names: {duplicates}")
        for index, entry in enumerate(entries, start=1):
            name = str(entry["name"])
            normalized_probe_name = name.rstrip("\t\r\n")
            common = {
                "source_category": category,
                "source_index": index,
                "source_rank": int(entry["rank"]),
                "source_display_rank": str(entry.get("displayRank", entry["rank"])),
                "source_name": name,
                "normalized_probe_name": normalized_probe_name,
            }
            specs.append(
                ConditionSpec(
                    **common,
                    kind="any",
                    expected_cohort=int(entry["voteCount"]),
                    # Keep the whitespace used by the existing co-vote
                    # checkpoints so their variables match byte-for-byte.
                    query_filter=(
                        f"{filter_key}: "
                        + json.dumps([name], ensure_ascii=False)
                    ),
                )
            )
            specs.append(
                ConditionSpec(
                    **common,
                    kind="first",
                    expected_cohort=int(entry["firstVoteCount"]),
                    query_filter=(
                        f"{filter_key}_first="
                        + json.dumps(name, ensure_ascii=False)
                    ),
                )
            )
    # Finish the reusable co-vote basis before first-choice cohorts.
    return sorted(
        specs,
        key=lambda item: (
            0 if item.kind == "any" else 1,
            0 if item.source_category == "character" else 1,
            item.source_index,
        ),
    )


def write_query_documents(config: core.RoundConfig) -> dict[str, dict[str, Any]]:
    root = advanced_root(config) / "query_documents"
    records: dict[str, dict[str, Any]] = {}
    for operation, document in QUERY_DOCUMENTS.items():
        path = root / f"{operation}.graphql"
        core.atomic_write_bytes(path, document.strip().encode("utf-8") + b"\n")
        records[operation] = {
            "path": path.relative_to(WORKSPACE).as_posix(),
            "sha256": core.sha256_file(path),
            "documentSha256AsSent": core.sha256_bytes(document.encode("utf-8")),
        }
    return records


def fetch_checkpoint_retry(
    client: core.PublicClient,
    path: Path,
    operation: str,
    document: str,
    variables: Mapping[str, Any],
    *,
    resume: bool,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    if resume and core.graphql_checkpoint_valid(
        path, operation=operation, variables=variables
    ):
        return core.load_json(path)
    last_error: BaseException | None = None
    for attempt in range(1, client.retries + 1):
        try:
            return core.fetch_graphql_checkpoint(
                client,
                path,
                operation,
                document,
                variables,
                resume=False,
                timeout=300,
                context=context,
            )
        except BaseException as exc:
            last_error = exc
            if attempt < client.retries:
                time.sleep(min(20.0, 0.75 * (2 ** (attempt - 1))))
    assert last_error is not None
    raise last_error


def ensure_normalized_defect_probe(
    config: core.RoundConfig,
    client: core.PublicClient,
    spec: ConditionSpec,
    *,
    resume: bool,
) -> dict[str, Any]:
    """Archive the non-destructive normalized-name probe for a GUI defect."""

    query_filter = query_filter_for_name(spec, spec.normalized_probe_name)
    context = {
        "round": config.number,
        "sourceCategory": spec.source_category,
        "conditionKind": spec.kind,
        "sourceIndex": spec.source_index,
        "sourceRank": spec.source_rank,
        **source_name_metadata(spec),
        "expectedCohort": spec.expected_cohort,
        "query": query_filter,
        "probePurpose": (
            "test whether removing only trailing TAB/CR/LF repairs the "
            "official GUI catalogue query"
        ),
        "analysisPolicy": (
            "preserve as defect evidence; never substitute a zero result for "
            "the nonzero unfiltered catalogue cohort"
        ),
    }
    value = fetch_checkpoint_retry(
        client,
        normalized_probe_path(config, spec),
        "AdvancedConditionAll",
        ADVANCED_ALL_QUERY,
        core.base_variables(config, query=query_filter),
        resume=resume,
        context=context,
    )
    try:
        observed = int(value["data"]["queryGlobalStats"]["numVote"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("normalized defect probe is malformed") from exc
    if observed not in (0, spec.expected_cohort):
        raise ValueError(
            f"normalized defect probe returned unexpected cohort {observed}"
        )
    return value


def validate_rankings(
    value: Mapping[str, Any], spec: ConditionSpec
) -> tuple[bool, str | None]:
    try:
        provenance = value["provenance"]
        response_parts = provenance.get("responseParts", [])
        if response_parts:
            for part in response_parts:
                part_path = WORKSPACE / str(part["path"])
                if not part_path.is_file():
                    return False, f"missing official response part: {part['path']}"
                if core.sha256_file(part_path) != str(part["sha256"]):
                    return False, f"official response part hash mismatch: {part['path']}"
                part_value = core.load_json(part_path)
                part_provenance = part_value["provenance"]
                # A projected checkpoint references the archived raw response;
                # ordinary parts carry the original HTTP 200 directly.
                if part_provenance.get("status") != 200:
                    source_path = part_provenance.get("sourceResponsePath")
                    if not source_path:
                        return False, f"official response part lacks HTTP 200: {part['path']}"
                    source_value = core.load_json(WORKSPACE / str(source_path))
                    if source_value.get("provenance", {}).get("status") != 200:
                        return False, f"source response lacks HTTP 200: {source_path}"
                if "data" not in part_value:
                    return False, f"official response part is not parsed JSON data: {part['path']}"
        elif provenance.get("status") != 200:
            return False, "official response HTTP status is not 200"
        data = value["data"]
        if value["context"]["query"] != spec.query_filter:
            return False, "context query mismatch"
        if value["context"]["sourceName"] != spec.source_name:
            return False, "context source mismatch"
        if value["context"]["conditionKind"] != spec.kind:
            return False, "context condition kind mismatch"
        observed_cohort = int(data["queryGlobalStats"]["numVote"])
        if observed_cohort != spec.expected_cohort:
            return (
                False,
                f"global cohort {observed_cohort} != {spec.expected_cohort}",
            )
        for key in (
            "queryCharacterRanking",
            "queryMusicRanking",
            "queryCPRanking",
        ):
            result = data[key]
            if not isinstance(result["entries"], list):
                return False, f"{key} entries is not a list"
            if int(result["global"]["totalVotes"]) > observed_cohort:
                return False, f"{key} totalVotes exceeds cohort"
        own_key = ranking_key(spec.source_category)
        own_result = data[own_key]
        if int(own_result["global"]["totalVotes"]) != spec.expected_cohort:
            return False, "own-department totalVotes mismatch"
        self_entries = [
            entry
            for entry in own_result["entries"]
            if str(entry["name"]) == spec.source_name
        ]
        # The official catalogue retains some zero-vote entries, while a
        # filtered ranking correctly omits all zero rows.  Absence is therefore
        # the expected self representation for a zero-sized cohort.
        if spec.expected_cohort == 0:
            if len(self_entries) > 1:
                return False, "zero-cohort source row duplicated"
            if self_entries and (
                int(self_entries[0]["voteCount"]) != 0
                or int(self_entries[0]["firstVoteCount"]) != 0
            ):
                return False, "zero-cohort source row is nonzero"
        else:
            if len(self_entries) != 1:
                return False, "source row missing or duplicated"
            if int(self_entries[0]["voteCount"]) != spec.expected_cohort:
                return False, "source voteCount mismatch"
            if spec.kind == "first" and int(self_entries[0]["firstVoteCount"]) != spec.expected_cohort:
                return False, "source firstVoteCount mismatch"
        for key in ("queryCharacterRanking", "queryMusicRanking"):
            names = [str(entry["name"]) for entry in data[key]["entries"]]
            if len(names) != len(set(names)):
                return False, f"{key} contains duplicate names"
            if any(
                not isinstance(entry.get("voteCount"), int)
                or not isinstance(entry.get("firstVoteCount"), int)
                for entry in data[key]["entries"]
            ):
                return False, f"{key} contains non-integer counts"
        if core.json_key_occurs(value, {"reasons", "reason", "voteToken"}):
            return False, "forbidden reason/token field present"
        return True, None
    except (KeyError, TypeError, ValueError):
        return False, "malformed response"


def existing_covote_source_valid(
    config: core.RoundConfig,
    spec: ConditionSpec,
) -> bool:
    if spec.kind != "any":
        return False
    return core.conditional_covote_checkpoint_valid(
        covote_source_path(config, spec),
        operation=covote_operation(spec.source_category),
        variables=core.base_variables(config, query=spec.query_filter),
        ranking_key=ranking_key(spec.source_category),
        source_name=spec.source_name,
        source_count=spec.expected_cohort,
    )


def project_covote_source(
    config: core.RoundConfig,
    spec: ConditionSpec,
    full_response: Mapping[str, Any],
) -> None:
    if spec.kind != "any" or existing_covote_source_valid(config, spec):
        return
    output = response_path(config, spec)
    operation = covote_operation(spec.source_category)
    wrapper = {
        "provenance": {
            "source": core.ENDPOINT,
            "method": "derived projection of archived official POST response",
            "operation": str(full_response["provenance"]["operation"]),
            "variables": core.base_variables(config, query=spec.query_filter),
            "derivedAt": core.utc_now(),
            "sourceResponsePath": output.relative_to(WORKSPACE).as_posix(),
            "sourceResponseSha256": core.sha256_file(output),
        },
        "context": {
            "sourceCategory": spec.source_category,
            "sourceIndex": spec.source_index,
            "sourceRank": spec.source_rank,
            **source_name_metadata(spec),
            "sourceVoteCount": spec.expected_cohort,
            "reconstructionRole": "official conditional ranking for one matrix row",
            "compatibleOperation": operation,
        },
        "data": {
            ranking_key(spec.source_category): full_response["data"][
                ranking_key(spec.source_category)
            ]
        },
    }
    path = covote_source_path(config, spec)
    core.atomic_write_json(path, wrapper)
    if not existing_covote_source_valid(config, spec):
        raise ValueError("projected co-vote source checkpoint failed validation")


def fetch_one(
    config: core.RoundConfig,
    client: core.PublicClient,
    spec: ConditionSpec,
    *,
    resume: bool,
) -> dict[str, Any]:
    output = response_path(config, spec)
    if resume and output.is_file():
        value = core.load_json(output)
        valid, _ = validate_rankings(value, spec)
        if valid:
            project_covote_source(config, spec, value)
            return value
        if official_query_defect_reason(value, spec):
            probe = ensure_normalized_defect_probe(
                config, client, spec, resume=resume
            )
            if int(probe["data"]["queryGlobalStats"]["numVote"]) == 0:
                return value

    variables = core.base_variables(config, query=spec.query_filter)
    context = {
        "round": config.number,
        "sourceCategory": spec.source_category,
        "conditionKind": spec.kind,
        "sourceIndex": spec.source_index,
        "sourceRank": spec.source_rank,
        "sourceDisplayRank": spec.source_display_rank,
        **source_name_metadata(spec),
        "expectedCohort": spec.expected_cohort,
        "query": spec.query_filter,
        "resultScope": "global plus character, music, and CP aggregate rankings",
    }

    if spec.kind == "any" and existing_covote_source_valid(config, spec):
        partial_path = covote_source_path(config, spec)
        partial = core.load_json(partial_path)
        if spec.source_category == "character":
            operation = "CharacterAnyComplement"
            document = CHARACTER_ANY_COMPLEMENT_QUERY
        else:
            operation = "MusicAnyComplement"
            document = MUSIC_ANY_COMPLEMENT_QUERY
        complement = fetch_checkpoint_retry(
            client,
            complement_path(config, spec),
            operation,
            document,
            variables,
            resume=resume,
            context={
                **context,
                "responsePart": "global and the two departments absent from the reused same-department checkpoint",
            },
        )
        data = dict(complement["data"])
        own_key = ranking_key(spec.source_category)
        if own_key in data:
            raise ValueError(f"complement unexpectedly contains {own_key}")
        data[own_key] = partial["data"][own_key]
        value = {
            "provenance": {
                "source": core.ENDPOINT,
                "method": "two archived official POST responses combined locally",
                "operation": "AdvancedConditionAllComposite",
                "variables": variables,
                "generatedAt": core.utc_now(),
                "responseParts": [
                    {
                        "path": partial_path.relative_to(WORKSPACE).as_posix(),
                        "sha256": core.sha256_file(partial_path),
                        "operation": partial["provenance"]["operation"],
                    },
                    {
                        "path": complement_path(config, spec)
                        .relative_to(WORKSPACE)
                        .as_posix(),
                        "sha256": core.sha256_file(complement_path(config, spec)),
                        "operation": complement["provenance"]["operation"],
                    },
                ],
            },
            "context": {**context, "responseMode": "reused_same_department_plus_complement"},
            "data": data,
        }
        core.atomic_write_json(output, value)
    else:
        value = fetch_checkpoint_retry(
            client,
            output,
            "AdvancedConditionAll",
            ADVANCED_ALL_QUERY,
            variables,
            resume=False,
            context={**context, "responseMode": "single_official_all_department_response"},
        )

    valid, reason = validate_rankings(value, spec)
    if not valid:
        defect = official_query_defect_reason(value, spec)
        if defect is None:
            raise ValueError(f"advanced response validation failed: {reason}")
        probe = ensure_normalized_defect_probe(
            config, client, spec, resume=resume
        )
        if int(probe["data"]["queryGlobalStats"]["numVote"]) != 0:
            raise ValueError(
                "normalized defect probe unexpectedly returned a nonzero cohort"
            )
    else:
        project_covote_source(config, spec, value)
    return value


def condition_record(
    config: core.RoundConfig,
    spec: ConditionSpec,
    *,
    status: str,
    error: str | None = None,
) -> dict[str, Any]:
    path = response_path(config, spec)
    if spec.kind == "any" and existing_covote_source_valid(config, spec):
        reused = covote_source_path(config, spec)
    else:
        reused = None
    record: dict[str, Any] = {
        "round": config.number,
        "sourceCategory": spec.source_category,
        "conditionKind": spec.kind,
        "sourceIndex": spec.source_index,
        "sourceRank": spec.source_rank,
        "sourceDisplayRank": spec.source_display_rank,
        **source_name_metadata(spec),
        "expectedCohort": spec.expected_cohort,
        "query": spec.query_filter,
        "officialEndpoint": core.ENDPOINT,
        "method": "POST",
        "variables": core.base_variables(config, query=spec.query_filter),
        "responsePath": (
            path.relative_to(WORKSPACE).as_posix() if path.is_file() else None
        ),
        "responseSha256": core.sha256_file(path) if path.is_file() else None,
        "status": status,
    }
    if path.is_file():
        try:
            value = core.load_json(path)
            valid, validation_error = validate_rankings(value, spec)
            defect_reason = official_query_defect_reason(value, spec)
            data = value.get("data", {})
            record["parseStatus"] = (
                "valid"
                if valid
                else "valid_official_query_defect"
                if defect_reason
                else "invalid"
            )
            record["graphqlComponents"] = {
                "queryGlobalStats": {
                    "present": "queryGlobalStats" in data,
                    "numVote": data.get("queryGlobalStats", {}).get("numVote"),
                },
                "queryCharacterRanking": {
                    "present": "queryCharacterRanking" in data,
                    "entryCount": len(
                        data.get("queryCharacterRanking", {}).get("entries", [])
                    ),
                },
                "queryMusicRanking": {
                    "present": "queryMusicRanking" in data,
                    "entryCount": len(
                        data.get("queryMusicRanking", {}).get("entries", [])
                    ),
                },
                "queryCPRanking": {
                    "present": "queryCPRanking" in data,
                    "entryCount": len(
                        data.get("queryCPRanking", {}).get("entries", [])
                    ),
                },
            }
            if defect_reason:
                probe_path = normalized_probe_path(config, spec)
                record["officialQueryDefect"] = {
                    "reason": defect_reason,
                    "officialGuiObservedCohort": data.get(
                        "queryGlobalStats", {}
                    ).get("numVote"),
                    "unfilteredExpectedCohort": spec.expected_cohort,
                    "normalizedProbePath": (
                        probe_path.relative_to(WORKSPACE).as_posix()
                        if probe_path.is_file()
                        else None
                    ),
                    "normalizedProbeSha256": (
                        core.sha256_file(probe_path)
                        if probe_path.is_file()
                        else None
                    ),
                }
            elif validation_error:
                record["validationError"] = validation_error
            part_records: list[dict[str, Any]] = []
            provenance = value.get("provenance", {})
            response_parts = provenance.get("responseParts", [])
            if response_parts:
                part_paths = [WORKSPACE / item["path"] for item in response_parts]
            else:
                part_paths = [path]
            for part_path in part_paths:
                part = core.load_json(part_path)
                part_provenance = part.get("provenance", {})
                part_records.append(
                    {
                        "path": part_path.relative_to(WORKSPACE).as_posix(),
                        "sha256": core.sha256_file(part_path),
                        "operation": part_provenance.get("operation"),
                        "httpStatus": part_provenance.get("status"),
                        "contentType": part_provenance.get("contentType"),
                        "retrievedAt": part_provenance.get("retrievedAt"),
                        "jsonParsed": "data" in part,
                    }
                )
            record["officialResponseParts"] = part_records
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            record["parseStatus"] = "invalid"
            record["validationError"] = f"{type(exc).__name__}: {exc}"
    else:
        record["parseStatus"] = "not_available"
        record["graphqlComponents"] = {
            key: {"present": False}
            for key in (
                "queryGlobalStats",
                "queryCharacterRanking",
                "queryMusicRanking",
                "queryCPRanking",
            )
        }
    if reused is not None:
        record["compatibleCovoteCheckpoint"] = reused.relative_to(WORKSPACE).as_posix()
        record["compatibleCovoteCheckpointSha256"] = core.sha256_file(reused)
    if error:
        record["error"] = error
    return record


def questionnaire_condition_records(
    config: core.RoundConfig,
) -> list[dict[str, Any]]:
    options_path = config.root / "questionnaire" / "options.json"
    options = core.load_json(options_path)
    records: list[dict[str, Any]] = []
    for option in options:
        question_id = option["questionId"]
        answer_id = option["answerId"]
        query_filter = f"q{question_id}={answer_id}"
        path = core.condition_path(config, question_id, answer_id)
        valid = path.is_file() and core.condition_checkpoint_valid(
            path,
            query_filter=query_filter,
            question_id=question_id,
            answer_id=answer_id,
        )
        record: dict[str, Any] = {
                "round": config.number,
                "conditionKind": "questionnaire_answer",
                "questionId": question_id,
                "answerId": answer_id,
                "questionType": option["questionType"],
                "question": option["question"],
                "answer": option["content"],
                "query": query_filter,
                "officialEndpoint": core.ENDPOINT,
                "method": "POST",
                "operation": "OptionCondition",
                "queryDocument": "OptionCondition.graphql",
                "variables": core.base_variables(config, query=query_filter),
                "responsePath": path.relative_to(WORKSPACE).as_posix() if path.is_file() else None,
                "responseSha256": core.sha256_file(path) if path.is_file() else None,
                "status": "available_crawled" if valid else "fetch_failed" if path.is_file() else "pending",
                "parseStatus": "valid" if valid else "invalid" if path.is_file() else "not_available",
                "analysisRole": (
                    "categorical_atomic_filter"
                    if option["questionType"] != "Input"
                    else "input_placeholder_zero_filter_preserved_but_excluded_from_analysis"
                ),
            }
        if path.is_file():
            try:
                value = core.load_json(path)
                provenance = value.get("provenance", {})
                data = value.get("data", {})
                record["officialResponseParts"] = [
                    {
                        "path": path.relative_to(WORKSPACE).as_posix(),
                        "sha256": core.sha256_file(path),
                        "operation": provenance.get("operation"),
                        "httpStatus": provenance.get("status"),
                        "contentType": provenance.get("contentType"),
                        "retrievedAt": provenance.get("retrievedAt"),
                        "jsonParsed": "data" in value,
                    }
                ]
                record["graphqlComponents"] = {
                    "queryGlobalStats": {
                        "present": "queryGlobalStats" in data,
                        "numVote": data.get("queryGlobalStats", {}).get("numVote"),
                    },
                    "queryCharacterRanking": {
                        "present": "queryCharacterRanking" in data,
                        "entryCount": len(data.get("queryCharacterRanking", {}).get("entries", [])),
                    },
                    "queryMusicRanking": {
                        "present": "queryMusicRanking" in data,
                        "entryCount": len(data.get("queryMusicRanking", {}).get("entries", [])),
                    },
                    "queryCPRanking": {
                        "present": "queryCPRanking" in data,
                        "entryCount": len(data.get("queryCPRanking", {}).get("entries", [])),
                    },
                }
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                record["parseStatus"] = "invalid"
                record["validationError"] = f"{type(exc).__name__}: {exc}"
        else:
            record["graphqlComponents"] = {
                key: {"present": False}
                for key in (
                    "queryGlobalStats",
                    "queryCharacterRanking",
                    "queryMusicRanking",
                    "queryCPRanking",
                )
            }
        records.append(record)
    return records


def questionnaire_pair_query(
    question1_id: int | str,
    answer1_id: int | str,
    question2_id: int | str,
    answer2_id: int | str,
) -> str:
    """Build one explicit modern Boolean filter for a legacy pair cell."""

    q1 = str(question1_id).removeprefix("q")
    q2 = str(question2_id).removeprefix("q")
    if not q1.isdigit() or not q2.isdigit():
        raise ValueError("question ids must be decimal identifiers")
    if q1 == q2:
        raise ValueError("questionnaire pair requires two distinct questions")
    a1 = str(answer1_id)
    a2 = str(answer2_id)
    if not a1.isdigit() or not a2.isdigit():
        raise ValueError("answer ids must be decimal identifiers")
    return f"q{q1}={a1} AND q{q2}={a2}"


def questionnaire_pair_specs(config: core.RoundConfig) -> list[dict[str, Any]]:
    """Return every unordered categorical-question pair and its options."""

    options = core.load_json(config.root / "questionnaire" / "options.json")
    by_question: dict[int, list[dict[str, Any]]] = {}
    for option in options:
        if option.get("questionType") not in {"Single", "Multiple"}:
            continue
        question_id = int(option["questionId"])
        by_question.setdefault(question_id, []).append(
            {
                "optionIndex": int(option["optionIndex"]),
                "answerId": int(option["answerId"]),
                "content": str(option.get("content", "")),
            }
        )
    questions: list[dict[str, Any]] = []
    for question_id, question_options in sorted(by_question.items()):
        originals = [
            option
            for option in options
            if int(option.get("questionId", -1)) == question_id
            and option.get("questionType") in {"Single", "Multiple"}
        ]
        ordered_options = sorted(question_options, key=lambda item: item["optionIndex"])
        if [item["optionIndex"] for item in ordered_options] != list(
            range(len(ordered_options))
        ):
            raise ValueError(f"question {question_id} option indexes are not contiguous")
        if len({item["answerId"] for item in ordered_options}) != len(ordered_options):
            raise ValueError(f"question {question_id} has duplicate answer ids")
        questions.append(
            {
                "questionId": question_id,
                "question": str(originals[0].get("question", "")),
                "questionType": str(originals[0]["questionType"]),
                "options": ordered_options,
            }
        )
    return [
        {
            "question1": left,
            "question2": right,
            "answerCellCount": len(left["options"]) * len(right["options"]),
        }
        for left, right in combinations(questions, 2)
    ]


def questionnaire_pair_cells(pair: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Expand one pair into the same second-row/first-column order as CN5--9."""

    question1 = pair["question1"]
    question2 = pair["question2"]
    return [
        {
            "question1OptionIndex": option1["optionIndex"],
            "question1AnswerId": option1["answerId"],
            "question1Option": option1["content"],
            "question2OptionIndex": option2["optionIndex"],
            "question2AnswerId": option2["answerId"],
            "question2Option": option2["content"],
            "query": questionnaire_pair_query(
                question1["questionId"],
                option1["answerId"],
                question2["questionId"],
                option2["answerId"],
            ),
        }
        for option2 in question2["options"]
        for option1 in question1["options"]
    ]


def questionnaire_pair_path(
    config: core.RoundConfig, pair: Mapping[str, Any]
) -> Path:
    return (
        advanced_root(config)
        / "questionnaire_pairs"
        / (
            f"q_{int(pair['question1']['questionId']):05d}__"
            f"q_{int(pair['question2']['questionId']):05d}.json"
        )
    )


def questionnaire_pair_cell_key(cell: Mapping[str, Any]) -> tuple[int, int]:
    return (int(cell["question1AnswerId"]), int(cell["question2AnswerId"]))


def questionnaire_pair_cell_response_valid(
    value: Mapping[str, Any],
    *,
    config: core.RoundConfig,
    query: str,
) -> tuple[bool, str | None]:
    try:
        provenance = value["provenance"]
        variables = core.base_variables(config, query=query)
        if provenance["operation"] != "QuestionnairePairCell":
            return False, "operation mismatch"
        if provenance["variables"] != variables:
            return False, "variables mismatch"
        if int(provenance["status"]) != 200:
            return False, "official response HTTP status is not 200"
        stats = value["data"]["queryGlobalStats"]
        if int(stats["voteYear"]) != config.number:
            return False, "vote year mismatch"
        if type(stats["numVote"]) is not int or stats["numVote"] < 0:
            return False, "numVote is not a non-negative integer"
        return True, None
    except (KeyError, TypeError, ValueError):
        return False, "malformed pair-cell response"


def load_questionnaire_pair_checkpoint(
    config: core.RoundConfig,
    pair: Mapping[str, Any],
) -> tuple[dict[tuple[int, int], dict[str, Any]], list[str]]:
    """Load only individually valid cells from a resumable pair checkpoint."""

    path = questionnaire_pair_path(config, pair)
    if not path.is_file():
        return {}, []
    errors: list[str] = []
    try:
        payload = core.load_json(path)
        if int(payload.get("round", -1)) != config.number:
            return {}, ["round mismatch"]
        if int(payload.get("question1", {}).get("questionId", -1)) != int(
            pair["question1"]["questionId"]
        ):
            return {}, ["question1 mismatch"]
        if int(payload.get("question2", {}).get("questionId", -1)) != int(
            pair["question2"]["questionId"]
        ):
            return {}, ["question2 mismatch"]
        raw_cells = payload.get("cells", [])
        if not isinstance(raw_cells, list):
            return {}, ["cells is not a list"]
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return {}, [f"{type(exc).__name__}: {exc}"]

    expected = {
        questionnaire_pair_cell_key(cell): cell
        for cell in questionnaire_pair_cells(pair)
    }
    valid: dict[tuple[int, int], dict[str, Any]] = {}
    for offset, raw in enumerate(raw_cells):
        try:
            key = questionnaire_pair_cell_key(raw)
            spec = expected[key]
            if key in valid:
                raise ValueError("duplicate cell")
            if str(raw["query"]) != spec["query"]:
                raise ValueError("query mismatch")
            response = raw["officialResponse"]
            response_valid, reason = questionnaire_pair_cell_response_valid(
                response,
                config=config,
                query=spec["query"],
            )
            if not response_valid:
                raise ValueError(reason or "invalid official response")
            if int(raw["count"]) != int(
                response["data"]["queryGlobalStats"]["numVote"]
            ):
                raise ValueError("stored count mismatch")
            valid[key] = dict(raw)
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"cell {offset}: {exc}")
    return valid, errors


def write_questionnaire_pair_checkpoint(
    config: core.RoundConfig,
    pair: Mapping[str, Any],
    cells: Mapping[tuple[int, int], Mapping[str, Any]],
    *,
    last_failure: Mapping[str, Any] | None = None,
) -> None:
    expected_cells = questionnaire_pair_cells(pair)
    ordered = [
        dict(cells[key])
        for spec in expected_cells
        if (key := questionnaire_pair_cell_key(spec)) in cells
    ]
    complete = len(ordered) == len(expected_cells)
    payload: dict[str, Any] = {
        "schemaVersion": 1,
        "round": config.number,
        "sourceSite": config.base_url,
        "officialEndpoint": core.ENDPOINT,
        "operation": "QuestionnairePairCell",
        "queryDocument": "QuestionnairePairCell.graphql",
        "question1": pair["question1"],
        "question2": pair["question2"],
        "expectedCellCount": len(expected_cells),
        "availableCellCount": len(ordered),
        "complete": complete,
        "status": "available_crawled" if complete else "partial",
        "updatedAt": core.utc_now(),
        "cells": ordered,
    }
    if last_failure is not None:
        payload["lastFailure"] = dict(last_failure)
    core.atomic_write_json(questionnaire_pair_path(config, pair), payload)


def questionnaire_pair_coverage(config: core.RoundConfig) -> dict[str, Any]:
    pairs = questionnaire_pair_specs(config)
    available_pairs = 0
    available_cells = 0
    invalid_details: list[dict[str, Any]] = []
    for pair in pairs:
        cells, errors = load_questionnaire_pair_checkpoint(config, pair)
        expected_cells = int(pair["answerCellCount"])
        available_cells += len(cells)
        if len(cells) == expected_cells and not errors:
            available_pairs += 1
        if errors:
            invalid_details.append(
                {
                    "question1Id": pair["question1"]["questionId"],
                    "question2Id": pair["question2"]["questionId"],
                    "path": questionnaire_pair_path(config, pair)
                    .relative_to(WORKSPACE)
                    .as_posix(),
                    "errors": errors,
                }
            )
    return {
        "expectedPairs": len(pairs),
        "availablePairs": available_pairs,
        "expectedAnswerCells": sum(int(pair["answerCellCount"]) for pair in pairs),
        "availableAnswerCells": available_cells,
        "invalidDetails": invalid_details,
        "complete": available_pairs == len(pairs) and not invalid_details,
    }


def questionnaire_pair_inventory(config: core.RoundConfig) -> dict[str, Any]:
    """Describe the exact legacy-style pair surface for one modern round.

    The modern backend has no one-call cross-tab operation, but the parity
    target is finite.  Count every unordered pair and every Boolean answer
    cell that the resumable modern pair stage must archive.
    """

    pair_specs = questionnaire_pair_specs(config)
    question_ids = {
        int(pair[side]["questionId"])
        for pair in pair_specs
        for side in ("question1", "question2")
    }
    answer_options = {
        (int(pair[side]["questionId"]), int(option["answerId"]))
        for pair in pair_specs
        for side in ("question1", "question2")
        for option in pair[side]["options"]
    }
    plan: list[dict[str, Any]] = []
    for pair in pair_specs:
        question1 = pair["question1"]
        question2 = pair["question2"]
        plan.append(
            {
                "question1Id": question1["questionId"],
                "question1": question1["question"],
                "question1Type": question1["questionType"],
                "question1OptionCount": len(question1["options"]),
                "question2Id": question2["questionId"],
                "question2": question2["question"],
                "question2Type": question2["questionType"],
                "question2OptionCount": len(question2["options"]),
                "answerCellCount": pair["answerCellCount"],
                "status": "scheduled_explicit_boolean_queries",
                "checkpointPath": questionnaire_pair_path(config, pair)
                .relative_to(WORKSPACE)
                .as_posix(),
            }
        )
    return {
        "schemaVersion": 1,
        "round": config.number,
        "eligibleQuestionCount": len(question_ids),
        "eligibleAnswerOptionCount": len(answer_options),
        "unorderedQuestionPairCount": len(plan),
        "answerCellCount": sum(item["answerCellCount"] for item in plan),
        "recordUnit": "unordered_question_pair_matrix",
        "answerCellQueryForm": "qA=a AND qB=b",
        "crawlPolicy": "one rate-limited official query per answer cell; every pair checkpoint resumes independently",
        "pairs": plan,
    }


def save_progress(
    config: core.RoundConfig,
    specs: Sequence[ConditionSpec],
    records: Sequence[Mapping[str, Any]],
    failures: Sequence[Mapping[str, Any]],
    query_documents: Mapping[str, Any],
    pair_coverage_snapshot: Mapping[str, Any] | None = None,
) -> None:
    q_records = questionnaire_condition_records(config)
    pair_inventory = questionnaire_pair_inventory(config)
    pair_coverage = (
        dict(pair_coverage_snapshot)
        if pair_coverage_snapshot is not None
        else questionnaire_pair_coverage(config)
    )
    pair_plan_path = advanced_root(config) / "questionnaire_pair_plan.json"
    q_categorical = [
        item for item in q_records if item.get("questionType") in {"Single", "Multiple"}
    ]
    q_excluded = [
        item for item in q_records if item.get("questionType") not in {"Single", "Multiple"}
    ]
    entity_sources = sorted({item.source_category for item in specs})
    entity_kinds = sorted({item.kind for item in specs})
    pair_reason = (
        "modern GraphQL archive has no official all-answer questionnaire "
        "cross-tab operation; parity is restored by the resumable explicit "
        "Boolean answer-cell crawl"
    )
    # Keep an explicit, machine-readable inventory of the query vocabulary.
    # This is intentionally separate from the response index: it documents
    # combinations the UI accepts even when the backend does not publish the
    # legacy all-answer pair matrix in one response.
    combination_catalog = {
        "schemaVersion": 1,
        "round": config.number,
        "sourceSite": config.base_url,
        "families": [
            {
                "id": "questionnaire_answer",
                "conditionCount": len(q_records),
                "eligibleConditionCount": len(q_categorical),
                "excludedConditionCount": len(q_excluded),
                "questionTypes": ["Single", "Multiple"],
                "excludedQuestionTypes": ["Input", "open_text"],
                "queryForm": "q<questionId>=<answerId>",
                "combination": "singleton; AND may combine multiple answers",
            },
            {
                "id": "entity_vote",
                "conditionCount": len(records),
                "sourceCategories": entity_sources,
                "conditionKinds": entity_kinds,
                "queryForms": [
                    "chars: [<name>]",
                    "chars_first=<name>",
                    "musics: [<name>]",
                    "musics_first=<name>",
                ],
                "combination": "singleton; Boolean products are on-demand",
            },
            {
                "id": "questionnaire_pair",
                "conditionCount": pair_inventory["unorderedQuestionPairCount"],
                "eligibleConditionCount": pair_inventory["unorderedQuestionPairCount"],
                "answerCellCount": pair_inventory["answerCellCount"],
                "queryForm": "qA=a AND qB=b",
                "combination": "unordered question pair with all answer cross-cells",
                "status": (
                    "available_crawled"
                    if pair_coverage["complete"]
                    else "partial"
                    if pair_coverage["availableAnswerCells"]
                    else "pending"
                ),
                "availableConditionCount": pair_coverage["availablePairs"],
                "availableAnswerCellCount": pair_coverage["availableAnswerCells"],
                "reason": pair_reason,
            },
        ],
        "booleanQueryLanguage": {
            "operators": ["AND", "OR"],
            "grouping": ["(", ")"],
            "enumerated": False,
            "reason": "the official DSL permits an unbounded product of atomic clauses",
        },
        "legacyParityComplete": pair_coverage["complete"],
        "legacyParityReason": pair_reason,
    }
    core.atomic_write_json(
        advanced_root(config) / "combination_catalog.json",
        combination_catalog,
        pretty=True,
    )
    core.atomic_write_json(
        pair_plan_path,
        pair_inventory,
        pretty=True,
    )
    payload = {
        "schemaVersion": 1,
        "generatedAt": core.utc_now(),
        "round": config.number,
        "sourceSite": config.base_url,
        "officialEndpoint": core.ENDPOINT,
        "scope": "bounded atomic advanced-search basis; all responses contain global + character/music/CP aggregate rankings",
        "queryDocuments": query_documents,
        "questionnaireAnswerConditions": q_records,
        "questionnairePairConditions": pair_coverage,
        "entityConditions": list(records),
        "officialQueryDefects": [
            record
            for record in records
            if record.get("status") == "official_query_defect"
        ],
        "zeroCohortFirstConditions": [
            {
                "sourceCategory": spec.source_category,
                "sourceIndex": spec.source_index,
                "sourceRank": spec.source_rank,
                **source_name_metadata(spec),
                "query": spec.query_filter,
                "expectedCohort": 0,
                "status": "zero_cohort_not_requested",
                "evidence": "official unfiltered base ranking firstVoteCount=0",
            }
            for spec in specs
            if spec.kind == "first" and spec.expected_cohort == 0
        ],
        "failures": list(failures),
    }
    core.atomic_write_json(
        advanced_root(config) / "index.json", payload, pretty=True
    )
    core.atomic_write_json(
        advanced_root(config) / "failures.json",
        {
            "round": config.number,
            "generatedAt": core.utc_now(),
            "failures": list(failures),
        },
        pretty=True,
    )


def crawl_questionnaire_pairs(
    config: core.RoundConfig,
    client: core.PublicClient,
    *,
    max_requests: int | None,
    transient_failure_threshold: int = 3,
) -> tuple[list[dict[str, Any]], int]:
    """Archive every legacy-style pair cell with durable pair checkpoints.

    One official request produces one exact intersection count.  A final
    failure stops this phase after the client's normal retries so an outage
    cannot turn the remaining tens of thousands of cells into an error storm.
    Healthy requests use the same adaptive sliding window as CN5--9.
    Existing valid cells are always reused because this official result
    surface is immutable and intentionally expensive to enumerate.
    """

    pairs = questionnaire_pair_specs(config)
    coverage_before = questionnaire_pair_coverage(config)
    total_cells = int(coverage_before["expectedAnswerCells"])
    completed_cells = int(coverage_before["availableAnswerCells"])
    requests_started = 0
    planned_requests = 0
    failures: list[dict[str, Any]] = []
    consecutive_transient_failures = 0
    pair_items = [
        {
            "id": f"q{pair['question1']['questionId']}__q{pair['question2']['questionId']}",
            "round": config.number,
            "phase": "advanced_questionnaire_pairs",
            "label": f"{pair['question1']['question']} × {pair['question2']['question']}",
            "resources": int(pair["answerCellCount"]),
            "completed": 0,
            "remaining": int(pair["answerCellCount"]),
            "status": "pending",
            "current": False,
        }
        for pair in pairs
    ]
    pair_items_by_id = {item["id"]: item for item in pair_items}

    def progress_context(
        pair_index: int,
        pair: Mapping[str, Any],
        spec: Mapping[str, Any],
        cells: Mapping[tuple[int, int], Mapping[str, Any]],
    ) -> dict[str, Any]:
        question1 = pair["question1"]
        question2 = pair["question2"]
        label = f"{question1['question']} × {question2['question']}"
        item = pair_items_by_id[
            f"q{question1['questionId']}__q{question2['questionId']}"
        ]
        for other in pair_items:
            if other is item:
                continue
            other["current"] = False
            if int(other.get("completed", 0)) >= int(other.get("resources", 0)):
                other["status"] = "completed"
            else:
                other["status"] = "pending"
        item_complete = len(cells) >= int(pair["answerCellCount"])
        item.update(
            {
                "completed": len(cells),
                "remaining": max(0, int(pair["answerCellCount"]) - len(cells)),
                # Once the last cell of a pair is archived, keep that row
                # green even if the queue has not emitted the next progress
                # update yet.  Otherwise the final completed pair would stay
                # highlighted as "current" forever in the dashboard.
                "status": "completed" if item_complete else "current",
                "current": not item_complete,
            }
        )
        return {
            "currentDimension": "questionnaire_pair",
            "currentSourceIndex": pair_index,
            "currentSourceName": label,
            "currentQuery": spec["query"],
            "contentItems": pair_items,
        }

    pair_cells: dict[str, dict[tuple[int, int], Mapping[str, Any]]] = {}
    work: list[tuple[int, Mapping[str, Any], Mapping[str, Any]]] = []
    budget_exhausted = False
    for pair_index, pair in enumerate(pairs, start=1):
        cells, _ = load_questionnaire_pair_checkpoint(config, pair)
        pair_id = f"q{pair['question1']['questionId']}__q{pair['question2']['questionId']}"
        pair_cells[pair_id] = cells
        pair_item = pair_items_by_id[pair_id]
        pair_item.update(
            {
                "completed": len(cells),
                "remaining": int(pair["answerCellCount"]) - len(cells),
                "status": (
                    "completed"
                    if len(cells) == int(pair["answerCellCount"])
                    else "pending"
                ),
                "current": False,
            }
        )
        for spec in questionnaire_pair_cells(pair):
            key = questionnaire_pair_cell_key(spec)
            if key in cells:
                continue
            if max_requests is not None and planned_requests >= max_requests:
                budget_exhausted = True
                break
            planned_requests += 1
            work.append((pair_index, pair, spec))
        if budget_exhausted:
            break

    if budget_exhausted and work:
        pair_index, pair, spec = work[-1]
        pair_id = f"q{pair['question1']['questionId']}__q{pair['question2']['questionId']}"
        write_queue_status(
            state="running",
            round=config.number,
            stage="advanced_questionnaire_pairs",
            **progress_context(pair_index, pair, spec, pair_cells[pair_id]),
            completed=completed_cells,
            total=total_cells,
            currentPair=pair_index,
            totalPairs=len(pairs),
            remaining=total_cells - completed_cells,
            remainingRequests=total_cells - completed_cells,
            recordedFailures=0,
            **(
                client.adaptive_speed.status()
                if isinstance(getattr(client, "adaptive_speed", None), core.AdaptiveSpeed)
                else {}
            ),
        )

    def fetch_cell(
        item: tuple[int, Mapping[str, Any], Mapping[str, Any]]
    ) -> Mapping[str, Any]:
        _, _, spec = item
        query = str(spec["query"])
        response = client.graphql(
            "QuestionnairePairCell",
            QUESTIONNAIRE_PAIR_CELL_QUERY,
            core.base_variables(config, query=query),
            timeout=300,
        )
        valid, reason = questionnaire_pair_cell_response_valid(
            response,
            config=config,
            query=query,
        )
        if not valid:
            raise ValueError(reason or "invalid pair-cell response")
        return response

    completed_this_run = 0
    for item, response, caught in core.adaptive_map(work, fetch_cell, client=client):
        requests_started += 1
        pair_index, pair, spec = item
        pair_id = f"q{pair['question1']['questionId']}__q{pair['question2']['questionId']}"
        cells = pair_cells[pair_id]
        key = questionnaire_pair_cell_key(spec)
        query = str(spec["query"])
        should_stop_after_failure = False
        if caught is not None:
            transient = core.transient_failure_reason(caught) is not None
            consecutive_transient_failures = (
                consecutive_transient_failures + 1 if transient else 0
            )
            failure = {
                "stage": "advanced_questionnaire_pair_cell",
                "question1Id": pair["question1"]["questionId"],
                "question1AnswerId": spec["question1AnswerId"],
                "question2Id": pair["question2"]["questionId"],
                "question2AnswerId": spec["question2AnswerId"],
                "query": query,
                "status": "fetch_failed",
                "error": f"{type(caught).__name__}: {caught}",
                "transient": transient,
            }
            failures.append(failure)
            write_questionnaire_pair_checkpoint(
                config, pair, cells, last_failure=failure
            )
            should_stop_after_failure = (
                not transient
                or consecutive_transient_failures >= transient_failure_threshold
            )
        else:
            consecutive_transient_failures = 0
            assert response is not None
            cells[key] = {
                **spec,
                "count": int(response["data"]["queryGlobalStats"]["numVote"]),
                "officialResponse": response,
            }
            write_questionnaire_pair_checkpoint(config, pair, cells)
            completed_cells += 1
            completed_this_run += 1
            pair_items_by_id[pair_id].update(
                {
                    "completed": len(cells),
                    "remaining": int(pair["answerCellCount"]) - len(cells),
                }
            )

        if caught is not None or completed_this_run == 1 or completed_this_run % 25 == 0:
            write_queue_status(
                state="running",
                round=config.number,
                stage="advanced_questionnaire_pairs",
                **progress_context(pair_index, pair, spec, cells),
                completed=completed_cells,
                total=total_cells,
                currentPair=pair_index,
                totalPairs=len(pairs),
                remaining=total_cells - completed_cells,
                remainingRequests=total_cells - completed_cells,
                recordedFailures=len(failures),
                **(
                    client.adaptive_speed.status()
                    if isinstance(getattr(client, "adaptive_speed", None), core.AdaptiveSpeed)
                    else {}
                ),
            )
        if should_stop_after_failure:
            # Closing the adaptive generator prevents refills; only already
            # admitted peers are allowed to drain inside its executor.
            break
        if completed_this_run == 1 or completed_this_run % 25 == 0:
            print(
                f"round {config.number} questionnaire pair cells: "
                f"{completed_cells}/{total_cells}",
                flush=True,
            )
    return failures, requests_started


def crawl_round(
    config: core.RoundConfig,
    client: core.PublicClient,
    *,
    resume: bool,
    max_requests: int | None,
    transient_failure_threshold: int = 3,
) -> list[dict[str, Any]]:
    if isinstance(getattr(client, "adaptive_speed", None), core.AdaptiveSpeed):
        # Treat the answer-condition pass and the expensive pair-cell pass as
        # separate content families.  A safety reduction learned for one
        # query shape should not silently throttle (or overdrive) the other.
        # The condition crawl is one logical content list for the whole
        # invocation (CN10 and CN11 are merely two partitions of that list).
        # Keep one adaptive phase key across rounds so moving to the next
        # round does not throw away the speed learned from the preceding
        # items.  A different content family (the pair-cell list below) still
        # gets its own phase and therefore its own deliberate boundary.
        client.adaptive_speed.set_phase("advanced_conditions")
    base_path = config.root / "graphql" / "base.json"
    if not base_path.is_file():
        raise FileNotFoundError(f"missing official base ranking: {base_path}")
    base = core.load_json(base_path)
    specs = build_specs(base)
    query_documents = write_query_documents(config)
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    requests_started = 0
    pair_coverage_snapshot = questionnaire_pair_coverage(config)
    meaningful = [
        spec
        for spec in specs
        if spec.kind == "any" or spec.expected_cohort > 0
    ]
    total = len(meaningful)
    # Build the resumable work list first.  The adaptive pool then keeps up to
    # the currently safe number of requests in flight and refills immediately
    # when a fast response completes (the CN5--9 crawler's sliding-window
    # behaviour).
    pending_specs: list[ConditionSpec] = []
    processed = 0
    for spec in meaningful:
        path = response_path(config, spec)
        already_accounted = False
        if resume and path.is_file():
            try:
                value = core.load_json(path)
                already_accounted = bool(
                    validate_rankings(value, spec)[0]
                    or official_query_defect_reason(value, spec)
                )
            except (OSError, ValueError, json.JSONDecodeError):
                already_accounted = False
        if max_requests is not None and requests_started >= max_requests and not already_accounted:
            records.append(condition_record(config, spec, status="pending"))
            continue
        if already_accounted:
            records.append(condition_record(config, spec, status=(
                "official_query_defect"
                if official_query_defect_reason(core.load_json(path), spec)
                else "available_crawled"
            )))
            processed += 1
            continue
        requests_started += 1
        pending_specs.append(spec)

    def fetch_condition(spec: ConditionSpec) -> Mapping[str, Any]:
        return fetch_one(config, client, spec, resume=resume)

    for spec, value, caught in core.adaptive_map(
        pending_specs, fetch_condition, client=client
    ):
        processed += 1
        try:
            if caught is not None:
                raise caught
            status = (
                "official_query_defect"
                if official_query_defect_reason(value, spec)
                else "available_crawled"
            )
            records.append(
                condition_record(config, spec, status=status)
            )
        except BaseException as exc:
            failure = {
                "sourceCategory": spec.source_category,
                "conditionKind": spec.kind,
                "sourceIndex": spec.source_index,
                "sourceRank": spec.source_rank,
                **source_name_metadata(spec),
                "expectedCohort": spec.expected_cohort,
                "query": spec.query_filter,
                "status": "fetch_failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
            failures.append(failure)
            records.append(
                condition_record(
                    config,
                    spec,
                    status="fetch_failed",
                    error=failure["error"],
                )
            )
        if processed == 1 or processed % 25 == 0 or processed == total:
            save_progress(
                config,
                specs,
                records,
                failures,
                query_documents,
                pair_coverage_snapshot,
            )
            write_queue_status(
                state="running",
                round=config.number,
                stage="advanced_conditions",
                completed=processed,
                total=total,
                currentDimension=spec.dimension,
                currentSourceIndex=spec.source_index,
                currentSourceName=spec.source_name,
                recordedFailures=len(failures),
                **(
                    client.adaptive_speed.status()
                if isinstance(getattr(client, "adaptive_speed", None), core.AdaptiveSpeed)
                    else {}
                ),
            )
            print(
                f"round {config.number} advanced conditions: {processed}/{total}; "
                f"failures={len(failures)}",
                flush=True,
            )
    remaining_request_budget = (
        None
        if max_requests is None
        else max(0, max_requests - requests_started)
    )
    if isinstance(getattr(client, "adaptive_speed", None), core.AdaptiveSpeed):
        # Pair cells form one logical list per content family.  Do not include
        # the round number in the phase key: when a resumed CN10/11 run moves
        # between round partitions, the controller must retain the speed
        # already proven safe while it is still crawling this list family.
        client.adaptive_speed.set_phase("questionnaire_pairs")
    pair_failures, pair_requests = crawl_questionnaire_pairs(
        config,
        client,
        max_requests=remaining_request_budget,
        transient_failure_threshold=transient_failure_threshold,
    )
    requests_started += pair_requests
    failures.extend(pair_failures)
    save_progress(
        config,
        specs,
        records,
        failures,
        query_documents,
        questionnaire_pair_coverage(config),
    )
    return failures


class QuestionnairePartitionSchemeError(RuntimeError):
    """Carry the complete partial-attempt audit into the fallback decision."""

    def __init__(self, message: str, attempt: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.attempt = dict(attempt)


def strict_nonnegative_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def decimal_identifier(value: Any, label: str) -> int:
    if type(value) is int and value >= 0:
        return value
    if (
        isinstance(value, str)
        and value
        and value.isascii()
        and value.isdigit()
    ):
        return int(value)
    raise ValueError(f"{label} must be a decimal identifier")


def questionnaire_question_identifier(value: Any) -> int:
    text = str(value)
    if text.startswith("q"):
        text = text[1:]
    return decimal_identifier(text, "questionId")


def build_questionnaire_partition_plan(
    *,
    question_id: int,
    questions: Sequence[Mapping[str, Any]],
    options: Sequence[Mapping[str, Any]],
    categorical_entries: Sequence[Mapping[str, Any]],
    expected_total_voters: int,
) -> dict[str, Any]:
    """Prove that one official question defines an exhaustive partition."""

    expected_total_voters = strict_nonnegative_int(
        expected_total_voters, "expectedTotalVoters"
    )
    selected_questions = [
        item
        for item in questions
        if decimal_identifier(item.get("id"), "question.id") == question_id
    ]
    if len(selected_questions) != 1:
        raise ValueError(
            f"question {question_id} occurs {len(selected_questions)} times"
        )
    question = selected_questions[0]
    if str(question.get("type")) != "Single":
        raise ValueError(f"question {question_id} is not Single")
    if str(question.get("questionnaireKey")) != "requiredQuestionnaire":
        raise ValueError(f"question {question_id} is not in the required questionnaire")

    selected_options = [
        item
        for item in options
        if decimal_identifier(item.get("questionId"), "option.questionId")
        == question_id
    ]
    option_count = strict_nonnegative_int(
        question.get("optionCount"), "question.optionCount"
    )
    if not selected_options or len(selected_options) != option_count:
        raise ValueError(
            f"question {question_id} option coverage is "
            f"{len(selected_options)}/{option_count}"
        )
    selected_options.sort(
        key=lambda item: strict_nonnegative_int(
            item.get("optionIndex"), "option.optionIndex"
        )
    )
    option_indexes = [
        strict_nonnegative_int(item.get("optionIndex"), "option.optionIndex")
        for item in selected_options
    ]
    if option_indexes != list(range(option_count)):
        raise ValueError(f"question {question_id} option indexes are not complete")
    answer_ids = [
        decimal_identifier(item.get("answerId"), "option.answerId")
        for item in selected_options
    ]
    if len(answer_ids) != len(set(answer_ids)):
        raise ValueError(f"question {question_id} has duplicate answerId values")
    if any(str(item.get("questionType")) != "Single" for item in selected_options):
        raise ValueError(f"question {question_id} option type disagrees with Single")

    selected_results = [
        item
        for item in categorical_entries
        if questionnaire_question_identifier(item.get("questionId")) == question_id
    ]
    if len(selected_results) != 1:
        raise ValueError(
            f"categorical result for question {question_id} occurs "
            f"{len(selected_results)} times"
        )
    result = selected_results[0]
    answer_counts: dict[int, int] = {}
    for answer in result.get("answersCat", []):
        answer_id = decimal_identifier(answer.get("aid"), "answersCat.aid")
        if answer_id in answer_counts:
            raise ValueError(
                f"question {question_id} categorical results duplicate {answer_id}"
            )
        answer_counts[answer_id] = strict_nonnegative_int(
            answer.get("totalVotes"), "answersCat.totalVotes"
        )
    if set(answer_counts) != set(answer_ids):
        raise ValueError(
            f"question {question_id} official result answer coverage differs "
            "from the full option definition"
        )
    total_answers = strict_nonnegative_int(
        result.get("totalAnswers"), "question.totalAnswers"
    )
    if sum(answer_counts.values()) != total_answers:
        raise ValueError(
            f"question {question_id} option counts do not sum to totalAnswers"
        )
    if total_answers != expected_total_voters:
        raise ValueError(
            f"question {question_id} totalAnswers {total_answers} != "
            f"round numVote {expected_total_voters}"
        )

    partitions = [
        {
            "questionId": question_id,
            "answerId": answer_id,
            "answer": str(option.get("content", "")),
            "optionIndex": strict_nonnegative_int(
                option.get("optionIndex"), "option.optionIndex"
            ),
            "expectedNumVote": answer_counts[answer_id],
            "query": f"q{question_id}={answer_id}",
        }
        for option, answer_id in zip(selected_options, answer_ids)
    ]
    return {
        "questionId": question_id,
        "question": str(question.get("question", "")),
        "questionType": "Single",
        "questionnaireKey": "requiredQuestionnaire",
        "optionCount": option_count,
        "totalAnswers": total_answers,
        "partitions": partitions,
        "mutualExclusionAndCoverageProof": {
            "questionTypeIsSingle": True,
            "answerIdsAreUnique": True,
            "allDefinedOptionsCovered": True,
            "officialResultAnswerSetEqualsDefinedOptionSet": True,
            "sumOfficialOptionVoters": sum(answer_counts.values()),
            "officialQuestionTotalAnswers": total_answers,
            "roundNumVote": expected_total_voters,
            "allThreeVoterTotalsEqual": True,
        },
    }


def build_questionnaire_residual_partition_plan(
    *,
    question_id: int,
    questions: Sequence[Mapping[str, Any]],
    options: Sequence[Mapping[str, Any]],
    categorical_entries: Sequence[Mapping[str, Any]],
    expected_total_voters: int,
    max_unanswered_voters: int,
) -> dict[str, Any]:
    """Prove explicit Single answers plus a bounded unanswered residual.

    ``build_questionnaire_partition_plan`` remains deliberately strict for
    globally exhaustive axes.  This wrapper first validates the complete
    explicit answer catalogue against its own official ``totalAnswers``, then
    proves that the only gap to round ``numVote`` is a small complement cohort.
    """

    expected_total_voters = strict_nonnegative_int(
        expected_total_voters, "expectedTotalVoters"
    )
    max_unanswered_voters = strict_nonnegative_int(
        max_unanswered_voters, "maxUnansweredVoters"
    )
    selected_results = [
        item
        for item in categorical_entries
        if questionnaire_question_identifier(item.get("questionId")) == question_id
    ]
    if len(selected_results) != 1:
        raise ValueError(
            f"categorical result for question {question_id} occurs "
            f"{len(selected_results)} times"
        )
    explicit_total = strict_nonnegative_int(
        selected_results[0].get("totalAnswers"), "question.totalAnswers"
    )
    explicit_plan = build_questionnaire_partition_plan(
        question_id=question_id,
        questions=questions,
        options=options,
        categorical_entries=categorical_entries,
        expected_total_voters=explicit_total,
    )
    if explicit_total > expected_total_voters:
        raise ValueError(
            f"question {question_id} totalAnswers {explicit_total} exceeds "
            f"round numVote {expected_total_voters}"
        )
    unanswered = expected_total_voters - explicit_total
    if unanswered > max_unanswered_voters:
        raise ValueError(
            f"question {question_id} unanswered residual {unanswered} exceeds "
            f"safe maximum {max_unanswered_voters}"
        )
    return {
        key: explicit_plan[key]
        for key in (
            "questionId",
            "question",
            "questionType",
            "questionnaireKey",
            "optionCount",
            "totalAnswers",
            "partitions",
        )
    } | {
        "globalNumVote": expected_total_voters,
        "unansweredResidualVoters": unanswered,
        "maxUnansweredResidualVoters": max_unanswered_voters,
        "mutualExclusionAndCoverageProof": {
            "questionTypeIsSingle": True,
            "answerIdsAreUnique": True,
            "allDefinedOptionsCovered": True,
            "officialResultAnswerSetEqualsDefinedOptionSet": True,
            "sumOfficialExplicitOptionVoters": explicit_total,
            "officialQuestionTotalAnswers": explicit_total,
            "roundNumVote": expected_total_voters,
            "unansweredResidualDefinedAsRoundMinusExplicitAnswers": unanswered,
            "unansweredResidualWithinSafeMaximum": True,
            "explicitAnswersPlusResidualEqualsRoundNumVote": (
                explicit_total + unanswered == expected_total_voters
            ),
            "explicitAnswersAreMutuallyExclusiveAndResidualIsTheirComplement": True,
        },
    }


def orient_music_pair_item(
    item: Mapping[str, Any], target_a: str, target_b: str
) -> dict[str, Any]:
    """Orient a contingency item to target_a/target_b without changing m00/m11."""

    returned_a = str(item["a"])
    returned_b = str(item["b"])
    if returned_a == returned_b or {returned_a, returned_b} != {target_a, target_b}:
        raise ValueError("response item is not the requested distinct target pair")
    cells = {
        key: strict_nonnegative_int(item.get(key), f"targetPair.{key}")
        for key in ("m00", "m01", "m10", "m11")
    }
    reversed_direction = returned_a == target_b and returned_b == target_a
    if reversed_direction:
        cells["m01"], cells["m10"] = cells["m10"], cells["m01"]
    elif returned_a != target_a or returned_b != target_b:
        raise ValueError("response item direction cannot be oriented")
    return {
        "a": target_a,
        "b": target_b,
        **cells,
        "returnedDirection": {"a": returned_a, "b": returned_b},
        "returnedDirectionReversed": reversed_direction,
    }


def music_partition_query(filters: Sequence[tuple[int, int]]) -> str:
    if not filters:
        raise ValueError("a partition query requires at least one filter")
    question_ids = [question_id for question_id, _ in filters]
    if len(question_ids) != len(set(question_ids)):
        raise ValueError("a partition query cannot repeat a question")
    return " AND ".join(
        f"q{question_id}={answer_id}" for question_id, answer_id in filters
    )


def conditional_residual_axis_applicable(
    partition: Mapping[str, Any], question_id: int
) -> bool:
    """Return whether a branch-question axis applies to this exact parent."""

    requirement = MUSIC_COVOTE_CONDITIONAL_AXIS_REQUIREMENTS.get(question_id)
    if requirement is None:
        return True
    observed = {
        (
            decimal_identifier(item["questionId"], "filter.questionId"),
            decimal_identifier(item["answerId"], "filter.answerId"),
        )
        for item in partition.get("filters", [])
    }
    return requirement in observed


def music_partition_key(filters: Sequence[tuple[int, int]]) -> str:
    return "__".join(
        f"q{question_id}_a{answer_id}" for question_id, answer_id in filters
    )


def music_partition_stats_path(
    config: core.RoundConfig, filters: Sequence[tuple[int, int]]
) -> Path:
    return (
        config.root
        / "covote"
        / "music_missing_pair_partitions"
        / f"{music_partition_key(filters)}_stats.json"
    )


def music_partition_covote_path(
    config: core.RoundConfig,
    filters: Sequence[tuple[int, int]],
    *,
    top_k: int,
) -> Path:
    return (
        config.root
        / "covote"
        / "music_missing_pair_partitions"
        / f"{music_partition_key(filters)}_covote_top{top_k}.json"
    )


def music_partition_residual_path(
    config: core.RoundConfig,
    parent_filters: Sequence[tuple[int, int]],
    *,
    question_id: int,
) -> Path:
    parent_key = music_partition_key(parent_filters) if parent_filters else "root"
    return (
        config.root
        / "covote"
        / "music_missing_pair_partitions"
        / f"{parent_key}__q{question_id}_unanswered_residual_stats.json"
    )


def has_trailing_unicode_control(value: str) -> bool:
    """Return whether the final code point is in Unicode category ``Cc``."""

    return bool(value) and unicodedata.category(value[-1]) == "Cc"


def music_witness_query(parent_query: str, witness_name: str) -> str:
    parent_query = str(parent_query)
    witness_name = str(witness_name)
    if not parent_query or not witness_name:
        raise ValueError("witness split requires a non-empty parent query and name")
    return (
        parent_query
        + " AND musics: "
        + json.dumps([witness_name], ensure_ascii=False)
    )


def music_witness_evidence_key(parent_query: str, witness_name: str) -> str:
    return canonical_json_sha256(
        {"parentQuery": str(parent_query), "witnessName": str(witness_name)}
    )


def music_witness_stats_path(
    config: core.RoundConfig, parent_query: str, witness_name: str
) -> Path:
    key = music_witness_evidence_key(parent_query, witness_name)
    return (
        config.root
        / "covote"
        / "music_missing_pair_partitions"
        / f"witness_{key}_stats.json"
    )


def music_witness_proof_path(
    config: core.RoundConfig, parent_query: str, witness_name: str
) -> Path:
    key = music_witness_evidence_key(parent_query, witness_name)
    return (
        config.root
        / "covote"
        / "music_missing_pair_partitions"
        / f"witness_{key}_proof.json"
    )


def music_partition_file_record(path: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": path.relative_to(WORKSPACE).as_posix(),
        "exists": path.is_file(),
    }
    if path.is_file():
        record["bytes"] = path.stat().st_size
        record["sha256"] = core.sha256_file(path)
    return record


def load_prior_partition_audit_history(path: Path) -> list[dict[str, Any]]:
    """Flatten the previous attempts audit before its atomic replacement."""

    if not path.is_file():
        return []
    evidence = music_partition_file_record(path)
    try:
        previous = core.load_json(path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return [
            {
                "archivedAt": core.utc_now(),
                "sourceFile": evidence,
                "loadError": f"{type(exc).__name__}: {exc}",
            }
        ]
    if not isinstance(previous, Mapping):
        return [
            {
                "archivedAt": core.utc_now(),
                "sourceFile": evidence,
                "loadError": "previous attempts audit is not an object",
            }
        ]
    inherited = previous.get("priorRunHistory", [])
    history = list(inherited) if isinstance(inherited, list) else []
    snapshot = {
        str(key): value
        for key, value in previous.items()
        if str(key) != "priorRunHistory"
    }
    history.append(
        {
            "archivedAt": core.utc_now(),
            "sourceFile": evidence,
            "audit": snapshot,
        }
    )
    return history


def equivalent_vote_start(left: Any, right: Any) -> bool:
    return str(left).replace(".000Z", "Z") == str(right).replace(".000Z", "Z")


def music_partition_stats_variables_match(
    variables: Any,
    config: core.RoundConfig,
    *,
    query_filter: str,
) -> bool:
    """Accept only the three official variables, with equivalent UTC spelling."""

    return (
        isinstance(variables, Mapping)
        and set(variables) == {"query", "voteStart", "voteYear"}
        and variables.get("query") == query_filter
        and type(variables.get("voteYear")) is int
        and variables.get("voteYear") == config.number
        and isinstance(variables.get("voteStart"), str)
        and equivalent_vote_start(variables.get("voteStart"), config.vote_start)
    )


def canonical_json_sha256(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return core.sha256_bytes(payload)


def ranking_name_sequence(entries: Sequence[Mapping[str, Any]]) -> list[str]:
    ordered = sorted(
        entries,
        key=lambda entry: strict_nonnegative_int(entry.get("rank"), "ranking.rank"),
    )
    names = [str(entry.get("name")) for entry in ordered]
    if any(not name for name in names) or len(names) != len(set(names)):
        raise ValueError("partition ranking name sequence is malformed or non-unique")
    return names


def endpoint_set_evidence(names_by_rank: Sequence[str], top_k: int) -> dict[str, Any]:
    top_k = strict_nonnegative_int(top_k, "topK")
    if top_k < 2 or top_k > len(names_by_rank):
        raise ValueError("topK is outside the validated ranking name sequence")
    endpoints = list(names_by_rank[:top_k])
    canonical_endpoints = sorted(endpoints)
    canonical_pairs = sorted(
        (min(left, right), max(left, right))
        for left, right in combinations(endpoints, 2)
    )
    return {
        "topK": top_k,
        "endpointCount": len(endpoints),
        "endpointNamesByRank": endpoints,
        "endpointNamesByRankSha256": canonical_json_sha256(endpoints),
        "canonicalEndpointSetSha256": canonical_json_sha256(canonical_endpoints),
        "expectedUnorderedPairCount": len(canonical_pairs),
        "expectedUnorderedPairSetSha256": canonical_json_sha256(canonical_pairs),
    }


def target_music_ranking_record(
    entries: Sequence[Mapping[str, Any]], target_name: str
) -> dict[str, Any]:
    matches = [entry for entry in entries if str(entry.get("name")) == target_name]
    if len(matches) > 1:
        raise ValueError("filtered music ranking duplicates a target name")
    if not matches:
        return {"name": target_name, "voteCount": 0, "rank": None}
    entry = matches[0]
    count = strict_nonnegative_int(entry.get("voteCount"), "target.voteCount")
    rank = strict_nonnegative_int(entry.get("rank"), "target.rank")
    if count <= 0 or rank <= 0:
        raise ValueError("a present target ranking row must have positive count and rank")
    if rank > len(entries):
        raise ValueError("target rank exceeds filtered ranking entry count")
    return {"name": target_name, "voteCount": count, "rank": rank}


def validate_music_partition_stats_response(
    value: Mapping[str, Any],
    config: core.RoundConfig,
    filters: Sequence[tuple[int, int]],
    *,
    target_a: str,
    target_b: str,
    operation: str,
    document: str,
    query_filter_override: str | None = None,
) -> dict[str, Any]:
    query_filter = (
        music_partition_query(filters)
        if query_filter_override is None
        else str(query_filter_override)
    )
    if not query_filter:
        raise ValueError("partition stats query is empty")
    provenance = value["provenance"]
    if provenance.get("source") != core.ENDPOINT:
        raise ValueError("partition stats source is not the official endpoint")
    if provenance.get("method") != "POST":
        raise ValueError("partition stats method is not POST")
    if provenance.get("operation") != operation:
        raise ValueError("partition stats operation mismatch")
    if provenance.get("status") != 200:
        raise ValueError("partition stats HTTP status is not 200")
    if "json" not in str(provenance.get("contentType", "")).lower():
        raise ValueError("partition stats content type is not JSON")
    if provenance.get("documentSha256") != core.sha256_bytes(document.encode("utf-8")):
        raise ValueError("partition stats document hash mismatch")
    if not music_partition_stats_variables_match(
        provenance.get("variables"), config, query_filter=query_filter
    ):
        raise ValueError("partition stats variables mismatch")

    data = value["data"]
    stats = data["queryGlobalStats"]
    if strict_nonnegative_int(stats.get("voteYear"), "stats.voteYear") != config.number:
        raise ValueError("partition stats voteYear mismatch")
    num_vote = strict_nonnegative_int(stats.get("numVote"), "stats.numVote")
    num_music = strict_nonnegative_int(stats.get("numMusic"), "stats.numMusic")
    if num_music > num_vote:
        raise ValueError("partition stats numMusic exceeds numVote")
    ranking = data["queryMusicRanking"]
    entries = ranking["entries"]
    if not isinstance(entries, list):
        raise ValueError("partition music ranking entries is not a list")
    names: set[str] = set()
    ranks: set[int] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValueError("partition music ranking contains a non-object entry")
        name = str(entry.get("name"))
        rank = strict_nonnegative_int(entry.get("rank"), "ranking.rank")
        count = strict_nonnegative_int(entry.get("voteCount"), "ranking.voteCount")
        if not name or name in names or rank <= 0 or rank in ranks or count <= 0:
            raise ValueError("partition music ranking has duplicate/zero malformed rows")
        names.add(name)
        ranks.add(rank)
    expected_ranks = set(range(1, len(entries) + 1))
    if ranks != expected_ranks:
        raise ValueError("partition music ranking ranks are not exactly 1..N")
    ordered_entries = sorted(
        entries,
        key=lambda entry: strict_nonnegative_int(entry.get("rank"), "ranking.rank"),
    )
    names_by_rank = ranking_name_sequence(ordered_entries)
    vote_counts_by_rank = [
        strict_nonnegative_int(entry.get("voteCount"), "ranking.voteCount")
        for entry in ordered_entries
    ]
    ranking_global = ranking["global"]
    if strict_nonnegative_int(
        ranking_global.get("totalUniqueItems"), "ranking.totalUniqueItems"
    ) != len(entries):
        raise ValueError("partition ranking totalUniqueItems mismatch")
    if strict_nonnegative_int(
        ranking_global.get("totalVotes"), "ranking.totalVotes"
    ) != num_music:
        raise ValueError("partition ranking totalVotes != global numMusic")
    return {
        "filters": [
            {"questionId": question_id, "answerId": answer_id}
            for question_id, answer_id in filters
        ],
        "query": query_filter,
        "numVote": num_vote,
        "numMusic": num_music,
        "rankingEntryCount": len(entries),
        "rankingNamesByRank": names_by_rank,
        "rankingNamesByRankSha256": canonical_json_sha256(names_by_rank),
        "rankingVoteCountsByRank": vote_counts_by_rank,
        "rankingVoteCountsByRankSha256": canonical_json_sha256(
            vote_counts_by_rank
        ),
        "targetA": target_music_ranking_record(entries, target_a),
        "targetB": target_music_ranking_record(entries, target_b),
    }


def load_or_fetch_music_partition_stats(
    config: core.RoundConfig,
    client: core.PublicClient,
    filters: Sequence[tuple[int, int]],
    *,
    target_a: str,
    target_b: str,
) -> dict[str, Any]:
    """Reuse an atomic official response, otherwise fetch one minimal ranking."""

    query_filter = music_partition_query(filters)
    if len(filters) == 1:
        question_id, answer_id = filters[0]
        atomic_path = core.condition_path(config, question_id, answer_id)
        if core.condition_checkpoint_valid(
            atomic_path,
            query_filter=query_filter,
            question_id=question_id,
            answer_id=answer_id,
        ):
            try:
                record = validate_music_partition_stats_response(
                    core.load_json(atomic_path),
                    config,
                    filters,
                    target_a=target_a,
                    target_b=target_b,
                    operation="OptionCondition",
                    document=core.CONDITION_QUERY,
                )
                record["statsEvidence"] = {
                    **music_partition_file_record(atomic_path),
                    "operation": "OptionCondition",
                    "reusedExistingAtomicResponse": True,
                }
                return record
            except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
                pass

    path = music_partition_stats_path(config, filters)
    variables = core.base_variables(config, query=query_filter)
    value: Mapping[str, Any]
    # The historical archive spells some equivalent UTC instants without
    # ``.000``.  Reuse is decided by the full semantic validator below, which
    # still rejects every extra/missing variable and all non-equivalent values.
    if path.is_file():
        try:
            value = core.load_json(path)
            record = validate_music_partition_stats_response(
                value,
                config,
                filters,
                target_a=target_a,
                target_b=target_b,
                operation="MusicCovotePartitionStats",
                document=MUSIC_COVOTE_PARTITION_STATS_QUERY,
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            value = {}
        else:
            record["statsEvidence"] = {
                **music_partition_file_record(path),
                "operation": "MusicCovotePartitionStats",
                "reusedCheckpoint": True,
            }
            return record
    value = core.fetch_graphql_checkpoint(
        client,
        path,
        "MusicCovotePartitionStats",
        MUSIC_COVOTE_PARTITION_STATS_QUERY,
        variables,
        resume=False,
        timeout=300,
        context={
            "scope": "minimal filtered ranking used to find exact target ranks and zero marginals",
            "query": query_filter,
            "filters": [
                {"questionId": question_id, "answerId": answer_id}
                for question_id, answer_id in filters
            ],
            "targetPair": {"a": target_a, "b": target_b},
        },
    )
    record = validate_music_partition_stats_response(
        value,
        config,
        filters,
        target_a=target_a,
        target_b=target_b,
        operation="MusicCovotePartitionStats",
        document=MUSIC_COVOTE_PARTITION_STATS_QUERY,
    )
    record["statsEvidence"] = {
        **music_partition_file_record(path),
        "operation": "MusicCovotePartitionStats",
        "reusedCheckpoint": False,
    }
    return record


def select_unit_music_witness(
    partition: Mapping[str, Any], *, target_a: str, target_b: str
) -> dict[str, Any]:
    """Choose the first exact rank-one-vote, normal-name non-target witness."""

    if strict_nonnegative_int(partition["numMusic"], "partition.numMusic") != 2:
        raise ValueError("witness fallback requires a parent with numMusic exactly 2")
    names = partition.get("rankingNamesByRank")
    counts = partition.get("rankingVoteCountsByRank")
    if (
        not isinstance(names, list)
        or not isinstance(counts, list)
        or len(names) != len(counts)
        or partition.get("rankingEntryCount") != len(names)
        or any(not isinstance(name, str) or not name for name in names)
    ):
        raise ValueError("witness fallback parent ranking evidence is malformed")
    if partition.get("rankingNamesByRankSha256") != canonical_json_sha256(names):
        raise ValueError("witness fallback parent ranking name hash mismatch")
    if partition.get("rankingVoteCountsByRankSha256") != canonical_json_sha256(
        counts
    ):
        raise ValueError("witness fallback parent ranking vote-count hash mismatch")
    normalized_counts = [
        strict_nonnegative_int(value, "rankingVoteCountsByRank") for value in counts
    ]
    candidates = [
        {
            "name": name,
            "rank": rank,
            "parentVoteCount": count,
        }
        for rank, (name, count) in enumerate(
            zip(names, normalized_counts), start=1
        )
        if count == 1
        and name not in {target_a, target_b}
        and not has_trailing_unicode_control(name)
    ]
    if not candidates:
        raise RuntimeError(
            "witness fallback has no non-target one-vote name without trailing controls"
        )
    return {
        **candidates[0],
        "selectionRule": (
            "lowest exact filtered rank whose parent voteCount is 1, whose name "
            "is neither target, and whose name has no trailing Unicode Cc code point"
        ),
        "eligibleCandidateCount": len(candidates),
    }


def validate_music_witness_child(
    parent: Mapping[str, Any],
    child: Mapping[str, Any],
    selection: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove that one official witness-filter response is an exact unit subset."""

    witness_name = str(selection["name"])
    parent_query = str(parent.get("query") or "")
    expected_query = music_witness_query(parent_query, witness_name)
    if child.get("query") != expected_query or child.get("witnessFilter") != {
        "type": "music_any",
        "name": witness_name,
    }:
        raise ValueError("witness child query/filter evidence mismatch")
    parent_values = {
        "numVote": strict_nonnegative_int(parent["numVote"], "parent.numVote"),
        "numMusic": strict_nonnegative_int(parent["numMusic"], "parent.numMusic"),
        "targetAVoteCount": strict_nonnegative_int(
            parent["targetA"]["voteCount"], "parent.targetA.voteCount"
        ),
        "targetBVoteCount": strict_nonnegative_int(
            parent["targetB"]["voteCount"], "parent.targetB.voteCount"
        ),
    }
    child_values = {
        "numVote": strict_nonnegative_int(child["numVote"], "child.numVote"),
        "numMusic": strict_nonnegative_int(child["numMusic"], "child.numMusic"),
        "targetAVoteCount": strict_nonnegative_int(
            child["targetA"]["voteCount"], "child.targetA.voteCount"
        ),
        "targetBVoteCount": strict_nonnegative_int(
            child["targetB"]["voteCount"], "child.targetB.voteCount"
        ),
    }
    if parent_values["numMusic"] != 2:
        raise ValueError("witness split parent numMusic is not exactly 2")
    if selection.get("parentVoteCount") != 1:
        raise ValueError("selected witness does not have exact parent voteCount 1")
    if child_values["numVote"] != 1 or child_values["numMusic"] != 1:
        raise ValueError("official witness child is not an exact one-voter music cohort")
    if any(child_values[key] > parent_values[key] for key in parent_values):
        raise ValueError("official witness child field exceeds its parent")

    parent_names = parent.get("rankingNamesByRank")
    parent_counts = parent.get("rankingVoteCountsByRank")
    child_names = child.get("rankingNamesByRank")
    child_counts = child.get("rankingVoteCountsByRank")
    if not all(
        isinstance(value, list)
        for value in (parent_names, parent_counts, child_names, child_counts)
    ) or len(parent_names) != len(parent_counts) or len(child_names) != len(
        child_counts
    ):
        raise ValueError("witness parent/child ranking sequences are malformed")
    if (
        any(not isinstance(name, str) or not name for name in parent_names)
        or any(not isinstance(name, str) or not name for name in child_names)
        or len(parent_names) != len(set(parent_names))
        or len(child_names) != len(set(child_names))
        or parent.get("rankingEntryCount") != len(parent_names)
        or child.get("rankingEntryCount") != len(child_names)
        or parent.get("rankingNamesByRankSha256")
        != canonical_json_sha256(parent_names)
        or parent.get("rankingVoteCountsByRankSha256")
        != canonical_json_sha256(parent_counts)
        or child.get("rankingNamesByRankSha256")
        != canonical_json_sha256(child_names)
        or child.get("rankingVoteCountsByRankSha256")
        != canonical_json_sha256(child_counts)
    ):
        raise ValueError("witness parent/child ranking evidence is inconsistent")
    parent_count_map = {
        name: strict_nonnegative_int(count, "parentRanking.voteCount")
        for name, count in zip(parent_names, parent_counts)
    }
    child_count_map = {
        name: strict_nonnegative_int(count, "childRanking.voteCount")
        for name, count in zip(child_names, child_counts)
    }
    selection_rank = strict_nonnegative_int(selection.get("rank"), "selection.rank")
    if (
        selection_rank <= 0
        or selection_rank > len(parent_names)
        or parent_names[selection_rank - 1] != witness_name
        or parent_count_map.get(witness_name) != 1
        or strict_nonnegative_int(
            selection.get("parentVoteCount"), "selection.parentVoteCount"
        )
        != 1
        or witness_name
        in {str(parent["targetA"]["name"]), str(parent["targetB"]["name"])}
        or has_trailing_unicode_control(witness_name)
    ):
        raise ValueError("selected witness does not match its exact parent ranking")
    if witness_name not in child_count_map or child_count_map[witness_name] != 1:
        raise ValueError("official witness child does not contain the witness once")
    if any(
        name not in parent_count_map or count > parent_count_map[name]
        for name, count in child_count_map.items()
    ):
        raise ValueError("official witness child ranking is not a subset of its parent")
    return {
        "expectedQuery": expected_query,
        "parentValues": parent_values,
        "childValues": child_values,
        "allChildFieldsWithinParent": True,
        "childRankingIsParentSubset": True,
        "witnessChildVoteCount": child_count_map[witness_name],
        "passed": True,
    }


def load_or_fetch_music_witness_stats(
    config: core.RoundConfig,
    client: core.PublicClient,
    parent: Mapping[str, Any],
    selection: Mapping[str, Any],
    *,
    target_a: str,
    target_b: str,
) -> dict[str, Any]:
    """Fetch one light official ranking for the deterministic witness subset."""

    witness_name = str(selection["name"])
    parent_query = str(parent.get("query") or "")
    query_filter = music_witness_query(parent_query, witness_name)
    path = music_witness_stats_path(config, parent_query, witness_name)
    variables = core.base_variables(config, query=query_filter)
    parent_filters = [
        (
            decimal_identifier(item["questionId"], "parentFilter.questionId"),
            decimal_identifier(item["answerId"], "parentFilter.answerId"),
        )
        for item in parent.get("filters", [])
    ]

    record: dict[str, Any] | None = None
    if path.is_file():
        try:
            record = validate_music_partition_stats_response(
                core.load_json(path),
                config,
                parent_filters,
                target_a=target_a,
                target_b=target_b,
                operation="MusicCovotePartitionStats",
                document=MUSIC_COVOTE_PARTITION_STATS_QUERY,
                query_filter_override=query_filter,
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            record = None
        else:
            record["statsEvidence"] = {
                **music_partition_file_record(path),
                "operation": "MusicCovotePartitionStats",
                "reusedCheckpoint": True,
                "role": "unit witness subset",
            }
    if record is None:
        value = core.fetch_graphql_checkpoint(
            client,
            path,
            "MusicCovotePartitionStats",
            MUSIC_COVOTE_PARTITION_STATS_QUERY,
            variables,
            resume=False,
            timeout=300,
            context={
                "scope": "unit witness split for an unresolved two-music-voter leaf",
                "parentQuery": parent_query,
                "query": query_filter,
                "witnessSelection": dict(selection),
                "targetPair": {"a": target_a, "b": target_b},
            },
        )
        record = validate_music_partition_stats_response(
            value,
            config,
            parent_filters,
            target_a=target_a,
            target_b=target_b,
            operation="MusicCovotePartitionStats",
            document=MUSIC_COVOTE_PARTITION_STATS_QUERY,
            query_filter_override=query_filter,
        )
        record["statsEvidence"] = {
            **music_partition_file_record(path),
            "operation": "MusicCovotePartitionStats",
            "reusedCheckpoint": False,
            "role": "unit witness subset",
        }
    record["witnessFilter"] = {"type": "music_any", "name": witness_name}
    validate_music_witness_child(parent, record, selection)
    return record


def derive_music_witness_split(
    parent: Mapping[str, Any],
    child: Mapping[str, Any],
    selection: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive the unqueried witness complement and resolve both unit cohorts."""

    child_validation = validate_music_witness_child(parent, child, selection)
    residual_values = {
        "numVote": strict_nonnegative_int(parent["numVote"], "parent.numVote")
        - strict_nonnegative_int(child["numVote"], "child.numVote"),
        "numMusic": strict_nonnegative_int(parent["numMusic"], "parent.numMusic")
        - strict_nonnegative_int(child["numMusic"], "child.numMusic"),
        "targetAVoteCount": strict_nonnegative_int(
            parent["targetA"]["voteCount"], "parent.targetA.voteCount"
        )
        - strict_nonnegative_int(
            child["targetA"]["voteCount"], "child.targetA.voteCount"
        ),
        "targetBVoteCount": strict_nonnegative_int(
            parent["targetB"]["voteCount"], "parent.targetB.voteCount"
        )
        - strict_nonnegative_int(
            child["targetB"]["voteCount"], "child.targetB.voteCount"
        ),
    }
    if any(value < 0 for value in residual_values.values()):
        raise ValueError("official witness child exceeds its parent")
    complement = {
        "filters": [dict(item) for item in parent.get("filters", [])],
        "query": None,
        "numVote": residual_values["numVote"],
        "numMusic": residual_values["numMusic"],
        "targetA": {
            "name": str(parent["targetA"]["name"]),
            "voteCount": residual_values["targetAVoteCount"],
            "rank": None,
        },
        "targetB": {
            "name": str(parent["targetB"]["name"]),
            "voteCount": residual_values["targetBVoteCount"],
            "rank": None,
        },
        "residualDefinition": {
            "operation": "exact parent minus official unit witness child",
            "witnessName": str(selection["name"]),
            "hasDirectOfficialQuery": False,
        },
    }
    if complement["numMusic"] != 1:
        raise ValueError("witness complement numMusic is not exactly 1")
    conservation = validate_partition_children(parent, [child, complement])
    child_resolution = uniquely_resolve_residual_intersection(child)
    complement_resolution = uniquely_resolve_residual_intersection(complement)
    cells = aggregate_partition_nodes(
        parent,
        [
            {"cells": child_resolution["cells"]},
            {"cells": complement_resolution["cells"]},
        ],
    )
    return {
        "selection": dict(selection),
        "childValidation": child_validation,
        "conservationProof": conservation,
        "childResolution": child_resolution,
        "complement": complement,
        "complementResolution": complement_resolution,
        "cells": cells,
    }


def derived_partition_cells(
    partition: Mapping[str, Any], intersection: int
) -> dict[str, int]:
    intersection = strict_nonnegative_int(intersection, "intersection")
    universe = strict_nonnegative_int(partition["numMusic"], "partition.numMusic")
    count_a = strict_nonnegative_int(
        partition["targetA"]["voteCount"], "partition.targetA.voteCount"
    )
    count_b = strict_nonnegative_int(
        partition["targetB"]["voteCount"], "partition.targetB.voteCount"
    )
    cells = {
        "m00": intersection,
        "m01": count_b - intersection,
        "m10": count_a - intersection,
        "m11": universe - count_a - count_b + intersection,
    }
    if (
        any(value < 0 for value in cells.values())
        or cells["m00"] + cells["m10"] != count_a
        or cells["m00"] + cells["m01"] != count_b
        or sum(cells.values()) != universe
    ):
        raise ValueError("partition intersection violates exact marginal identities")
    return cells


def validate_music_partition_covote_response(
    value: Mapping[str, Any],
    config: core.RoundConfig,
    partition: Mapping[str, Any],
    *,
    top_k: int,
    target_a: str,
    target_b: str,
) -> dict[str, Any]:
    query_filter = str(partition["query"])
    variables = core.base_variables(config, query=query_filter, topK=top_k)
    provenance = value["provenance"]
    if (
        provenance.get("source") != core.ENDPOINT
        or provenance.get("operation") != "MusicCovoteQuestionnairePartition"
        or provenance.get("variables") != variables
        or provenance.get("status") != 200
        or "json" not in str(provenance.get("contentType", "")).lower()
        or provenance.get("documentSha256")
        != core.sha256_bytes(MUSIC_COVOTE_QUESTIONNAIRE_PARTITION_QUERY.encode("utf-8"))
    ):
        raise ValueError("partition co-vote provenance/variables validation failed")
    stats = value["data"]["queryGlobalStats"]
    if (
        strict_nonnegative_int(stats.get("voteYear"), "stats.voteYear")
        != config.number
        or strict_nonnegative_int(stats.get("numVote"), "stats.numVote")
        != partition["numVote"]
        or strict_nonnegative_int(stats.get("numMusic"), "stats.numMusic")
        != partition["numMusic"]
    ):
        raise ValueError("partition co-vote global stats differ from ranking evidence")
    names_by_rank = partition.get("rankingNamesByRank")
    if not isinstance(names_by_rank, list) or any(
        not isinstance(name, str) for name in names_by_rank
    ):
        raise ValueError("partition lacks a validated ranking name sequence")
    if partition.get("rankingNamesByRankSha256") != canonical_json_sha256(
        names_by_rank
    ):
        raise ValueError("partition ranking name sequence hash mismatch")
    endpoint_evidence = endpoint_set_evidence(names_by_rank, top_k)
    expected_endpoints = set(endpoint_evidence["endpointNamesByRank"])
    expected_pair_set = {
        frozenset((left, right))
        for left, right in combinations(
            endpoint_evidence["endpointNamesByRank"], 2
        )
    }
    items = value["data"]["queryMusicsCovote"]["items"]
    expected_pairs = endpoint_evidence["expectedUnorderedPairCount"]
    if not isinstance(items, list) or len(items) != expected_pairs:
        raise ValueError(
            f"partition co-vote pair coverage {len(items) if isinstance(items, list) else 'invalid'} "
            f"!= {expected_pairs}"
        )
    pairs: set[frozenset[str]] = set()
    observed_endpoints: set[str] = set()
    target_items: list[Mapping[str, Any]] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise ValueError("partition co-vote contains a non-object item")
        a = str(item.get("a"))
        b = str(item.get("b"))
        pair = frozenset((a, b))
        if a == b or pair in pairs:
            raise ValueError("partition co-vote contains a duplicate/diagonal pair")
        pairs.add(pair)
        observed_endpoints.update((a, b))
        cells = [
            strict_nonnegative_int(item.get(key), f"partition.{key}")
            for key in ("m00", "m01", "m10", "m11")
        ]
        if sum(cells) != partition["numMusic"]:
            raise ValueError("partition co-vote item cells do not sum to numMusic")
        if pair == frozenset((target_a, target_b)):
            target_items.append(item)
    if observed_endpoints != expected_endpoints:
        raise ValueError(
            "partition co-vote endpoint set differs from filtered ranking topK"
        )
    if pairs != expected_pair_set:
        raise ValueError(
            "partition co-vote unordered pair set is not the complete topK graph"
        )
    canonical_observed_pairs = sorted(
        (min(pair), max(pair)) for pair in (tuple(pair) for pair in pairs)
    )
    observed_pair_hash = canonical_json_sha256(canonical_observed_pairs)
    if observed_pair_hash != endpoint_evidence["expectedUnorderedPairSetSha256"]:
        raise ValueError("partition co-vote pair-set hash mismatch")
    endpoint_evidence.update(
        {
            "observedEndpointCount": len(observed_endpoints),
            "observedCanonicalEndpointSetSha256": canonical_json_sha256(
                sorted(observed_endpoints)
            ),
            "observedUnorderedPairCount": len(pairs),
            "observedUnorderedPairSetSha256": observed_pair_hash,
            "exactEndpointAndUnorderedPairSetsMatched": True,
        }
    )
    if len(target_items) != 1:
        raise ValueError(f"target pair occurs {len(target_items)} times")
    target = orient_music_pair_item(target_items[0], target_a, target_b)
    derived = derived_partition_cells(partition, target["m00"])
    if any(target[key] != derived[key] for key in derived):
        raise ValueError("official target cells disagree with filtered ranking marginals")
    return {
        "topK": top_k,
        "expectedPairCount": expected_pairs,
        "observedPairCount": len(items),
        "endpointSetEvidence": endpoint_evidence,
        "targetPair": target,
        "cells": derived,
    }


def fetch_music_partition_covote(
    config: core.RoundConfig,
    client: core.PublicClient,
    partition: Mapping[str, Any],
    *,
    target_a: str,
    target_b: str,
) -> dict[str, Any]:
    rank_a = partition["targetA"].get("rank")
    rank_b = partition["targetB"].get("rank")
    if rank_a is None or rank_b is None:
        raise ValueError("cannot request co-vote for a zero-marginal partition")
    top_k = max(
        strict_nonnegative_int(rank_a, "targetA.rank"),
        strict_nonnegative_int(rank_b, "targetB.rank"),
    )
    if top_k > MUSIC_COVOTE_SAFE_TOP_K:
        raise ValueError(
            f"partition topK {top_k} exceeds safe limit "
            f"{MUSIC_COVOTE_SAFE_TOP_K}; refine before requesting co-vote"
        )
    path = music_partition_covote_path(
        config,
        [
            (
                decimal_identifier(item["questionId"], "filter.questionId"),
                decimal_identifier(item["answerId"], "filter.answerId"),
            )
            for item in partition["filters"]
        ],
        top_k=top_k,
    )
    variables = core.base_variables(config, query=partition["query"], topK=top_k)
    if core.graphql_checkpoint_valid(
        path,
        operation="MusicCovoteQuestionnairePartition",
        variables=variables,
    ):
        try:
            value = core.load_json(path)
            result = validate_music_partition_covote_response(
                value,
                config,
                partition,
                top_k=top_k,
                target_a=target_a,
                target_b=target_b,
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            pass
        else:
            result["responseEvidence"] = {
                **music_partition_file_record(path),
                "reusedCheckpoint": True,
            }
            return result
    value = core.fetch_graphql_checkpoint(
        client,
        path,
        "MusicCovoteQuestionnairePartition",
        MUSIC_COVOTE_QUESTIONNAIRE_PARTITION_QUERY,
        variables,
        resume=False,
        timeout=900,
        context={
            "scope": "minimal topK exact co-vote response for one adaptive partition leaf",
            "query": partition["query"],
            "filters": partition["filters"],
            "topK": top_k,
            "topKDerivation": "max exact filtered rank of the two target tracks",
            "targetPair": {"a": target_a, "b": target_b},
        },
    )
    result = validate_music_partition_covote_response(
        value,
        config,
        partition,
        top_k=top_k,
        target_a=target_a,
        target_b=target_b,
    )
    result["responseEvidence"] = {
        **music_partition_file_record(path),
        "reusedCheckpoint": False,
    }
    return result


def validate_partition_children(
    parent: Mapping[str, Any], children: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    if not children:
        raise ValueError("a refinement split has no children")
    sums = {
        "numVote": sum(
            strict_nonnegative_int(child["numVote"], "child.numVote")
            for child in children
        ),
        "numMusic": sum(
            strict_nonnegative_int(child["numMusic"], "child.numMusic")
            for child in children
        ),
        "targetAVoteCount": sum(
            strict_nonnegative_int(
                child["targetA"]["voteCount"], "child.targetA.voteCount"
            )
            for child in children
        ),
        "targetBVoteCount": sum(
            strict_nonnegative_int(
                child["targetB"]["voteCount"], "child.targetB.voteCount"
            )
            for child in children
        ),
    }
    expected = {
        "numVote": parent["numVote"],
        "numMusic": parent["numMusic"],
        "targetAVoteCount": parent["targetA"]["voteCount"],
        "targetBVoteCount": parent["targetB"]["voteCount"],
    }
    if sums != expected:
        raise ValueError(
            "refinement children do not exactly cover parent: "
            + json.dumps({"observed": sums, "expected": expected}, ensure_ascii=False)
        )
    return {"observedSums": sums, "expectedParentValues": expected, "passed": True}


def derive_unanswered_residual_partition(
    parent: Mapping[str, Any],
    explicit_children: Sequence[Mapping[str, Any]],
    *,
    question_id: int,
    explicit_answer_ids: Sequence[int],
    max_global_unanswered_voters: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Derive a complement cohort by exact parent-minus-children arithmetic."""

    max_global_unanswered_voters = strict_nonnegative_int(
        max_global_unanswered_voters, "maxGlobalUnansweredVoters"
    )
    expected_answer_ids = [
        decimal_identifier(answer_id, "explicitAnswerId")
        for answer_id in explicit_answer_ids
    ]
    if not expected_answer_ids or len(expected_answer_ids) != len(
        set(expected_answer_ids)
    ):
        raise ValueError("explicit residual-axis answer IDs are empty or duplicated")
    if len(explicit_children) != len(expected_answer_ids):
        raise ValueError("explicit residual-axis child count is incomplete")

    parent_filters = [
        (
            decimal_identifier(item["questionId"], "parentFilter.questionId"),
            decimal_identifier(item["answerId"], "parentFilter.answerId"),
        )
        for item in parent.get("filters", [])
    ]
    observed_answer_ids: list[int] = []
    for child in explicit_children:
        child_filters = [
            (
                decimal_identifier(item["questionId"], "childFilter.questionId"),
                decimal_identifier(item["answerId"], "childFilter.answerId"),
            )
            for item in child.get("filters", [])
        ]
        if (
            len(child_filters) != len(parent_filters) + 1
            or child_filters[:-1] != parent_filters
            or child_filters[-1][0] != question_id
            or child.get("query") != music_partition_query(child_filters)
        ):
            raise ValueError(
                "explicit residual-axis child filters do not extend the parent exactly"
            )
        observed_answer_ids.append(child_filters[-1][1])
    if set(observed_answer_ids) != set(expected_answer_ids) or len(
        observed_answer_ids
    ) != len(set(observed_answer_ids)):
        raise ValueError("explicit residual-axis answer coverage is not exact")

    field_specs = {
        "numVote": lambda item: item["numVote"],
        "numMusic": lambda item: item["numMusic"],
        "targetAVoteCount": lambda item: item["targetA"]["voteCount"],
        "targetBVoteCount": lambda item: item["targetB"]["voteCount"],
    }
    parent_values = {
        "numVote": strict_nonnegative_int(parent["numVote"], "parent.numVote"),
        "numMusic": strict_nonnegative_int(parent["numMusic"], "parent.numMusic"),
        "targetAVoteCount": strict_nonnegative_int(
            parent["targetA"]["voteCount"], "parent.targetA.voteCount"
        ),
        "targetBVoteCount": strict_nonnegative_int(
            parent["targetB"]["voteCount"], "parent.targetB.voteCount"
        ),
    }
    explicit_sums = {
        field: sum(
            strict_nonnegative_int(getter(child), f"child.{field}")
            for child in explicit_children
        )
        for field, getter in field_specs.items()
    }
    residual_values = {
        field: parent_values[field] - explicit_sums[field] for field in field_specs
    }
    if any(value < 0 for value in residual_values.values()):
        raise ValueError(
            "explicit residual-axis children exceed their parent: "
            + json.dumps(
                {
                    "parent": parent_values,
                    "explicitChildren": explicit_sums,
                    "residual": residual_values,
                },
                ensure_ascii=False,
            )
        )
    if residual_values["numVote"] > max_global_unanswered_voters:
        raise ValueError(
            "conditional unanswered residual exceeds the proven global maximum"
        )
    if residual_values["numMusic"] > residual_values["numVote"]:
        raise ValueError("residual numMusic exceeds residual numVote")
    if (
        residual_values["targetAVoteCount"] > residual_values["numMusic"]
        or residual_values["targetBVoteCount"] > residual_values["numMusic"]
    ):
        raise ValueError("residual target marginal exceeds residual numMusic")

    residual = {
        "filters": [
            {"questionId": question, "answerId": answer}
            for question, answer in parent_filters
        ],
        "query": None,
        "numVote": residual_values["numVote"],
        "numMusic": residual_values["numMusic"],
        "targetA": {
            "name": str(parent["targetA"]["name"]),
            "voteCount": residual_values["targetAVoteCount"],
            "rank": None,
        },
        "targetB": {
            "name": str(parent["targetB"]["name"]),
            "voteCount": residual_values["targetBVoteCount"],
            "rank": None,
        },
        "answer": "unanswered residual (parent minus all explicit answers)",
        "residualDefinition": {
            "questionId": question_id,
            "explicitAnswerIds": sorted(expected_answer_ids),
            "operation": "exact parent minus explicit official child statistics",
            "hasDirectOfficialQuery": False,
            "maxGlobalUnansweredVoters": max_global_unanswered_voters,
        },
    }
    combined_proof = validate_partition_children(
        parent, [*explicit_children, residual]
    )
    subtractions = {
        field: {
            "parent": parent_values[field],
            "explicitChildrenSum": explicit_sums[field],
            "residual": residual_values[field],
            "identityPassed": (
                explicit_sums[field] + residual_values[field]
                == parent_values[field]
            ),
        }
        for field in field_specs
    }
    proof = {
        "method": "component-wise parent minus all explicit answer children",
        "questionId": question_id,
        "explicitAnswerIdsExpected": sorted(expected_answer_ids),
        "explicitAnswerIdsObserved": sorted(observed_answer_ids),
        "explicitChildCount": len(explicit_children),
        "subtractions": subtractions,
        "nonnegativeResidualPassed": True,
        "residualNumVoteWithinGlobalMaximum": True,
        "combinedExactConservationProof": combined_proof,
    }
    return residual, proof


def partition_frechet_bounds(partition: Mapping[str, Any]) -> dict[str, Any]:
    """Return exact binary-event Fréchet bounds from local integer marginals."""

    universe = strict_nonnegative_int(partition["numMusic"], "partition.numMusic")
    count_a = strict_nonnegative_int(
        partition["targetA"]["voteCount"], "partition.targetA.voteCount"
    )
    count_b = strict_nonnegative_int(
        partition["targetB"]["voteCount"], "partition.targetB.voteCount"
    )
    if count_a > universe or count_b > universe:
        raise ValueError("partition target marginal exceeds partition numMusic")
    lower = max(0, count_a + count_b - universe)
    upper = min(count_a, count_b)
    return {
        "method": "binary-event Frechet bounds from exact local marginals",
        "universeNumMusic": universe,
        "targetAVoteCount": count_a,
        "targetBVoteCount": count_b,
        "intersectionLowerBound": lower,
        "intersectionUpperBound": upper,
        "boundsAreEqual": lower == upper,
    }


def try_uniquely_resolve_partition_intersection(
    partition: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Resolve locally when exact marginals make the intersection unique."""

    proof = partition_frechet_bounds(partition)
    if not proof["boundsAreEqual"]:
        return None
    intersection = proof["intersectionLowerBound"]
    cells = derived_partition_cells(partition, intersection)
    return {
        "cells": cells,
        "proof": {
            **proof,
            "uniqueIntersection": intersection,
            "allCellIdentitiesPassed": True,
        },
    }


def uniquely_resolve_residual_intersection(
    partition: Mapping[str, Any],
) -> dict[str, Any]:
    """Use exact Fréchet bounds; fail closed unless the intersection is unique."""

    result = try_uniquely_resolve_partition_intersection(partition)
    if result is not None:
        return result
    proof = partition_frechet_bounds(partition)
    raise RuntimeError(
        "unanswered residual marginals do not uniquely determine the target "
        "intersection "
        f"(lower={proof['intersectionLowerBound']}, "
        f"upper={proof['intersectionUpperBound']})"
    )


def evaluate_global_residual_intersection(
    partition: Mapping[str, Any], *, question_id: int
) -> dict[str, Any]:
    """Apply the stricter global proof only to globally relevant residuals."""

    question_id = decimal_identifier(question_id, "questionId")
    observed_bounds = partition_frechet_bounds(partition)
    if question_id in MUSIC_COVOTE_GLOBAL_INTERSECTION_OPTIONAL:
        return {
            "globalIntersectionRequired": False,
            "globalIntersectionStatus": "not_required",
            "globalIntersectionReason": (
                "this branch question is used only inside its exact parent "
                "condition; global explicit-plus-residual conservation is "
                "required, but the global complement intersection is not part "
                "of the resolution tree"
            ),
            "observedFrechetBounds": observed_bounds,
        }
    resolution = uniquely_resolve_residual_intersection(partition)
    return {
        "globalIntersectionRequired": True,
        "globalIntersectionStatus": "uniquely_resolved",
        "observedFrechetBounds": observed_bounds,
        "localIntersectionProof": resolution["proof"],
        "cells": resolution["cells"],
    }


def aggregate_partition_nodes(
    parent: Mapping[str, Any], nodes: Sequence[Mapping[str, Any]]
) -> dict[str, int]:
    cells = {
        key: sum(
            strict_nonnegative_int(node["cells"][key], f"node.cells.{key}")
            for node in nodes
        )
        for key in ("m00", "m01", "m10", "m11")
    }
    expected = derived_partition_cells(parent, cells["m00"])
    if cells != expected:
        raise ValueError("refined leaf cells do not aggregate to parent marginals")
    return cells


def public_partition_record(partition: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: partition[key]
        for key in (
            "filters",
            "query",
            "numVote",
            "numMusic",
            "rankingEntryCount",
            "rankingNamesByRank",
            "rankingNamesByRankSha256",
            "rankingVoteCountsByRank",
            "rankingVoteCountsByRankSha256",
            "targetA",
            "targetB",
            "statsEvidence",
            "residualDefinition",
            "witnessFilter",
        )
        if key in partition
    }


def partition_resolution_counts(node: Mapping[str, Any]) -> Counter[str]:
    counts: Counter[str] = Counter({str(node["nodeType"]): 1})
    for child in node.get("children", []):
        counts.update(partition_resolution_counts(child))
    return counts


def fetch_music_missing_pair_questionnaire_bridge(
    config: core.RoundConfig,
    client: core.PublicClient,
    base: Mapping[str, Any],
    *,
    top_k: int,
    target_a: str,
    target_b: str,
    target_a_count: int,
    target_b_count: int,
) -> dict[str, Any]:
    """Recover one pair through an exact, adaptive hierarchy of Single answers."""

    del top_k  # Every co-vote request derives its smaller exact filtered topK.
    attempts_path = (
        config.root / "covote" / "music_missing_pair_partition_attempts.json"
    )
    proof_path = config.root / "covote" / "music_missing_pair_partition_proof.json"
    query_documents = write_query_documents(config)
    questions_path = config.root / "questionnaire" / "questions.json"
    options_path = config.root / "questionnaire" / "options.json"
    categorical_path = config.root / "questionnaire" / "categorical_results.json"
    base_path = config.root / "graphql" / "base.json"
    questions = core.load_json(questions_path)
    options = core.load_json(options_path)
    categorical = core.load_json(categorical_path)
    total_voters = strict_nonnegative_int(
        base["data"]["queryGlobalStats"]["numVote"], "base.numVote"
    )
    total_music = strict_nonnegative_int(
        base["data"]["queryGlobalStats"]["numMusic"], "base.numMusic"
    )
    plans: list[tuple[str, dict[str, Any]]] = []
    for axis_name, question_id in MUSIC_COVOTE_REFINEMENT_AXES:
        plans.append(
            (
                axis_name,
                build_questionnaire_partition_plan(
                    question_id=question_id,
                    questions=questions,
                    options=options,
                    categorical_entries=categorical["data"]["queryQuestionnaire"][
                        "entries"
                    ],
                    expected_total_voters=total_voters,
                ),
            )
        )
    residual_plans: list[tuple[str, int, int, dict[str, Any]]] = []
    for axis_name, question_id, max_unanswered_voters in (
        MUSIC_COVOTE_RESIDUAL_AXES
    ):
        residual_plan = build_questionnaire_residual_partition_plan(
            question_id=question_id,
            questions=questions,
            options=options,
            categorical_entries=categorical["data"]["queryQuestionnaire"]["entries"],
            expected_total_voters=total_voters,
            max_unanswered_voters=max_unanswered_voters,
        )
        if residual_plan["unansweredResidualVoters"] != max_unanswered_voters:
            raise ValueError(
                f"question {question_id} unanswered residual differs from the "
                f"verified value {max_unanswered_voters}"
            )
        residual_plans.append(
            (
                axis_name,
                question_id,
                max_unanswered_voters,
                residual_plan,
            )
        )

    base_entries = base["data"]["queryMusicRanking"]["entries"]
    base_entries_by_rank = sorted(
        base_entries,
        key=lambda entry: strict_nonnegative_int(entry.get("rank"), "base.rank"),
    )
    base_names_by_rank = [str(entry["name"]) for entry in base_entries_by_rank]
    base_vote_counts_by_rank = [
        strict_nonnegative_int(entry.get("voteCount"), "base.voteCount")
        for entry in base_entries_by_rank
    ]
    root = {
        "filters": [],
        "query": None,
        "numVote": total_voters,
        "numMusic": total_music,
        "rankingEntryCount": len(base_entries),
        "rankingNamesByRank": base_names_by_rank,
        "rankingNamesByRankSha256": canonical_json_sha256(base_names_by_rank),
        "rankingVoteCountsByRank": base_vote_counts_by_rank,
        "rankingVoteCountsByRankSha256": canonical_json_sha256(
            base_vote_counts_by_rank
        ),
        "targetA": target_music_ranking_record(base_entries, target_a),
        "targetB": target_music_ranking_record(base_entries, target_b),
        "statsEvidence": {
            **music_partition_file_record(base_path),
            "operation": base["provenance"]["operation"],
            "role": "unfiltered root",
        },
    }
    if (
        root["targetA"]["voteCount"] != target_a_count
        or root["targetB"]["voteCount"] != target_b_count
    ):
        raise ValueError("target base counts differ from reconstruction catalogue")

    prior_run_history = load_prior_partition_audit_history(attempts_path)
    audit: dict[str, Any] = {
        "schemaVersion": 1,
        "round": config.number,
        "algorithm": (
            "adaptive required-Single partition tree with bounded unanswered "
            "residual complement"
        ),
        "safeTopKLimit": MUSIC_COVOTE_SAFE_TOP_K,
        "refinementAxisPriority": [
            *[name for name, _ in plans],
            *[name for name, _, _, _ in residual_plans],
        ],
        "statsRequests": [],
        "covoteAttempts": [],
        "derivedResiduals": [],
        "witnessFallbacks": [],
        "priorRunHistory": prior_run_history,
        "complete": False,
    }

    def save_audit(*, error: str | None = None, complete: bool = False) -> None:
        payload = {**audit, "updatedAt": core.utc_now(), "complete": complete}
        if error is not None:
            payload["error"] = error
        core.atomic_write_json(attempts_path, payload, pretty=True)

    def get_child_stats(filters: Sequence[tuple[int, int]]) -> dict[str, Any]:
        query_filter = music_partition_query(filters)
        expected_path = music_partition_stats_path(config, filters)
        try:
            child = load_or_fetch_music_partition_stats(
                config,
                client,
                filters,
                target_a=target_a,
                target_b=target_b,
            )
        except Exception as exc:
            audit["statsRequests"].append(
                {
                    "query": query_filter,
                    "expectedPath": expected_path.relative_to(WORKSPACE).as_posix(),
                    "status": "failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            save_audit(error=f"{type(exc).__name__}: {exc}")
            raise
        audit["statsRequests"].append(
            {
                "query": query_filter,
                "status": "validated",
                **child["statsEvidence"],
            }
        )
        save_audit()
        return child

    def split_partition(
        parent: Mapping[str, Any], axis_index: int
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        axis_name, plan = plans[axis_index]
        parent_filters = [
            (
                decimal_identifier(item["questionId"], "filter.questionId"),
                decimal_identifier(item["answerId"], "filter.answerId"),
            )
            for item in parent["filters"]
        ]
        children = []
        for answer in plan["partitions"]:
            child_filters = [
                *parent_filters,
                (
                    decimal_identifier(answer["questionId"], "answer.questionId"),
                    decimal_identifier(answer["answerId"], "answer.answerId"),
                ),
            ]
            child = get_child_stats(child_filters)
            child["answer"] = answer["answer"]
            children.append(child)
        sum_proof = validate_partition_children(parent, children)
        split_proof = {
            "axisName": axis_name,
            "questionId": plan["questionId"],
            "question": plan["question"],
            "questionType": plan["questionType"],
            "optionCount": plan["optionCount"],
            "definitionMutualExclusionAndGlobalCoverageProof": plan[
                "mutualExclusionAndCoverageProof"
            ],
            "conditionalChildSumProof": sum_proof,
        }
        return split_proof, children

    def split_partition_with_unanswered_residual(
        parent: Mapping[str, Any], residual_axis_index: int, *, role: str
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        if not 0 <= residual_axis_index < len(residual_plans):
            raise ValueError(
                f"residual axis index {residual_axis_index} is out of range"
            )
        (
            residual_axis_name,
            residual_question_id,
            max_global_unanswered_voters,
            residual_plan,
        ) = residual_plans[residual_axis_index]
        parent_filters = [
            (
                decimal_identifier(item["questionId"], "filter.questionId"),
                decimal_identifier(item["answerId"], "filter.answerId"),
            )
            for item in parent["filters"]
        ]
        conditional_requirement = MUSIC_COVOTE_CONDITIONAL_AXIS_REQUIREMENTS.get(
            residual_question_id
        )
        conditional_requirement_satisfied = (
            conditional_requirement is None
            or conditional_requirement in set(parent_filters)
        )
        explicit_children: list[dict[str, Any]] = []
        explicit_answer_ids: list[int] = []
        for answer in residual_plan["partitions"]:
            answer_id = decimal_identifier(
                answer["answerId"], "residualAnswer.answerId"
            )
            child_filters = [
                *parent_filters,
                (residual_question_id, answer_id),
            ]
            child = get_child_stats(child_filters)
            child["answer"] = answer["answer"]
            if not parent_filters and child["numVote"] != answer["expectedNumVote"]:
                raise ValueError(
                    "global residual-axis child numVote differs from official "
                    f"categorical result for {child['query']}"
                )
            explicit_children.append(child)
            explicit_answer_ids.append(answer_id)

        residual, residual_proof = derive_unanswered_residual_partition(
            parent,
            explicit_children,
            question_id=residual_question_id,
            explicit_answer_ids=explicit_answer_ids,
            max_global_unanswered_voters=max_global_unanswered_voters,
        )
        residual_path = music_partition_residual_path(
            config,
            parent_filters,
            question_id=residual_question_id,
        )
        residual_payload = {
            "schemaVersion": 1,
            "round": config.number,
            "generatedAt": core.utc_now(),
            "role": role,
            "axisName": residual_axis_name,
            "residualAxisIndex": residual_axis_index,
            "conditionalParentRequirement": (
                {
                    "questionId": conditional_requirement[0],
                    "answerId": conditional_requirement[1],
                }
                if conditional_requirement is not None
                else None
            ),
            "conditionalParentRequirementSatisfied": (
                conditional_requirement_satisfied
            ),
            "method": (
                "exact parent minus "
                f"{len(explicit_children)} explicit official answer cohorts"
            ),
            "parent": public_partition_record(parent),
            "questionDefinitionProof": residual_plan[
                "mutualExclusionAndCoverageProof"
            ],
            "explicitChildren": [
                public_partition_record(child) for child in explicit_children
            ],
            "residual": public_partition_record(residual),
            "residualDerivationProof": residual_proof,
        }
        core.atomic_write_json(residual_path, residual_payload, pretty=True)
        residual_evidence = {
            **music_partition_file_record(residual_path),
            "operation": "local_exact_unanswered_complement",
            "role": role,
        }
        residual["statsEvidence"] = residual_evidence
        audit["derivedResiduals"].append(
            {
                "role": role,
                "axisName": residual_axis_name,
                "questionId": residual_question_id,
                "residualAxisIndex": residual_axis_index,
                "parentQuery": parent.get("query"),
                "status": "validated",
                **residual_evidence,
                "subtractions": residual_proof["subtractions"],
                "nonnegativeResidualPassed": True,
                "combinedExactConservationPassed": True,
            }
        )
        save_audit()
        split_proof = {
            "axisName": residual_axis_name,
            "residualAxisIndex": residual_axis_index,
            "questionId": residual_plan["questionId"],
            "question": residual_plan["question"],
            "questionType": residual_plan["questionType"],
            "optionCount": residual_plan["optionCount"],
            "conditionalParentRequirement": (
                {
                    "questionId": conditional_requirement[0],
                    "answerId": conditional_requirement[1],
                }
                if conditional_requirement is not None
                else None
            ),
            "conditionalParentRequirementSatisfied": (
                conditional_requirement_satisfied
            ),
            "coverageMode": (
                f"{len(explicit_children)} explicit official answers plus exact "
                "unanswered residual"
            ),
            "definitionMutualExclusionAndGlobalCoverageProof": residual_plan[
                "mutualExclusionAndCoverageProof"
            ],
            "conditionalResidualDerivationProof": residual_proof,
            "residualEvidence": residual_evidence,
        }
        return split_proof, explicit_children, residual

    def resolve_partition_with_unit_witness(
        parent: Mapping[str, Any],
        *,
        failed_covote_attempt: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Final exact fallback for an unresolved two-music-voter parent."""

        selection: dict[str, Any] | None = None
        expected_stats_path: Path | None = None
        expected_proof_path: Path | None = None
        try:
            selection = select_unit_music_witness(
                parent, target_a=target_a, target_b=target_b
            )
            parent_query = str(parent["query"])
            expected_stats_path = music_witness_stats_path(
                config, parent_query, selection["name"]
            )
            expected_proof_path = music_witness_proof_path(
                config, parent_query, selection["name"]
            )
            child = load_or_fetch_music_witness_stats(
                config,
                client,
                parent,
                selection,
                target_a=target_a,
                target_b=target_b,
            )
            audit["statsRequests"].append(
                {
                    "query": child["query"],
                    "status": "validated",
                    "role": "unit witness subset",
                    **child["statsEvidence"],
                }
            )
            split = derive_music_witness_split(parent, child, selection)
            child_resolution = split["childResolution"]
            complement = split["complement"]
            complement_resolution = split["complementResolution"]
            witness_proof = {
                "schemaVersion": 1,
                "round": config.number,
                "generatedAt": core.utc_now(),
                "method": (
                    "deterministic one-vote normal-name music witness; one "
                    "official light child query plus exact parent-minus-child "
                    "complement; both one-music-voter intersections resolved by "
                    "equal Frechet bounds"
                ),
                "parent": public_partition_record(parent),
                "targetPair": {"a": target_a, "b": target_b},
                "selection": split["selection"],
                "officialChildQuery": child["query"],
                "officialChildResponseEvidence": child["statsEvidence"],
                "officialChild": public_partition_record(child),
                "childValidation": split["childValidation"],
                "complement": public_partition_record(complement),
                "conservationProof": split["conservationProof"],
                "childFrechetProof": child_resolution["proof"],
                "complementFrechetProof": complement_resolution["proof"],
                "aggregatedCells": split["cells"],
                "complete": True,
            }
            core.atomic_write_json(expected_proof_path, witness_proof, pretty=True)
            proof_evidence = {
                **music_partition_file_record(expected_proof_path),
                "role": "unit witness exact split proof",
            }
            audit["witnessFallbacks"].append(
                {
                    "parentQuery": parent.get("query"),
                    "status": "validated",
                    "selection": selection,
                    "officialChildResponseEvidence": child["statsEvidence"],
                    "proofEvidence": proof_evidence,
                    "conservationPassed": True,
                    "bothFrechetIntersectionsUnique": True,
                }
            )
            save_audit()
            return {
                "nodeType": "witness_partition_split",
                "partition": public_partition_record(parent),
                "failedCovoteAttempt": dict(failed_covote_attempt),
                "splitProof": {
                    "method": "unit music witness plus exact complement",
                    "selection": selection,
                    "proofEvidence": proof_evidence,
                    "officialChildResponseEvidence": child["statsEvidence"],
                    "conservationProof": split["conservationProof"],
                },
                "children": [
                    {
                        "nodeType": "locally_proven_frechet_leaf",
                        "partition": public_partition_record(child),
                        "exactIntersectionReason": (
                            "official witness child has numMusic=1"
                        ),
                        "localIntersectionProof": child_resolution["proof"],
                        "cells": child_resolution["cells"],
                    },
                    {
                        "nodeType": "locally_proven_frechet_leaf",
                        "partition": public_partition_record(complement),
                        "exactIntersectionReason": (
                            "exact parent-minus-witness complement has numMusic=1"
                        ),
                        "localIntersectionProof": complement_resolution["proof"],
                        "cells": complement_resolution["cells"],
                    },
                ],
                "cells": split["cells"],
            }
        except Exception as exc:
            failure: dict[str, Any] = {
                "parentQuery": parent.get("query"),
                "status": "failed",
                "selection": selection,
                "error": f"{type(exc).__name__}: {exc}",
            }
            if expected_stats_path is not None:
                failure["expectedOfficialChildResponse"] = (
                    music_partition_file_record(expected_stats_path)
                )
            if expected_proof_path is not None:
                failure["expectedProof"] = music_partition_file_record(
                    expected_proof_path
                )
            audit["witnessFallbacks"].append(failure)
            save_audit(error=f"{type(exc).__name__}: {exc}")
            raise RuntimeError(
                "all questionnaire axes were exhausted and the exact unit-witness "
                f"fallback failed for {parent.get('query')}: {exc}"
            ) from exc

    def resolve_partition(
        partition: Mapping[str, Any],
        next_axis_index: int,
        *,
        next_residual_axis_index: int = 0,
    ) -> dict[str, Any]:
        count_a = partition["targetA"]["voteCount"]
        count_b = partition["targetB"]["voteCount"]
        if partition["numMusic"] == 0 or count_a == 0 or count_b == 0:
            cells = derived_partition_cells(partition, 0)
            return {
                "nodeType": "zero_marginal_leaf",
                "partition": public_partition_record(partition),
                "exactIntersectionReason": (
                    "at least one target has official filtered voteCount=0; "
                    "therefore m00=0"
                ),
                "cells": cells,
            }

        local_resolution = try_uniquely_resolve_partition_intersection(partition)
        if local_resolution is not None:
            return {
                "nodeType": "locally_proven_frechet_leaf",
                "partition": public_partition_record(partition),
                "exactIntersectionReason": (
                    "the partition's exact target marginals make its Frechet "
                    "lower and upper bounds equal before any co-vote request"
                ),
                "localIntersectionProof": local_resolution["proof"],
                "cells": local_resolution["cells"],
            }

        rank_a = strict_nonnegative_int(partition["targetA"]["rank"], "rankA")
        rank_b = strict_nonnegative_int(partition["targetB"]["rank"], "rankB")
        requested_top_k = max(rank_a, rank_b)
        expected_endpoint_evidence = endpoint_set_evidence(
            partition["rankingNamesByRank"], requested_top_k
        )
        expected_covote_path = music_partition_covote_path(
            config,
            [
                (
                    decimal_identifier(item["questionId"], "filter.questionId"),
                    decimal_identifier(item["answerId"], "filter.answerId"),
                )
                for item in partition["filters"]
            ],
            top_k=requested_top_k,
        )
        request_record = {
            "query": partition["query"],
            "topK": requested_top_k,
            "safeTopKLimit": MUSIC_COVOTE_SAFE_TOP_K,
            "topKDerivation": {"targetARank": rank_a, "targetBRank": rank_b},
            "expectedEndpointSetEvidence": expected_endpoint_evidence,
            "expectedResponsePath": expected_covote_path.relative_to(
                WORKSPACE
            ).as_posix(),
        }
        unresolved_error: BaseException | None = None
        result: dict[str, Any] | None = None
        if requested_top_k > MUSIC_COVOTE_SAFE_TOP_K:
            unresolved_error = ValueError(
                f"topK {requested_top_k} exceeds safe limit "
                f"{MUSIC_COVOTE_SAFE_TOP_K}"
            )
            request_record.update(
                {
                    "status": "skipped_unsafe_topk",
                    "requestIssued": False,
                    "error": f"ValueError: {unresolved_error}",
                }
            )
            audit["covoteAttempts"].append(request_record)
            save_audit()
        else:
            try:
                result = fetch_music_partition_covote(
                    config,
                    client,
                    partition,
                    target_a=target_a,
                    target_b=target_b,
                )
            except Exception as exc:
                unresolved_error = exc
                request_record.update(
                    {
                        "status": "failed",
                        "requestIssued": True,
                        "error": f"{type(exc).__name__}: {exc}",
                        "responseEvidence": music_partition_file_record(
                            expected_covote_path
                        ),
                    }
                )
                audit["covoteAttempts"].append(request_record)
                save_audit()

        if result is None:
            assert unresolved_error is not None
            if next_axis_index < len(plans):
                split_proof, children = split_partition(partition, next_axis_index)
                child_nodes = [
                    resolve_partition(
                        child,
                        next_axis_index + 1,
                        next_residual_axis_index=next_residual_axis_index,
                    )
                    for child in children
                ]
            else:
                applicable_residual_axis_index = next_residual_axis_index
                while applicable_residual_axis_index < len(residual_plans):
                    candidate_question_id = residual_plans[
                        applicable_residual_axis_index
                    ][1]
                    if conditional_residual_axis_applicable(
                        partition, candidate_question_id
                    ):
                        break
                    applicable_residual_axis_index += 1
                if applicable_residual_axis_index >= len(residual_plans):
                    return resolve_partition_with_unit_witness(
                        partition, failed_covote_attempt=request_record
                    )

                residual_axis_name = residual_plans[
                    applicable_residual_axis_index
                ][0]
                split_proof, children, residual = (
                    split_partition_with_unanswered_residual(
                        partition,
                        applicable_residual_axis_index,
                        role=f"conditional refinement via {residual_axis_name}",
                    )
                )
                child_nodes = [
                    resolve_partition(
                        child,
                        next_axis_index,
                        next_residual_axis_index=(
                            applicable_residual_axis_index + 1
                        ),
                    )
                    for child in children
                ]
                # Conditional complements are part of the actual resolution
                # tree, so unlike the optional global checks below they must be
                # uniquely determined or the bridge fails closed.
                residual_resolution = uniquely_resolve_residual_intersection(
                    residual
                )
                residual_node = {
                    "nodeType": "locally_proven_residual_leaf",
                    "partition": public_partition_record(residual),
                    "exactIntersectionReason": (
                        "the unanswered complement's exact marginals make its "
                        "Frechet lower and upper bounds equal"
                    ),
                    "localIntersectionProof": residual_resolution["proof"],
                    "cells": residual_resolution["cells"],
                }
                child_nodes.append(residual_node)
                audit["derivedResiduals"].append(
                    {
                        "role": "conditional unique intersection",
                        "axisName": residual_axis_name,
                        "questionId": residual_plans[
                            applicable_residual_axis_index
                        ][1],
                        "residualAxisIndex": applicable_residual_axis_index,
                        "parentQuery": partition.get("query"),
                        "status": "locally_proven",
                        "statsEvidence": residual.get("statsEvidence"),
                        "intersectionProof": residual_resolution["proof"],
                    }
                )
                save_audit()
            cells = aggregate_partition_nodes(partition, child_nodes)
            return {
                "nodeType": "refinement_split",
                "partition": public_partition_record(partition),
                "failedCovoteAttempt": request_record,
                "splitProof": split_proof,
                "children": child_nodes,
                "cells": cells,
            }
        assert result is not None
        request_record.update(
            {
                "status": "validated",
                "requestIssued": True,
                **result["responseEvidence"],
                "observedPairCount": result["observedPairCount"],
                "endpointSetEvidence": result["endpointSetEvidence"],
            }
        )
        audit["covoteAttempts"].append(request_record)
        save_audit()
        return {
            "nodeType": "official_covote_leaf",
            "partition": public_partition_record(partition),
            "topK": result["topK"],
            "pairCoverage": {
                "expected": result["expectedPairCount"],
                "observed": result["observedPairCount"],
            },
            "responseEvidence": result["responseEvidence"],
            "endpointSetEvidence": result["endpointSetEvidence"],
            "returnedTargetPair": result["targetPair"],
            "cells": result["cells"],
        }

    try:
        global_residual_axis_proofs: list[dict[str, Any]] = []
        for residual_axis_index, (
            residual_axis_name,
            residual_question_id,
            _,
            _,
        ) in enumerate(residual_plans):
            (
                global_residual_split_proof,
                _global_explicit_children,
                global_unanswered_residual,
            ) = split_partition_with_unanswered_residual(
                root,
                residual_axis_index,
                role=f"global conservation check for {residual_axis_name}",
            )
            global_intersection_evidence = evaluate_global_residual_intersection(
                global_unanswered_residual,
                question_id=residual_question_id,
            )
            global_intersection_required = global_intersection_evidence[
                "globalIntersectionRequired"
            ]
            global_record: dict[str, Any] = {
                "axisName": residual_axis_name,
                "questionId": residual_question_id,
                "residualAxisIndex": residual_axis_index,
                "conditionalParentRequirement": (
                    {
                        "questionId": MUSIC_COVOTE_CONDITIONAL_AXIS_REQUIREMENTS[
                            residual_question_id
                        ][0],
                        "answerId": MUSIC_COVOTE_CONDITIONAL_AXIS_REQUIREMENTS[
                            residual_question_id
                        ][1],
                    }
                    if residual_question_id
                    in MUSIC_COVOTE_CONDITIONAL_AXIS_REQUIREMENTS
                    else None
                ),
                "splitProof": global_residual_split_proof,
                "unansweredResidual": public_partition_record(
                    global_unanswered_residual
                ),
                "observedFacts": {
                    "numVote": global_unanswered_residual["numVote"],
                    "numMusic": global_unanswered_residual["numMusic"],
                    "targetAVoteCount": global_unanswered_residual["targetA"][
                        "voteCount"
                    ],
                    "targetBVoteCount": global_unanswered_residual["targetB"][
                        "voteCount"
                    ],
                },
                **global_intersection_evidence,
            }
            if global_intersection_required:
                audit["derivedResiduals"].append(
                    {
                        "role": "global unique intersection",
                        "axisName": residual_axis_name,
                        "questionId": residual_question_id,
                        "residualAxisIndex": residual_axis_index,
                        "parentQuery": None,
                        "status": "locally_proven",
                        "statsEvidence": global_unanswered_residual.get(
                            "statsEvidence"
                        ),
                        "intersectionProof": global_intersection_evidence[
                            "localIntersectionProof"
                        ],
                    }
                )
            else:
                audit["derivedResiduals"].append(
                    {
                        "role": "global conservation only",
                        "axisName": residual_axis_name,
                        "questionId": residual_question_id,
                        "residualAxisIndex": residual_axis_index,
                        "parentQuery": None,
                        "status": "validated_conservation_only",
                        "statsEvidence": global_unanswered_residual.get(
                            "statsEvidence"
                        ),
                        "globalIntersectionRequired": False,
                        "observedFrechetBounds": global_intersection_evidence[
                            "observedFrechetBounds"
                        ],
                    }
                )
            global_residual_axis_proofs.append(global_record)
            save_audit()
        root_split_proof, root_children = split_partition(root, 0)
        root_nodes = [resolve_partition(child, 1) for child in root_children]
        root_cells = aggregate_partition_nodes(root, root_nodes)
        resolution_tree = {
            "nodeType": "refinement_split",
            "partition": public_partition_record(root),
            "splitProof": root_split_proof,
            "children": root_nodes,
            "cells": root_cells,
        }
        node_counts = partition_resolution_counts(resolution_tree)
        proof = {
            "schemaVersion": 1,
            "round": config.number,
            "officialEndpoint": core.ENDPOINT,
            "generatedAt": core.utc_now(),
            "method": (
                "exact adaptive hierarchy over four exhaustive required Single "
                "answers, capped official co-vote topK, and ordered near-exhaustive "
                "or conditionally exhaustive Single-answer splits with exact "
                "unanswered complements; uniquely equal Frechet bounds are "
                "resolved before co-vote requests; a final deterministic unit "
                "music witness split is available for a two-music-voter leaf"
            ),
            "safeTopKLimit": MUSIC_COVOTE_SAFE_TOP_K,
            "queryDocuments": {
                key: query_documents[key]
                for key in (
                    "OptionCondition",
                    "MusicCovotePartitionStats",
                    "MusicCovoteQuestionnairePartition",
                )
            },
            "definitionSources": {
                "questions": {
                    **music_partition_file_record(questions_path),
                },
                "options": {**music_partition_file_record(options_path)},
                "categoricalResults": {
                    **music_partition_file_record(categorical_path)
                },
                "base": {**music_partition_file_record(base_path)},
            },
            "refinementAxisPriority": [
                *[
                    {
                        "axisName": name,
                        "questionId": plan["questionId"],
                        "coverageMode": "exhaustive explicit Single answers",
                    }
                    for name, plan in plans
                ],
                *[
                    {
                        "axisName": name,
                        "questionId": plan["questionId"],
                        "maximumGlobalUnansweredVoters": maximum,
                        "conditionalParentRequirement": (
                            {
                                "questionId": MUSIC_COVOTE_CONDITIONAL_AXIS_REQUIREMENTS[
                                    plan["questionId"]
                                ][0],
                                "answerId": MUSIC_COVOTE_CONDITIONAL_AXIS_REQUIREMENTS[
                                    plan["questionId"]
                                ][1],
                            }
                            if plan["questionId"]
                            in MUSIC_COVOTE_CONDITIONAL_AXIS_REQUIREMENTS
                            else None
                        ),
                        "globalIntersectionRequired": (
                            plan["questionId"]
                            not in MUSIC_COVOTE_GLOBAL_INTERSECTION_OPTIONAL
                        ),
                        "coverageMode": (
                            "explicit answers plus exact unanswered residual"
                        ),
                    }
                    for name, _, maximum, plan in residual_plans
                ],
            ],
            "globalResidualAxisProofs": global_residual_axis_proofs,
            "targetPair": {
                "a": target_a,
                "b": target_b,
                "aBaseVoteCount": target_a_count,
                "bBaseVoteCount": target_b_count,
            },
            "resolutionTree": resolution_tree,
            "resolutionNodeCounts": dict(node_counts),
            "aggregatedTargetPair": {"a": target_a, "b": target_b, **root_cells},
            "rootIdentityProof": {
                "sumLeafNumVote": total_voters,
                "roundNumVote": total_voters,
                "sumLeafNumMusic": sum(root_cells.values()),
                "roundNumMusic": total_music,
                "aMarginalExpression": "m00 + m10",
                "aMarginalObserved": root_cells["m00"] + root_cells["m10"],
                "aBaseVoteCount": target_a_count,
                "bMarginalExpression": "m00 + m01",
                "bMarginalObserved": root_cells["m00"] + root_cells["m01"],
                "bBaseVoteCount": target_b_count,
                "allIdentitiesPassed": True,
            },
            "complete": True,
        }
        core.atomic_write_json(proof_path, proof, pretty=True)
        audit["proofPath"] = proof_path.relative_to(WORKSPACE).as_posix()
        audit["proofSha256"] = core.sha256_file(proof_path)
        save_audit(complete=True)
    except Exception as exc:
        save_audit(error=f"{type(exc).__name__}: {exc}")
        raise
    return {
        "intersection": root_cells["m00"],
        "partitionCount": (
            node_counts["zero_marginal_leaf"]
            + node_counts["official_covote_leaf"]
            + node_counts["locally_proven_residual_leaf"]
            + node_counts["locally_proven_frechet_leaf"]
        ),
        "refinementSplitCount": (
            node_counts["refinement_split"]
            + node_counts["witness_partition_split"]
        ),
        "proofPath": proof_path,
        "proofSha256": core.sha256_file(proof_path),
        "attemptsPath": attempts_path,
        "attemptsSha256": core.sha256_file(attempts_path),
    }


def reconstruct_music_covote_with_reciprocal_sources(
    config: core.RoundConfig,
    client: core.PublicClient,
    base: Mapping[str, Any],
    specs: Sequence[ConditionSpec],
    output: Path,
    *,
    direct_count_error: BaseException,
) -> None:
    """Complete a music matrix when a few official name filters are broken.

    Co-vote intersections are symmetric.  Therefore every pair with at least
    one queryable endpoint is available from that endpoint's official
    conditional ranking.  Only pairs whose *both* endpoints have the official
    trailing-control defect need a bridge value.  Four exhaustive official
    required-Single axes, followed if necessary by ordered near-exhaustive
    Single axes whose explicit answers and exact unanswered complements cover
    every voter, supply that intersection without an oversized unfiltered
    all-pairs response.
    """

    entries = list(base["data"]["queryMusicRanking"]["entries"])
    names = [str(entry["name"]) for entry in entries]
    if len(names) != len(set(names)):
        raise ValueError("music catalogue contains ambiguous duplicate names")
    base_counts = {
        str(entry["name"]): int(entry["voteCount"]) for entry in entries
    }
    universe = int(base["data"]["queryGlobalStats"]["numMusic"])
    name_set = set(names)

    filtered_maps: dict[int, dict[str, int]] = {}
    missing_specs: list[ConditionSpec] = []
    for spec in specs:
        if not existing_covote_source_valid(config, spec):
            missing_specs.append(spec)
            continue
        wrapper = core.load_json(covote_source_path(config, spec))
        result = wrapper["data"]["queryMusicRanking"]
        filtered = {
            str(item["name"]): int(item["voteCount"])
            for item in result["entries"]
        }
        unknown = sorted(set(filtered) - name_set)
        if unknown:
            raise ValueError(
                f"conditional music source {spec.source_index} contains unknown names: "
                f"{unknown[:10]}"
            )
        filtered_maps[spec.source_index - 1] = filtered

    bridge_lookup: dict[frozenset[str], int] = {}
    partition_bridge: dict[str, Any] | None = None
    for spec in missing_specs:
        response = response_path(config, spec)
        probe = normalized_probe_path(config, spec)
        if (
            not response.is_file()
            or official_query_defect_reason(core.load_json(response), spec) is None
            or not probe.is_file()
            or int(core.load_json(probe)["data"]["queryGlobalStats"]["numVote"])
            != 0
        ):
            raise ValueError(
                f"music source {spec.source_index} is missing without the full "
                "archived official-query-defect proof chain"
            )
    if len(missing_specs) > 1:
        if len(missing_specs) != 2:
            raise ValueError(
                "adaptive questionnaire bridge currently requires exactly two "
                "fully proven defective music filters"
            )
        missing_specs.sort(key=lambda item: item.source_index)
        target_a_spec, target_b_spec = missing_specs
        partition_bridge = fetch_music_missing_pair_questionnaire_bridge(
            config,
            client,
            base,
            top_k=max(spec.source_index for spec in missing_specs),
            target_a=target_a_spec.source_name,
            target_b=target_b_spec.source_name,
            target_a_count=target_a_spec.expected_cohort,
            target_b_count=target_b_spec.expected_cohort,
        )
        bridge_lookup[
            frozenset((target_a_spec.source_name, target_b_spec.source_name))
        ] = int(partition_bridge["intersection"])

    items: list[dict[str, Any]] = []
    symmetry_mismatches: list[dict[str, Any]] = []
    invariant_failures: list[dict[str, Any]] = []
    missing_pair_evidence: list[dict[str, Any]] = []
    evidence_counts = {
        "twoConditionalDirections": 0,
        "oneReciprocalConditionalDirection": 0,
        "officialQuestionnairePartitionSum": 0,
    }
    for source_index in range(1, len(entries)):
        source_name = names[source_index]
        count_a = base_counts[source_name]
        for target_index in range(source_index):
            target_name = names[target_index]
            count_b = base_counts[target_name]
            candidates: list[tuple[str, int]] = []
            if source_index in filtered_maps:
                candidates.append(
                    (
                        "a_filter",
                        filtered_maps[source_index].get(target_name, 0),
                    )
                )
            if target_index in filtered_maps:
                candidates.append(
                    (
                        "b_filter",
                        filtered_maps[target_index].get(source_name, 0),
                    )
                )
            if len(candidates) == 2:
                evidence_counts["twoConditionalDirections"] += 1
                if candidates[0][1] != candidates[1][1]:
                    if len(symmetry_mismatches) < 20:
                        symmetry_mismatches.append(
                            {
                                "a": source_name,
                                "b": target_name,
                                "aFilterCountB": candidates[0][1],
                                "bFilterCountA": candidates[1][1],
                            }
                        )
                intersection = candidates[0][1]
            elif len(candidates) == 1:
                evidence_counts["oneReciprocalConditionalDirection"] += 1
                intersection = candidates[0][1]
            else:
                pair = frozenset((source_name, target_name))
                if pair not in bridge_lookup:
                    if len(missing_pair_evidence) < 20:
                        missing_pair_evidence.append(
                            {"a": source_name, "b": target_name}
                        )
                    continue
                evidence_counts["officialQuestionnairePartitionSum"] += 1
                intersection = bridge_lookup[pair]

            item = {
                "a": source_name,
                "b": target_name,
                "m00": intersection,
                "m01": count_b - intersection,
                "m10": count_a - intersection,
                "m11": universe - count_a - count_b + intersection,
            }
            if (
                any(item[key] < 0 for key in ("m00", "m01", "m10", "m11"))
                or item["m00"] + item["m10"] != count_a
                or item["m00"] + item["m01"] != count_b
                or sum(item[key] for key in ("m00", "m01", "m10", "m11"))
                != universe
            ) and len(invariant_failures) < 20:
                invariant_failures.append(
                    {
                        **item,
                        "expectedCountA": count_a,
                        "expectedCountB": count_b,
                        "universe": universe,
                    }
                )
            items.append(item)

    expected_pairs = len(entries) * (len(entries) - 1) // 2
    if (
        len(items) != expected_pairs
        or symmetry_mismatches
        or invariant_failures
        or missing_pair_evidence
    ):
        raise AssertionError(
            json.dumps(
                {
                    "expectedPairs": expected_pairs,
                    "observedPairs": len(items),
                    "symmetryMismatches": symmetry_mismatches,
                    "invariantFailures": invariant_failures,
                    "missingPairEvidence": missing_pair_evidence,
                },
                ensure_ascii=False,
            )
        )

    crosscheck_k = min(10, len(entries))
    crosscheck_path = config.root / "covote" / f"direct_top{crosscheck_k}_music.json"
    direct_topk_crosscheck: dict[str, Any]
    try:
        direct_topk = core.fetch_graphql_checkpoint(
            client,
            crosscheck_path,
            "MusicCovoteCounts",
            core.MUSIC_COVOTE_COUNTS_QUERY,
            core.base_variables(config, topK=crosscheck_k),
            resume=True,
            timeout=300,
            context={
                "scope": f"top-{crosscheck_k} field-convention cross-check",
                "expectedPairCount": crosscheck_k * (crosscheck_k - 1) // 2,
            },
        )
        reconstructed = {
            (str(item["a"]), str(item["b"])): item
            for item in items
            if str(item["a"]) in set(names[:crosscheck_k])
            and str(item["b"]) in set(names[:crosscheck_k])
        }
        direct_items = direct_topk["data"]["queryMusicsCovote"]["items"]
        mismatches = []
        for direct_item in direct_items:
            rebuilt = reconstructed.get(
                (str(direct_item["a"]), str(direct_item["b"]))
            )
            if rebuilt is None or any(
                int(direct_item[cell]) != rebuilt[cell]
                for cell in ("m00", "m01", "m10", "m11")
            ):
                mismatches.append(
                    {"direct": direct_item, "reconstructed": rebuilt}
                )
        if (
            len(direct_items) != crosscheck_k * (crosscheck_k - 1) // 2
            or mismatches
        ):
            raise AssertionError(
                json.dumps(mismatches[:20], ensure_ascii=False)
            )
        direct_topk_crosscheck = {
            "available": True,
            "topK": crosscheck_k,
            "pairsChecked": len(direct_items),
            "mismatches": [],
        }
    except Exception as exc:
        if isinstance(exc, AssertionError):
            raise
        direct_topk_crosscheck = {
            "available": False,
            "topK": crosscheck_k,
            "error": f"{type(exc).__name__}: {exc}",
        }

    validation_path = config.root / "covote" / "music_reconstruction_validation.json"
    validation = {
        "round": config.number,
        "category": "music",
        "sourceItems": len(entries),
        "sourceCheckpointsAvailable": len(filtered_maps),
        "missingConditionalSources": [
            {
                "sourceIndex": spec.source_index,
                **source_name_metadata(spec),
                "reason": "official_query_defect",
            }
            for spec in missing_specs
        ],
        "expectedPairs": expected_pairs,
        "observedPairs": len(items),
        "universe": universe,
        "pairEvidenceCounts": evidence_counts,
        "cellConvention": {
            "m00": "both selected (intersection)",
            "m01": "a not selected, b selected",
            "m10": "a selected, b not selected",
            "m11": "neither selected",
        },
        "allMarginalAndUniverseIdentitiesPassed": True,
        "allAvailableConditionalSymmetryChecksPassed": True,
        "symmetryPairsChecked": evidence_counts["twoConditionalDirections"],
        "directTopKCrosscheck": direct_topk_crosscheck,
        "questionnairePartitionBridge": (
            {
                "proofPath": partition_bridge["proofPath"]
                .relative_to(WORKSPACE)
                .as_posix(),
                "proofSha256": partition_bridge["proofSha256"],
                "attemptsPath": partition_bridge["attemptsPath"]
                .relative_to(WORKSPACE)
                .as_posix(),
                "attemptsSha256": partition_bridge["attemptsSha256"],
                "finalLeafCount": partition_bridge["partitionCount"],
                "refinementSplitCount": partition_bridge[
                    "refinementSplitCount"
                ],
                "pairsUsed": evidence_counts[
                    "officialQuestionnairePartitionSum"
                ],
            }
            if partition_bridge
            else None
        ),
    }
    core.atomic_write_json(validation_path, validation, pretty=True)
    validation_sha256 = core.sha256_file(validation_path)
    wrapper = {
        "provenance": {
            "source": core.ENDPOINT,
            "method": "official POST responses combined locally",
            "operation": "MusicCovoteReciprocalMatrixReconstruction",
            "generatedAt": core.utc_now(),
            "sourceCheckpointDirectory": (
                config.root / "covote" / "conditional_music"
            ).relative_to(WORKSPACE).as_posix(),
            "sourceCheckpointCount": len(filtered_maps),
            "questionnairePartitionProofPath": (
                partition_bridge["proofPath"].relative_to(WORKSPACE).as_posix()
                if partition_bridge
                else None
            ),
            "questionnairePartitionProofSha256": (
                partition_bridge["proofSha256"] if partition_bridge else None
            ),
            "questionnairePartitionAttemptsPath": (
                partition_bridge["attemptsPath"].relative_to(WORKSPACE).as_posix()
                if partition_bridge
                else None
            ),
            "questionnairePartitionAttemptsSha256": (
                partition_bridge["attemptsSha256"] if partition_bridge else None
            ),
        },
        "context": {
            "topK": len(entries),
            "expectedPairCount": expected_pairs,
            "scope": "complete unfiltered ranking, not merely a display top-N",
            "responseMode": (
                "official reciprocal conditional rankings plus an exact "
                "adaptive official questionnaire-partition sum"
            ),
            "metricPolicy": (
                "retain official contingency cells; recompute association "
                "metrics locally"
            ),
            "fieldConvention": validation["cellConvention"],
            "validationPath": validation_path.relative_to(WORKSPACE).as_posix(),
            "validationSha256": validation_sha256,
            "officialFullCountMatrixFailure": (
                f"{type(direct_count_error).__name__}: {direct_count_error}"
            ),
        },
        "data": {"queryMusicsCovote": {"items": items}},
    }
    core.atomic_write_json(output, wrapper)


def advanced_covote_matrix_checkpoint_valid(
    path: Path,
    *,
    category: str,
    graphql_key: str,
    expected_pairs: int,
    base: Mapping[str, Any],
) -> bool:
    """Use the evidence-bound validator for locally reconstructed music.

    Direct official matrices and non-music matrices retain the generic format,
    while the CN11 reciprocal reconstruction must prove the exact catalogue,
    every marginal identity, and its hashed questionnaire-bridge chain.
    """

    if category == "music":
        try:
            wrapper = core.load_json(path)
            provenance = wrapper.get("provenance", {})
            context = wrapper.get("context", {})
            operation = provenance.get("operation")
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            return False
        reconstruction_markers = (
            provenance.get("method") == "official POST responses combined locally"
            or any(
                key in provenance
                for key in (
                    "questionnairePartitionProofPath",
                    "questionnairePartitionProofSha256",
                    "questionnairePartitionAttemptsPath",
                    "questionnairePartitionAttemptsSha256",
                )
            )
            or "validationSha256" in context
            or "adaptive official questionnaire-partition sum"
            in str(context.get("responseMode", ""))
        )
        if (
            operation == "MusicCovoteReciprocalMatrixReconstruction"
            or reconstruction_markers
        ):
            return reconstructed_music_matrix_checkpoint_valid(
                path,
                base=base,
                workspace=WORKSPACE,
                require_bridge=True,
            )
        if (
            provenance.get("source") != core.ENDPOINT
            or provenance.get("method") != "POST"
            or operation
            not in {
                "MusicCovote",
                "MusicCovoteCounts",
                "MusicCovoteConditionalSourceMatrixReconstruction",
            }
        ):
            return False
    return core.covote_matrix_checkpoint_valid(
        path, graphql_key=graphql_key, expected_pairs=expected_pairs
    )


def rebuild_covote(
    config: core.RoundConfig,
    client: core.PublicClient,
) -> list[dict[str, Any]]:
    base = core.load_json(config.root / "graphql" / "base.json")
    failures: list[dict[str, Any]] = []
    for category, output_name, graphql_key, rank_key, filter_key, operation, document, direct_operation, direct_document, count_operation, count_document in [
        (
            "character",
            "characters.json",
            "queryCharsCovote",
            "queryCharacterRanking",
            "chars",
            "CharacterCovoteConditionalSource",
            core.CHARACTER_COVOTE_CONDITIONAL_QUERY,
            "CharacterCovote",
            core.CHARACTER_COVOTE_QUERY,
            "CharacterCovoteCounts",
            core.CHARACTER_COVOTE_COUNTS_QUERY,
        ),
        (
            "music",
            "music.json",
            "queryMusicsCovote",
            "queryMusicRanking",
            "musics",
            "MusicCovoteConditionalSource",
            core.MUSIC_COVOTE_CONDITIONAL_QUERY,
            "MusicCovote",
            core.MUSIC_COVOTE_QUERY,
            "MusicCovoteCounts",
            core.MUSIC_COVOTE_COUNTS_QUERY,
        ),
    ]:
        count = len(base["data"][rank_key]["entries"])
        expected_pairs = count * (count - 1) // 2
        output = config.root / "covote" / output_name
        if advanced_covote_matrix_checkpoint_valid(
            output,
            category=category,
            graphql_key=graphql_key,
            expected_pairs=expected_pairs,
            base=base,
        ):
            print(f"round {config.number} {category} covote matrix: resumed", flush=True)
            continue
        direct_count_error: Exception | None = None
        try:
            core.fetch_graphql_checkpoint(
                client,
                output,
                count_operation,
                count_document,
                core.base_variables(config, topK=count),
                resume=False,
                timeout=900 if category == "music" else 600,
                context={
                    "topK": count,
                    "expectedPairCount": expected_pairs,
                    "scope": "complete unfiltered ranking, not merely a display top-N",
                    "responseMode": "official_contingency_counts_only",
                    "metricPolicy": (
                        "retain official m00/m01/m10/m11 and recompute derived "
                        "association metrics locally"
                    ),
                },
            )
            if not advanced_covote_matrix_checkpoint_valid(
                output,
                category=category,
                graphql_key=graphql_key,
                expected_pairs=expected_pairs,
                base=base,
            ):
                raise ValueError("official count-only matrix failed validation")
            print(
                f"round {config.number} {category} covote matrix: "
                "official count-only endpoint",
                flush=True,
            )
            continue
        except Exception as exc:
            direct_count_error = exc
        specs = [
            spec
            for spec in build_specs(base)
            if spec.source_category == category and spec.kind == "any"
        ]
        missing = [
            spec.source_index
            for spec in specs
            if not existing_covote_source_valid(config, spec)
        ]
        if missing:
            if category == "music" and direct_count_error is not None:
                try:
                    reconstruct_music_covote_with_reciprocal_sources(
                        config,
                        client,
                        base,
                        specs,
                        output,
                        direct_count_error=direct_count_error,
                    )
                    if not advanced_covote_matrix_checkpoint_valid(
                        output,
                        category=category,
                        graphql_key=graphql_key,
                        expected_pairs=expected_pairs,
                        base=base,
                    ):
                        raise ValueError(
                            "reciprocal music matrix failed final validation"
                        )
                    print(
                        f"round {config.number} music covote matrix: "
                        "reciprocal conditions plus exact questionnaire-partition sum",
                        flush=True,
                    )
                except Exception as exc:
                    failures.append(
                        {
                            "category": category,
                            "status": "fetch_failed",
                            "missingConditionalSources": missing,
                            "officialCountMatrixError": (
                                f"{type(direct_count_error).__name__}: "
                                f"{direct_count_error}"
                            ),
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                continue
            failures.append(
                {
                    "category": category,
                    "status": "pending",
                    "missingConditionalSources": missing,
                    "officialCountMatrixError": (
                        f"{type(direct_count_error).__name__}: {direct_count_error}"
                    ),
                }
            )
            continue
        try:
            core.reconstruct_covote_from_conditional_rankings(
                config,
                client,
                base,
                category=category,
                output_path=output,
                graphql_key=graphql_key,
                ranking_key=rank_key,
                filter_key=filter_key,
                operation=operation,
                document=document,
                direct_operation=direct_operation,
                direct_document=direct_document,
                resume=True,
                direct_failure_evidence={
                    "status": "fetch_failed",
                    "operation": count_operation,
                    "error": (
                        f"{type(direct_count_error).__name__}: {direct_count_error}"
                    ),
                    "interpretation": (
                        "official count-only matrix failed, so the matrix was "
                        "reconstructed from official conditional rankings"
                    ),
                },
            )
        except Exception as exc:
            failures.append(
                {
                    "category": category,
                    "status": "fetch_failed",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    return failures


def validate_round(config: core.RoundConfig) -> dict[str, Any]:
    base = core.load_json(config.root / "graphql" / "base.json")
    specs = build_specs(base)
    index_path = advanced_root(config) / "index.json"
    q_records = questionnaire_condition_records(config)
    groups: dict[str, dict[str, Any]] = {}
    invalid_details: list[dict[str, Any]] = []
    official_query_defects: list[dict[str, Any]] = []
    for category in ("character", "music"):
        for kind in ("any", "first"):
            selected = [
                spec
                for spec in specs
                if spec.source_category == category
                and spec.kind == kind
                and (kind == "any" or spec.expected_cohort > 0)
            ]
            valid_count = 0
            defect_count = 0
            missing = 0
            invalid = 0
            for spec in selected:
                path = response_path(config, spec)
                if not path.is_file():
                    missing += 1
                    continue
                try:
                    value = core.load_json(path)
                    ok, reason = validate_rankings(value, spec)
                    defect_reason = official_query_defect_reason(value, spec)
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    ok, reason, defect_reason = (
                        False,
                        f"{type(exc).__name__}: {exc}",
                        None,
                    )
                if ok:
                    valid_count += 1
                elif defect_reason:
                    defect_count += 1
                    probe_path = normalized_probe_path(config, spec)
                    official_query_defects.append(
                        {
                            "dimension": f"{category}_{kind}",
                            "sourceIndex": spec.source_index,
                            **source_name_metadata(spec),
                            "expectedCohort": spec.expected_cohort,
                            "officialGuiQuery": spec.query_filter,
                            "officialGuiObservedCohort": 0,
                            "reason": defect_reason,
                            "responsePath": path.relative_to(WORKSPACE).as_posix(),
                            "responseSha256": core.sha256_file(path),
                            "normalizedProbePath": (
                                probe_path.relative_to(WORKSPACE).as_posix()
                                if probe_path.is_file()
                                else None
                            ),
                            "normalizedProbeSha256": (
                                core.sha256_file(probe_path)
                                if probe_path.is_file()
                                else None
                            ),
                        }
                    )
                else:
                    invalid += 1
                    if len(invalid_details) < 50:
                        invalid_details.append(
                            {
                                "dimension": f"{category}_{kind}",
                                "sourceIndex": spec.source_index,
                                "sourceName": spec.source_name,
                                "reason": reason,
                            }
                        )
            zero = sum(
                1
                for spec in specs
                if spec.source_category == category
                and spec.kind == kind
                and spec.expected_cohort == 0
            )
            groups[f"{category}_{kind}"] = {
                "catalogueItems": sum(
                    1
                    for spec in specs
                    if spec.source_category == category and spec.kind == kind
                ),
                "statisticallyNonemptyExpected": len(selected),
                "availableCrawled": valid_count,
                "officialQueryDefects": defect_count,
                "accountedResponses": valid_count + defect_count,
                "missing": missing,
                "invalid": invalid,
                "zeroCohortNotRequested": zero if kind == "first" else 0,
            }

    covote: dict[str, Any] = {}
    for category, filename, graphql_key, rank_key in [
        ("character", "characters.json", "queryCharsCovote", "queryCharacterRanking"),
        ("music", "music.json", "queryMusicsCovote", "queryMusicRanking"),
    ]:
        count = len(base["data"][rank_key]["entries"])
        expected = count * (count - 1) // 2
        path = config.root / "covote" / filename
        valid = advanced_covote_matrix_checkpoint_valid(
            path,
            category=category,
            graphql_key=graphql_key,
            expected_pairs=expected,
            base=base,
        )
        covote[category] = {
            "sourceItems": count,
            "expectedPairs": expected,
            "availablePairs": expected if valid else 0,
            "complete": valid,
        }

    entity_complete = all(
        item["missing"] == 0 and item["invalid"] == 0
        for item in groups.values()
    )
    questionnaire_valid = sum(
        item["status"] == "available_crawled" for item in q_records
    )
    questionnaire_analytical = [
        item for item in q_records if item["questionType"] != "Input"
    ]
    questionnaire_placeholders = [
        item for item in q_records if item["questionType"] == "Input"
    ]
    pair_inventory = questionnaire_pair_inventory(config)
    pair_coverage = questionnaire_pair_coverage(config)
    complete = (
        entity_complete
        and questionnaire_valid == len(q_records)
        and all(item["complete"] for item in covote.values())
        and pair_coverage["complete"]
    )
    # CN5--9 expose a dedicated PHP ``votepaper`` endpoint that returns the
    # complete answer-by-answer matrix for each unordered questionnaire pair.
    # The CN10/11 GraphQL schema exposes only the generic Boolean query string,
    # so the crawler restores the same finite cross-table one answer cell at a
    # time and keeps every official response in a resumable pair checkpoint.
    questionnaire_pair_status = (
        "available_crawled"
        if pair_coverage["complete"]
        else "partial"
        if pair_coverage["availableAnswerCells"]
        else "pending"
    )
    questionnaire_pair_reason = (
        "modern GraphQL archive has no official all-answer questionnaire "
        "cross-tab operation; parity uses explicit qA=a AND qB=b cell queries"
    )
    pair_plan_path = advanced_root(config) / "questionnaire_pair_plan.json"
    return {
        "round": config.number,
        "sourceSite": config.base_url,
        "complete": complete,
        "legacyParityComplete": complete,
        "legacyParityReason": questionnaire_pair_reason,
        "questionnaireAnswerConditions": {
            "archivalExpected": len(q_records),
            "archivalAvailableCrawled": questionnaire_valid,
            "analyticallyMeaningfulExpected": len(questionnaire_analytical),
            "analyticallyMeaningfulAvailableCrawled": sum(
                item["status"] == "available_crawled"
                for item in questionnaire_analytical
            ),
            "inputPlaceholderExpected": len(questionnaire_placeholders),
            "inputPlaceholderAvailableCrawled": sum(
                item["status"] == "available_crawled"
                for item in questionnaire_placeholders
            ),
            "inputPlaceholderPolicy": "preserve the zero-result official response for completeness; exclude it from numerical analysis because the Input answer body is not a categorical option",
            "fetchFailed": sum(item["status"] == "fetch_failed" for item in q_records),
            "pending": sum(item["status"] == "pending" for item in q_records),
        },
        "entityAtomicConditions": groups,
        "questionnaireUnorderedPairs": {
            "status": questionnaire_pair_status,
            "eligibleQuestions": pair_inventory["eligibleQuestionCount"],
            "eligibleAnswerOptions": pair_inventory["eligibleAnswerOptionCount"],
            "expected": pair_inventory["unorderedQuestionPairCount"],
            "available": pair_coverage["availablePairs"],
            "expectedAnswerCells": pair_inventory["answerCellCount"],
            "availableAnswerCells": pair_coverage["availableAnswerCells"],
            "invalidDetails": pair_coverage["invalidDetails"],
            "recordUnit": "unordered_question_pair_matrix",
            "reason": questionnaire_pair_reason,
            "queryLanguageEquivalent": True,
            "planPath": (
                pair_plan_path.relative_to(WORKSPACE).as_posix()
                if pair_plan_path.is_file()
                else None
            ),
            "planExpectedPath": pair_plan_path.relative_to(WORKSPACE).as_posix(),
        },
        "covoteMatrices": covote,
        "officialQueryDefects": official_query_defects,
        "invalidDetails": invalid_details,
        "indexPath": index_path.relative_to(WORKSPACE).as_posix() if index_path.is_file() else None,
        "boundedCoveragePolicy": {
            "captured": [
                "every categorical questionnaire-answer singleton -> global + character/music/CP rankings",
                "every character-any singleton -> global + character/music/CP rankings",
                "every nonzero character-first singleton -> global + character/music/CP rankings",
                "every music-any singleton was issued through the official GUI spelling; successful responses and reproducible official empty-cohort defects are both archived",
                "every nonzero music-first singleton was issued through the official GUI spelling; successful responses and reproducible official empty-cohort defects are both archived",
                "every categorical questionnaire pair -> every answer intersection count via explicit Boolean cell queries",
            ],
            "notEnumerated": [
                "higher-order and mixed-family AND/OR products beyond the finite two-question legacy parity surface",
                "zero-cohort first-choice constraints (official base firstVoteCount=0)",
                "front-end keyword/rank/count display filters reproducible locally from archived rankings",
            ],
            "contentExcluded": [
                "recommendation reasons and comments",
                "images and fonts",
                "private vote-token interfaces",
            ],
            "officialDefectPolicy": (
                "a HTTP-200 empty response for a nonzero catalogue item is only "
                "accounted as an official_query_defect when the catalogue name "
                "ends in TAB/CR/LF and a separately archived control-trimmed "
                "probe also returns zero; it is never treated as a real zero cohort"
            ),
        },
        "coverage_contract": advanced_coverage_contract(
            questionnaire_pair_status=questionnaire_pair_status,
            questionnaire_pair_reason=questionnaire_pair_reason,
        ),
    }


def existing_advanced_definition_sources(round_root: Path) -> list[Path]:
    """Return only proof definition sources that actually exist on disk."""

    return [
        round_root / relative_path
        for relative_path in ADVANCED_MANIFEST_DEFINITION_RELATIVE_PATHS
        if (round_root / relative_path).is_file()
    ]


def advanced_manifest_candidate_paths(config: core.RoundConfig) -> list[Path]:
    candidates = list(advanced_root(config).rglob("*"))
    candidates += list((config.root / "conditions").glob("*.json"))
    # Include the adaptive partition responses/proofs nested below ``covote``
    # as well as the same-department checkpoints.
    candidates += list((config.root / "covote").rglob("*.json"))
    # The bridge proof hashes these exact definitions.  They live outside the
    # advanced/covote trees, so include only the four referenced JSON files.
    candidates += existing_advanced_definition_sources(config.root)
    return candidates


def build_metadata(
    configs: Sequence[core.RoundConfig],
    validations: Sequence[Mapping[str, Any]],
) -> None:
    all_files: list[dict[str, Any]] = []
    rounds: list[dict[str, Any]] = []
    for config in configs:
        candidates = advanced_manifest_candidate_paths(config)
        seen: set[Path] = set()
        round_files: list[dict[str, Any]] = []
        for path in sorted(candidates):
            # A manifest cannot carry a stable hash of itself.  It is named by
            # the round record in the global manifest instead.
            if (
                not path.is_file()
                or path in seen
                or path == advanced_root(config) / "manifest.json"
            ):
                continue
            seen.add(path)
            record = {
                "path": path.relative_to(WORKSPACE).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": core.sha256_file(path),
            }
            round_files.append(record)
            all_files.append(record)
        manifest = {
            "schemaVersion": 1,
            "generatedAt": core.utc_now(),
            "round": config.number,
            "sourceSite": config.base_url,
            "officialEndpoint": core.ENDPOINT,
            "files": round_files,
        }
        core.atomic_write_json(
            advanced_root(config) / "manifest.json", manifest, pretty=True
        )
        rounds.append(
            {
                "round": config.number,
                "fileCount": len(round_files) + 1,
                "manifestPath": (
                    advanced_root(config) / "manifest.json"
                ).relative_to(WORKSPACE).as_posix(),
            }
        )
    core.atomic_write_json(
        METADATA_ROOT / "cn_modern_advanced_manifest.json",
        {
            "schemaVersion": 1,
            "generatedAt": core.utc_now(),
            "crawler": "scripts_pipeline/crawl_cn_modern_advanced.py",
            "officialEndpoint": core.ENDPOINT,
            "rounds": rounds,
            "files": all_files,
        },
        pretty=True,
    )
    core.atomic_write_json(
        METADATA_ROOT / "cn_modern_advanced_coverage.json",
        {
            "schemaVersion": 1,
            "generatedAt": core.utc_now(),
            "scope": "CN10/11 official bounded atomic advanced-search basis",
            "rounds": list(validations),
            "allRequiredChecksPassed": all(item.get("complete") for item in validations),
            "statusPolicy": (
                "fetch_failed is never converted to official_not_offered; "
                "official_query_defect requires archived HTTP-200 official-GUI "
                "and normalized-name zero responses plus a contradictory nonzero "
                "unfiltered catalogue cohort"
            ),
        },
        pretty=True,
    )


def parse_rounds(value: str) -> list[core.RoundConfig]:
    return core.parse_rounds(value)


def execute_queue(
    args: argparse.Namespace,
    configs: Sequence[core.RoundConfig],
) -> int:
    initial_pause = args.batch_pause if args.batch_pause is not None else args.delay
    speed = core.AdaptiveSpeed(
        workers=args.workers,
        request_limit=args.request_limit,
        pause=initial_pause,
        worker_ceiling=args.worker_ceiling,
        request_limit_ceiling=args.request_limit_ceiling,
        pause_ceiling=args.batch_pause_ceiling,
        failure_threshold=args.transient_failure_threshold,
        adaptive_tuning=args.adaptive_tuning,
        stage_id=os.environ.get("DATA_CRAWL_QUEUE_STAGE_ID"),
    )
    client = core.PublicClient(
        delay=args.delay,
        retries=args.retries,
        timeout=args.timeout,
        adaptive_speed=speed,
    )
    crawl_failures: list[dict[str, Any]] = []
    if not args.validate_only:
        for config in configs:
            write_queue_status(
                state="running",
                round=config.number,
                stage="advanced_conditions_start",
                requestedRounds=[item.number for item in configs],
                **speed.status(),
            )
            print(f"round {config.number}: bounded advanced-search crawl", flush=True)
            try:
                failures = crawl_round(
                    config,
                    client,
                    resume=args.resume,
                    max_requests=args.max_requests,
                    transient_failure_threshold=args.transient_failure_threshold,
                )
                crawl_failures.extend(
                    {"round": config.number, **failure} for failure in failures
                )
                if not args.skip_covote_rebuild and not failures:
                    write_queue_status(
                        state="running",
                        round=config.number,
                        stage="covote_rebuild",
                        recordedFailures=len(crawl_failures),
                        **speed.status(),
                    )
                    crawl_failures.extend(
                        {"round": config.number, **failure}
                        for failure in rebuild_covote(config, client)
                    )
            except BaseException as exc:
                crawl_failures.append(
                    {
                        "round": config.number,
                        "stage": "advanced crawl",
                        "status": "fetch_failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                print(
                    f"round {config.number}: FAILED: {exc}",
                    file=sys.stderr,
                    flush=True,
                )

    write_queue_status(
        state="running",
        stage="validation_and_manifest",
        recordedFailures=len(crawl_failures),
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
            }
        validations.append(validation)
        print(
            f"round {config.number}: advanced validation "
            f"{'PASS' if validation.get('complete') else 'FAIL'}",
            flush=True,
        )
    build_metadata(configs, validations)
    result = 0 if all(item.get("complete") for item in validations) and not crawl_failures else 1
    write_queue_status(
        state="complete" if result == 0 else "incomplete",
        stage="finished",
        exitCode=result,
        requestedRounds=[item.number for item in configs],
        recordedFailures=len(crawl_failures),
        **speed.status(),
        coveragePath=(
            METADATA_ROOT / "cn_modern_advanced_coverage.json"
        ).relative_to(WORKSPACE).as_posix(),
        manifestPath=(
            METADATA_ROOT / "cn_modern_advanced_manifest.json"
        ).relative_to(WORKSPACE).as_posix(),
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", default="10,11")
    parser.add_argument("--delay", type=float, default=0.50)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--request-limit", type=int, default=30)
    parser.add_argument("--batch-pause", type=float, default=None)
    parser.add_argument("--worker-ceiling", type=int, default=None)
    parser.add_argument("--request-limit-ceiling", type=int, default=None)
    parser.add_argument("--batch-pause-ceiling", type=float, default=None)
    parser.add_argument(
        "--no-adaptive-tuning",
        dest="adaptive_tuning",
        action="store_false",
        help="keep the configured worker/pause values; retries still apply",
    )
    parser.set_defaults(adaptive_tuning=True)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--transient-failure-threshold", type=int, default=3)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument(
        "--max-requests",
        type=int,
        help="bounded test/batch mode; remaining conditions stay pending",
    )
    parser.add_argument("--skip-covote-rebuild", action="store_true")
    parser.add_argument(
        "--lock-poll-seconds",
        type=float,
        default=5.0,
        help="seconds between checks while another queue process owns the lock",
    )
    args = parser.parse_args(argv)
    configs = parse_rounds(args.rounds)
    if args.delay < 0:
        parser.error("--delay must be non-negative")
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if args.request_limit < 1:
        parser.error("--request-limit must be at least 1")
    if args.batch_pause is not None and args.batch_pause < 0:
        parser.error("--batch-pause must be non-negative")
    if args.retries < 1:
        parser.error("--retries must be at least 1")
    if not 1 <= args.transient_failure_threshold <= 30:
        parser.error("--transient-failure-threshold must be between 1 and 30")
    if args.max_requests is not None and args.max_requests < 0:
        parser.error("--max-requests must be non-negative")
    if args.lock_poll_seconds <= 0:
        parser.error("--lock-poll-seconds must be positive")

    queue_lock = QueueLock(LOCK_PATH, poll_seconds=args.lock_poll_seconds)
    queue_lock.acquire()
    write_queue_status(
        state="running",
        stage="lock_acquired",
        requestedRounds=[item.number for item in configs],
        resume=bool(args.resume),
        command=[sys.executable, *sys.argv],
        lockPath=LOCK_PATH.relative_to(WORKSPACE).as_posix(),
    )
    try:
        return execute_queue(args, configs)
    except BaseException as exc:
        write_queue_status(
            state="error",
            stage="unhandled_exception",
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    finally:
        queue_lock.release()


if __name__ == "__main__":
    raise SystemExit(main())

"""Resume the official CN10/11 entity-filtered questionnaire snapshots.

The modern questionnaire page sends its advanced-search string to the same
``queryQuestionnaire`` operation used by the global page.  This small,
checkpointed crawler captures that documented interface for every non-empty
character/music ``any`` condition.  It never requests ballot text, reasons,
tokens, or recommendation fields.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence

try:  # package import in tests
    from . import crawl_cn_modern as core
    from . import crawl_cn_modern_advanced as advanced
except ImportError:  # direct script execution from scripts_pipeline/
    import crawl_cn_modern as core
    import crawl_cn_modern_advanced as advanced


OUTPUT = core.METADATA_ROOT / "cn_modern_entity_questionnaire_coverage.json"
STATUS_PATH = core.METADATA_ROOT / "cn_modern_entity_questionnaire_queue_status.json"

ENTITY_QUESTIONNAIRE_QUERY = """
query EntityQuestionnaire(
  $voteStart: DateTimeUtc!
  $voteYear: Int!
  $query: String
  $questionsOfInterest: [String!]!
) {
  queryGlobalStats(voteStart: $voteStart, voteYear: $voteYear, query: $query) {
    voteYear
    numVote
    numChar
    numMusic
    numCp
    numDoujin
    numMale
    numFemale
  }
  queryQuestionnaire(
    voteStart: $voteStart
    voteYear: $voteYear
    query: $query
    questionsOfInterest: $questionsOfInterest
  ) {
    entries {
      questionId
      answersCat { aid totalVotes maleVotes femaleVotes }
      totalAnswers
      totalMale
      totalFemale
    }
  }
  queryCompletionRates(voteStart: $voteStart, voteYear: $voteYear, query: $query) {
    items { name numComplete }
  }
}
"""

def transient_failure_reason(exc: BaseException) -> str | None:
    """Classify only transport/site availability failures for circuit use."""

    return core.transient_failure_reason(exc)


def entity_root(config: core.RoundConfig) -> Path:
    return config.root / "entity_questionnaire" / "responses"


def entity_path(config: core.RoundConfig, spec: advanced.ConditionSpec) -> Path:
    return (
        entity_root(config)
        / spec.dimension
        / f"source_{spec.source_index:04d}.json"
    )


def write_queue_status(**updates: Any) -> None:
    """Publish small, attempt-owned progress for the local dashboard.

    The coverage document remains the durable, detailed checkpoint.  This
    file is deliberately compact and is rewritten atomically so the control
    panel can show the current entity without reading a partially-written
    JSON document.  Queue identity fields mirror the legacy/modern crawlers;
    they prevent a later dashboard poll from reusing an older attempt.
    """

    status: dict[str, Any]
    try:
        value = core.load_json(STATUS_PATH)
        status = value if isinstance(value, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        status = {}
    if updates.get("state") == "running":
        context_changed = (
            status.get("pid") != os.getpid()
            or ("stage" in updates and updates.get("stage") != status.get("stage"))
            or ("round" in updates and updates.get("round") != status.get("round"))
        )
        if context_changed:
            for stale_key in (
                "round",
                "completed",
                "successful",
                "processed",
                "total",
                "remaining",
                "recordedFailures",
                "currentDimension",
                "currentSourceIndex",
                "currentSourceName",
                "currentQuery",
                "recentItems",
                "transientCircuitOpen",
                "stoppedReason",
                "resumable",
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


def question_ids(config: core.RoundConfig) -> list[str]:
    categorical = config.root / "questionnaire" / "categorical_results.json"
    if categorical.is_file():
        value = core.load_json(categorical)
        variables = value.get("provenance", {}).get("variables", {})
        ids = variables.get("questionsOfInterest")
        if isinstance(ids, list) and all(isinstance(item, str) for item in ids):
            return list(ids)
    questions = core.load_json(config.root / "questionnaire" / "questions.json")
    return [
        f"q{item['id']}"
        for item in questions
        if isinstance(item, dict)
        and item.get("id") is not None
        and item.get("type") != "Input"
    ]


def response_valid(
    value: Mapping[str, Any],
    spec: advanced.ConditionSpec,
    variables: Mapping[str, Any],
) -> tuple[bool, str | None]:
    try:
        provenance = value["provenance"]
        if provenance.get("status") != 200:
            return False, "official response HTTP status is not 200"
        if provenance.get("operation") != "EntityQuestionnaire":
            return False, "operation mismatch"
        if provenance.get("variables") != dict(variables):
            return False, "variables mismatch"
        context = value["context"]
        if context.get("query") != spec.query_filter:
            return False, "query mismatch"
        if context.get("sourceCategory") != spec.source_category:
            return False, "source category mismatch"
        if context.get("conditionKind") != "any":
            return False, "condition kind mismatch"
        data = value["data"]
        stats = data["queryGlobalStats"]
        observed = int(stats["numVote"])
        defect = bool(context.get("officialQueryDefect"))
        if observed != spec.expected_cohort:
            if not (defect and observed == 0):
                return False, f"global cohort {observed} != {spec.expected_cohort}"
        entries = data["queryQuestionnaire"]["entries"]
        if not isinstance(entries, list) or not entries:
            return False, "questionnaire entries are empty"
        question_ids_seen: set[str] = set()
        for entry in entries:
            question_id = str(entry["questionId"])
            if question_id in question_ids_seen:
                return False, "duplicate questionnaire question"
            question_ids_seen.add(question_id)
            if int(entry["totalAnswers"]) < 0:
                return False, "negative totalAnswers"
            for answer in entry.get("answersCat", []):
                for field in ("totalVotes", "maleVotes", "femaleVotes"):
                    if type(answer.get(field)) is not int or answer[field] < 0:
                        return False, f"invalid {field}"
        if "queryCompletionRates" not in data:
            return False, "completion rates missing"
        if core.json_key_occurs(value, {"reasons", "reason", "voteToken", "answersStr"}):
            return False, "forbidden reason/token/open-text field present"
        return True, None
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False, "malformed response"


def fetch_one(
    config: core.RoundConfig,
    client: core.PublicClient,
    spec: advanced.ConditionSpec,
    ids: Sequence[str],
    *,
    resume: bool,
) -> tuple[str, str | None]:
    variables = {
        **core.base_variables(config, query=spec.query_filter),
        "questionsOfInterest": list(ids),
    }
    path = entity_path(config, spec)
    if resume and path.is_file():
        try:
            value = core.load_json(path)
            valid, reason = response_valid(value, spec, variables)
            if valid:
                return "resumed", None
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    context = {
        "round": config.number,
        "sourceCategory": spec.source_category,
        "conditionKind": "any",
        "sourceIndex": spec.source_index,
        "sourceRank": spec.source_rank,
        "sourceName": spec.source_name,
        "officialGuiQueryName": spec.source_name,
        "normalizedProbeName": spec.normalized_probe_name,
        "expectedCohort": spec.expected_cohort,
        "query": spec.query_filter,
        "resultScope": "official filtered questionnaire aggregate for every question of interest",
    }
    if (
        spec.source_category == "music"
        and spec.normalized_probe_name != spec.source_name
    ):
        # Preserve the official GUI's reproducible trailing-control defect as
        # evidence; do not silently substitute the trimmed spelling.
        context["officialQueryDefect"] = True
    value = core.fetch_graphql_checkpoint(
        client,
        path,
        "EntityQuestionnaire",
        ENTITY_QUESTIONNAIRE_QUERY,
        variables,
        resume=False,
        timeout=300,
        context=context,
    )
    valid, reason = response_valid(value, spec, variables)
    if not valid:
        raise ValueError(reason or "entity questionnaire response failed validation")
    return "downloaded", None


def crawl_round(
    config: core.RoundConfig,
    client: core.PublicClient,
    *,
    resume: bool,
    max_requests: int | None,
    transient_failure_threshold: int = 3,
) -> dict[str, Any]:
    base = core.load_json(config.root / "graphql" / "base.json")
    specs = [
        item
        for item in advanced.build_specs(base)
        if item.kind == "any"
    ]
    ids = question_ids(config)
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    started = 0
    total = len(specs)
    consecutive_transient_failures = 0
    circuit_reason: str | None = None

    def pending_record(spec: advanced.ConditionSpec) -> dict[str, Any]:
        path = entity_path(config, spec)
        return {
            "sourceCategory": spec.source_category,
            "conditionKind": "any",
            "sourceIndex": spec.source_index,
            "sourceRank": spec.source_rank,
            "sourceName": spec.source_name,
            "query": spec.query_filter,
            "expectedCohort": spec.expected_cohort,
            "responsePath": path.relative_to(core.WORKSPACE).as_posix(),
            "status": "pending",
            "parseStatus": "not_attempted",
        }

    def publish(spec: advanced.ConditionSpec, *, state: str = "running") -> None:
        available = sum(item.get("status") == "available_crawled" for item in records)
        failed = len(failures)
        processed = available + failed
        write_queue_status(
            state=state,
            round=config.number,
            stage="entity_questionnaire",
            completed=available,
            successful=available,
            processed=processed,
            total=total,
            remaining=max(0, total - available),
            recordedFailures=failed,
            currentDimension=spec.dimension,
            currentSourceIndex=spec.source_index,
            currentSourceName=spec.source_name,
            currentQuery=spec.query_filter,
            recentItems=(
                list(records[max(0, position - 25) : position])
                if circuit_reason
                else list(records[-25:])
            ),
            responseRoot=entity_root(config).relative_to(core.WORKSPACE).as_posix(),
            **(
                client.adaptive_speed.status()
                if isinstance(getattr(client, "adaptive_speed", None), core.AdaptiveSpeed)
                else {}
            ),
        )

    for position, spec in enumerate(specs, start=1):
        path = entity_path(config, spec)
        variables = {
            **core.base_variables(config, query=spec.query_filter),
            "questionsOfInterest": list(ids),
        }
        already = False
        if resume and path.is_file():
            try:
                already = response_valid(core.load_json(path), spec, variables)[0]
            except (OSError, ValueError, json.JSONDecodeError):
                already = False
        if max_requests is not None and started >= max_requests and not already:
            records.append(pending_record(spec))
            continue
        publish(spec)
        if not already:
            started += 1
        try:
            status, _ = fetch_one(config, client, spec, ids, resume=resume)
            consecutive_transient_failures = 0
            records.append(
                {
                    "sourceCategory": spec.source_category,
                    "conditionKind": "any",
                    "sourceIndex": spec.source_index,
                    "sourceRank": spec.source_rank,
                    "sourceName": spec.source_name,
                    "query": spec.query_filter,
                    "expectedCohort": spec.expected_cohort,
                    "responsePath": path.relative_to(core.WORKSPACE).as_posix(),
                    "status": "available_crawled",
                    "parseStatus": "valid",
                    "resumeStatus": status,
                }
            )
        except BaseException as exc:
            error = f"{type(exc).__name__}: {exc}"
            transient_reason = transient_failure_reason(exc)
            consecutive_transient_failures = (
                consecutive_transient_failures + 1
                if transient_reason is not None
                else 0
            )
            failures.append(
                {
                    "sourceCategory": spec.source_category,
                    "sourceIndex": spec.source_index,
                    "sourceName": spec.source_name,
                    "query": spec.query_filter,
                    "status": "fetch_failed",
                    "error": error,
                    "transient": transient_reason is not None,
                    "transientReason": transient_reason,
                }
            )
            records.append(
                {
                    "sourceCategory": spec.source_category,
                    "conditionKind": "any",
                    "sourceIndex": spec.source_index,
                    "sourceRank": spec.source_rank,
                    "sourceName": spec.source_name,
                    "query": spec.query_filter,
                    "expectedCohort": spec.expected_cohort,
                    "responsePath": path.relative_to(core.WORKSPACE).as_posix(),
                    "status": "fetch_failed",
                    "parseStatus": "invalid",
                    "validationError": error,
                    "transient": transient_reason is not None,
                    "transientReason": transient_reason,
                }
            )
            if consecutive_transient_failures >= transient_failure_threshold:
                circuit_reason = (
                    f"{consecutive_transient_failures} consecutive final transient "
                    f"failures after per-request retries; latest={transient_reason}"
                )
                records.extend(pending_record(item) for item in specs[position:])
        publish(spec)
        if circuit_reason is not None:
            payload = build_payload(
                config,
                ids,
                specs,
                records,
                failures,
                circuit_reason=circuit_reason,
            )
            core.atomic_write_json(OUTPUT, payload, pretty=True)
            write_queue_status(
                state="recovery_wait",
                round=config.number,
                stage="entity_questionnaire_recovery_wait",
                completed=payload["rounds"][0]["availableCrawled"],
                successful=payload["rounds"][0]["availableCrawled"],
                processed=(
                    payload["rounds"][0]["availableCrawled"]
                    + payload["rounds"][0]["fetchFailed"]
                ),
                total=total,
                remaining=total - payload["rounds"][0]["availableCrawled"],
                recordedFailures=len(failures),
                currentDimension=spec.dimension,
                currentSourceIndex=spec.source_index,
                currentSourceName=spec.source_name,
                currentQuery=spec.query_filter,
                recentItems=list(records[max(0, position - 25) : position]),
                transientCircuitOpen=True,
                stoppedReason=circuit_reason,
                resumable=True,
                responseRoot=entity_root(config).relative_to(core.WORKSPACE).as_posix(),
                coveragePath=OUTPUT.relative_to(core.WORKSPACE).as_posix(),
            )
            print(
                f"round {config.number} entity questionnaire: recovery stop at "
                f"{position}/{total}; {circuit_reason}",
                flush=True,
            )
            break
        if position == 1 or position % 25 == 0 or position == len(specs):
            core.atomic_write_json(
                OUTPUT,
                build_payload(config, ids, specs, records, failures),
                pretty=True,
            )
            print(
                f"round {config.number} entity questionnaire: {position}/{len(specs)}; failures={len(failures)}",
                flush=True,
            )
    payload = build_payload(
        config,
        ids,
        specs,
        records,
        failures,
        circuit_reason=circuit_reason,
    )
    core.atomic_write_json(OUTPUT, payload, pretty=True)
    if specs:
        last_spec = specs[-1]
        available = sum(item.get("status") == "available_crawled" for item in records)
        complete = available == total and not failures
        write_queue_status(
            state=(
                "complete"
                if complete
                else "recovery_wait" if circuit_reason else "incomplete"
            ),
            round=config.number,
            stage=(
                "entity_questionnaire_recovery_wait"
                if circuit_reason
                else "entity_questionnaire_finished"
            ),
            completed=available,
            successful=available,
            processed=available + len(failures),
            total=total,
            remaining=max(0, total - available),
            recordedFailures=len(failures),
            currentDimension=last_spec.dimension,
            currentSourceIndex=last_spec.source_index,
            currentSourceName=last_spec.source_name,
            currentQuery=last_spec.query_filter,
            recentItems=(
                list(records[max(0, position - 25) : position])
                if circuit_reason
                else list(records[-25:])
            ),
            responseRoot=entity_root(config).relative_to(core.WORKSPACE).as_posix(),
            coveragePath=OUTPUT.relative_to(core.WORKSPACE).as_posix(),
            transientCircuitOpen=bool(circuit_reason),
            stoppedReason=circuit_reason,
            resumable=not complete,
        )
    return payload["rounds"][0]


def build_payload(
    config: core.RoundConfig,
    ids: Sequence[str],
    specs: Sequence[advanced.ConditionSpec],
    records: Sequence[Mapping[str, Any]],
    failures: Sequence[Mapping[str, Any]],
    *,
    circuit_reason: str | None = None,
) -> dict[str, Any]:
    expected = len(specs)
    available = sum(item.get("status") == "available_crawled" for item in records)
    pending = expected - available - len(failures)
    return {
        "schemaVersion": 1,
        "generatedAt": core.utc_now(),
        "scope": "CN10/11 official entity-filtered questionnaire aggregate",
        "interfaceFamily": "国区第10–11届现代 GraphQL 问卷搜索接口",
        "sourceEndpoint": core.ENDPOINT,
        "rounds": [
            {
                "round": config.number,
                "complete": available == expected and not failures,
                "expectedResponses": expected,
                "availableCrawled": available,
                "fetchFailed": len(failures),
                "pending": max(0, pending),
                "transientCircuitOpen": bool(circuit_reason),
                "stoppedReason": circuit_reason,
                "resumable": available < expected,
                "questionIds": list(ids),
                "responseRoot": entity_root(config).relative_to(core.WORKSPACE).as_posix(),
                "records": list(records),
                "failures": list(failures),
            }
        ],
        "allRequiredChecksPassed": available == expected and not failures,
        "queryDocument": {
            "operation": "EntityQuestionnaire",
            "documentSha256": core.sha256_bytes(ENTITY_QUESTIONNAIRE_QUERY.encode("utf-8")),
        },
    }


def parse_rounds(value: str) -> list[core.RoundConfig]:
    return core.parse_rounds(value)


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
    parser.add_argument("--max-requests", type=int, default=None)
    args = parser.parse_args(argv)
    if args.delay < 0 or args.retries < 1 or args.timeout <= 0:
        parser.error("delay must be non-negative; retries and timeout must be positive")
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    if args.request_limit < 1:
        parser.error("--request-limit must be at least 1")
    if args.batch_pause is not None and args.batch_pause < 0:
        parser.error("--batch-pause must be non-negative")
    if args.max_requests is not None and args.max_requests < 0:
        parser.error("--max-requests must be non-negative")
    if not 1 <= args.transient_failure_threshold <= 30:
        parser.error("--transient-failure-threshold must be between 1 and 30")
    configs = parse_rounds(args.rounds)
    speed = core.AdaptiveSpeed(
        workers=args.workers,
        request_limit=args.request_limit,
        pause=args.batch_pause if args.batch_pause is not None else args.delay,
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
    payload_rounds: list[dict[str, Any]] = []
    circuit_open = False
    write_queue_status(
        state="running",
        stage="lock_acquired",
        requestedRounds=[item.number for item in configs],
        resume=bool(args.resume),
        command=[sys.executable, *sys.argv],
        coveragePath=OUTPUT.relative_to(core.WORKSPACE).as_posix(),
        **speed.status(),
    )
    # CN10 and CN11 entries are presented as one continuous entity
    # questionnaire content list.  Keep a stable phase key across the round
    # partitions so the adaptive controller carries its proven speed forward
    # instead of resetting to the configured starting values at CN11.
    speed.set_phase("entity_questionnaire")
    for config in configs:
        write_queue_status(
            state="running",
            round=config.number,
            stage="entity_questionnaire_start",
            requestedRounds=[item.number for item in configs],
            responseRoot=entity_root(config).relative_to(core.WORKSPACE).as_posix(),
            coveragePath=OUTPUT.relative_to(core.WORKSPACE).as_posix(),
            **speed.status(),
        )
        try:
            round_payload = crawl_round(
                config,
                client,
                resume=args.resume,
                max_requests=args.max_requests,
                transient_failure_threshold=args.transient_failure_threshold,
            )
            payload_rounds.append(round_payload)
            if round_payload.get("transientCircuitOpen"):
                circuit_open = True
                break
        except BaseException as exc:
            payload_rounds.append(
                {
                    "round": config.number,
                    "complete": False,
                    "expectedResponses": 0,
                    "availableCrawled": 0,
                    "fetchFailed": 1,
                    "pending": 0,
                    "failures": [{"status": "fetch_failed", "error": f"{type(exc).__name__}: {exc}"}],
                }
            )
            write_queue_status(
                state="incomplete",
                round=config.number,
                stage="entity_questionnaire_error",
                recordedFailures=1,
                error=f"{type(exc).__name__}: {exc}",
                coveragePath=OUTPUT.relative_to(core.WORKSPACE).as_posix(),
                **speed.status(),
            )
    payload = {
        "schemaVersion": 1,
        "generatedAt": core.utc_now(),
        "scope": "CN10/11 official entity-filtered questionnaire aggregate",
        "interfaceFamily": "国区第10–11届现代 GraphQL 问卷搜索接口",
        "sourceEndpoint": core.ENDPOINT,
        "rounds": payload_rounds,
        "allRequiredChecksPassed": (
            len(payload_rounds) == len(configs)
            and all(item.get("complete") for item in payload_rounds)
        ),
        "transientCircuitOpen": circuit_open,
        "queryDocument": {
            "operation": "EntityQuestionnaire",
            "documentSha256": core.sha256_bytes(ENTITY_QUESTIONNAIRE_QUERY.encode("utf-8")),
        },
    }
    core.atomic_write_json(OUTPUT, payload, pretty=True)
    write_queue_status(
        state=(
            "complete"
            if payload["allRequiredChecksPassed"]
            else "recovery_wait" if circuit_open else "incomplete"
        ),
        stage="entity_questionnaire_recovery_wait" if circuit_open else "finished",
        requestedRounds=[item.number for item in configs],
        recordedFailures=sum(int(item.get("fetchFailed") or 0) for item in payload_rounds),
        coveragePath=OUTPUT.relative_to(core.WORKSPACE).as_posix(),
        transientCircuitOpen=circuit_open,
        resumable=not payload["allRequiredChecksPassed"],
        **speed.status(),
    )
    print(json.dumps({
        "allRequiredChecksPassed": payload["allRequiredChecksPassed"],
        "rounds": [{k: item.get(k) for k in ("round", "complete", "expectedResponses", "availableCrawled", "fetchFailed", "pending")} for item in payload_rounds],
    }, ensure_ascii=False, indent=2))
    return 0 if payload["allRequiredChecksPassed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

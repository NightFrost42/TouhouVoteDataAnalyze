"""Write, read, and verify reproducible network-analysis run manifests.

The dataset manifests in this repository describe how portable tables were
built.  This module describes one *statistical model run*: its exact files,
code revision, statistical settings, node universe, pair-selection rule, and
integrity checks.  It intentionally uses only the Python standard library so
analysis scripts can import it without adding a dependency.

A manifest is normally written after every analysis output has been closed::

    from pathlib import Path
    from scripts_pipeline.model_run_manifest import write_model_run_manifest

    write_model_run_manifest(
        Path("analysis_results/network/model_run_manifest.json"),
        root=Path("."),
        analysis="character_covote_network",
        analysis_version="1.0.0",
        inputs=["vote_explorer/data/analysis_covote_pairs_all.csv"],
        outputs=["analysis_results/network/edges.csv"],
        parameters={"round": "CN11", "min_count": 100},
        random_seed=20260801,
        permutations=20_000,
        tail="two-sided",
        node_set={
            "entity_type": "character",
            "source": "analysis_character_metrics_all.csv",
            "selection_rule": "rank <= 100",
            "ids": ["reimu", "marisa"],
        },
        pair_inclusion={
            "rule": "intersection_count >= 100",
            "missing_pair_policy": "exclude_and_report",
        },
        data_integrity={
            "status": "passed",
            "checks": [{"name": "round_coverage", "ok": True}],
        },
    )

The manifest itself is deliberately not included in ``outputs``.  Including
it would create a self-referential hash.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import posixpath
import subprocess
import tempfile
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, TypeAlias


SCHEMA_VERSION = 1
MANIFEST_TYPE = "network_statistical_analysis"
VALID_TAILS = frozenset({"two-sided", "greater", "less"})
SHA256_LENGTH = 64

FileSpec: TypeAlias = str | Path | Mapping[str, Any]


class ManifestValidationError(ValueError):
    """Raised when a run manifest does not satisfy the repository contract."""


def utc_now() -> str:
    """Return the manifest timestamp in stable UTC ISO-8601 form."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def sha256_file(path: Path | str) -> str:
    """Return the lowercase SHA-256 digest of a file."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(value: bytes) -> str:
    """Return the lowercase SHA-256 digest of bytes."""
    return hashlib.sha256(value).hexdigest()


def canonical_node_ids(ids: Iterable[Any]) -> list[str]:
    """Normalize, sort, and validate a node-ID collection.

    IDs are represented as non-empty strings in the JSON contract.  Sorting is
    part of the contract so the same node set has the same digest regardless
    of the order in which a graph library yielded its nodes.
    """
    normalized: list[str] = []
    for value in ids:
        if value is None or isinstance(value, (bool, dict, list, tuple, set)):
            raise ManifestValidationError(
                f"node IDs must be scalar non-empty values, got {value!r}"
            )
        text = str(value).strip()
        if not text:
            raise ManifestValidationError("node IDs must not be empty")
        normalized.append(text)
    if len(set(normalized)) != len(normalized):
        raise ManifestValidationError("node_set.ids contains duplicate IDs")
    return sorted(normalized)


def node_ids_sha256(ids: Iterable[Any]) -> str:
    """Hash the canonical JSON representation of normalized node IDs.

    The digest input is UTF-8 JSON with ``ensure_ascii=False`` and compact
    separators, e.g. ``["a","b"]``.  The list is normalized and sorted first.
    """
    normalized = canonical_node_ids(ids)
    payload = json.dumps(
        normalized, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return sha256_bytes(payload)


def _json_copy(value: Any, *, label: str) -> Any:
    """Copy a value through strict JSON to reject sets, NaN, and custom types."""
    try:
        return json.loads(
            json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        )
    except (TypeError, ValueError) as exc:
        raise ManifestValidationError(f"{label} must be JSON serializable") from exc


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ManifestValidationError(f"{label} must be an object")
    return value


def _require_nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ManifestValidationError(f"{label} must be a non-empty string")
    return value.strip()


def _require_utc_timestamp(value: Any, label: str) -> str:
    text = _require_nonempty_string(value, label)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ManifestValidationError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        raise ManifestValidationError(f"{label} must include the UTC timezone")
    return text


def _require_nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ManifestValidationError(f"{label} must be a non-negative integer")
    return value


def _require_bool_or_none(value: Any, label: str) -> bool | None:
    if value is not None and not isinstance(value, bool):
        raise ManifestValidationError(f"{label} must be boolean or null")
    return value


def _normalize_tail(value: Any) -> str:
    # Accept the common Python spelling at the API boundary but emit one schema
    # spelling everywhere.  Values outside the documented enum fail closed.
    if value == "two_sided":
        value = "two-sided"
    if value not in VALID_TAILS:
        raise ManifestValidationError(
            f"statistical_test.tail must be one of {sorted(VALID_TAILS)}"
        )
    return str(value)


def _workspace_root(root: Path | str) -> Path:
    resolved = Path(root).expanduser().resolve()
    if not resolved.is_dir():
        raise ManifestValidationError(f"workspace root is not a directory: {root}")
    return resolved


def _path_inside_root(root: Path, path: Path | str, *, require_file: bool) -> tuple[Path, str]:
    if not isinstance(path, (str, Path)):
        raise ManifestValidationError(f"path must be a path string, got {path!r}")
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve(strict=False)
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ManifestValidationError(
            f"path must be inside workspace root {root}: {path}"
        ) from exc
    if require_file and not resolved.is_file():
        raise FileNotFoundError(resolved)
    return resolved, relative.as_posix()


def _normalize_reference(root: Path, value: Any, label: str) -> str:
    """Normalize an optional source-code reference without requiring it to exist."""
    if not isinstance(value, (str, Path)):
        raise ManifestValidationError(f"{label} must be a path string")
    raw = str(value)
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        _, relative = _path_inside_root(root, candidate, require_file=False)
        return relative
    normalized = posixpath.normpath(raw.replace("\\", "/"))
    if normalized in {"", "."} or normalized == ".." or normalized.startswith("../"):
        raise ManifestValidationError(f"{label} must not escape the workspace root")
    return normalized


def _file_record(root: Path, spec: FileSpec, *, kind: str) -> dict[str, Any]:
    if isinstance(spec, Mapping):
        raw = dict(spec)
        if "path" not in raw:
            raise ManifestValidationError(f"{kind} file record is missing path")
        source = raw.pop("path")
    elif isinstance(spec, (str, Path)):
        raw = {}
        source = spec
    else:
        raise ManifestValidationError(
            f"{kind} file record must be a path or object, got {spec!r}"
        )

    resolved, relative = _path_inside_root(root, source, require_file=True)
    record: dict[str, Any] = {
        "path": relative,
        # These values are intentionally calculated after reading the file.
        # Caller-supplied stale hashes/sizes are never trusted.
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }
    for key, value in raw.items():
        if key in {"path", "sha256", "size_bytes"}:
            continue
        record[key] = _json_copy(value, label=f"{kind}.{key}")
    return record


def _file_records(root: Path, specs: Iterable[FileSpec] | None, *, kind: str) -> list[dict[str, Any]]:
    if specs is None:
        return []
    if isinstance(specs, (str, Path, Mapping)):
        specs = [specs]
    records = [_file_record(root, spec, kind=kind) for spec in specs]
    paths = [record["path"] for record in records]
    if len(paths) != len(set(paths)):
        raise ManifestValidationError(f"duplicate {kind} file path")
    return records


def _analysis_record(analysis: str | Mapping[str, Any], version: str | None) -> dict[str, Any]:
    if isinstance(analysis, str):
        record: dict[str, Any] = {"name": _require_nonempty_string(analysis, "analysis")}
    else:
        record = dict(_require_mapping(analysis, "analysis"))
        record["name"] = _require_nonempty_string(record.get("name"), "analysis.name")
    if version is not None:
        record["version"] = _require_nonempty_string(version, "analysis_version")
    else:
        record.setdefault("version", "unknown")
    return _json_copy(record, label="analysis")


def _run_git(root: Path, *arguments: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    value = completed.stdout.strip()
    return value or None


def _git_status_dirty(root: Path) -> bool | None:
    try:
        completed = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return bool(completed.stdout.strip())


def _code_record(
    root: Path,
    *,
    code: Mapping[str, Any] | None,
    code_version: str | None,
    script: str | Path | None,
) -> dict[str, Any]:
    dirty = _git_status_dirty(root)
    record: dict[str, Any] = {
        "git_commit": _run_git(root, "rev-parse", "HEAD") or "unknown",
        "git_describe": _run_git(root, "describe", "--always", "--long", "--tags") or "unknown",
        "git_dirty": dirty,
        "python_version": platform.python_version(),
        "version": code_version.strip() if isinstance(code_version, str) and code_version.strip() else "unknown",
    }
    if script is not None:
        record["script"] = _normalize_reference(root, script, "script")
    if code is not None:
        overrides = dict(_require_mapping(code, "code"))
        if "script" in overrides:
            overrides["script"] = _normalize_reference(root, overrides["script"], "code.script")
        record.update(_json_copy(overrides, label="code"))
    for key in ("git_commit", "git_describe", "python_version", "version"):
        record[key] = _require_nonempty_string(record.get(key), f"code.{key}")
    record["git_dirty"] = _require_bool_or_none(record.get("git_dirty"), "code.git_dirty")
    return record


def _statistical_test_record(
    *,
    method: str,
    random_seed: int | None,
    permutations: int,
    tail: str,
    supplied: Mapping[str, Any] | None,
) -> dict[str, Any]:
    record = dict(_require_mapping(supplied, "statistical_test")) if supplied is not None else {}
    record.setdefault("method", method)
    record.setdefault("random_seed", random_seed)
    record.setdefault("permutations", permutations)
    record.setdefault("tail", tail)
    record["method"] = _require_nonempty_string(record.get("method"), "statistical_test.method")
    seed = record.get("random_seed")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise ManifestValidationError("statistical_test.random_seed must be an integer or null")
    record["random_seed"] = seed
    record["permutations"] = _require_nonnegative_int(
        record.get("permutations"), "statistical_test.permutations"
    )
    record["tail"] = _normalize_tail(record.get("tail"))
    return _json_copy(record, label="statistical_test")


def _node_set_record(node_set: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(_require_mapping(node_set, "node_set"))
    for field in ("entity_type", "source", "selection_rule"):
        record[field] = _require_nonempty_string(record.get(field), f"node_set.{field}")
    if "ids" in record:
        if not isinstance(record["ids"], list):
            raise ManifestValidationError("node_set.ids must be an array when present")
        supplied_count = record.get("count")
        if supplied_count is not None and (
            isinstance(supplied_count, bool)
            or not isinstance(supplied_count, int)
            or supplied_count < 0
        ):
            raise ManifestValidationError("node_set.count must be a non-negative integer")
        ids = canonical_node_ids(record["ids"])
        if supplied_count is not None and supplied_count != len(ids):
            raise ManifestValidationError("node_set.count does not match node_set.ids")
        supplied_digest = record.get("ids_sha256")
        if supplied_digest is not None and supplied_digest != node_ids_sha256(ids):
            raise ManifestValidationError("node_set.ids_sha256 does not match node_set.ids")
        record["ids"] = ids
        record["count"] = len(ids)
        record["ids_sha256"] = node_ids_sha256(ids)
    else:
        record["count"] = _require_nonnegative_int(record.get("count"), "node_set.count")
        if "ids_sha256" in record:
            digest = record["ids_sha256"]
            if not isinstance(digest, str) or len(digest) != SHA256_LENGTH or any(
                char not in "0123456789abcdef" for char in digest
            ):
                raise ManifestValidationError("node_set.ids_sha256 must be a lowercase SHA-256 digest")
    return _json_copy(record, label="node_set")


def _pair_inclusion_record(pair_inclusion: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(_require_mapping(pair_inclusion, "pair_inclusion"))
    record["rule"] = _require_nonempty_string(record.get("rule"), "pair_inclusion.rule")
    directed = record.setdefault("directed", False)
    self_pairs = record.setdefault("self_pairs", False)
    if not isinstance(directed, bool) or not isinstance(self_pairs, bool):
        raise ManifestValidationError("pair_inclusion.directed and self_pairs must be boolean")
    record.setdefault("deduplication", "ordered" if directed else "unordered")
    record.setdefault("missing_pair_policy", "exclude_and_report")
    for field in ("deduplication", "missing_pair_policy"):
        record[field] = _require_nonempty_string(record[field], f"pair_inclusion.{field}")
    for field in ("included_pairs", "excluded_pairs"):
        if field in record:
            record[field] = _require_nonnegative_int(record[field], f"pair_inclusion.{field}")
    for field in ("minimum_count", "minimum_intersection_count", "threshold"):
        if field in record:
            value = record[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ManifestValidationError(f"pair_inclusion.{field} must be non-negative")
    return _json_copy(record, label="pair_inclusion")


def _data_integrity_record(data_integrity: Mapping[str, Any] | None) -> dict[str, Any]:
    record = dict(_require_mapping(data_integrity, "data_integrity")) if data_integrity is not None else {}
    record.setdefault("status", "not_evaluated")
    record["status"] = _require_nonempty_string(record["status"], "data_integrity.status")
    record.setdefault("checks", [])
    if not isinstance(record["checks"], list):
        raise ManifestValidationError("data_integrity.checks must be an array")
    record.setdefault("coverage", {})
    record.setdefault("missing", {})
    if not isinstance(record["coverage"], Mapping) or not isinstance(record["missing"], Mapping):
        raise ManifestValidationError("data_integrity.coverage and missing must be objects")
    record.setdefault("duplicate_count", 0)
    record.setdefault("invalid_count", 0)
    record["duplicate_count"] = _require_nonnegative_int(
        record["duplicate_count"], "data_integrity.duplicate_count"
    )
    record["invalid_count"] = _require_nonnegative_int(
        record["invalid_count"], "data_integrity.invalid_count"
    )
    record.setdefault("warnings", [])
    if not isinstance(record["warnings"], list) or any(
        not isinstance(item, str) for item in record["warnings"]
    ):
        raise ManifestValidationError("data_integrity.warnings must be an array of strings")
    return _json_copy(record, label="data_integrity")


def create_model_run_manifest(
    root: Path | str,
    *,
    analysis: str | Mapping[str, Any],
    inputs: Iterable[FileSpec] | None = None,
    outputs: Iterable[FileSpec] | None = None,
    input_files: Iterable[FileSpec] | None = None,
    output_files: Iterable[FileSpec] | None = None,
    analysis_version: str | None = None,
    parameters: Mapping[str, Any] | None = None,
    test_method: str = "permutation",
    random_seed: int | None = None,
    permutations: int = 0,
    tail: str = "two-sided",
    statistical_test: Mapping[str, Any] | None = None,
    node_set: Mapping[str, Any] | None = None,
    pair_inclusion: Mapping[str, Any] | None = None,
    data_integrity: Mapping[str, Any] | None = None,
    code: Mapping[str, Any] | None = None,
    code_version: str | None = None,
    script: str | Path | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Create a validated manifest and calculate all file hashes.

    ``inputs``/``outputs`` accept paths or records with optional metadata such
    as ``role``, ``notes``, ``row_count``, and ``columns``.  Existing
    ``sha256`` and ``size_bytes`` values in those records are ignored and
    recalculated from disk.
    """
    if inputs is not None and input_files is not None:
        raise ManifestValidationError("use inputs or input_files, not both")
    if outputs is not None and output_files is not None:
        raise ManifestValidationError("use outputs or output_files, not both")
    if node_set is None:
        raise ManifestValidationError("node_set is required")
    if pair_inclusion is None:
        raise ManifestValidationError("pair_inclusion is required")
    workspace = _workspace_root(root)
    input_specs = inputs if inputs is not None else input_files
    output_specs = outputs if outputs is not None else output_files
    if generated_at_utc is not None:
        generated_at = _require_utc_timestamp(generated_at_utc, "generated_at_utc")
    else:
        generated_at = utc_now()
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "manifest_type": MANIFEST_TYPE,
        "analysis": _analysis_record(analysis, analysis_version),
        "generated_at_utc": generated_at,
        "code": _code_record(
            workspace, code=code, code_version=code_version, script=script
        ),
        "parameters": _json_copy(
            dict(_require_mapping(parameters, "parameters")) if parameters is not None else {},
            label="parameters",
        ),
        "statistical_test": _statistical_test_record(
            method=test_method,
            random_seed=random_seed,
            permutations=permutations,
            tail=tail,
            supplied=statistical_test,
        ),
        "node_set": _node_set_record(node_set),
        "pair_inclusion": _pair_inclusion_record(pair_inclusion),
        "data_integrity": _data_integrity_record(data_integrity),
        "inputs": _file_records(workspace, input_specs, kind="input"),
        "outputs": _file_records(workspace, output_specs, kind="output"),
    }
    return validate_model_run_manifest(manifest)


def validate_model_run_manifest(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return a JSON-safe copy of a manifest.

    This is a dependency-free validator mirroring
    ``metadata/model_run_manifest.schema.json``.  It checks constraints that
    JSON Schema cannot conveniently express here, notably node-ID digests and
    file-path normalization.
    """
    if not isinstance(value, Mapping):
        raise ManifestValidationError("manifest must be a JSON object")
    manifest = _json_copy(dict(value), label="manifest")
    required = (
        "schema_version", "manifest_type", "analysis", "generated_at_utc", "code",
        "parameters", "statistical_test", "node_set", "pair_inclusion",
        "data_integrity", "inputs", "outputs",
    )
    missing = [field for field in required if field not in manifest]
    if missing:
        raise ManifestValidationError(f"manifest is missing required fields: {missing}")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise ManifestValidationError(
            f"unsupported schema_version: {manifest['schema_version']!r}"
        )
    if manifest["manifest_type"] != MANIFEST_TYPE:
        raise ManifestValidationError(
            f"manifest_type must be {MANIFEST_TYPE!r}"
        )
    _require_utc_timestamp(manifest["generated_at_utc"], "generated_at_utc")

    analysis = _require_mapping(manifest["analysis"], "analysis")
    _require_nonempty_string(analysis.get("name"), "analysis.name")
    _require_nonempty_string(analysis.get("version"), "analysis.version")
    code = _require_mapping(manifest["code"], "code")
    for field in ("git_commit", "git_describe", "python_version", "version"):
        _require_nonempty_string(code.get(field), f"code.{field}")
    if "git_dirty" not in code:
        raise ManifestValidationError("code.git_dirty is required")
    _require_bool_or_none(code.get("git_dirty"), "code.git_dirty")
    if "script" in code:
        _require_nonempty_string(code["script"], "code.script")
    parameters = _require_mapping(manifest["parameters"], "parameters")
    _json_copy(parameters, label="parameters")

    test = _require_mapping(manifest["statistical_test"], "statistical_test")
    _require_nonempty_string(test.get("method"), "statistical_test.method")
    seed = test.get("random_seed")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        raise ManifestValidationError("statistical_test.random_seed must be an integer or null")
    _require_nonnegative_int(test.get("permutations"), "statistical_test.permutations")
    _normalize_tail(test.get("tail"))

    nodes = _require_mapping(manifest["node_set"], "node_set")
    for field in ("entity_type", "source", "selection_rule"):
        _require_nonempty_string(nodes.get(field), f"node_set.{field}")
    count = _require_nonnegative_int(nodes.get("count"), "node_set.count")
    if "ids" in nodes:
        if not isinstance(nodes["ids"], list):
            raise ManifestValidationError("node_set.ids must be an array")
        ids = canonical_node_ids(nodes["ids"])
        if nodes["ids"] != ids:
            raise ManifestValidationError("node_set.ids must be normalized and sorted")
        if count != len(ids):
            raise ManifestValidationError("node_set.count does not match node_set.ids")
        expected_digest = node_ids_sha256(ids)
        if nodes.get("ids_sha256") != expected_digest:
            raise ManifestValidationError("node_set.ids_sha256 does not match node_set.ids")
    elif "ids_sha256" in nodes:
        digest = nodes["ids_sha256"]
        if not isinstance(digest, str) or len(digest) != SHA256_LENGTH or any(
            char not in "0123456789abcdef" for char in digest
        ):
            raise ManifestValidationError("node_set.ids_sha256 must be a lowercase SHA-256 digest")

    pairs = _require_mapping(manifest["pair_inclusion"], "pair_inclusion")
    _require_nonempty_string(pairs.get("rule"), "pair_inclusion.rule")
    for field in ("directed", "self_pairs"):
        if not isinstance(pairs.get(field), bool):
            raise ManifestValidationError(f"pair_inclusion.{field} must be boolean")
    for field in ("deduplication", "missing_pair_policy"):
        _require_nonempty_string(pairs.get(field), f"pair_inclusion.{field}")
    for field in ("included_pairs", "excluded_pairs"):
        if field in pairs:
            _require_nonnegative_int(pairs[field], f"pair_inclusion.{field}")
    for field in ("minimum_count", "minimum_intersection_count", "threshold"):
        if field in pairs:
            value = pairs[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
                raise ManifestValidationError(f"pair_inclusion.{field} must be non-negative")

    integrity = _require_mapping(manifest["data_integrity"], "data_integrity")
    _require_nonempty_string(integrity.get("status"), "data_integrity.status")
    if not isinstance(integrity.get("checks"), list):
        raise ManifestValidationError("data_integrity.checks must be an array")
    if not isinstance(integrity.get("coverage"), Mapping) or not isinstance(integrity.get("missing"), Mapping):
        raise ManifestValidationError("data_integrity.coverage and missing must be objects")
    _require_nonnegative_int(integrity.get("duplicate_count"), "data_integrity.duplicate_count")
    _require_nonnegative_int(integrity.get("invalid_count"), "data_integrity.invalid_count")
    if not isinstance(integrity.get("warnings"), list) or any(
        not isinstance(item, str) for item in integrity["warnings"]
    ):
        raise ManifestValidationError("data_integrity.warnings must be an array of strings")

    for kind in ("inputs", "outputs"):
        records = manifest[kind]
        if not isinstance(records, list):
            raise ManifestValidationError(f"{kind} must be an array")
        paths: set[str] = set()
        for index, record in enumerate(records):
            item = _require_mapping(record, f"{kind}[{index}]")
            path = _require_nonempty_string(item.get("path"), f"{kind}[{index}].path")
            if path != path.replace("\\", "/"):
                raise ManifestValidationError(f"{kind}[{index}].path must use '/' separators")
            pure = PurePosixPath(path)
            if pure.is_absolute() or ".." in pure.parts or path.startswith("//"):
                raise ManifestValidationError(f"{kind}[{index}].path must be workspace-relative")
            if path in paths:
                raise ManifestValidationError(f"duplicate {kind} path: {path}")
            paths.add(path)
            digest = item.get("sha256")
            if not isinstance(digest, str) or len(digest) != SHA256_LENGTH or any(
                char not in "0123456789abcdef" for char in digest
            ):
                raise ManifestValidationError(f"{kind}[{index}].sha256 must be a lowercase SHA-256 digest")
            _require_nonnegative_int(item.get("size_bytes"), f"{kind}[{index}].size_bytes")
            if "row_count" in item:
                _require_nonnegative_int(item["row_count"], f"{kind}[{index}].row_count")
            if "columns" in item:
                if not isinstance(item["columns"], list) or any(
                    not isinstance(column, str) for column in item["columns"]
                ):
                    raise ManifestValidationError(f"{kind}[{index}].columns must be an array of strings")
            for field in ("role", "notes"):
                if field in item and not isinstance(item[field], str):
                    raise ManifestValidationError(f"{kind}[{index}].{field} must be a string")
    return manifest


def refresh_model_run_manifest(
    manifest: Mapping[str, Any], root: Path | str
) -> dict[str, Any]:
    """Recalculate input/output file records while retaining other metadata."""
    workspace = _workspace_root(root)
    refreshed = _json_copy(dict(manifest), label="manifest")
    for kind in ("inputs", "outputs"):
        records = refreshed.get(kind)
        if not isinstance(records, list):
            raise ManifestValidationError(f"{kind} must be an array")
        refreshed[kind] = _file_records(workspace, records, kind=kind)
    return validate_model_run_manifest(refreshed)


def _destination_is_recorded_output(
    manifest: Mapping[str, Any], destination: Path, root: Path | None
) -> bool:
    if root is None:
        return False
    resolved_destination = destination.resolve(strict=False)
    for record in manifest.get("outputs", []):
        if not isinstance(record, Mapping) or not isinstance(record.get("path"), str):
            continue
        resolved_record = (root / record["path"]).resolve(strict=False)
        if resolved_record == resolved_destination:
            return True
    return False


def write_model_run_manifest(
    path: Path | str,
    manifest: Mapping[str, Any] | None = None,
    *,
    root: Path | str | None = None,
    **create_kwargs: Any,
) -> dict[str, Any]:
    """Write a manifest atomically and return the exact written payload.

    Either pass a pre-built ``manifest`` or pass the keyword arguments accepted
    by :func:`create_model_run_manifest`.  When a pre-built manifest is paired
    with ``root``, file hashes are refreshed before writing.
    """
    destination = Path(path).expanduser().resolve()
    if manifest is None:
        if root is None:
            root = destination.parent
        payload = create_model_run_manifest(root, **create_kwargs)
        workspace = _workspace_root(root)
    else:
        if create_kwargs:
            raise ManifestValidationError(
                "create kwargs cannot be combined with a pre-built manifest"
            )
        workspace = _workspace_root(root) if root is not None else None
        payload = (
            refresh_model_run_manifest(manifest, workspace)
            if workspace is not None
            else validate_model_run_manifest(manifest)
        )
    if _destination_is_recorded_output(payload, destination, workspace):
        raise ManifestValidationError(
            "manifest path must not also be listed in outputs (self-referential hash)"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent, delete=False
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(encoded)
            stream.flush()
        temporary_path.replace(destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return payload


def read_model_run_manifest(path: Path | str) -> dict[str, Any]:
    """Read UTF-8 JSON from disk and validate the manifest structure."""
    with Path(path).open("r", encoding="utf-8-sig") as stream:
        value = json.load(stream)
    return validate_model_run_manifest(value)


def _verify_file_records(
    records: list[Mapping[str, Any]], root: Path, *, kind: str
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for record in records:
        path_text = str(record["path"])
        try:
            resolved, _ = _path_inside_root(root, path_text, require_file=False)
        except ManifestValidationError as exc:
            results.append(
                {
                    "path": path_text,
                    "kind": kind,
                    "exists": False,
                    "expected_sha256": record["sha256"],
                    "actual_sha256": None,
                    "expected_size_bytes": record["size_bytes"],
                    "actual_size_bytes": None,
                    "sha256_ok": False,
                    "size_ok": False,
                    "ok": False,
                    "error": str(exc),
                }
            )
            continue
        exists = resolved.is_file()
        actual_size = resolved.stat().st_size if exists else None
        actual_hash = sha256_file(resolved) if exists else None
        size_ok = exists and actual_size == record["size_bytes"]
        hash_ok = exists and actual_hash == record["sha256"]
        results.append(
            {
                "path": path_text,
                "kind": kind,
                "exists": exists,
                "expected_sha256": record["sha256"],
                "actual_sha256": actual_hash,
                "expected_size_bytes": record["size_bytes"],
                "actual_size_bytes": actual_size,
                "sha256_ok": bool(hash_ok),
                "size_ok": bool(size_ok),
                "ok": bool(hash_ok and size_ok),
            }
        )
    return results


def verify_model_run_manifest(
    manifest_or_path: Mapping[str, Any] | Path | str,
    root: Path | str | None = None,
) -> dict[str, Any]:
    """Re-hash every recorded input/output and return an audit result.

    ``root`` is required for a manifest object because its file paths are
    workspace-relative.  For a manifest path, omitting ``root`` uses the
    manifest's parent directory; callers should pass the repository root when
    the manifest lives in ``metadata/`` or an analysis subdirectory.
    """
    if isinstance(manifest_or_path, Mapping):
        manifest = validate_model_run_manifest(manifest_or_path)
        if root is None:
            raise ManifestValidationError("root is required when verifying a manifest object")
        workspace = _workspace_root(root)
    else:
        manifest_path = Path(manifest_or_path).expanduser().resolve()
        manifest = read_model_run_manifest(manifest_path)
        workspace = _workspace_root(root if root is not None else manifest_path.parent)
    input_results = _verify_file_records(manifest["inputs"], workspace, kind="input")
    output_results = _verify_file_records(manifest["outputs"], workspace, kind="output")
    files = input_results + output_results
    return {
        "ok": all(item["ok"] for item in files),
        "inputs": input_results,
        "outputs": output_results,
        "files": files,
        "missing_files": [item["path"] for item in files if not item["exists"]],
        "hash_mismatches": [item["path"] for item in files if not item["sha256_ok"]],
        "size_mismatches": [item["path"] for item in files if not item["size_ok"]],
    }


def _cli() -> int:
    parser = argparse.ArgumentParser(description="Validate or verify a model_run_manifest.json")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "verify"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("manifest", type=Path)
        if command == "verify":
            subparser.add_argument("--root", type=Path, required=False)
    args = parser.parse_args()
    if args.command == "validate":
        read_model_run_manifest(args.manifest)
        print(f"valid: {args.manifest}")
    else:
        result = verify_model_run_manifest(args.manifest, args.root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())

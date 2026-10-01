"""Stage one authoritative copy of each logical dataset for Windows packages."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path


def stage(source: Path, destination: Path):
    source, destination = source.resolve(), destination.resolve()
    if source == destination or source in destination.parents:
        raise ValueError("Staging directory must be outside the source data directory")
    manifests = list(source.glob("*.parts.json"))
    excluded, parts = set(), set()
    for path in manifests:
        manifest = json.loads(path.read_bytes())
        base = manifest["base_name"]
        excluded.add(base)
        excluded.update(p.name for p in source.glob(base + ".part-*"))
        excluded.update(p.name for p in source.glob(base + ".bundle-*"))
        excluded.update(p.name for p in destination.glob(base + ".part-*"))
        excluded.update(p.name for p in destination.glob(base + ".bundle-*"))
        for entry in manifest["parts"]:
            part = source / entry["name"]
            if part.parent != source:
                raise ValueError("Partition escapes source directory")
            digest = hashlib.sha256()
            with part.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != entry["sha256"] or part.stat().st_size != entry["bytes"]:
                raise ValueError(f"Partition hash mismatch: {part}")
            parts.add(part.name)
    selected = [p for p in source.iterdir() if p.is_file() and (p.name not in excluded or p.name in parts) and not p.name.endswith('.tmp')]
    destination.mkdir(parents=True, exist_ok=True)
    # This is a generated staging directory; only remove files declared by a prior run.
    manifest_path = destination / "staging-manifest.json"
    old = json.loads(manifest_path.read_bytes()).get("files", []) if manifest_path.exists() else []
    names = {p.name for p in selected}
    for name in old:
        if Path(name).name != name:
            raise ValueError("Invalid previous staging manifest")
        if name not in names:
            (destination / name).unlink(missing_ok=True)
    for path in selected:
        shutil.copyfile(path, destination / path.name)
    for name in excluded - parts:
        # The authoritative replacement volumes have all been validated/copied.
        (destination / name).unlink(missing_ok=True)
    result = dict(files=sorted(names), bytes=sum(p.stat().st_size for p in selected))
    manifest_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Staged {len(names)} files, {result['bytes']:,} bytes")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    stage(args.source, args.destination)

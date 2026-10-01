"""Build a Pages-only artifact from active manifests, excluding source archives."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build(output):
    web = ROOT / "vote_explorer_web"
    files = [web / n for n in ("index.html", "app.js", "styles.css", "research.js", "shards.js")]
    files += [ROOT / "vote_explorer/data" / n for n in (
        "analysis_character_metrics_all.csv", "analysis_music_metrics_all.csv", "analysis_cp_metrics_all.csv",
        "analysis_character_factions.csv", "analysis_vote_combinations_all.csv", "analysis_questionnaire_all.csv",
        "analysis_character_music_links_all.csv", "analysis_data_manifest.json")]
    index = web / "web_data/templates.json"
    files.append(index)
    templates = json.loads(index.read_bytes())
    for entry in templates["template_shards"].values():
        path = index.parent / entry["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], path
        files.append(path)
    for directory in ("research", "tables"):
        index = web / "web_data" / directory / "index.json"
        files.append(index)
        manifest = json.loads(index.read_bytes())
        entries = manifest["entries"]
        if isinstance(entries, dict):
            entries = [item for group in entries.values() for item in group]
        for e in entries:
            path = index.parent / e["path"]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == e["sha256"], path
            files.append(path)
    output.mkdir(parents=True, exist_ok=True)
    manifest_path = output / "pages-manifest.json"
    old = json.loads(manifest_path.read_bytes())["files"] if manifest_path.exists() else []
    records = []
    for source in sorted(set(files)):
        relative = source.relative_to(ROOT).as_posix()
        size = source.stat().st_size
        if size >= 100 * 1024 * 1024:
            raise ValueError(f"Pages file exceeds 100 MiB: {relative}")
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        records.append(dict(path=relative, bytes=size, sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    names = {r["path"] for r in records}
    for record in old:
        obsolete = (output / record["path"]).resolve()
        if record["path"] not in names and obsolete.is_relative_to(output.resolve()):
            obsolete.unlink(missing_ok=True)
    total = sum(r["bytes"] for r in records)
    if total >= 1024**3:
        raise ValueError("Pages artifact exceeds 1 GiB")
    result = dict(bytes=total, files=records)
    manifest_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Pages: {len(records)} files, {total:,} bytes, largest {max(r['bytes'] for r in records):,}; {output}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/pages")
    build(parser.parse_args().output)

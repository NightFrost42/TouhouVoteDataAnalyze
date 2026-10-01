import csv
import gzip
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from vote_explorer_web.data_shards import SOURCES, build_data_shards, split_templates
from scripts_pipeline.split_binary_archive import split, restore


class ShardTests(unittest.TestCase):
    def test_lossless_scope_split_and_empty_missing_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / "data"
            out = Path(temp) / "web"
            data.mkdir()
            rows = [dict(region="cn", round="11", round_label="CN11", pair_category="character", category="character", question_key="age", blank="", zero="0", seed="8509473029546610632", text='a,\n"字"'),
                    dict(region="jp", round="22", round_label="JP22", pair_category="music", category="music", question_key="sex", blank="", zero="0", seed="8509473029546610632", text="x")]
            for filename in SOURCES.values():
                opener = gzip.open if filename.endswith(".gz") else open
                with opener(data / filename, "wt", encoding="utf-8-sig", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)
            index = build_data_shards(data, out, rows_per_shard=1)
            actual = []
            for key, entries in index["entries"].items():
                for entry in entries:
                    raw = (out / entry["path"]).read_bytes()
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), entry["sha256"])
                    p = json.loads(gzip.decompress(raw))
                    actual.extend(dict(p["defaults"], **dict(zip(p["columns"], v))) for v in p["values"])
            self.assertCountEqual(actual, rows * 3)
            self.assertEqual(len(index["entries"]), 6)
            self.assertNotIn('["covote_pairs","CN1","character"]', index["entries"])
            first = (out / "index.json").read_bytes()
            files = set(out.iterdir())
            build_data_shards(data, out, rows_per_shard=1)
            self.assertEqual((out / "index.json").read_bytes(), first)
            self.assertEqual(set(out.iterdir()), files)

    def test_templates_keep_availability_without_embedding_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            result = split_templates({"snapshots": {"x": {"CN11": {"table_rows": [[1]]}, "CN1": {"table_rows": []}}}, "pair_snapshots": {}}, Path(temp))
            self.assertEqual(result["snapshots"]["x"]["CN11"], {"available": True})
            self.assertEqual(result["snapshots"]["x"]["CN1"], {"available": False})

    def test_archive_roundtrip_and_corruption_preserve_original(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "file.gz"
            original = gzip.compress("字\n".encode() * 100, mtime=0)
            source.write_bytes(original)
            manifest = split(source, 17)
            mpath = source.with_name(source.name + ".binary-parts.json")
            source.unlink()
            self.assertEqual(restore(mpath).read_bytes(), original)
            (source.parent / manifest["parts"][0]["name"]).write_bytes(b"bad")
            with self.assertRaises(ValueError):
                restore(mpath)
            self.assertEqual(source.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()

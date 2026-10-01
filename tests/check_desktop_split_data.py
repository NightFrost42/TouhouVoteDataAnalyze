"""Fixed Tk flow against the actual Windows package data (no full pair CSV)."""
import csv
import json
import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "vote_explorer"))
import resource_paths
resource_paths.DATA_DIR = ROOT / "vote_explorer/.build_data"
assert not (resource_paths.DATA_DIR / "analysis_covote_pairs_all.csv").exists()
import tkinter as tk
import app
import analysis_workbench as workbench
from analysis_engine import TEMPLATE_BY_KEY


def fail(*args, **kwargs):
    raise AssertionError(str(args))


def main():
    start = time.perf_counter()
    output = ROOT / "tests/.tmp-desktop-split"
    output.mkdir(exist_ok=True)
    root = tk.Tk()
    root.withdraw()
    try:
        with patch.object(workbench.messagebox, "showerror", side_effect=fail), patch.object(workbench.messagebox, "showinfo"):
            explorer = app.VoteExplorerApp(root)
            assert explorer.tree.get_children(), "Ranking table empty"
            explorer.open_analysis()
            wb = explorer.analysis_workbench
            wb.window.withdraw()
            wb.current_round.set("CN11")
            wb.compare_round.set("CN10")
            wb.rank_start.set("1")
            wb.rank_end.set("100")
            wb.top_n.set("100")
            tested = []
            for key in ("c13_comments_top", "a02_network", "a01_count_matrix"):
                wb.template_display.set(TEMPLATE_BY_KEY[key].display)
                wb.on_template_changed()
                wb.refresh()
                root.update_idletasks()
                assert wb.chart.get("table_rows"), key
                if key == "a02_network":
                    assert len(wb.chart["nodes"]) == 100
                if key == "a01_count_matrix":
                    assert len(wb.chart["matrix"]) == 100
                    assert all(len(row) == 100 for row in wb.chart["matrix"])
                target = output / (key + ".csv")
                with patch.object(workbench.filedialog, "asksaveasfilename", return_value=str(target)):
                    wb.export_csv()
                with target.open(encoding="utf-8-sig", newline="") as f:
                    assert len(list(csv.reader(f))) == len(wb.chart["table_rows"]) + 1
                tested.append(key)
            result = dict(status="PASS", templates=tested, seconds=round(time.perf_counter() - start, 3), pair_source="manifest partitions only")
            (output / "report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps(result))
    finally:
        root.destroy()


if __name__ == "__main__":
    main()

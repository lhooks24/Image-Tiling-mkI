"""Infer per-pass timing from the data and calculate tomorrow's capacities.

Source TIFFs are never modified. Filesystem write times are estimates and are
labelled as such in the report.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path

DEFAULT_DATA_ROOT = Path(r"C:\Users\ladmin\OneDrive - University of Utah\grad school\research\Super-Res\Data\08_26_26")
DEFAULT_REPORT_DIR = Path(__file__).resolve().parent / "reports"
EXPOSURE_PATTERN = re.compile(r"^exp_([0-9]+(?:\.[0-9]+)?)s$", re.IGNORECASE)
POSITION_PATTERN = re.compile(r"_p(\d+)_", re.IGNORECASE)
Z_PATTERN = re.compile(r"_z(\d+)", re.IGNORECASE)


def parse(path: Path, root: Path):
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return None
    match = EXPOSURE_PATTERN.match(parts[-2]) if len(parts) >= 5 else None
    return ((parts[-5], parts[-4], parts[-3]), float(match.group(1))) if match else None


def plan(label, seconds_per_position, usable_seconds, manual_seconds, cells):
    positions = max(0, math.floor((usable_seconds - manual_seconds) / seconds_per_position))
    positions -= positions % cells
    return {"plan": label, "manual_minutes": manual_seconds / 60,
            "maximum_total_positions_per_color": positions, "positions_per_cell_type": positions // cells,
            "estimated_acquisition_minutes": positions * seconds_per_position / 60,
            "estimated_plan_minutes": (positions * seconds_per_position + manual_seconds) / 60}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--window-minutes", type=float, default=570)
    parser.add_argument("--buffer-minutes", type=float, default=30)
    parser.add_argument("--setup-minutes", type=float, default=0)
    parser.add_argument("--manual-minutes-full", type=float, default=20)
    parser.add_argument("--manual-minutes-split", type=float, default=40)
    args = parser.parse_args()
    usable_seconds = (args.window_minutes - args.buffer_minutes - args.setup_minutes) * 60
    if not args.data_root.is_dir() or usable_seconds <= 0:
        parser.error("dataset root must exist and usable time must be positive")
    grouped = defaultdict(list)
    for path in {*args.data_root.rglob("*.tif"), *args.data_root.rglob("*.tiff")}:
        if parsed := parse(path, args.data_root):
            grouped[parsed[0]].append(path)
    rows = []
    for condition, files in sorted(grouped.items()):
        times = [path.stat().st_mtime for path in files]
        positions = {m.group(1) for path in files if (m := POSITION_PATTERN.search(path.name))}
        z_planes = {m.group(1) for path in files if (m := Z_PATTERN.search(path.name))}
        exposures = sorted({parse(path, args.data_root)[1] for path in files})
        span = max(times) - min(times)
        rows.append({"cell_type": condition[0], "color": condition[1], "doe_state": condition[2], "frames": len(files),
                     "positions": len(positions), "z_planes": len(z_planes), "exposures_seconds": ";".join(map(str, exposures)),
                     "first_write": datetime.fromtimestamp(min(times)).isoformat(sep=" ", timespec="seconds"),
                     "last_write": datetime.fromtimestamp(max(times)).isoformat(sep=" ", timespec="seconds"),
                     "observed_write_span_seconds": span, "estimated_seconds_per_position": span / len(positions)})
    if not rows:
        parser.error("no matching TIFF layout found")
    by_cell = defaultdict(list)
    for row in rows:
        by_cell[row["cell_type"]].append(row)
    full = []
    for cell, cell_rows in sorted(by_cell.items()):
        seconds = sum(row["estimated_seconds_per_position"] for row in cell_rows)
        result = plan(f"Full scan: {cell}", seconds, usable_seconds, args.manual_minutes_full * 60, 1)
        result["observed_seconds_per_position_across_all_8_passes"] = seconds
        full.append(result)
    split_seconds = sum(row["estimated_seconds_per_position"] for row in rows) / len(by_cell)
    split = plan("Two half-scans: all discovered cell types", split_seconds, usable_seconds, args.manual_minutes_split * 60, len(by_cell))
    split["observed_seconds_per_total_position_across_all_8_passes"] = split_seconds
    args.report_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.report_dir / "observed_pass_timing.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    report = {"data_root": str(args.data_root), "timing_source": "filesystem last-write timestamps; excludes time before first and after final write",
              "usable_minutes_before_plan_manual_allowance": usable_seconds / 60, "observed_passes": rows,
              "full_scan_plans": full, "two_half_scan_plan": split,
              "caution": "Use a slower stopwatch measurement if available."}
    json_path = args.report_dir / "capture_capacity_report.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2)); print(f"\nWrote {csv_path} and {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

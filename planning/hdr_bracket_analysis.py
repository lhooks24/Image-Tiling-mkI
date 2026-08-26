"""Analyze every HDR TIFF condition in the configured dataset with one command.

This program is read-only with respect to microscope data. Reports are written
only to this repository's ``planning/reports`` folder.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import tifffile

DEFAULT_DATA_ROOT = Path(r"C:\Users\ladmin\OneDrive - University of Utah\grad school\research\Super-Res\Data\08_26_26")
DEFAULT_REPORT_DIR = Path(__file__).resolve().parent / "reports"
EXPOSURE_PATTERN = re.compile(r"^exp_([0-9]+(?:\.[0-9]+)?)s$", re.IGNORECASE)


def condition_and_exposure(path: Path, root: Path):
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return None
    if len(parts) < 5:
        return None
    match = EXPOSURE_PATTERN.match(parts[-2])
    if not match:
        return None
    return (parts[-5], parts[-4], parts[-3]), float(match.group(1))


def summarize_frame(path: Path, saturation_value: int) -> dict:
    image = tifffile.imread(path)
    if image.size == 0:
        raise ValueError("empty image")
    values = np.asarray(image, dtype=np.uint16).reshape(-1)
    return {
        "file": str(path), "pixel_count": int(values.size), "minimum": int(values.min()),
        "p01": float(np.percentile(values, 0.1)), "p1": float(np.percentile(values, 1)),
        "p50": float(np.percentile(values, 50)), "p99": float(np.percentile(values, 99)),
        "p999": float(np.percentile(values, 99.9)), "maximum": int(values.max()),
        "saturated_fraction": float(np.mean(values >= saturation_value)),
    }


def exposure_summary(rows: list[dict], saturation_value: int) -> dict:
    return {
        "frame_count": len(rows), "worst_p999": max(float(row["p999"]) for row in rows),
        "median_p999": float(np.median([float(row["p999"]) for row in rows])),
        "worst_saturated_fraction": max(float(row["saturated_fraction"]) for row in rows),
        "frames_with_any_saturation": sum(float(row["saturated_fraction"]) > 0 for row in rows),
        "full_scale": saturation_value,
    }


def recommend(exposures: dict[float, list[dict]], saturation_value: int) -> dict:
    """Return an evidence-labelled decision; never invent untested exposures."""
    summaries = {exposure: exposure_summary(rows, saturation_value) for exposure, rows in exposures.items()}
    tested = sorted(summaries)
    safe = [exposure for exposure in tested if summaries[exposure]["worst_p999"] <= 0.85 * saturation_value
            and summaries[exposure]["worst_saturated_fraction"] <= 0.0001]
    result = {
        "tested_exposures_seconds": tested,
        "per_exposure": {str(exposure): summaries[exposure] for exposure in tested},
        "criteria": "p99.9 <= 85% full scale and <= 0.01% saturated pixels in every frame",
    }
    if not safe:
        result.update(status="shorter_exposure_required", provisional_use=None,
                      reason="No tested exposure satisfies the conservative clipping criteria.")
    elif safe[-1] == tested[-1]:
        result.update(status="longer_exposure_test_required", provisional_use=tested,
                      reason="The longest tested exposure is conservative, so the maximum useful long band is not established.",
                      next_test_seconds=[tested[-1] * 2, tested[-1] * 4])
    else:
        result.update(status="tested_bracket_available", provisional_use=tested,
                      longest_conservative_exposure_seconds=safe[-1],
                      reason="A longer tested exposure fails clipping criteria; inspect frame content before final selection.")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--saturation-value", type=int, default=65535)
    args = parser.parse_args()
    if not args.data_root.is_dir():
        parser.error(f"data root does not exist: {args.data_root}")
    files = sorted({*args.data_root.rglob("*.tif"), *args.data_root.rglob("*.tiff")})
    grouped = defaultdict(lambda: defaultdict(list))
    skipped = []
    for index, path in enumerate(files, 1):
        parsed = condition_and_exposure(path, args.data_root)
        if parsed is None:
            skipped.append(f"unrecognized layout: {path}")
            continue
        condition, exposure = parsed
        try:
            row = summarize_frame(path, args.saturation_value)
        except Exception as error:
            skipped.append(f"unreadable: {path}: {error}")
            continue
        row.update(cell_type=condition[0], color=condition[1], doe_state=condition[2], exposure_seconds=exposure)
        grouped[condition][exposure].append(row)
        if index % 250 == 0:
            print(f"Analyzed {index}/{len(files)} TIFFs...", flush=True)
    args.report_dir.mkdir(parents=True, exist_ok=True)
    frame_rows = [row for by_exposure in grouped.values() for rows in by_exposure.values() for row in rows]
    csv_path = args.report_dir / "hdr_frame_statistics.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(frame_rows[0]))
        writer.writeheader()
        writer.writerows(frame_rows)
    conditions = []
    for condition in sorted(grouped):
        item = {"cell_type": condition[0], "color": condition[1], "doe_state": condition[2]}
        item.update(recommend(grouped[condition], args.saturation_value))
        conditions.append(item)
    report = {"data_root": str(args.data_root), "tiff_files_found": len(files), "frames_analyzed": len(frame_rows),
              "conditions_analyzed": len(conditions), "skipped_files": skipped, "conditions": conditions,
              "warning": "Numerical clipping does not validate diffraction-feature fidelity; inspect representative frames before choosing bands."}
    json_path = args.report_dir / "hdr_condition_report.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nWrote {csv_path} and {json_path}")
    return 0 if frame_rows else 2


if __name__ == "__main__":
    raise SystemExit(main())

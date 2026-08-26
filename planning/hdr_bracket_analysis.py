"""Analyze manually captured TIFF exposure sweeps without controlling hardware."""

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

EXPOSURE_PATTERNS = (
    re.compile(r"exp_([0-9]+(?:\.[0-9]+)?)s", re.IGNORECASE),
    re.compile(r"(?:^|[_-])([0-9]+(?:\.[0-9]+)?)ms(?:[_-]|$)", re.IGNORECASE),
)


def exposure_seconds(path: Path) -> float | None:
    """Read exposure from a parent directory or filename.

    Accepted examples are ``exp_0.015s`` and ``15ms.tiff``.
    """
    for candidate in (str(path.parent), path.stem):
        for index, pattern in enumerate(EXPOSURE_PATTERNS):
            match = pattern.search(candidate)
            if match:
                value = float(match.group(1))
                return value if index == 0 else value / 1000.0
    return None


def summarize_frame(path: Path, saturation_value: int) -> dict[str, float | str]:
    image = tifffile.imread(path)
    if image.size == 0:
        raise ValueError("empty image")
    values = np.asarray(image, dtype=np.float64).reshape(-1)
    return {
        "file": str(path),
        "pixel_count": int(values.size),
        "minimum": float(np.min(values)),
        "p01": float(np.percentile(values, 0.1)),
        "p1": float(np.percentile(values, 1)),
        "p50": float(np.percentile(values, 50)),
        "p99": float(np.percentile(values, 99)),
        "p999": float(np.percentile(values, 99.9)),
        "maximum": float(np.max(values)),
        "saturated_fraction": float(np.mean(values >= saturation_value)),
    }


def select_bracket(rows: list[dict[str, float | str]], saturation_value: int) -> dict[str, object]:
    """Recommend a conservative 3-band 4x bracket from aggregate statistics."""
    grouped: dict[float, list[dict[str, float | str]]] = defaultdict(list)
    for row in rows:
        grouped[float(row["exposure_seconds"])].append(row)

    aggregates = []
    for exposure, values in grouped.items():
        aggregates.append({
            "exposure_seconds": exposure,
            "worst_p999": max(float(item["p999"]) for item in values),
            "worst_saturated_fraction": max(float(item["saturated_fraction"]) for item in values),
        })
    aggregates.sort(key=lambda item: item["exposure_seconds"])

    # Keep the brightest 0.1% below 85% full scale and allow <=0.01% clipped pixels.
    acceptable = [item for item in aggregates if item["worst_p999"] <= 0.85 * saturation_value
                  and item["worst_saturated_fraction"] <= 0.0001]
    if not acceptable:
        return {
            "status": "no_conservative_exposure_found",
            "reason": "Every tested exposure exceeded the clipping thresholds. Test shorter exposures.",
            "tested_exposures_seconds": aggregates,
        }

    longest = acceptable[-1]["exposure_seconds"]
    recommended = [longest / 16.0, longest / 4.0, longest]
    return {
        "status": "review_required",
        "rule": "Longest tested exposure with p99.9 <= 85% full scale and <= 0.01% saturated pixels; 4x HDR ladder below it.",
        "recommended_exposures_seconds": recommended,
        "longest_conservative_exposure_seconds": longest,
        "tested_exposures_seconds": aggregates,
        "warning": "This is a numerical screening result, not validation of diffraction-feature fidelity. Inspect the frames before use.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_dir", type=Path, help="Folder containing TIFFs in exposure-labelled paths.")
    parser.add_argument("--saturation-value", type=int, default=65535, help="ADC value treated as saturated (default: 65535).")
    args = parser.parse_args()

    files = sorted({*args.input_dir.rglob("*.tif"), *args.input_dir.rglob("*.tiff")})
    if not files:
        print(f"No TIFF files found below {args.input_dir}", file=sys.stderr)
        return 2

    rows = []
    skipped = []
    for path in files:
        exposure = exposure_seconds(path)
        if exposure is None:
            skipped.append(str(path))
            continue
        try:
            row = summarize_frame(path, args.saturation_value)
        except Exception as error:
            skipped.append(f"{path}: {error}")
            continue
        row["exposure_seconds"] = exposure
        rows.append(row)
    if not rows:
        print("No analyzable TIFFs had an exposure label.", file=sys.stderr)
        return 2

    report = select_bracket(rows, args.saturation_value)
    report["input_dir"] = str(args.input_dir.resolve())
    report["saturation_value"] = args.saturation_value
    report["frames_analyzed"] = len(rows)
    report["skipped_files"] = skipped

    csv_path = args.input_dir / "hdr_report.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: (float(row["exposure_seconds"]), str(row["file"]))))
    json_path = args.input_dir / "hdr_report.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report, indent=2))
    print(f"\nWrote {csv_path} and {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


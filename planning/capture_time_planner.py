"""Calculate position capacity for the planned HDR Z-stack acquisition."""

from __future__ import annotations

import argparse
import math


def positions_per_cell_type(total_positions: int, cell_types: int) -> int:
    return total_positions // cell_types


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds-per-position-pass", type=float, required=True,
                        help="Measured worst-case time for one XY position, one DOE state, all Z planes, and all HDR bands.")
    parser.add_argument("--window-minutes", type=float, default=570,
                        help="Arrival-to-latest-finish window (default: 570 = 08:00–17:30).")
    parser.add_argument("--buffer-minutes", type=float, default=30,
                        help="Protected unallocated buffer (default: 30).")
    parser.add_argument("--setup-minutes", type=float, default=0,
                        help="Additional setup time excluded from acquisition capacity.")
    parser.add_argument("--manual-minutes-full", type=float, default=20,
                        help="Manual transitions for the one-cell-type full plan.")
    parser.add_argument("--manual-minutes-split", type=float, default=40,
                        help="Manual transitions for the two-cell-type split plan.")
    parser.add_argument("--colors", type=int, default=4, help="Number of color/illumination scan types (default: 4).")
    parser.add_argument("--passes", type=int, default=2, help="DOE states per color (default: 2: no DOE and with DOE).")
    parser.add_argument("--candidate-total-positions", type=int, default=None,
                        help="Optional planned total positions per color; reports its expected duration.")
    args = parser.parse_args()

    if args.seconds_per_position_pass <= 0 or args.colors <= 0 or args.passes <= 0:
        parser.error("time, colors, and passes must be positive")
    usable = args.window_minutes - args.buffer_minutes - args.setup_minutes
    if usable <= 0:
        parser.error("No usable minutes remain after buffer/setup.")

    units_per_position = args.colors * args.passes
    print(f"Usable time before plan-specific manual work: {usable:.1f} min")
    print(f"Measured worst-case position/pass time: {args.seconds_per_position_pass:.2f} s")
    print(f"Acquisition passes per position across all colors: {units_per_position}")

    plans = (("Full scan (one cell type)", 1, args.manual_minutes_full),
             ("Two half-scans (two cell types)", 2, args.manual_minutes_split))
    for name, cell_types, manual_minutes in plans:
        acquisition_minutes = usable - manual_minutes
        maximum = max(0, math.floor(acquisition_minutes * 60 / (args.seconds_per_position_pass * units_per_position)))
        each = positions_per_cell_type(maximum, cell_types)
        used_positions = each * cell_types
        duration = manual_minutes + used_positions * args.seconds_per_position_pass * units_per_position / 60
        print(f"\n{name}")
        print(f"  Plan-specific manual allowance: {manual_minutes:.1f} min")
        print(f"  Maximum total positions per color: {used_positions}")
        print(f"  Positions per cell type: {each}")
        print(f"  Estimated used time excluding protected buffer/setup: {duration:.1f} min")
        if args.candidate_total_positions is not None:
            candidate = args.candidate_total_positions
            candidate_duration = manual_minutes + candidate * args.seconds_per_position_pass * units_per_position / 60
            remaining = usable - candidate_duration
            print(f"  Candidate {candidate} total positions/color: {candidate_duration:.1f} min; remaining before protected buffer/setup: {remaining:.1f} min")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


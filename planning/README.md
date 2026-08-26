# Tomorrow's HDR acquisition planning

This folder is intentionally separate from the acquisition suite.  Nothing here
opens the camera, moves either stage, changes illumination, or edits an existing
scan script.  It is a decision aid for today's characterization and tomorrow's
time budget.

## Existing-suite run map

The current `zstack_hdr_scan.py` accepts one HDR exposure list and one output
base directory per execution.  It then performs a no-DOE pass, pauses for the
manual DOE flip, and performs the paired with-DOE pass.  Consequently:

* The **full plan** is four executions: all, green, blue, and red.  Each
  execution includes both DOE states.
* The **two-half-scan plan** is eight executions: cell type A then cell type B
  for each of all, green, blue, and red.  Each execution includes both DOE
  states and receives half the positions assigned to that color.

Use the existing, known-good parameter editing workflow to select each final
exposure list and destination before its execution.  This planning package does
not change those parameters for you.

## 1. Preserve the acquisition state

The acquisition suite was committed before this folder was added.  The commit is
`6296955` (`Preserve current microscope acquisition suite`).  Do not change the
settings in a production scan during characterization.  Capture characterization
frames with the vendor camera interface or another already-validated manual
method, then copy the resulting TIFFs into `planning/capture_inputs/`.

## 2. Characterize every optical condition that could be used tomorrow

For each cell type, collect a short, manual exposure sweep for every condition
that will be compared:

| Cell type | Optical state | Illumination/filter |
|---|---|---|
| Cell type A | no DOE, with DOE | all, green, blue, red |
| Cell type B | no DOE, with DOE | all, green, blue, red |

Use one representative in-focus field for each row.  If the specimen is visibly
heterogeneous, repeat the row at a dim and a bright field; choose brackets that
cover both fields, not only the attractive one.  Keep camera gain, sensor mode,
ROI/binning, objective, illumination setting, and optical geometry identical to
tomorrow's acquisition.

For each field, capture a geometric exposure sweep around the expected usable
range.  A practical starting sweep is 5, 10, 20, 40, 80, 160, and 320 ms, but
**this is a starting test range, not a final bracket recommendation**.  Omit any
duration your hardware does not permit and extend the series shorter/longer if
the dimmest frame is already bright or the longest frame is not close to
saturation.  Do not adjust gain between frames.

Record the exposure in either directory names such as `exp_0.020s/` or filenames
such as `20ms.tif`.  Example:

```
planning/capture_inputs/cell_A_green_withDOE/exp_0.020s/frame.tiff
planning/capture_inputs/cell_A_green_withDOE/exp_0.040s/frame.tiff
```

The checked-in scripts now default to the permitted `08_26_26` dataset root and
discover every `cell/color/DOE-state/exposure` condition automatically. Run the
HDR analysis once with:

```
python planning/hdr_bracket_analysis.py
```

The command writes a full-frame CSV and a per-condition JSON report in
`planning/reports/`. It does not write into the image-data tree. Its decision is
deliberately evidence-labelled: it flags whether shorter or longer exposures
must be tested rather than inventing an unmeasured bracket. Review the report
and representative frames yourself before deciding; diffraction patterns may
have scientifically relevant bright features that a global percentile does not
distinguish from unwanted clipping.

## 3. Measure scan time, do not estimate it

For each final candidate three-exposure bracket, run one already-validated scan
on a **single XY position** with the intended Z range and Z spacing.  Time the
no-DOE pass and with-DOE pass separately from the printed “Acquiring ... Pos”
line until that position is complete.  Include camera readout and TIFF writing.
Log the measurements in `scan_timing_log.csv`.  Take at least two repetitions
for the slowest bracket; use the slower value in the capacity calculator.

The relevant measure is seconds per position **per optical pass**, with all Z
planes and HDR exposures included.  Do not use the raw sum of exposure times.

## 4. Calculate tomorrow's capacity

The usable 8:00 AM–5:30 PM window after the requested 30-minute buffer is 540
minutes. The timing planner automatically reads each condition's TIFF write
timestamps and estimates per-position timing. Run it once:

```
python planning/capture_time_planner.py
```

It writes both a pass-level timing CSV and a capacity JSON report in
`planning/reports/`, and reports both decision cases:

* **Full scan:** one cell type, each of all/green/blue/red acquired no-DOE and
  with-DOE.
* **Two half-scans:** the same total positions per color split equally between
  two cell types, with a separately configurable manual well-change allowance.

The reported limit is an upper bound because filesystem timestamps exclude time
before the first image and after the final image. Use a slower stopwatch result
instead if available. Set `--manual-minutes-full`, `--manual-minutes-split`, or
`--setup-minutes` to change those explicit allowances.

## Decision checklist before tomorrow

1. Confirm the final bracket separately for every cell-type × color × DOE state
   that might be acquired.
2. Choose either the full or split plan using the measured **slowest** required
   condition, not an average.
3. Confirm all intended frame counts and storage space before beginning.
4. Save the reports, timing CSV, final chosen brackets, and scan parameters in
   the experiment notebook or alongside the destination dataset.

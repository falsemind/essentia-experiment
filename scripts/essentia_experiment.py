#!/usr/bin/env python3
"""Run and summarize Essentia BPM/key experiments.

The script is designed for local exploration. It reads the reference-track CSV,
analyzes available audio files with Essentia, stores raw per-track outputs, and
produces normalized CSV/JSONL plus a Markdown report.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = PROJECT_ROOT / "data" / "metadata" / "reference-tracks.csv"
DEFAULT_RAW_DIR = PROJECT_ROOT / "outputs" / "raw"
DEFAULT_NORMALIZED_DIR = PROJECT_ROOT / "outputs" / "normalized"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "outputs" / "reports"


@dataclass(frozen=True)
class ReferenceTrack:
    """Reference metadata for one local audio file."""

    track_id: str
    artist: str
    title: str
    file_path: str
    reference_bpm: float | None
    reference_key: str
    reference_source: str
    notes: str


@dataclass(frozen=True)
class AnalysisResult:
    """Normalized analysis result that can be compared across runs."""

    analysis_run_id: str
    track_id: str
    artist: str
    title: str
    file_path: str
    status: str
    error: str
    reference_bpm: float | None
    detected_bpm: float | None
    bpm_confidence: float | None
    bpm_error: float | None
    bpm_ratio_case: str
    reference_key: str
    detected_key: str
    detected_scale: str
    key_strength: float | None
    key_match: str
    reference_source: str
    analysis_source: str
    analysis_version: str
    analyzed_at: str
    notes: str


def utc_now_id() -> str:
    """Return a filesystem-friendly UTC timestamp."""

    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def parse_optional_float(value: str) -> float | None:
    """Parse optional numeric CSV values."""

    clean_value = value.strip()
    if not clean_value:
        return None
    try:
        return float(clean_value)
    except ValueError:
        return None


def read_reference_tracks(path: Path) -> list[ReferenceTrack]:
    """Read reference tracks from CSV."""

    if not path.exists():
        raise FileNotFoundError(f"Reference CSV does not exist: {path}")

    with path.open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        rows = []
        for index, row in enumerate(reader, start=2):
            track_id = (row.get("track_id") or "").strip()
            file_path = (row.get("file_path") or "").strip()
            if not track_id and not file_path:
                continue
            rows.append(
                ReferenceTrack(
                    track_id=track_id or f"row-{index}",
                    artist=(row.get("artist") or "").strip(),
                    title=(row.get("title") or "").strip(),
                    file_path=file_path,
                    reference_bpm=parse_optional_float(row.get("reference_bpm") or ""),
                    reference_key=(row.get("reference_key") or "").strip(),
                    reference_source=(row.get("reference_source") or "").strip(),
                    notes=(row.get("notes") or "").strip(),
                )
            )
    return rows


def resolve_audio_path(file_path: str) -> Path:
    """Resolve a track path relative to the project root when needed."""

    path = Path(file_path).expanduser()
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def normalize_key(key: str, scale: str = "") -> str:
    """Normalize key strings enough for first-pass exact matching."""

    clean_key = key.strip().replace("♭", "b").replace("♯", "#")
    clean_scale = scale.strip().lower()
    if not clean_key:
        return ""
    if clean_scale and clean_scale not in clean_key.lower():
        return f"{clean_key} {clean_scale}".strip().lower()
    return clean_key.lower()


def classify_bpm(reference_bpm: float | None, detected_bpm: float | None) -> tuple[float | None, str]:
    """Classify BPM errors, including common half/double tempo cases."""

    if reference_bpm is None or detected_bpm is None or reference_bpm <= 0:
        return None, ""

    direct_error = abs(detected_bpm - reference_bpm)
    half_error = abs((detected_bpm * 2) - reference_bpm)
    double_error = abs((detected_bpm / 2) - reference_bpm)

    best_error = min(direct_error, half_error, double_error)
    if best_error == half_error and half_error + 0.01 < direct_error:
        return round(direct_error, 4), "half-time"
    if best_error == double_error and double_error + 0.01 < direct_error:
        return round(direct_error, 4), "double-time"
    return round(direct_error, 4), "direct"


def analyze_track(
    track: ReferenceTrack,
    analysis_run_id: str,
    raw_dir: Path,
    analysis_version: str,
) -> AnalysisResult:
    """Run Essentia BPM and key analysis for one track."""

    analyzed_at = datetime.now(timezone.utc).isoformat()
    audio_path = resolve_audio_path(track.file_path)

    if not track.file_path:
        return failed_result(track, analysis_run_id, "missing file_path", analysis_version, analyzed_at)
    if not audio_path.exists():
        return failed_result(
            track,
            analysis_run_id,
            f"audio file not found: {audio_path}",
            analysis_version,
            analyzed_at,
        )

    try:
        mono_loader = get_essentia_algorithm("MonoLoader")
        rhythm_extractor = get_essentia_algorithm("RhythmExtractor2013")
        key_extractor = get_essentia_algorithm("KeyExtractor")

        audio = mono_loader(filename=str(audio_path))()
        bpm, _beats, _beats_confidence, _beats_intervals, bpm_confidence = rhythm_extractor(
            method="multifeature"
        )(audio)
        detected_key, detected_scale, key_strength = key_extractor()(audio)
    except Exception as exc:
        return failed_result(track, analysis_run_id, f"{type(exc).__name__}: {exc}", analysis_version, analyzed_at)

    bpm_error, bpm_ratio_case = classify_bpm(track.reference_bpm, float(bpm))
    key_match = compare_keys(track.reference_key, detected_key, detected_scale)

    raw_output = {
        "track": asdict(track),
        "essentia": {
            "bpm": bpm,
            "bpm_confidence": bpm_confidence,
            "key": detected_key,
            "scale": detected_scale,
            "key_strength": key_strength,
        },
        "analysis_run_id": analysis_run_id,
        "analysis_version": analysis_version,
        "analyzed_at": analyzed_at,
    }
    write_json(raw_dir / f"{safe_filename(track.track_id)}.json", raw_output)

    return AnalysisResult(
        analysis_run_id=analysis_run_id,
        track_id=track.track_id,
        artist=track.artist,
        title=track.title,
        file_path=track.file_path,
        status="ok",
        error="",
        reference_bpm=track.reference_bpm,
        detected_bpm=round(float(bpm), 4),
        bpm_confidence=round(float(bpm_confidence), 4),
        bpm_error=bpm_error,
        bpm_ratio_case=bpm_ratio_case,
        reference_key=track.reference_key,
        detected_key=str(detected_key),
        detected_scale=str(detected_scale),
        key_strength=round(float(key_strength), 4),
        key_match=key_match,
        reference_source=track.reference_source,
        analysis_source="essentia",
        analysis_version=analysis_version,
        analyzed_at=analyzed_at,
        notes=track.notes,
    )


def failed_result(
    track: ReferenceTrack,
    analysis_run_id: str,
    error: str,
    analysis_version: str,
    analyzed_at: str,
) -> AnalysisResult:
    """Build a normalized failed result row."""

    return AnalysisResult(
        analysis_run_id=analysis_run_id,
        track_id=track.track_id,
        artist=track.artist,
        title=track.title,
        file_path=track.file_path,
        status="error",
        error=error,
        reference_bpm=track.reference_bpm,
        detected_bpm=None,
        bpm_confidence=None,
        bpm_error=None,
        bpm_ratio_case="",
        reference_key=track.reference_key,
        detected_key="",
        detected_scale="",
        key_strength=None,
        key_match="",
        reference_source=track.reference_source,
        analysis_source="essentia",
        analysis_version=analysis_version,
        analyzed_at=analyzed_at,
        notes=track.notes,
    )


def compare_keys(reference_key: str, detected_key: str, detected_scale: str) -> str:
    """Compare reference and detected keys for a first-pass report."""

    if not reference_key:
        return ""
    reference = normalize_key(reference_key)
    detected = normalize_key(detected_key, detected_scale)
    if reference == detected:
        return "exact"
    if reference and detected and reference.split()[0] == detected.split()[0]:
        return "tonic-only"
    return "different"


def safe_filename(value: str) -> str:
    """Convert an arbitrary track ID into a safe filename stem."""

    safe = "".join(char if char.isalnum() or char in ("-", "_") else "-" for char in value.strip())
    return safe or "track"


def write_json(path: Path, data: dict[str, Any]) -> None:
    """Write JSON with stable formatting."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[AnalysisResult]) -> None:
    """Write normalized result rows as JSON Lines."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(asdict(row), sort_keys=True) for row in rows]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def write_csv(path: Path, rows: list[AnalysisResult]) -> None:
    """Write normalized result rows as CSV."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(AnalysisResult.__dataclass_fields__.keys())
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def get_essentia_version() -> str:
    """Return the installed Essentia version."""

    try:
        import essentia

        return str(getattr(essentia, "__version__", "unknown"))
    except Exception as exc:
        return f"unavailable ({type(exc).__name__}: {exc})"


def get_essentia_algorithm(name: str) -> Any:
    """Return an Essentia algorithm exposed dynamically by essentia.standard."""

    try:
        import essentia.standard as es
    except Exception as exc:
        raise RuntimeError(f"Could not import essentia.standard: {exc}") from exc

    algorithm = getattr(es, name, None)
    if algorithm is None:
        raise RuntimeError(f"Essentia algorithm is unavailable: {name}")
    return algorithm


def analyze(args: argparse.Namespace) -> None:
    """Analyze all tracks from the input CSV."""

    input_path = Path(args.input)
    analysis_run_id = args.run_id or utc_now_id()
    raw_dir = Path(args.raw_dir) / analysis_run_id
    normalized_dir = Path(args.normalized_dir)
    report_dir = Path(args.report_dir)
    analysis_version = get_essentia_version()

    tracks = read_reference_tracks(input_path)
    if args.limit is not None:
        tracks = tracks[: args.limit]

    results = [
        analyze_track(
            track=track,
            analysis_run_id=analysis_run_id,
            raw_dir=raw_dir,
            analysis_version=analysis_version,
        )
        for track in tracks
    ]

    normalized_jsonl = normalized_dir / f"{analysis_run_id}.jsonl"
    normalized_csv = normalized_dir / f"{analysis_run_id}.csv"
    report_path = report_dir / f"{analysis_run_id}.md"

    write_jsonl(normalized_jsonl, results)
    write_csv(normalized_csv, results)
    write_report(report_path, results)

    ok_count = sum(1 for result in results if result.status == "ok")
    error_count = len(results) - ok_count
    print(f"analysis_run_id={analysis_run_id}")
    print(f"tracks={len(results)} ok={ok_count} errors={error_count}")
    print(f"normalized_jsonl={normalized_jsonl}")
    print(f"normalized_csv={normalized_csv}")
    print(f"report={report_path}")


def read_result_jsonl(path: Path) -> list[AnalysisResult]:
    """Read normalized JSONL output back into dataclasses."""

    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(AnalysisResult(**json.loads(line)))
    return rows


def report(args: argparse.Namespace) -> None:
    """Create a report from a normalized JSONL file."""

    input_path = Path(args.input)
    results = read_result_jsonl(input_path)
    report_path = Path(args.output) if args.output else DEFAULT_REPORT_DIR / f"{input_path.stem}-report.md"
    write_report(report_path, results)
    print(f"report={report_path}")


def write_report(path: Path, results: list[AnalysisResult]) -> None:
    """Write a compact Markdown report for an experiment run."""

    path.parent.mkdir(parents=True, exist_ok=True)
    ok_results = [result for result in results if result.status == "ok"]
    bpm_errors = [result.bpm_error for result in ok_results if result.bpm_error is not None]
    exact_keys = [result for result in ok_results if result.key_match == "exact"]
    direct_bpm = [result for result in ok_results if result.bpm_ratio_case == "direct"]
    ratio_cases = count_values(result.bpm_ratio_case for result in ok_results if result.bpm_ratio_case)
    key_cases = count_values(result.key_match for result in ok_results if result.key_match)

    lines = [
        "# Essentia Experiment Report",
        "",
        f"- tracks: {len(results)}",
        f"- ok: {len(ok_results)}",
        f"- errors: {len(results) - len(ok_results)}",
        f"- direct BPM matches: {len(direct_bpm)}",
        f"- exact key matches: {len(exact_keys)}",
    ]

    if bpm_errors:
        lines.extend(
            [
                f"- mean BPM error: {round(mean(bpm_errors), 4)}",
                f"- median BPM error: {round(median(bpm_errors), 4)}",
                f"- max BPM error: {round(max(bpm_errors), 4)}",
            ]
        )

    lines.extend(["", "## BPM Ratio Cases", "", markdown_counts(ratio_cases)])
    lines.extend(["", "## Key Match Cases", "", markdown_counts(key_cases)])
    lines.extend(["", "## Largest BPM Errors", ""])
    lines.extend(markdown_largest_bpm_errors(ok_results))
    lines.extend(["", "## Errors", ""])
    lines.extend(markdown_errors(results))

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def count_values(values: Iterable[str]) -> dict[str, int]:
    """Count string values for reports."""

    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def markdown_counts(counts: dict[str, int]) -> str:
    """Render count dictionaries for Markdown."""

    if not counts:
        return "_No comparable values yet._"
    return "\n".join(f"- {key}: {value}" for key, value in counts.items())


def markdown_largest_bpm_errors(results: list[AnalysisResult]) -> list[str]:
    """Render the largest BPM misses."""

    comparable = [result for result in results if result.bpm_error is not None and not math.isnan(result.bpm_error)]
    if not comparable:
        return ["_No BPM reference comparisons yet._"]

    rows = sorted(comparable, key=lambda result: result.bpm_error or 0, reverse=True)[:10]
    return [
        (
            f"- {result.track_id}: reference={result.reference_bpm}, "
            f"detected={result.detected_bpm}, error={result.bpm_error}, "
            f"case={result.bpm_ratio_case}"
        )
        for result in rows
    ]


def markdown_errors(results: list[AnalysisResult]) -> list[str]:
    """Render failed rows."""

    failed = [result for result in results if result.status != "ok"]
    if not failed:
        return ["_No failed tracks._"]
    return [f"- {result.track_id}: {result.error}" for result in failed]


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""

    parser = argparse.ArgumentParser(description="Run Essentia BPM/key experiments.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser("analyze", help="Analyze tracks from the reference CSV.")
    analyze_parser.add_argument("--input", default=str(DEFAULT_INPUT), help="Reference CSV path.")
    analyze_parser.add_argument("--run-id", default="", help="Optional stable analysis run ID.")
    analyze_parser.add_argument("--limit", type=int, default=None, help="Optional number of rows to analyze.")
    analyze_parser.add_argument("--raw-dir", default=str(DEFAULT_RAW_DIR), help="Raw output directory.")
    analyze_parser.add_argument(
        "--normalized-dir",
        default=str(DEFAULT_NORMALIZED_DIR),
        help="Normalized output directory.",
    )
    analyze_parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR), help="Report output directory.")
    analyze_parser.set_defaults(func=analyze)

    report_parser = subparsers.add_parser("report", help="Create a report from normalized JSONL.")
    report_parser.add_argument("--input", required=True, help="Normalized JSONL path.")
    report_parser.add_argument("--output", default="", help="Optional report output path.")
    report_parser.set_defaults(func=report)

    return parser


def main() -> None:
    """CLI entrypoint."""

    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

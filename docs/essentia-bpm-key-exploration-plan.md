# Essentia BPM and Key Exploration Plan

## Purpose

This project is an experimental space for testing whether Essentia can produce BPM and musical key estimates that are useful enough to become a Vinyl Listen feature later.

The goal is not to prove that Essentia is always correct. The goal is to understand:

- how hard the analysis pipeline is to run locally;
- how stable BPM and key estimates are across real music files;
- what confidence or quality signals are available;
- where results are obviously wrong;
- what metadata Vinyl Listen should store if the feature moves forward.

Treat all outputs as estimates, not facts. A future Vinyl Listen implementation should store the detected value, confidence or quality signals, analysis source, analysis version, and analyzed timestamp.

## Expected Workflow

1. Prepare a small, legally usable test dataset.
2. Run Essentia analysis locally against each file.
3. Save raw and normalized results.
4. Compare results against known or manually checked reference values.
5. Inspect failure cases by genre, recording quality, tempo range, and track structure.
6. Decide whether the feature is useful as automatic metadata, user-editable suggestions, or only as a research direction for now.

## Local Setup

Assumed starting point:

- Python virtual environment exists at `.venv/`.
- The `essentia` Python package is installed.
- This repo can be used freely for scripts, generated reports, and temporary test metadata.

Recommended setup checks:

```bash
.venv/bin/python --version
.venv/bin/python -c "import essentia; print(essentia.__version__)"
.venv/bin/python -c "import essentia.standard as es; print(hasattr(es, 'RhythmExtractor2013'), hasattr(es, 'KeyExtractor'))"
```

Recommended project folders:

```text
data/
  audio/
    reference/
    unknown/
  metadata/
    reference-tracks.csv
outputs/
  raw/
  normalized/
  reports/
scripts/
```

Do not commit commercial audio files. Keep `data/audio/` local-only unless the files are explicitly licensed for repository use.

## Test Data Preparation

Start with a deliberately small dataset. Around 20 to 40 tracks is enough for the first useful pass.

Use a mix of:

- clean digital files with known BPM and key;
- vinyl rips or recordings if available;
- slow, mid-tempo, and fast tracks;
- tracks with live drums or tempo drift;
- tracks with intros, breakdowns, long ambient sections, or beatless openings;
- genres relevant to actual Vinyl Listen users and DJ-session workflows.

For each reference track, keep a metadata row:

```csv
track_id,artist,title,file_path,reference_bpm,reference_key,reference_source,notes
```

Reference values can come from trusted DJ software, manual tap tempo, producer notes, MusicBrainz-style metadata, or previous user-entered metadata. Record the source because reference data can also be wrong.

## First Analysis Slice

The first script should do the simplest useful thing:

1. Load one audio file.
2. Convert it to mono if needed.
3. Run BPM detection.
4. Run key detection.
5. Print a compact JSON result.

Expected normalized output shape:

```json
{
  "track_id": "local-file-id",
  "file_path": "data/audio/reference/example.flac",
  "bpm": 124.8,
  "bpm_confidence": 2.73,
  "key": "A",
  "scale": "minor",
  "key_strength": 0.81,
  "analysis_source": "essentia",
  "analysis_version": "local-package-version",
  "analyzed_at": "2026-06-26T00:00:00Z"
}
```

The exact fields may change after checking what the installed Essentia build returns, but the normalized shape should stay close to this because it maps cleanly to future app storage.

## Batch Testing

After the one-file script works, add a batch script that:

- reads `data/metadata/reference-tracks.csv`;
- analyzes every file that exists locally;
- writes one raw JSON file per track to `outputs/raw/`;
- writes one normalized CSV or JSONL file to `outputs/normalized/`;
- marks missing files without crashing the whole run.

The batch runner should be repeatable. Include an `analysis_run_id` or timestamp so results from different algorithm settings can be compared.

## Result Analysis

Analyze BPM separately from key.

For BPM:

- absolute BPM error against reference;
- doubled or halved BPM cases;
- confidence distribution;
- failure patterns by genre or recording type;
- whether rounding to whole BPM improves product usefulness.

For key:

- exact key plus scale match;
- relative major/minor cases;
- nearby harmonic matches if using Camelot/Open Key notation later;
- key strength distribution;
- whether results are stable across full-track versus excerpt analysis.

Useful report columns:

```csv
track_id,artist,title,reference_bpm,detected_bpm,bpm_error,bpm_ratio_case,reference_key,detected_key,key_match,key_strength,notes
```

## Understanding Failure Cases

When results look wrong, classify the reason before blaming the library.

Common BPM failure classes:

- half-time or double-time interpretation;
- beatless intro dominates the analysis;
- live drummer or tempo drift;
- noisy vinyl rip or low-quality source;
- genre rhythm does not match common beat-tracking assumptions.

Common key failure classes:

- ambiguous tonality;
- modal harmony;
- key changes;
- detuned samples or old vinyl pitch drift;
- percussion-heavy track with weak harmonic content;
- reference key is itself questionable.

These categories matter because Vinyl Listen can still use imperfect estimates if the UI presents them as editable suggestions.

## Experiment Variants

Once the baseline works, test variants one at a time:

- full track versus middle 60 to 120 seconds;
- original audio versus normalized loudness;
- MP3 versus FLAC/WAV;
- vinyl rip versus clean digital source;
- Essentia default settings versus tuned settings;
- optional comparison against another library such as `librosa` or `aubio`.

Avoid changing many settings in one run. Each run should answer one question.

## Decision Criteria

This is promising for Vinyl Listen if:

- BPM is usually close enough for sorting, filtering, or DJ-prep use;
- half/double BPM errors can be detected or handled;
- key results are useful often enough to show as suggestions;
- runtime is acceptable for backend background processing;
- confidence or strength signals help decide when to show, hide, or label estimates;
- storage and API shape can support future re-analysis.

This is not ready if:

- results vary wildly across ordinary tracks;
- wrong key estimates look overconfident;
- analysis is too slow or fragile for backend processing;
- the feature would require presenting estimates as authoritative facts.

## Possible Vinyl Listen Shape

If the experiment is successful, the app feature should likely be:

- backend-side background audio analysis;
- estimates stored per track or record-side track;
- user-editable BPM and key fields;
- visible analysis provenance;
- re-analysis support when algorithms or settings change;
- optional confidence-aware UI states such as "detected", "low confidence", or "manually edited".

Avoid making BPM/key detection the center of the product. It should support broader workflows: listening, DJ sessions, crate digging, record hunting, and insights.

## Immediate Next Steps

1. Add `.gitignore` rules for local audio and generated outputs.
2. Create `data/metadata/reference-tracks.csv` with 20 to 40 candidate tracks.
3. Write a one-file Essentia analysis script.
4. Write a batch runner after the one-file script is verified.
5. Generate the first comparison report.
6. Review the worst failures and decide which variant to test next.

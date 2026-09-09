# Development expert preflight failure — 2026-09-09

The first local expert-launcher attempt stopped before any expert fit with `DEVELOPMENT_PROCESSED_NOT_VERIFIED`.

Controller review identified an implementation-only JSON key-order bug. Accepted development snapshots write `labels.jsonl.gz` using canonical `json.dumps(..., sort_keys=True)`, so the nested horizon keys are serialized lexicographically (`120,15,240,30,60`). The PR #41 development expert loader incorrectly required insertion order `15,30,60,120,240` even though JSON object key order is not part of the label semantics. It already reads numeric values by the frozen horizon order.

The narrow repair validates the exact horizon-key set and then reads the values in the frozen order. A regression test reproduces the real canonical sorted-key serialization. Target, features, snapshots, HGB expert parameters, rolling-origin split, metrics, clipping/calibration policy, and holdout boundary are unchanged.

The failed launcher status records: one development-data candidate found; no expert model trained; no reliability gate trained; final holdout 2019-03/06/09/12 not accessed; existing worktrees preserved.

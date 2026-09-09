# Development expert preflight failure note — 2026-09-09

The first local expert-launcher attempt stopped before any model fit with `DEVELOPMENT_PROCESSED_NOT_VERIFIED`.

Controller diagnosis identified an implementation-only label JSON key-order bug: prepared `labels.jsonl.gz` is canonically serialized with `sort_keys=True`, while the development expert loader incorrectly required insertion order `15,30,60,120,240`. JSON object key order is not a semantic part of the label contract. The values were already read by the fixed horizon order, so the repair is to validate the exact key set rather than insertion order and to add a regression test using the actual sorted-key serialization.

No expert model was trained; final holdout 2019-03/06/09/12 was not accessed; existing processed snapshots remain unchanged.

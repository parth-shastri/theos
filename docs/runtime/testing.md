# Test selection

Keep a case when it protects a distinct observable behavior, meaningful input boundary, or important regression.
State that behavior in the test name. Reuse an existing case when its inputs can also check related output fields.

Keep separate cases for these failures:

- Approval denial, expiry, edited arguments, and repeated decisions.
- Cross-owner access and credential or private-content disclosure.
- Unknown external outcomes, interrupted execution, and unsafe retries.
- Checkpoint persistence, restart recovery, and migration rollback.
- Compaction boundaries, split-turn ordering, model limits, and tool-call retention.
- Provider wire formats, signed state, malformed arguments, stream failure, and usage accounting.

Use complete request and response contracts for related provider fields.
Keep minimal requests beside configured requests to check omitted optional fields.
Keep malformed, refusal, replay, and interruption scenarios separate because they have different outcomes.

Avoid cases that only check constructors, dataclass metadata, standard-library behavior, or test-fixture diagnostics.
Use representative inputs for independent branches. Use combination matrices when interactions can change behavior.
Keep the standard pytest command as the entry point for the retained suite.

## Reduction on 2026-10-18

The suite now has 1,017 local cases, down from 1,153.
The cleanup removed overlapping checks and consolidated related assertions across 19 test files.
Application, harness, renderer, and prompt sources did not change.

| Area | Before | After |
| --- | ---: | ---: |
| Application | 568 | 558 |
| Providers | 236 | 174 |
| Deployment | 70 | 61 |
| Harness and renderer | 279 | 224 |
| Total | 1,153 | 1,017 |

The baseline and retained suite execute the same 11,171 source lines and 3,218 branch outcomes.
Line coverage is 84.92 percent. Branch coverage is 71.93 percent.
Coverage supports the consolidation review. Input boundaries and asserted outcomes also determine whether a case remains useful.

The retained adapter contracts reject an estimator that always returns one token.
The earlier positive-count checks accepted that behavior.

## Run checks

```sh
uv run pytest -q
```

For a temporary coverage audit:

```sh
uv run --with coverage coverage run --branch --source=harness,theos,renderer,config -m pytest -q
uv run --with coverage coverage report
```

Coverage.py is an optional audit tool. These commands need no change to project dependencies.

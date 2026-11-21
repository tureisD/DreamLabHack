# Standalone evaluation workflow

`StatisticalEvaluator.evaluate` takes a validated `EvaluationRequest` and returns
an `EvaluationReport`. The runner owns file I/O and invocation metadata. Other
project modules can call the same protocol or supply JSON. The producer is
responsible for freezing the plan, providing all attempts and labels, and keeping
collection and assignment records. Unique IDs alone cannot verify independence.

From an installed checkout on Linux, run:

```sh
uv sync --locked --extra eval --group dev
uv run --locked --extra eval dream-eval evaluate --input request.json --output-dir run-001
```

`python -m dreamlab.evaluation evaluate --input - --output-dir run-002` runs the
same command in the installed environment and reads one JSON request from
standard input. The parent directory must already exist. Each invocation requires
a new destination. The command writes its results to files.

| File | Contents |
| --- | --- |
| `request.raw.json` | Submitted bytes, including original encoding, whitespace, and line endings. May be malformed. |
| `request.json` | Validated canonical JSON using the [v1 checksum rule](contracts.md). Includes effective defaults and preserves trial order. The file has no trailing newline. |
| `report.json` | Schema-validated `EvaluationReport`. The runner also verifies IDs, checkpoint roles, raw counts, the canonical SHA-256, and consistency of the decision and estimates with the plan. V1 binds task identity through request membership and the hash. |
| `summary.txt` | Decision, counts, estimated rates, effect in probability units, uncertainty, rationale and limitations. Sequential estimates may use an earlier prefix than the raw counts. |
| `manifest.json` | Artifact-relative input paths, raw and canonical SHA-256, submitted size, effective plan and seed, method settings, engine and package versions, Python and platform, source identity and lockfile SHA-256. |
| `diagnostics.json` | Failure bundle only. Contains `schema_version`, `exit_code`, `code`, `stage`, `message` and `details`, such as validation paths or expected and actual report values. |

For evaluable reports, the runner first checks internal estimate/interval
consistency and then recomputes the deterministic public evaluator result from
the same canonical request. It requires exact agreement on decisions, arm rates
and intervals, effect and difference interval, method, engine version, warnings
and rationale. This prevents a forged but internally consistent report from
claiming estimates that do not follow from the submitted outcomes. The request
snapshot is consequently evaluated twice in the normal CLI path; the evaluator
is pure and deterministic. A `not_evaluable` report must omit inferential estimates.

Source identity hashes a compact sorted JSON mapping of package-relative Python
source paths to each file's byte SHA-256. This covers dirty and untracked Python
files within the package in a checkout, as well as installed package code. Only
an editable install whose distribution `direct_url.json` identifies the imported
checkout records its `uv.lock` and, when available, Git `HEAD`. Otherwise the
runner hashes `dreamlab/uv.lock` shipped in the wheel, including in a `--target`
install under an unrelated project. A missing lock has a null checksum; the
runner does not search ancestor directories. Installed package versions are
reported separately from the shipped lock identity.

| Exit | Meaning |
| --- | --- |
| `0` | A valid report was published. Inspect `report.decision`, including `not_evaluable`. |
| `2` | Malformed request content (`malformed_request`) or command-line usage error. |
| `3` | Evaluator failure (`evaluator_error` or `evaluator_unavailable`). |
| `4` | Output violated the report schema (`invalid_report`) or did not match the request (`report_mismatch`). |
| `5` | Input read error (`input_unreadable`), destination collision (`output_collision`), or filesystem failure (`output_error`). |

An unsuccessful evaluation publishes diagnostics and the submitted bytes if read,
plus the canonical snapshot if validated. The report, summary and manifest appear
only in successful bundles. An unreadable input can yield a diagnostics-only
bundle, including when `--input -` is used with closed standard input. Standard
error points to published diagnostics or explains usage and publication failures.
If the bundle cannot be written or published, no partial destination is exposed.

The CLI requires Linux with `renameat2(RENAME_NOREPLACE)` and a destination
filesystem that supports it and enforces Linux/POSIX permissions. On Windows,
macOS, or a Linux filesystem lacking that rename operation, the CLI exits `5`
with `output_error` and does not publish. The pure Python evaluator is separate
and does not need these filesystem primitives.

The runner uses an exclusive sibling reservation to coordinate simultaneous
runs. It opens the output parent once and stages the bundle inside a private
same-filesystem directory. It exclusively creates files without following
symlinks, then atomically moves the actual completed directory from inside the
private directory, without replacing existing files, directories or symlinks.
Replacing the visible staging entry cannot redirect those writes or publication.
The caller must select the output parent via a trusted path; this does not protect
against processes that can access the private staging directory (such as the same
UID) or modify the destination after publication.

Cleanup errors emit `cleanup_warning` on stderr without changing the result of
publication. Interruption, failed cleanup or an altered staging name can leave
hidden reservations or staging directories. Verify ownership and that the runner
has exited before removing leftovers. Publication is atomic for visibility, not
a guarantee of durability across a system crash.

## Statistical scope

The [numerical guide](../src/dreamlab/evaluation/README.md) describes supported
v1 fixed-horizon and declared-look group-sequential comparisons. Well-formed
unsupported or ineligible requests produce `not_evaluable`. `inconclusive`
describes a supported comparison without a directional verdict. Neither decision
authorizes deployment. V1 lacks fields for randomization manifests, reset
confirmation and intervention policies. Preserve that producer evidence separately.

Run repeated looks only using the predeclared schedule and retain each submitted
snapshot in its own directory. The engine replays the first terminal decision from
ordered attempts. The runner neither manages live trial collection nor maintains
cross-invocation stopping state. Repeated fixed-horizon analyses do not control
sequential error.

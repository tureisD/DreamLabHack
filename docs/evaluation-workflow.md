# Standalone architecture and integration

Status: implementation design. The engine today is an unavailable stub.

```text
Versioned request JSON / project producer
  -> schema validation
  -> immutable input snapshot + canonical hash
  -> StatisticalEvaluator.evaluate(request)
       eligibility -> supported method -> decision -> report
  -> correspondence checks
  -> report JSON + readable summary + reproducibility manifest
```

## Ownership

The engine takes `EvaluationRequest` and returns `EvaluationReport`. It depends on
shared contracts and numerical libraries. A thin runner owns file I/O, invocation
metadata and error presentation. Future project modules call the same protocol or
supply JSON; no HTTP service is needed.

The producer supplies task/plan identity, all attempts, verified labels, checkpoint
identity and collection provenance. The engine checks statistical suitability.
Valid JSON and unique session IDs do not prove randomization or independence.

Keep `src/dreamlab/contracts/models.py` unchanged unless a reviewed extension is
needed. Its `extra='forbid'` boundary means rich audit metadata belongs in a sidecar
manifest until incorporated into a jointly reviewed schema version.

## Planned runner and artifacts

Implement `src/dreamlab/evaluation/cli.py` later. Proposed invocation:
`dream-eval evaluate --input request.json --output-dir artifacts/run-001`.
**This command does not exist yet**; there is no console entry point. Add it with
integration tests, not a placeholder claiming success.

Validate input, save canonical bytes using [contracts](contracts.md), call the engine,
then verify report evaluation/checkpoint IDs, trial identities, input hash and raw
counts. Preserve trial order and agree its report convention in shared fixtures.

```text
artifacts/<run-id>/
  request.json             exact canonical input
  report.json              validated result, if produced
  manifest.json            input hash, engine/config, code and lock identities
  summary.txt              counts, effect units, uncertainty and limitations
  diagnostics.json         structured failures when present
```

Use a new directory per invocation, atomic publication and explicit handling of
existing outputs. Never rewrite an old report after labels or methods change.
Record method options and RNG seed explicitly. Failed execution retains input
and diagnostics, never a fabricated report.

Recommended exit semantics: success means a well-formed report was produced,
including `not_evaluable`; malformed input or execution failure returns nonzero.
Consumers inspect `report.decision`, not the process status, to interpret findings.
Document exact exit codes when implementing the CLI.

## Capabilities and decisions

Publish supported schema/design/mode/label-policy combinations in a versioned
capability description. An importable class does not establish method support.
Unsupported well-formed designs return `not_evaluable`; the current unimplemented
engine raises `EvaluationUnavailable`. Programming/numerical exceptions remain errors.

Keep `inconclusive`, `not_evaluable` and execution failure distinct. Undefined
estimates are null, not zero. Account for success, failure, unknown and invalid.
Effects are candidate minus baseline in probability units; percentage points are
display formatting. Reports never authorize deployment.

## Sequential execution and contract gaps

Enable repeated-look execution only after method, schedule and replay validation.
Persist every look's exact input/result and preserve the first terminal decision.
Restarts and post-stop data must not rewrite history. Repeated fixed-horizon
reports are not sequential error control.

V1 cannot fully express randomization manifests, reset confirmation, intervention
policies, source aliases or simulator-oracle labels. Preserve producer evidence
and refuse unsupported inference; never invent required values. Sidecars alone
do not establish validity. Contract changes require fixtures and consumer tests.

## Integration acceptance

Fresh installation -> known request -> real engine -> save/reload -> verify
IDs/hash/counts and deterministic output. Test unsupported and malformed requests
separately. This replaces the former browser/database integration requirement and
needs no hardware, network, video decoder or paid service.

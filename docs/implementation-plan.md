# Standalone evaluation implementation plan

This assignment replaces the local application plan. Preserve the numerical
guidance in the package README. No method is implemented by this reorganization.

| Step | Deliverable | Acceptance |
| --- | --- | --- |
| E01 | Supported design, decision policy, checksum and fixture conventions | One explicit independent fixed-horizon specification; unsupported cases listed |
| E02 | Eligibility validation and descriptive counts | Contaminated, incomplete, unknown, invalid and unsupported inputs cannot produce a directional verdict |
| E03 | Arm/difference intervals and decisions | Independent references, boundaries, orientation and margin comparisons verified |
| E04 | Deterministic reports and correspondence checks | Correct hashes, IDs, counts, finite JSON/null semantics |
| E05 | Thin JSON runner and readable report | Fresh install and save/reload; distinct input, unavailable and numerical errors |
| E06 | Validation/diagnosis facility | Reproducible scenarios, expected/actual evidence, saved seeds and targeted reruns |
| E07 | Operating-characteristic study | Coverage, false claims and power with Monte Carlo uncertainty and predeclared tolerances |
| E08 | Sequential method after fixed-horizon validation | Valid error allocation, full-schedule false-claim tests and terminal-decision replay |
| E09 | Optional planning utilities/additional designs | Separate assumptions, references and capability declarations |
| E10 | Integration PR into main | Windows/Linux checks, package build, reproducible example and validation evidence |

The first milestone is E01–E07 for one justified design. E08–E09 should not delay
an honest fixed-horizon deliverable. Keep unsupported modes explicit.

## File structure

```text
src/dreamlab/contracts/       existing versioned boundary
src/dreamlab/evaluation/
  engine.py                  unavailable entry point to implement
  cli.py                     planned file-based invocation
  methods/                   eligibility and numerical methods
  reporting/                 report construction/readable rendering
tests/contracts/             existing structural tests
tests/evaluation/            reference, eligibility, reporting and simulation tests
tests/fixtures/              requests and reviewed expected outputs
docs/                        assignment, workflow, evidence and testing guides
```

No video importer or automatic success classifier is required. Use prepared
requests with explicit provenance. Public demonstrations cannot be turned into
a real checkpoint comparison by assigning invented labels or identities.

## Definition of done

Deliver an engine, method specification, standalone reproducible example,
independent numerical tests, operating-characteristic results and limitations.
Replace the unavailable-stub test when real behavior is implemented. Package/CI
success alone is not method validation. Follow [branching](branching.md); no
intermediate application integration remains.

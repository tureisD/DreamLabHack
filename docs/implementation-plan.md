# Standalone evaluation implementation plan

This plan defines the component's deliverables and acceptance criteria. See the
package README and workflow guide for implemented numerical methods and commands.

| Step | Deliverable | Acceptance |
| --- | --- | --- |
| E01 | Supported design, decision policy, checksum and fixture conventions | One explicit independent fixed-horizon specification; unsupported cases listed |
| E02 | Eligibility validation and descriptive counts | Contaminated, incomplete, unknown, invalid and unsupported inputs cannot produce a directional verdict |
| E03 | Arm/difference intervals and decisions | Independent references, boundaries, orientation and margin comparisons verified |
| E04 | Deterministic reports and correspondence checks | Correct hashes, IDs, counts, finite JSON/null semantics |
| E05 | Thin JSON runner and readable report | Fresh wheel install and save/reload; safe Linux no-follow/no-replace publication; Windows/macOS fail closed; distinct input, unavailable and numerical errors |
| E06 | Validation/diagnosis facility | Reproducible scenarios, expected/actual evidence, saved seeds and targeted reruns |
| E07 | Operating-characteristic study | Coverage, false claims and power with Monte Carlo uncertainty and predeclared tolerances |
| E08 | Sequential method after fixed-horizon validation | Valid error allocation, full-schedule false-claim tests and terminal-decision replay |
| E09 | Optional planning utilities/additional designs | Separate assumptions, references and capability declarations |
| E10 | Integration PR into main | Windows/Linux checks, package build, reproducible example and validation evidence |

The evaluator, finite-look method, planner and standalone file runner are implemented. The artifact-writing CLI currently requires Linux `renameat2(RENAME_NOREPLACE)`; Windows/macOS keep the pure Python evaluator but deliberately do not publish bundles. The runner recomputes the expected deterministic report from the exact canonical request before publishing. Keep unsupported modes and this platform restriction explicit. Statistical method validation is separate from runner/security tests.

## File structure

```text
src/dreamlab/contracts/       existing versioned boundary
src/dreamlab/evaluation/
  engine.py                  pure evaluator implementing the shared protocol
  cli.py                     standalone JSON and artifact command
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

Delivered: engine, method specification, standalone reproducible example,
independent numerical tests, operating-characteristic results, limitations and
artifact runner. The original unavailable-stub test has been replaced by method,
CLI and security regression tests. Package/CI success alone is not method
validation. Follow [branching](branching.md); no intermediate application
integration remains.

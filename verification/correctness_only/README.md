# Prepared Linux correctness-only route

Root must review `PROTOCOL.json`, both helper scripts and `.github/workflows/t3-v5b-linux-correctness.yml` before dispatch. The original timing route, 240-file bundle and 657-path freeze remain unchanged. The exported selected runtime also remains byte-identical to local v5b.

After the new T3 repository is published, the manual workflow takes the reviewed immutable HTTPS bundle URL and the exact 40-character repository commit containing these helper files. The workflow verifies the helper bytes against embedded SHA256 values and verifies the bundle against `5b34abb947d3e01fd86d2e0ade7590e467e15e762546c77302097b71433cc387`. No checkout action or mutable branch is used for helper code.

The route admits a readable valid hosted CPU quota for source correctness only. It still requires actual Linux/amd64, cgroup v2, at least 12 GiB total/4 GiB available memory, nonempty affinity and the exact dependency image. The host receipt is written before evaluating guards and records all read failures. The reference-acquisition tail is taken from the unchanged frozen `prepare_host.py`; it is executed only after those checks. Exact pinned public files remain evaluator data after runtime exits.

Actual Python 3.11 and 3.13 controls precede the original harness's correctness arm: all 71 units, both variants, 142 fresh processes. A separate host monitor records memory, `/proc/stat` and root cgroup CPU statistics; read/parse failure or low memory stops the controller, triggers the original cleanup, preserves all records and rejects admission. Original container telemetry exception handling is unchanged; its successful samples remain required and cannot certify uninterrupted telemetry coverage.

The original correctness harness records incidental wall times, events per second and per-unit ratios. They are retained as diagnostics and excluded from correctness-only admission. The route never calls timing mode or produces a speed estimate, bootstrap interval, performance gate, official promotion, new OCI layer or submission. Any failed process is preserved without replacement. GitHub artifact retention remains 14 days, including failures.

Local preparation checked script ASTs, the exact reference-tail AST, all source export hashes and every immutable bundle member. The Mac preflight refusal saved a host receipt with structured missing-Linux-surface errors and no reference acquisition. No actual Linux helper/controls/cohort execution has occurred.

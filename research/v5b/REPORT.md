# T3 bulk message-column experiment

The frozen bulk-conversion revision passes its predeclared local admission rule. Against retained v3, the five-scenario final cohort has a macro geometric-mean speed ratio of **1.036002×**, with a descriptive 95% hierarchical paired-bootstrap interval **[1.028737, 1.043696]×**. All five paired scenario medians improve, median peak memory falls in every scenario, and every one of the 84 pilot/final process outputs preserves exact Parquet bytes and event counts. The candidate also passes all 71 original public units, all 190 public reference frames and 566 differential message-column controls on each of two dependency stacks. A second agent independently reproduces the frozen arithmetic and admission. This establishes a modest native-Mac research improvement; it does not establish Linux, gVisor, B200 or official ranking performance.

## Change and exact behavior

The baseline is the exact retained `../research1008v3/runtime`, frozen as 59 source/license files. Only `runtime/abides_fork/trace.py` changes beyond v3. `source_changes.diff` shows the full change. The original extractor remains available as `_extract_message_trace_original`.

The new route preserves the original `(int(message_id), int(dst_id))` delivery-map lookup, excludes undelivered ledger rows, and uses the same stable sequence sort. Nullable `t_send_ns`, `order_id` and `causal_parent` use the same explicit Pandas `Int64` arrays, preserving nanosecond integers without float rounding. String columns retain Pandas string construction. Nonnullable numeric columns use NumPy bulk inference only for boolean/signed-integer domains, check the final dtype range, and cast without general DataFrame inference. Float, unsigned, object, malformed and overflow cases fall back to the unchanged original extractor. No kernel ledger emission, event/message processing, RNG draw, matching rule or trace schema changes.

The earlier scalar-column candidate is preserved and rejected under `../research1008v5/`: its matched profile regressed from 0.302557 s to 0.402474 s in message extraction. This separate bulk candidate reduces that diagnostic component to 0.205513 s, with exact profiled output bytes. Profiling is used to motivate measurement, not to select a speed result.

## Frozen protocol and verification

`PROTOCOL.json` and `CANDIDATE_FREEZE.json` precede profiling and timing. They pin baseline/candidate source, scenario inputs, harness/control files, pilot/final rosters, paired order, warmups/repeats, memory rule and the fixed bootstrap. Both-stack controls pass all 566 cases on Python 3.9 / NumPy 1.26.4 / Pandas 1.5.3 and Python 3.13 / NumPy 2.2.6 / Pandas 2.3.3. Controls include missing and empty ledgers, broadcast recipient keys, undelivered messages, stable equal-sequence order, nullable/large nanosecond values, final integer bounds, unusual scalar conversion and matching error classes, missing fields and 400 synthetic ledgers.

The full candidate sweep completes 71/71 original public units. Every process exits zero, every unchanged developer-verifier verdict is admissible, every public frame has exact values/dtypes, and all output bytes match the preserved submission-v2 outputs, which v3 already matched. There are 190 exact reference frames, including all six batch units. The unchanged one-hour documentation example is outside the original 71-unit roster. Reference files are read by evaluation helpers after the simulator exits, never passed into the runtime. Raw records and gate logs remain under `validation/all71/`.

`FINAL_REHASH_RECEIPT.json` independently rehashes every output of all 84 timing processes and all 71 public units after completion; every saved digest and incumbent byte comparison agrees. All 118 baseline/candidate source hashes and six control/harness hashes still match the premeasurement freeze. Independent `independent_track2/receipt_timing.json` and `receipt_final.json` check 137 source/control/input hashes, every final record, warmup/parity/paired ordering, denominator, memory arithmetic, fixed-seed interval and full correctness/decision agreement. No simulator is rerun for that review.

## Timing and memory

The three-scenario pilot has one recorded/discarded warmup pair plus three alternating measured pairs per scenario, totaling 24 processes. All bytes/counts are exact. Paired medians are 1.051316× for base throughput, 1.046581× for high frequency and 1.042512× for heterogeneous batch. All outliers remain, including the base pair at 0.986526×. Pilot results authorize only the already-frozen separate final cohort.

The final five-scenario cohort has one recorded/discarded warmup pair plus five alternating measured pairs per scenario, totaling 60 fresh processes. Numerical thread counts are one, bytecode writing is disabled, runs are sequential, and peer agents held numerical work during the timing window. Parent host wall includes the `/usr/bin/time` wrapper, startup/imports, config loading, simulation, extraction, validation, Parquet/events writes and shutdown. Host `/usr/bin/time -l` supplies maximum RSS rather than a runtime self-report. Resources are host descriptive observations, not organizer-enforced container telemetry.

| Final scenario | Paired median speed ratio | Geometric-mean speed ratio | Median RSS candidate/baseline |
|---|---:|---:|---:|
| Deep book/state size | 1.032713× | 1.028782× | 0.964445 |
| Deterministic latency baseline | 1.026844× | 1.028608× | 0.982755 |
| Homogeneous four-market batch | 1.038780× | 1.040019× | 0.997388 |
| Variable-size batch | 1.034453× | 1.038929× | 0.997668 |
| Mid-session fundamental shock | 1.045993× | 1.043766× | 0.977141 |

Speed is baseline host wall divided by candidate host wall, equivalent to candidate/incumbent events per second because counts are exact. RSS is the ratio of separate variant medians over five measured processes per scenario. No outlier, warmup or failing process is silently discarded. The hierarchical paired geometric speed bootstrap uniformly resamples scenarios and then pairs within each selected scenario, using 20,000 draws and seed 171050. Scenario choice, local hardware/cache conditions and only five final workloads limit generalization; the interval is descriptive.

Admission requires both-stack controls, all 71/190 exact public checks, exact timed bytes/counts, macro interval lower bound above 1, at least four of five median improvements, no median below 0.97 and every median RSS ratio at most 1.05. `decision.json` records all conditions as true. No repeat was run to improve significance.

## Selection and next boundary

Keep this exact 59-file source as the selected local research revision under `runtime/`, with `source_manifest.json`, final decision and every raw artifact preserved. Candidate trace SHA256 is `b7cea49f0b992d60bbde435374d47e8558b2198ed9cb5d164d6c868b0c5aa141`; retained-v3 trace SHA256 is `ac4a28892f903f1c5790f54e25833188efa7e57e32fab8e651092a9b329733e7`. Earlier rounds and submitted v2 remain immutable. The official v2 score reported by the coordinator is 13797.7076; this source has no official score.

No image was built, published or submitted by this experiment. The user now requires method polishing and complete evidence before official submission. Linux packaging must reproduce the selected source manifest and verify the actual pinned container dependency stack, interface and output contracts before the coordinator considers official submission. Current local exactness and a 3.6% Mac speed gain do not substitute for that environment check.

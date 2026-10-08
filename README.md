# Agenthon Track 3 simulation

This repository contains the exact selected local v5b simulator source in `src/`, its licenses and pinned dependencies, compact experiment decisions, and the frozen Linux verification source bundle. It contains only Track 3 work and the public evaluator components required by that bundle. The workspace keeps the complete original experiments separately; reference Parquets, generated output targets, OCI layers and credentials are excluded from this export.

The submitted v2 Development practice result is **13797.7076** (submission 968322). The selected v5b source has **no official score**. Its native-Mac matched final comparison against retained v3 gives a geometric speed ratio of **1.036002**, with a descriptive 95% interval **[1.028737, 1.043696]**. All 71 public units, 190 reference frames and 566 differential controls on each local dependency stack passed. These measurements do not certify Linux or official Final performance.

Linux v5b remains **UNVERIFIED**. The sole dispatched timing route, run [37752817228](https://github.com/kouzhizhuo/agenthon-t1/actions/runs/37752817228) at workflow commit `c5f4a257cf86181585b78e7fce2c428cfe9adfca`, stopped in host preparation because the hosted cgroup imposed a CPU quota. No reference acquisition, image pull, actual-stack controls, correctness or timing cohort began. The original strict timing workflow is preserved in `.github/workflows/t3-v5b-linux-timing.yml`; its CPU gate must remain unchanged. The immutable compact bundle SHA256 is `5b34abb947d3e01fd86d2e0ade7590e467e15e762546c77302097b71433cc387`.

`verification/correctness_only/` contains a separate prepared amendment for actual Python 3.11/3.13 controls and 142 correctness processes. It records hosted CPU quotas and cannot produce a performance admission or official ranking claim. Root review is required before its single dispatch. No contestant image build, push or official submission is part of either verification route.

The runtime implements both verbs:

```sh
python src/agent.py simulate --config scenario.json --out output/trace.parquet
python src/agent.py simulate-batch --batch-dir scenarios --out-dir output
```

Use the exact pinned Python 3.11 image stack or install `src/requirements.txt` in a suitable environment. Runtime input is scenario data; references and scorers belong to the evaluator after runtime exit. `src/vendor/abides/LICENSE`, `src/abides_fork/ORGANIZER-LICENSE` and `src/abides_fork/ORGANIZER-NOTICES.md` retain the original notices. `EXPORT_MANIFEST.json` pins exported source paths, hashes and sizes.

The rejected v5 scalar-column profile and v6 immutable-child copy pilot remain recorded under `research/`. V6 failed its predeclared heterogeneous-batch median gate despite exact outputs; v5b remains selected. These histories were not rerun or converted into successful evidence.

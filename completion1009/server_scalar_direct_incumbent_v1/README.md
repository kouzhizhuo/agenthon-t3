This experiment compares the retained native output version directly with the new exact scalar-read version on the same Linux runner. Both frozen candidates retain their original construction checks, serializer controls, whole-market state controls and official developer gates. Five selected tasks and five launches per version are a diagnostic comparison, not a full competition score.

# Direct comparison

Build the two unchanged source archives separately. Alternate their order for each task and repeat. Discard the first launch from timing while requiring all five launches to pass. Use actual Docker StartedAt to FinishedAt, take each task's median of four measured rates and then the arithmetic mean. Preserve all source, C/object/ELF, raw lifecycle, state and output evidence.

The incumbent has already passed full finite controls. The new V2.1 has passed61containers,180official gates and218saved Parquets, but its comparison with light does not establish improvement over the incumbent. This test exists to resolve that uncertainty. The232000EPS objective remains unmet.

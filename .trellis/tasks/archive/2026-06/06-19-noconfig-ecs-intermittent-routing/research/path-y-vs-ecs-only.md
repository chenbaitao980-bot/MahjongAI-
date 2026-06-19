# Path Y vs ECS-only diagnosis

## Question

Why does noconfig sometimes appear to connect to ECS and sometimes not? Is the phone occasionally connecting to the real server?

## Evidence

1. `c8cd0a2` introduced Path Y.
   - `remote/noconfig/hijack/netconf_patch.py` at that revision appended ECS entries to `LOCAL_TCP_LIST[5045]` while keeping the original real-server entries.
   - The same revision rewrote `LOCAL_TCP_LIST_50[5067/5167]` to `[ECS, real]`.
   - The task PRD `06-17-ecs-failover-direct-fallback/prd.md` explicitly describes this strategy.

2. The stock NetEngine behavior for the non-`_50` path is not deterministic ECS.
   - Current APK dump comments and the old PRD both describe ordinary path selection as random after merging config/cached lists.
   - With a 5045 list shaped like `[real, real, ECS, ECS]`, the client can naturally hit either side.

3. HEAD intentionally rolled Path Y back.
   - `remote/noconfig/hijack/netconf_patch.py` now replaces the real lobby IP in place with ECS and removes real-server fallback from `_50`.
   - `remote/noconfig/hijack/setup_mitm.py` raised the served version build offset from `+1000` to `+2000`.
   - The inline comment states this bump is specifically to force phones that already downloaded the old Path Y NetConf to redownload the ECS-only patch. Otherwise they stay on the old hotfix and keep the mixed real+ECS behavior.

## Conclusion

- Yes, historical code absolutely allowed occasional direct real-server connections.
- Current HEAD is trying to eliminate that behavior.
- If the symptom still exists now, the most likely explanation is stale hotfix assets on the phone rather than the current repo still intentionally shipping Path Y.

## What would disprove this

- A fresh phone that definitely downloaded the `+2000` ECS-only hotfix still shows mixed ECS/direct behavior.
- Or current deployment artifacts on ECS are older than `a8b8b2e` / still serving the Path Y variant.

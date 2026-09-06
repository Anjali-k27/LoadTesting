# POSTMORTEM — EPOCH Cluster Stress Test
# Date: 2026-08-26   Shape: StagedRamp (0→50→0 users)   Duration: 360s
# Cluster: ../Session5 (2 containers: fastapi gateway + mock litellm), host:8080

## Summary

P99 latency rose from **420ms** (baseline, 1 user) to **~8000ms** (steady state
at 50 concurrent users, oscillating 6800-8600ms across the 5-minute hold).
Error rate stayed at **0.05%** (1 failure in 1912 requests — a single
`RemoteDisconnected`) for the entire 50-user run. The system **held** — no
error storm, no cascading failure — but violated a 5s SLA almost immediately
after the ramp completed. A separate, higher-concurrency run at 200 users
(details below) *did* fall over: 42.6% error rate, P99 pinned at the 30s
httpx timeout ceiling, 502s from the gateway. So: **soft cliff found and
confirmed at 50 users; hard cliff exists but sits somewhere between 50 and
200 users, not inside the mission's originally-specified 50-user ceiling.**

This cluster has no Redis, no vLLM, no GPU, and no autoscaler — it's two
single-uvicorn-worker containers (`fastapi` gateway, mock `litellm` backend).
The canonical "triage triangle" (P99 vs error rate vs vLLM queue depth) does
not apply as written; the applicable version is P99 vs error rate vs the
mock backend's single-threaded blocking call, and P99 moved alone.

## Timeline (run: `reports/stress-50users-staged-ramp.html`, started 18:34:12 local)

| t+ (s) | Users | Event |
|---|---|---|
| 0   | 0  | Locust StagedRamp begins, spawn_rate 5/s |
| 10  | 50 | Ramp complete — target concurrency reached (faster than the 30s ramp window allows for, since 50 users / 5 per-s = 10s) |
| 13  | 50 | P99 = 4700-5000ms — approaching 5s SLA |
| 15  | 50 | **P99 crosses 5000ms** (P99=5900ms) — soft cliff. Error rate: still 0.000 |
| 15-300 | 50 | P99 oscillates 6800-8600ms for the entire hold. Error rate stays at 0.000 for ~150s, then exactly 1 failure total (0.05%) — never a second one |
| 300 | 50→0 | Ramp-down begins |
| ~330 | 0  | All users stopped; in-flight requests drain over next ~15s (P99 in the tail readings is stale/last-known, not live) |

**First mover: P99.** Error rate never moved in any sustained way. There is
no queue-depth metric in this cluster (no vLLM, no explicit queue), so the
three-way triage triangle collapses to a two-way one here — and P99 moved
alone, cleanly, exactly matching the "event-loop starvation / blocking call"
signature.

## Root Cause

**Mechanical, falsifiable claim:** `services/mock_llm/app.py`'s
`chat_completions` handler calls `time.sleep(random.uniform(0.1, 0.35))`
directly inside an `async def` route, on a single uvicorn worker (no
`--workers` flag in the Dockerfile CMD). `time.sleep()` blocks the entire
process's single event loop for its full duration — no other request,
including newly-arriving connections, can be serviced while it runs. This
caps the backend's true throughput at roughly `1 / mean_latency` ≈
`1 / 0.225s` ≈ **4.4 req/s**, regardless of how many client connections are
open concurrently.

Measured evidence:
- `docker stats` during the 50-user hold: `epoch-cluster-fastapi-1` CPU
  0.28-10.33%, `epoch-cluster-litellm-1` CPU 0.26-1.05%, memory flat (~223MB
  / ~32-41MB). **Neither container was CPU- or memory-bound** — ruling out
  resource exhaustion as the cause and confirming it's a concurrency-model
  problem, not a capacity problem.
- Backend call counter (`GET /stats` on the mock, added this session):
  1474 calls actually reached the backend over the 300s hold ≈ 4.9 req/s —
  consistent with the ~4.4 req/s theoretical serial ceiling (the gap is
  gateway-side overhead: JSON parsing, PII regex, a fresh
  `httpx.AsyncClient` per request in `main.py`'s `_handle_invoke`).
- Aggregate observed RPS during the hold: 5.0-6.4 req/s (Locust's own
  count, including requests that never reached the backend — e.g. blocked
  403s, 400s — which don't consume litellm's serial capacity at all).

The arrival rate at 50 concurrent users (each with 1-3s think time,
`chat_completion` weight 5 / `tool_heavy_query` weight 1) is roughly
20-25 req/s — several times the backend's ~4.4-5 req/s ceiling. The excess
queues in the gateway's outbound HTTP call to litellm; P99 rises to reflect
queueing delay, not compute cost. At 200 concurrent users (the other run),
arrival rate is high enough that queued requests routinely exceed the
gateway's `httpx.AsyncClient(timeout=30.0)` window (`main.py:96`) before
litellm can service them, producing the 502 `except Exception` branch.

## Triage Triangle Result

First metric to move:   [x] P99 (event-loop starvation)
                        [ ] Error rate (pool/limit exhaustion)
                        [ ] Queue depth (n/a — no explicit queue in this cluster)

Confirmed suspect: **synchronous `time.sleep()` in an `async def` handler,
single uvicorn worker, in `services/mock_llm/app.py`** — the canonical
"sync call in an async handler" failure mode, reproduced directly rather
than assumed.

## Numbers

| Metric              | Baseline (1 user) | Soft cliff (50 users, steady) | Hard cliff (200 users) |
|---------------------|--------------------|-------------------------------|--------------------------|
| RPS                 | 0.43               | 5.65                          | 6.61 (of which 2.80/s were failures) |
| P50 latency         | 250ms              | 6400ms                        | 10ms (bimodal — most requests hit instant 403/400 paths; the ones that reached the backend hit the 30s timeout) |
| P99 latency         | 420ms              | 8000ms                        | 30380ms (httpx timeout ceiling) |
| Error rate          | 0%                 | 0.05% (1/1912)                 | 42.4% (528/1245) — mostly 502 Bad Gateway |
| Backend calls       | n/a                | 1474 (measured via `/stats`)   | n/a (not captured this run — added the counter mid-session) |
| Gateway CPU         | n/a                | 0.28-10.33%                    | not captured |
| Backend CPU         | n/a                | 0.26-1.05%                     | not captured |

Soft cliff (P99 > 5s SLA): **~50 concurrent users** (crossed within 15s of
reaching that concurrency — data resolution between 1 and 50 users wasn't
captured at finer granularity this run).
Hard cliff (errors > 0.5%): **somewhere between 50 and 200 concurrent
users** — bounded, not pinpointed. See Action Items.
Lag (buffer) between soft and hard cliff: **not yet measured** — needs a
bisection run (e.g. 100 users) to narrow.

## Optimization Applied (if any)

Lever: **[ ] Prompt-cache tuning [ ] Parallel tool dispatch [x] Root-caused,
not yet fixed** — this run was scoped to *finding* the cliff, not fixing it.
The obvious fix (wrap the mock's `time.sleep()` in
`asyncio.to_thread(...)`, or use `asyncio.sleep()` if literally simulating
I/O-bound latency rather than modeling a real GPU-bound inference call) was
identified but deliberately not applied yet, so the "before" measurement in
this postmortem stays valid for comparison in the next session.

Before: P99 = 8000ms at 50 users (this run)
After:  not yet measured

## Action Items

- [ ] Wrap `services/mock_llm/app.py`'s `time.sleep()` in
      `asyncio.to_thread()` (or switch to `asyncio.sleep()` if blocking
      realism isn't the point) and re-run the identical StagedRamp to
      measure the P99 delta at 50 users — owner: TODO — due: TODO
- [ ] Bisect concurrency between 50 and 200 users (try 100) to pin down
      the actual hard-cliff threshold, not just the bounding range —
      owner: TODO — due: TODO
- [ ] Reuse one `httpx.AsyncClient` across requests in
      `services/fastapi/app/main.py::_handle_invoke` instead of opening a
      new one per call — secondary contributor to gateway-side overhead,
      not yet isolated from the primary backend bottleneck — owner: TODO
      — due: TODO
- [ ] Add a `--workers N` (or run behind a process manager) for the mock
      backend if it's meant to keep standing in for a real multi-worker
      LiteLLM proxy — right now 1 worker caps it far below what 50 real
      concurrent tenants would need — owner: TODO — due: TODO

## Security note (not a regression, but worth recording)

Both authority-under-load checks held for the full run with **zero**
leakage, verified two ways — not just by HTTP status:
- `AdversarialUser.injection_attempt` (viewer role, admin-gated prompt):
  177 requests in the earlier run, 0 failures — all correctly rejected
  with 401/403, never a 200.
- `EpochTenantUser.tool_heavy_query` for non-admin roles: rejected before
  reaching the backend in every case — confirmed via the mock's `/stats`
  call counter never incrementing for a blocked request (this closes the
  gap flagged in `../Session5/README.md`'s "Known gotchas" §1: the smoke
  suite's span assertions are inert because nothing feeds
  `FakePhoenixTracer` from the real process; this load test instead
  verifies against a real counter in the actual backend process).

## Artifacts

- Locust HTML report (50-user StagedRamp, the primary run):
  `reports/stress-50users-staged-ramp.html`
- Locust HTML report (200-user run — found via a bug, see below):
  `reports/stress-200users-spike-accidental.html`
- Baseline (1 user) report: `reports/baseline-1user.html`
- Full per-second CSV history for both stress runs:
  `reports/stress-50users-staged-ramp_stats_history.csv`,
  `reports/stress-200users-spike-accidental_stats_history.csv`

## Appendix — a bug found and fixed during this session

The first stress-test attempt accidentally ran **`SpikeShape`** (target 200
users) instead of the intended **`StagedRamp`** (target 50) — `load_shapes.py`
originally defined both as direct `LoadTestShape` subclasses in the same
file, and Locust silently picks one with no error when more than one exists.
This was only caught by noticing the CSV history's "User Count" column read
200, not 50. Fixed by refactoring both into plain (non-`LoadTestShape`)
classes and adding a single `ActiveShape(LoadTestShape)` that delegates
based on `LOCUST_SHAPE` — see the docstring in `load_shapes.py`. The
200-user data wasn't wasted: it's what established that a hard cliff exists
above 50 users, giving this postmortem a bounded (if not pinpointed) range
instead of an open question.

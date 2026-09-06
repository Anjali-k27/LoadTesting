# EPOCH — Session 16.3: locustfile.py — The Breaking Point

Load-tests the EPOCH gateway cluster built in Session 16.2 (`../Session5`)
under a staged 0→50→0 user ramp, finds where it stops holding up, and
writes up what actually happened. This directory does **not** contain a
cluster of its own — it's a Locust client that drives requests at the
cluster living in the sibling `Session5` repo.

```
   16.1  containerize   →  ../session4    (5-service docker-compose cluster)
   16.2  smoke-test it  →  ../Session5    (2-service cluster: fastapi + mock litellm)
   16.3  load-test it   →  this directory (Locust: staged ramp, find the cliff)
```

---

## 0. Before you start — the two-repo dependency

This repo (Session6) is a **Locust client only**. It has no server of its
own. Everything it drives traffic at lives in `../Session5`. If you're
setting this up somewhere Session5 doesn't already exist as a sibling
directory, clone it first:

```bash
git clone https://github.com/waseemkhan606/phase5-session5.git Session5
cd Session5
docker compose up -d --build
```

### Why the mock backend has a `time.sleep()` in it

The cluster's mock LLM backend (`services/mock_llm/app.py`) responded
instantly by default — nothing queues, so a load test against the
original version would never reproduce the cliff described in
`POSTMORTEM.md`. This session found that problem and fixed it directly in
`../Session5` (commit `b2fe185`, "Add realistic inference latency and
call counter to mock LLM backend"): a blocking `time.sleep(0.1-0.35s)`
per call, plus a `GET /stats` call counter. A plain `git clone` of
Session5 now includes this — no manual patch step needed.

If you ever check out an older commit of Session5 (before `b2fe185`) or
deliberately revert this change to compare, expect the stress test to
show near-zero latency and no cliff at all — there's nothing for 50
concurrent users to contend over without it. After changing
`services/mock_llm/app.py`, rebuild just that one service:

```bash
docker compose build litellm && docker compose up -d litellm
```

---

## 1. Prerequisites

```bash
python3 --version   # 3.11+ (built and tested on 3.12.3)
docker --version    # Docker Engine 24+
docker compose version   # Compose v2 — no hyphen
git --version
```

---

## 2. Setup — cloning and running this repo

```bash
# 1. Clone this repo (Session6) — adjust the URL once you've pushed one
git clone <your-repo-url> epoch-loadtest
cd epoch-loadtest

# 2. Make sure ../Session5 exists as a sibling directory (see Section 0)
#    and its cluster is running:
cd ../Session5 && docker compose ps
#    Both epoch-cluster-fastapi-1 and epoch-cluster-litellm-1 must show "healthy".
#    If not: docker compose up -d --build
cd ../epoch-loadtest   # back to this repo

# 3. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 4. Install dependencies
pip install -r requirements.txt
```

---

## 3. Step 0 — verify Session 16.2 before touching this session

Never assume the cluster is still healthy just because it was last time
you looked. From `../Session5`:

```bash
cd ../Session5
source .venv/bin/activate   # Session5 has its own venv; create one if missing
pip install pytest httpx PyJWT   # only if this venv doesn't have them yet
bash validate.sh
pytest -v --maxfail=1 tests/smoke_test.py
```

Expected: `8 passed`. If anything fails, fix Session5 before continuing —
don't debug a load test against a cluster that's already broken.

```bash
cd ../epoch-loadtest   # back to this repo
```

---

## 4. Running the load tests

All commands below assume you're in this directory with `.venv` activated
and Session5's cluster already up and healthy at `http://localhost:8080`.

### 4.1 Baseline (1 user, establishes healthy P99)

```bash
locust -f locustfile.py EpochTenantUser \
  --host http://localhost:8080 \
  --users 1 --spawn-rate 1 \
  --run-time 45s \
  --headless \
  --html reports/baseline-1user.html \
  --csv reports/baseline-1user
```

`EpochTenantUser` is named explicitly here — with more than one `HttpUser`
class in `locustfile.py`, Locust distributes 1 user across all of them by
weight, which at `--users 1` picks only the heaviest-weighted class. Naming
it pins the baseline to the chat/tools traffic mix the mission cares about.

### 4.2 Stress ramp (the real deliverable — finds the cliff)

```bash
locust -f locustfile.py,load_shapes.py \
  --host http://localhost:8080 \
  --headless \
  --html reports/stress-50users-staged-ramp.html \
  --csv reports/stress-50users-staged-ramp \
  --csv-full-history
```

Runs `StagedRamp` from `load_shapes.py` by default (0→50 users over 30s,
hold 300s, ramp down over 30s — 360s / 6 minutes total). `--csv-full-history`
is what makes it possible to reconstruct a timeline afterward instead of
only seeing the final aggregate.

**Note the `-f locustfile.py,load_shapes.py` comma syntax, not two separate
`-f` flags.** Two separate `-f` flags silently drop the first file's user
classes (`locust: error: No User class found!`) in this Locust version.

### 4.3 (Optional) Spike shape

```bash
LOCUST_SHAPE=spike locust -f locustfile.py,load_shapes.py \
  --host http://localhost:8080 \
  --headless \
  --html reports/spike-200users.html \
  --csv reports/spike-200users \
  --csv-full-history
```

Runs `SpikeShape` instead (0→200 users in 5s, hold 2min, drop to 5, hold,
ramp off). Useful for seeing what happens well past the soft cliff — this
is how the hard cliff (>40% error rate) got found in this session, even
though it wasn't the primary target.

### 4.4 Watching resource usage live (optional, run in another terminal)

```bash
watch -n2 docker stats --no-stream epoch-cluster-fastapi-1 epoch-cluster-litellm-1
```

### 4.5 Confirming the authority gate held under load

```bash
docker exec epoch-cluster-litellm-1 python -c \
  "import urllib.request; print(urllib.request.urlopen('http://localhost:4000/stats').read())"
```

`call_count` should equal only the requests that were actually *permitted*
through the gateway (admin-role deliverable calls + all chat calls) — never
the blocked viewer/analyst attempts or malformed/injection requests. If it's
higher than expected, the authority gate leaked under concurrency.

### 4.6 Capstone review

```bash
python capstone_review.py
```

Prints all 12 weeks' architectural decisions and either `CapstoneReview
COMPLETE` or a list of what's still blank. `student=` at the top of the
file still needs your name filled in — everything else in it is already
grounded in this course's actual code (see the file itself for citations
into `../session1` through `../Session5`).

No UI is required for any of this — everything above runs and validates
from the terminal. Locust's optional web dashboard (drop `--headless`,
then open `http://localhost:8089`) is a nicer way to *watch* a run live,
never required to run or validate one.

---

## 5. Expected output (this session's actual run)

```
Type             Name                          # reqs  # fails   Avg    P99
POST  /v1/agent/invoke [chat]                     253    0(0.0%)  6547   8500
POST  /v1/agent/invoke [long-prompt]             1187    1(0.1%)  6494   8300
POST  /v1/agent/invoke [malformed]                324    0(0.0%)     8     94
POST  /v1/agent/invoke [tools]                     43    0(0.0%)  1122   7600
POST  /v1/agent/invoke [injection]                105    0(0.0%)    10     77
--------------------------------------------------------------------------
Aggregated                                       1912    1(0.05%) 4926   8000
```

P99 crossed a 5-second SLA within 15 seconds of reaching 50 concurrent
users, and stayed there for the full 5-minute hold — with error rate
essentially at zero the entire time. See `POSTMORTEM.md` for the full
timeline, root cause (a blocking `time.sleep()` in the mock backend
serializing every request through a single uvicorn worker), and numbers.

---

## 6. Directory structure

```
.
├── .venv/                  # local virtualenv — gitignored, recreate per Section 2
├── .gitignore               # .venv/, __pycache__/, reports/*.html, reports/*.csv
├── requirements.txt         # locust, PyJWT, httpx, pytest — pinned versions
├── README.md                 # this file
├── locustfile.py             # EpochTenantUser, LongPromptUser, AdversarialUser
├── load_shapes.py            # ActiveShape — StagedRamp (default) / SpikeShape (LOCUST_SHAPE=spike)
├── capstone_review.py        # 12-week decision matrix, grounded in real course code
├── POSTMORTEM.md             # filled in from this session's actual runs — real numbers
└── reports/
    ├── .gitkeep
    ├── baseline-1user.*                   # 1-user baseline (P99 ≈420ms)
    ├── stress-50users-staged-ramp.*       # the primary deliverable run
    └── stress-200users-spike-accidental.* # kept as evidence — see POSTMORTEM.md appendix
```

No other directories exist in this repo, and none are needed — everything
that isn't Locust output (`reports/`) or the venv is a single flat file.

---

## 7. Known gotchas found while building this session

1. **Two `LoadTestShape` subclasses in one file is silently ambiguous.**
   `load_shapes.py` originally defined `StagedRamp` and `SpikeShape` as
   direct `LoadTestShape` subclasses side by side. Locust picked one with
   no error — the first stress run target 200 users instead of the
   intended 50, caught only by noticing the CSV history's `User Count`
   column. Fixed by making both plain classes and adding a single
   `ActiveShape(LoadTestShape)` that delegates via `LOCUST_SHAPE` — see the
   docstring in `load_shapes.py`.
2. **`-f file1.py -f file2.py` (two flags) silently drops the first file's
   classes** on this Locust version (`No User class found!`). Use
   `-f file1.py,file2.py` (one flag, comma-separated) instead.
3. **The mock backend's default instant response means no load test will
   ever find a cliff.** See Section 0's patch — without it, 50 or even 500
   concurrent users against the unmodified Session5 cluster produce
   near-zero latency and no interesting failure mode.
4. **`--run-time` is ignored whenever a `LoadTestShape` is active** — the
   shape's own stage durations control when the run ends, not the CLI flag.

---

## 8. Final checklist

- [x] `../Session5` cluster verified healthy (`validate.sh` + `pytest` 8/8) before this session started
- [x] Mock backend patched with realistic blocking latency + `/stats` counter — committed in Session5 as `b2fe185`
- [x] `locustfile.py` — chat:tools weighted 5:1, `LongPromptUser` + `AdversarialUser` present, `wait_time` never commented out
- [x] `load_shapes.py` — exactly one `LoadTestShape` in scope (`ActiveShape`), `StagedRamp` ramps over 30s / holds 300s
- [x] Baseline run captured (`reports/baseline-1user.*`)
- [x] Stress run captured, full CSV history (`reports/stress-50users-staged-ramp.*`)
- [x] First-mover metric identified (P99), root cause verified via `docker stats` + backend call counter, not guessed
- [x] Authority gate confirmed to hold under load — verified via backend call counter, not HTTP status alone
- [x] `POSTMORTEM.md` filled in with real numbers from the actual runs above
- [x] `capstone_review.py` prints all 12 weeks filled from real course code (only `student=` name field left for you)
- [ ] Push this repo to a remote, and `git push` the Session5 commit above, if you want this reproducible from a clean clone on another machine

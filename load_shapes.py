"""
load_shapes.py — Explicit load shapes for the EPOCH cluster (../Session5).

Use StagedRamp for the stress run (finding the cliff).
Use SpikeShape for the surge run (autoscaler-equivalent response — this
cluster has no autoscaler, so this shape instead measures whether the two
containers recover on their own once load drops).

Why not --users 50 --spawn-rate 50?
    That is the instant-stampede pattern. It tests cold-start under a
    stampede, not steady-state under load. Real traffic ramps. The ramp
    gives the mock backend's per-request latency stub, the gateway's
    per-request httpx.AsyncClient, and connection acceptance time to
    settle before steady-state measurement begins.

Usage:
    # Stress (find the cliff) — the default:
    locust -f locustfile.py,load_shapes.py --host http://localhost:8080 --headless

    # Spike (surge / recovery):
    LOCUST_SHAPE=spike locust -f locustfile.py,load_shapes.py --host http://localhost:8080 --headless

Why this file defines only ONE concrete LoadTestShape subclass:
    Locust requires exactly one LoadTestShape in scope and will silently
    pick whichever one it discovers if more than one subclasses it
    directly — there is no error, no warning, just a wrong shape running.
    That happened once during this session's own Session 16.3 run: with
    both StagedRamp(LoadTestShape) and SpikeShape(LoadTestShape) defined
    unconditionally, Locust ran SpikeShape (target 200 users) while the
    intended run was StagedRamp (target 50) — caught only by noticing the
    "User Count" column in the CSV history read back 200, not 50. Fixed
    by making _StagedRampImpl / _SpikeShapeImpl plain classes and
    exposing a single ActiveShape(LoadTestShape) that picks one via
    LOCUST_SHAPE at import time — so only one LoadTestShape subclass
    ever exists in the module, and the ambiguity is structurally
    impossible instead of merely documented against.

Introduced: Session 16.3.
"""
import os
from locust import LoadTestShape


class _StagedRampImpl:
    """
    Stress test: ramp 0->50 over 30s, hold 5min, ramp down.

    Stage 1 (0-30s):    spawn 5 users/s until 50 users
    Stage 2 (30-330s):  hold 50 users, spawn_rate 1 (maintains headcount)
    Stage 3 (330-360s): ramp down 5 users/s to 0

    This cluster has no autoscaler (two fixed containers, one uvicorn
    worker each) — the 30s ramp instead gives the mock backend's per-call
    latency stub and the gateway's connection handling time to reach a
    steady request rate before the hold window is measured.

    To find the cliff faster: set hold to 60-120s and re-run incrementally.
    To reproduce a known cliff: set target to the cliff RPS + 10%.
    """
    stages = [
        {"duration":  30, "users": 50, "spawn_rate": 5},   # ramp up
        {"duration": 330, "users": 50, "spawn_rate": 1},   # hold
        {"duration": 360, "users":  0, "spawn_rate": 5},   # ramp down
    ]

    def tick(self):
        run_time = self.get_run_time()
        for stage in self.stages:
            if run_time < stage["duration"]:
                return (stage["users"], stage["spawn_rate"])
        return None   # end the test


class _SpikeShapeImpl:
    """
    Spike test: 0->10x in 5s, hold 2min, drop back.

    Simulates: viral event, cron job stampede, marketing email blast.
    Tests: connection-accept burst behavior and recovery once load drops —
    there is no autoscaler in this cluster to react, so "recovery" here
    means P99 returning to baseline once concurrency drops, not new
    replicas coming online.

    Baseline must be established with a smoke run first.
    'Spike' is relative — 10x of your measured baseline RPS.
    """
    stages = [
        {"duration":   5, "users": 200, "spawn_rate": 40},  # instant spike
        {"duration": 125, "users": 200, "spawn_rate":  1},  # hold 2 min
        {"duration": 130, "users":   5, "spawn_rate": 40},  # drop back to baseline
        {"duration": 190, "users":   5, "spawn_rate":  1},  # hold baseline (observe recovery)
        {"duration": 195, "users":   0, "spawn_rate": 10},  # ramp off
    ]

    def tick(self):
        run_time = self.get_run_time()
        for stage in self.stages:
            if run_time < stage["duration"]:
                return (stage["users"], stage["spawn_rate"])
        return None


_IMPLS = {"stress": _StagedRampImpl, "spike": _SpikeShapeImpl}


class ActiveShape(LoadTestShape):
    """
    The one and only LoadTestShape Locust ever sees from this module.
    Delegates to _StagedRampImpl (default) or _SpikeShapeImpl
    (LOCUST_SHAPE=spike), so exactly one shape can ever run per process —
    no silent pick between two ambiguous LoadTestShape subclasses.
    """
    _impl_cls = _IMPLS[os.environ.get("LOCUST_SHAPE", "stress")]
    stages    = _impl_cls.stages

    def tick(self):
        return self._impl_cls.tick(self)

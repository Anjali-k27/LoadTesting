"""
capstone_review.py — The decision matrix you defend at graduation.

Fill in every row before your 10-minute capstone pitch.
Blank tradeoff or failure fields -> the row is incomplete.
Incomplete row -> the decision is not yet defended.

A defended decision names:
    what you chose (specific, not generic)
    what it bought you (measured, not intuited)
    what it cost (honest, not minimized)
    how it will fail (concrete failure mode, not "could be better")

The two worked examples below (W1, W3) are filled from decisions actually
present in this repo's cluster (../Session5: services/fastapi/app/main.py,
services/mock_llm/) so you can see the expected level of specificity.
Every other row is a real TODO — those are YOUR calls from the rest of
the bootcamp, and only you can defend them.

Usage:
    python capstone_review.py

Introduced: Session 16.3. Permanent.
"""
from dataclasses import dataclass, field
from typing import List


@dataclass
class Decision:
    primitive:        str
    week_introduced:  int
    choice:           str
    tradeoff:         str   # what you bought vs what you paid
    failure_mode:     str   # how this decision will eventually fail


@dataclass
class CapstoneReview:
    student:   str
    decisions: List[Decision] = field(default_factory=list)

    def add(self, **kw) -> "CapstoneReview":
        self.decisions.append(Decision(**kw))
        return self

    def render(self) -> None:
        print(f"\nCapstone Review — {self.student}")
        print("=" * 78)
        for d in sorted(self.decisions, key=lambda x: x.week_introduced):
            print(f"  W{d.week_introduced:02d}  {d.primitive:<28s}  {d.choice}")
            print(f"        tradeoff:  {d.tradeoff}")
            print(f"        failure:   {d.failure_mode}")
            print()

    def validate(self) -> bool:
        """Returns True only if all 12 required weeks are covered."""
        required = {1, 3, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15}
        covered  = {d.week_introduced for d in self.decisions}
        missing  = required - covered
        if missing:
            print(f"INCOMPLETE: missing weeks {sorted(missing)}")
            return False
        blank = [d for d in self.decisions if not d.tradeoff or not d.failure_mode
                 or "TODO" in d.choice or "TODO" in d.tradeoff or "TODO" in d.failure_mode]
        if blank:
            print(f"INCOMPLETE: TODO/blank fields in: {[b.primitive for b in blank]}")
            return False
        return True


# ── FILL THIS IN ───────────────────────────────────────────────────────────
# Replace every "TODO" string with your actual decisions from the bootcamp.
# W1 and W3 are filled from real, verifiable decisions in this repo's
# cluster as worked examples of the expected specificity.

review = CapstoneReview(student="TODO: your name")

review.add(
    primitive       = "LLM provider abstraction",
    week_introduced = 1,
    choice          = "Gateway calls a single internal LiteLLM-shaped endpoint "
                      "(services/mock_llm in ../Session5) instead of an SDK for "
                      "any one model provider — main.py posts to LITELLM_URL "
                      "with the OpenAI chat-completions shape.",
    tradeoff        = "Bought: the gateway's _handle_invoke never changes when "
                      "the backend swaps (mock now, real LiteLLM proxy later, "
                      "any OpenAI-compatible model behind it) — proven by "
                      "swapping in a latency+call-counter stub (Session 16.3) "
                      "with zero changes to main.py. Paid: an extra network "
                      "hop and JSON round-trip versus calling a provider SDK "
                      "in-process.",
    failure_mode    = "LITELLM_URL misconfigured or the backend container down "
                      "-> every request 502s from the `except Exception` branch "
                      "in _handle_invoke; detect via error-rate alert on that "
                      "one status code rather than a generic 5xx bucket.",
)

review.add(
    primitive       = "Authority gate placement",
    week_introduced = 3,
    choice          = "Keyword-gated admin check (`requires_admin_tool`) runs "
                      "BEFORE the call to the LLM backend, not after — verified "
                      "directly via the mock backend's /stats call counter "
                      "(Session 16.3): blocked requests never increment it.",
    tradeoff        = "Bought: a provably cheap, provably safe rejection — a "
                      "blocked request costs one regex check, not a wasted "
                      "backend round-trip, and can be verified without real "
                      "tracing infra. Paid: the gate is a keyword match on the "
                      "prompt string (`\"clinical pdf\"`, `\"deliverable\"`), "
                      "not a structured tool-call classifier — a differently "
                      "worded request for the same privileged action could "
                      "slip past undetected.",
    failure_mode    = "A user phrases the same admin-only request without "
                      "matching keywords ('put together the CT summary PDF for "
                      "billing') -> gate never fires -> request reaches the "
                      "backend as if it were a normal chat query. Caught only "
                      "by widening ADMIN_ONLY_KEYWORDS or replacing the keyword "
                      "match with real tool-call intent classification.",
)

# ── Remaining 10 rows — read directly from the actual code across ─────────
# ../session1, ../session2, ../session3 (15.1-15.3) and ../session4,
# ../Session5 (16.1-16.2). Every "choice" cites the real class/file; the
# tradeoff/failure_mode are inferred from that code's own documented
# behavior, not invented. Where nothing was implemented (W13), that's
# stated directly instead of filled with a plausible-sounding guess.

review.add(
    primitive       = "Tool calling pattern",
    week_introduced = 5,
    choice          = "Sequential, not parallel — epoch_invoke() "
                      "(session2/epoch_auth.py) loops over tool_calls one at "
                      "a time: execute, audit, next. No asyncio.gather "
                      "anywhere in the stack.",
    tradeoff        = "Bought: every tool call is individually audited "
                      "(actor + hospital + jti) before the next one starts — "
                      "trivial to reason about and to replay from the audit "
                      "log. Paid: total latency is the sum of every tool's "
                      "latency, not the max — a 3-tool turn takes 3x as long "
                      "as the slowest tool alone.",
    failure_mode    = "A model response with N tool calls where each takes "
                      "~1s costs ~Ns of wall-clock time regardless of how "
                      "independent the tools are; under concurrent users "
                      "this compounds directly into the P99 latency this "
                      "session's own stress test measured. Caught by: a "
                      "load test showing per-tool-call latency summing "
                      "linearly instead of clustering near the slowest tool.",
)

review.add(
    primitive       = "Retrieval architecture",
    week_introduced = 7,
    choice          = "FakeFAISSRouter (session1/epoch_ingest.py) — one "
                      "simulated FAISS index file per (hospital_id, "
                      "expert_id); only one expert's index is ever loaded "
                      "into memory at a time, and loading a new one evicts "
                      "the previous one.",
    tradeoff        = "Bought: the isolation guarantee is structural, not a "
                      "filter — 'Hospital B cannot see Hospital A's traces' "
                      "has the one-sentence proof 'the file is never open,' "
                      "verified directly by assert_no_cross_expert_retrieval. "
                      "Paid: no cross-expert or cross-hospital retrieval is "
                      "possible even when it would be legitimately useful "
                      "(e.g. a multi-expert consult) — the isolation is total, "
                      "not policy-gated.",
    failure_mode    = "A caller that reuses one FakeFAISSRouter instance "
                      "across concurrent requests for two different experts "
                      "will thrash the single loaded-index slot — every "
                      "request evicts the previous one, and if the eviction "
                      "and the search race, load_calls/unload_calls diverge "
                      "from search calls. The class's own docstring flags "
                      "this: 'a threading.Lock' is required in production, "
                      "which this teaching version does not have.",
)

review.add(
    primitive       = "Evaluation harness",
    week_introduced = 8,
    choice          = "No LLM-as-judge and no golden set exist anywhere in "
                      "this codebase. Every session verifies itself with "
                      "hardcoded assert-based checks (run_session_verification "
                      "-> 'N/N checks passed') plus Session5's pytest smoke "
                      "suite — deterministic assertions on status codes, "
                      "claims, and tool lists, never a model-graded score.",
    tradeoff        = "Bought: verification is instant (<250ms for 8 checks), "
                      "deterministic, and needs zero API key or model call to "
                      "run in CI. Paid: nothing evaluates actual answer "
                      "quality — a correctly-authorized, correctly-shaped "
                      "response that is factually wrong about Dr. Chen's "
                      "protocol would pass every single check in this repo.",
    failure_mode    = "A prompt or model change that degrades answer quality "
                      "(but keeps status codes, role fields, and header "
                      "contracts intact) ships with all tests green. Nothing "
                      "in 15.1-16.2 would catch it — there is no golden-set "
                      "regression check on the actual text of an answer.",
)

review.add(
    primitive       = "Agent control flow",
    week_introduced = 9,
    choice          = "A fixed linear pipeline, not free-form ReAct — "
                      "FakeEpochAgent.STEPS (session3/epoch_sla.py) hardcodes "
                      "the exact node sequence (plan -> retrieve -> reflect -> "
                      "tool_call -> reflect_2 -> tool_call_2 -> answer); each "
                      "node appends one atomic note to a shared "
                      "internal_notes scratchpad and checkpoints before the "
                      "next node runs.",
    tradeoff        = "Bought: a cancelled run always leaves a coherent, "
                      "replayable partial state — every note is a complete "
                      "standalone sentence by convention, which is exactly "
                      "what makes the HTTP 206 partial-content response "
                      "legible to a client. Paid: the agent cannot adapt its "
                      "own step sequence — it cannot skip reflect_2, add an "
                      "extra tool call, or re-order steps based on what it "
                      "finds; the graph shape is compiled in, not decided at "
                      "runtime.",
    failure_mode    = "A question that genuinely needs zero tool calls (or "
                      "three) still runs the same fixed 7 steps and pays for "
                      "all of them — the 'reflect' and 'reflect_2' steps fire "
                      "unconditionally even when nothing changed between them. "
                      "Caught by: comparing internal_notes content across "
                      "different question types and finding boilerplate, "
                      "non-informative notes on simple questions.",
)

review.add(
    primitive       = "Memory / checkpointer",
    week_introduced = 10,
    choice          = "FakeMemorySaverCompositeKey / FakeCheckpointer — "
                      "primary key (hospital_id, expert_id, thread_id, step), "
                      "not the stock LangGraph SqliteSaver shape of "
                      "(thread_id, checkpoint_id) alone.",
    tradeoff        = "Bought: a thread_id-guessing attack is structurally "
                      "harmless — two hospitals can reuse thread_id='100' "
                      "and the composite miss is silent and correct, proven "
                      "by assert_no_checkpoint_bleed. Paid: every read and "
                      "write call site must supply all three identity fields "
                      "or get a TypeError at call time — there is no "
                      "convenience path that reads by thread_id alone, even "
                      "for legitimate same-hospital debugging tools.",
    failure_mode    = "Exactly reproduced in session1/epoch_ingest.py's own "
                      "exercise_break_composite_key: dropping hospital_id "
                      "from the WHERE clause (a plausible-looking 'simplify "
                      "the query' refactor) lets Hospital B read Hospital A's "
                      "checkpoint data under a guessed thread_id. Caught only "
                      "by assert_no_checkpoint_bleed — nothing else in the "
                      "stack would notice.",
)

review.add(
    primitive       = "Vector store",
    week_introduced = 11,
    choice          = "The same FakeFAISSRouter as W7 — in-process, "
                      "file-per-tenant simulation, not a hosted multi-tenant "
                      "vector DB (Pinecone/Weaviate/etc.) with metadata "
                      "filtering.",
    tradeoff        = "Bought: zero network hop for retrieval, and the "
                      "isolation argument stays a one-liner ('the file isn't "
                      "open') instead of 'the metadata filter is correctly "
                      "applied on every query path.' Paid: this doesn't scale "
                      "past one process/one machine — there's no sharding or "
                      "replication story for when the corpus outgrows one "
                      "host's memory.",
    failure_mode    = "At real scale (many hospitals x many experts), "
                      "loading one index per request thrashes memory and "
                      "load_calls climbs linearly with request fan-out across "
                      "distinct experts — the class's own docstring already "
                      "names the fix (real faiss.read_index from GCS with a "
                      "lock) as a 16.x-era concern, not yet done.",
)

review.add(
    primitive       = "Observability stack",
    week_introduced = 12,
    choice          = "trace_tags() (session2/epoch_auth.py) emits an "
                      "OTel-semantic-convention dict (enduser.id, "
                      "enduser.role, tenant.id, auth.jti, agent.tool) per "
                      "tool call — but it is never wired to a real "
                      "collector anywhere in 15.1-16.2.",
    tradeoff        = "Bought: the tag shape is already Phoenix/OTel-native, "
                      "so wiring a real collector later is a plumbing change, "
                      "not a redesign. Paid: right now it's documentation of "
                      "intent, not working coverage — Session5's own README "
                      "proves this directly (see below).",
    failure_mode    = "Reproduced, not hypothetical: Session5's README "
                      "'Known gotchas' section disabled the authority gate "
                      "entirely (let Viewer invoke an admin-only tool) and "
                      "the full 8-test smoke suite still reported 8 passed, "
                      "because FakePhoenixTracer lives only in the test "
                      "process and nothing in main.py feeds it real spans. "
                      "Any span-based assertion in this codebase is "
                      "currently inert.",
)

review.add(
    primitive       = "Cost controls",
    week_introduced = 13,
    choice          = "Not implemented. Redis is provisioned in "
                      "docker-compose.yml (its own volume, healthcheck, "
                      "dependency ordering) but the only place it's touched "
                      "in application code is /cluster/health's ping — never "
                      "for a token budget, rate limit, or request cap.",
    tradeoff        = "Bought: nothing yet — there's no cost-control "
                      "mechanism to trade off. The closest artifact is the "
                      "ROI commentary in epoch_sla.py's SLA_BUDGET_SECONDS "
                      "comment (breach-cost economics), which explains why "
                      "SLA matters but doesn't enforce any spend limit.",
    failure_mode    = "A single tenant (or a compromised/misbehaving client) "
                      "can call generate_client_deliverable — documented as "
                      "'~$6/call at frontier model rates' in "
                      "session2/epoch_auth.py's own docstring — as many "
                      "times as their role allows, with nothing in the stack "
                      "to notice or throttle the spend. This is a real, "
                      "open gap, not a design choice.",
)

review.add(
    primitive       = "Fallback strategy",
    week_introduced = 14,
    choice          = "A provider cascade, not app-level try/except — "
                      "services/litellm/config.yaml registers vLLM and "
                      "Gemini under the same model_name ('epoch-default'), "
                      "routing_strategy: least-busy, num_retries: 2. "
                      "Separately, CircuitBreaker (session3/epoch_sla.py) "
                      "fails fast with 503 once the sliding-window failure "
                      "rate crosses 15%, with exactly one HALF_OPEN probe on "
                      "cooldown to avoid a thundering herd on recovery.",
    tradeoff        = "Bought: two independent fallback layers at different "
                      "timescales — LiteLLM absorbs a single provider being "
                      "down or slow (retries + reroute), while the circuit "
                      "breaker absorbs a sustained systemic failure (fails "
                      "fast instead of queueing requests behind a dead "
                      "backend). Paid: a silent model swap from vLLM to "
                      "Gemini mid-cascade changes answer style/latency/cost "
                      "characteristics with no signal to the caller that it "
                      "happened.",
    failure_mode    = "If Gemini's fallback entry also degrades, "
                      "num_retries: 2 at the LiteLLM layer still burns 2x "
                      "the latency budget before the circuit breaker's own "
                      "failure-rate window even registers the failures — the "
                      "two layers aren't tuned against each other's timing, "
                      "just stacked.",
)

review.add(
    primitive       = "Multi-tenancy + RBAC",
    week_introduced = 15,
    choice          = "Row-level, not schema-level, and split across two "
                      "mechanisms: FakePostgresRLS (hospital_id-scoped, "
                      "deny-by-default on an unset GUC) for tenant data, and "
                      "ROLE_TOOLS + BoundGeminiModel for role-based tool "
                      "access — the role is resolved to a concrete tool list "
                      "BEFORE the model is constructed, not filtered out of "
                      "a system prompt afterward.",
    tradeoff        = "Bought: 'the system prompt is not a security control, "
                      "bind_tools() is' — a prompt-injection attack has "
                      "nothing to hallucinate a call into, since the tool's "
                      "schema was never attached for that role. Verified "
                      "directly by the red-team drill: Viewer's injection "
                      "prompt never produces a generate_client_deliverable "
                      "call. Paid: row-level isolation means every table and "
                      "every query must remember to scope by hospital_id — "
                      "there's no schema boundary that makes a forgotten "
                      "scope structurally impossible the way a separate "
                      "per-tenant schema would.",
    failure_mode    = "A RLS policy created with ENABLE but not FORCE lets "
                      "the table owner (or a role with BYPASSRLS) silently "
                      "see everything — a documented, named failure mode in "
                      "FakePostgresRLS's own docstring, not a hypothetical. "
                      "Same class: pgbouncer transaction pooling reusing a "
                      "connection's GUC across different tenants' requests "
                      "if SET (not SET LOCAL) is used outside an explicit "
                      "transaction.",
)


if __name__ == "__main__":
    review.render()
    ok = review.validate()
    if ok:
        print("CapstoneReview COMPLETE — ready to present.\n")
    else:
        print("Fill in all TODO fields before your graduation review.\n")

"""The benchmark exercises real components with local, fixed provider fixtures."""
from contextlib import contextmanager
from hashlib import sha256
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
from time import perf_counter_ns
from types import SimpleNamespace
from uuid import UUID

import pytest

from benchmarks.effectiveness.report import write_reports
from server import scop_agent_integration as agent
from server import scop_firewall_checks as checks
from server import scop_verify_syntax as syntax
from server.scop_agent_feedback import checked_feedback
from server.scop_firewall_memory import Memory
from test_scop_firewall_checks import PROJECT, REVIEWER, SECRET, WORKER, contents, delivery, metadata, pg, revision, rpc

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "benchmarks/effectiveness/scenarios-v1.json"
REF = "lbklqqqbmeyseeccdqog"


def cpu_seconds():
    return sum(v.ru_utime + v.ru_stime for v in (resource.getrusage(resource.RUSAGE_SELF),
                                                resource.getrusage(resource.RUSAGE_CHILDREN)))


def elapsed_ms(start):
    return round((perf_counter_ns() - start) / 1_000_000, 3)


class Fixtures:
    def __init__(self, pg):
        self.pg = pg
        self.artifact = None
        self.case = None
        self.profile_ms = {"database_ms": 0.0, "agent_io_ms": 0.0}
        self.memory = checks.StagingMemory(REF, "sb_publishable_fixture", "fixture-worker")
        self.github = checks.GitHubEvidence("fixture-read-only", PROJECT)

    def ids(self):
        return revision(self.case["pr"])

    def github_response(self, url, deadline=None):
        rev = self.ids()
        endpoint = f"https://api.github.com/repos/{PROJECT.repository}/pulls/{rev.pr}"
        prefix = f"https://api.github.com/repos/{PROJECT.repository}/contents/"
        path = "fixture.py"
        old = contents(path, b"value = 1\n")
        after = self.case["head"]
        new = contents(path, (after + "\n").encode())
        if url == endpoint:
            actual = revision(399) if self.case["fault"] == "divergent" else rev
            response = metadata(actual)
            return {**response, "number": rev.pr, "changed_files": 1,
                    "html_url": f"https://github.com/{PROJECT.repository}/pull/{rev.pr}"}
        if url == endpoint + "/files?per_page=100&page=1":
            patch = None if self.case["fault"] == "incomplete" else "@@ -1 +1 @@\n-value = 1\n+" + after
            return [{"filename": path, "sha": new["sha"], "status": "modified", "additions": 1,
                     "deletions": 1, "patch": patch}]
        for ref in (rev, revision(399)):
            if url == f"{prefix}{path}?ref={ref.base_sha}":
                return old
            if url == f"{prefix}{path}?ref={ref.head_sha}":
                return new
        if url == f"{prefix}{checks.ARTIFACT}?ref={rev.base_sha}" and self.artifact is not None:
            suffix = b" " if self.case["fault"] == "tampered" else b""
            return contents(checks.ARTIFACT, self.artifact + suffix)
        raise AssertionError("Unexpected fixture request")

    @contextmanager
    def profile(self, name):
        started = perf_counter_ns()
        try:
            yield
        finally:
            self.profile_ms[name] += elapsed_ms(started)

    def read_run(self, run_id):
        run_id = str(UUID(run_id))
        with self.profile("database_ms"):
            raw = self.pg(f"begin; set local role authenticated; set local request.jwt.claim.sub = '{REVIEWER}'; "
                          f"select reivro_checks_api.read_run(101, '{run_id}'); commit;")
        return json.loads(raw) if raw else None

    def transport(self, method, url, headers, payload=None, **kwargs):
        if url == f"https://{REF}.supabase.co/rest/v1/rpc/dispatch" and method == "POST":
            assert headers["Authorization"] == "Bearer fixture-worker"
            with self.profile("database_ms"):
                return rpc(self.pg, WORKER, payload["action"], payload["request"])
        if url == f"https://{REF}.supabase.co/rest/v1/rpc/read_run" and method == "POST":
            assert payload["p_repository_id"] == 101
            return self.read_run(payload["p_run_id"])
        if method != "GET" or url.endswith("/check-runs"):
            pytest.fail("Unexpected outbound operation in dry-run benchmark")
        if f"/contents/{checks.ARTIFACT}?" in url:
            if self.case["fault"] == "missing_artifact":
                raise checks.ProviderHTTPError(404)
            if self.case["fault"] == "provider_503":
                raise checks.ProviderHTTPError(503)
        return self.github_response(url)

    def counters(self):
        return tuple(int(value) for value in self.pg(
            "select (select count(*) from reivro_cloud.runs), "
            "(select count(*) from reivro_cloud.findings), (select count(*) from reivro_cloud.events);"
        ).split("|"))

    def analyze(self, signed):
        return checks.analyze(*signed, project=PROJECT, secret=SECRET, memory=self.memory,
                              github=self.github, durable=True)


@contextmanager
def measured_verifier(monkeypatch, fixtures):
    stats = {"verify_wall_ms": 0.0, "verify_cpu_ms": 0.0}
    original = syntax.verify_syntax

    def execute(source, deadline):
        if fixtures.case["fault"] == "executor":
            raise syntax._IsolationUnavailable("Synthetic isolated execution failure")
        return syntax._compile(source, deadline)

    def verify(url, permissions, **kwargs):
        start, cpu = perf_counter_ns(), cpu_seconds()
        try:
            return original(url, permissions, executor=execute)
        finally:
            stats["verify_wall_ms"] += elapsed_ms(start)
            stats["verify_cpu_ms"] += round((cpu_seconds() - cpu) * 1000, 3)

    with monkeypatch.context() as patch:
        patch.setattr(checks, "verify_syntax", verify)
        yield verify, stats


def make_row(case, mode, status, detected, started, stats, effects):
    return {"scenario": case["id"], "mode": mode, "truth": case["truth"], "recurrence": case["recurrence"],
            "status": status, "expected": case["expected"]["ABC".index(mode)], "detected": detected,
            "elapsed_ms": elapsed_ms(started), **stats, "duplicate_effects": effects,
            "human_rework_seconds": None, "correction_attempts": None, "project_recurrence_count": None,
            "resolution_seconds": None}


def verdict(verifier):
    return True if verifier == "REGRESSION_DETECTED" else False if verifier == "PASS" else None


def test_effectiveness_benchmark(monkeypatch, tmp_path, pg):
    output = os.environ.get("REIVRO_BENCHMARK_OUTPUT")
    if not output:
        pytest.skip("Run the opt-in benchmark with the disposable PostgreSQL harness")
    version = int(os.environ.get("REIVRO_BENCHMARK_VERSION", "1"))
    source = MANIFEST.with_name(f"scenarios-v{version}.json").read_bytes()
    manifest = json.loads(source)
    repeats = manifest.get("repetitions", 1)
    cases = [{**case, "pr": case["pr"] + repeat * 1000,
              "id": f"{case['id']}/r{repeat + 1}" if repeats > 1 else case["id"]}
             for repeat in range(repeats) for case in manifest["scenarios"]]
    fixtures = Fixtures(pg)
    monkeypatch.setattr(syntax.github, "fetch_json", fixtures.github_response)
    monkeypatch.setattr(checks, "_request", fixtures.transport)
    op_memory = Memory(tmp_path / "agent-memory", PROJECT.repository)
    op_memory.initialize()
    scope = {"repository_id": PROJECT.repository_id, "reason": "Synthetic benchmark reviewer"}
    rows = []
    seen = {}
    agent_receipts = {}
    proposal = None
    review = None
    for index, case in enumerate(cases):
        fixtures.case = case
        fixtures.profile_ms = dict.fromkeys(fixtures.profile_ms, 0.0)
        rev = fixtures.ids()
        url = f"https://github.com/{PROJECT.repository}/pull/{rev.pr}"
        started = perf_counter_ns()
        rows.append(make_row(case, "A", "ACCEPTED", False, started,
                             {"verify_wall_ms": 0.0, "verify_cpu_ms": 0.0}, 0))
        with measured_verifier(monkeypatch, fixtures) as (verify, stats):
            started = perf_counter_ns()
            try:
                result = verify(url, (checks.GITHUB_READ,))
                outcome = result["status"] if result.get("head_sha") == rev.head_sha else "INCONCLUSIVE"
            except Exception:
                outcome = "HARNESS_ERROR"
            rows.append(make_row(case, "B", outcome, verdict(outcome), started, stats, 0))

        stats = {"verify_wall_ms": 0.0, "verify_cpu_ms": 0.0}
        started = perf_counter_ns()
        try:
            if case["fault"] == "approve":
                rpc(pg, REVIEWER, "confirm", review)
                proposal = rpc(pg, REVIEWER, "propose", review)
                assert sha256(proposal["manifest"].encode()).hexdigest() == proposal["digest"]
                fixtures.artifact = proposal["manifest"].encode()
                decision = {**scope, "subject": proposal["protection_id"], "digest": proposal["digest"]}
                rpc(pg, REVIEWER, "approve", decision)
            if case["fault"] == "revoke":
                rpc(pg, REVIEWER, "revoke", decision)

            signed = seen.setdefault(rev.pr, delivery(rev.pr))
            before = fixtures.counters() if case["fault"] == "replay" else None
            with measured_verifier(monkeypatch, fixtures) as (_, stats):
                started = perf_counter_ns()
                result = fixtures.analyze(signed)
                outcome = result["status"]
                run = fixtures.read_run(result["run_id"])
                verifier = ((run["run"].get("report") or {}).get("status") if run else None)
                if case["id"].split("/")[0] in {"novel", "seed"} and run and run["findings"]:
                    review = {**scope, "subject": run["findings"][0]["id"]}
                deliverable = (outcome in {"OBSERVED", "PASS", "VIOLATION"} or
                               version == 2 and outcome == "INCONCLUSIVE" and verdict(verifier) is not None)
                if run and deliverable:
                    envelope = agent.validate({"version": 1, "agent": "independent", "project": PROJECT.repository,
                                               "pr": rev.pr, "head_sha": rev.head_sha,
                                               "task_id": str(UUID(int=1)), "event_id": str(UUID(int=index + 1))})
                    options = SimpleNamespace(repository=PROJECT.repository, store=op_memory.directory,
                                              protection=None, cloud_run=result["run_id"],
                                              repository_id=PROJECT.repository_id)
                    db_before_agent = fixtures.profile_ms["database_ms"]
                    with fixtures.profile("agent_io_ms"):
                        report = agent.review(envelope, options, {"REIVRO_STAGING_REF": REF,
                                              "REIVRO_PUBLISHABLE_KEY": "sb_publishable_fixture",
                                              "REIVRO_AGENT_READER_JWT": "fixture-reviewer"})
                        assert report["status"] == outcome
                        assert report["verifier_status"] == verifier
                        assert checked_feedback(op_memory, report, envelope["event_id"]) == report
                    db_during_agent = fixtures.profile_ms["database_ms"] - db_before_agent
                    fixtures.profile_ms["agent_io_ms"] = max(0.0, fixtures.profile_ms["agent_io_ms"] - db_during_agent)
                    agent_receipts[rev.pr] = (envelope, options)
                if case["fault"] == "replay":
                    original, options = agent_receipts[rev.pr]
                    with op_memory.transaction() as db:
                        old_journal = op_memory.history(db, "agent-event-" + original["event_id"])
                    repeated = agent.review(original, options, {})
                    assert repeated.get("reason") == "duplicate_event"
                    with op_memory.transaction() as db:
                        assert op_memory.history(db, "agent-event-" + original["event_id"]) == old_journal
                effects = sum(after - old for after, old in zip(fixtures.counters(), before)) if before else 0
                # A replay is a transport outcome, not a second detection.
                detected = verdict(verifier) if (outcome in {"OBSERVED", "PASS", "VIOLATION"}
                                                or version == 2 and outcome == "INCONCLUSIVE") else None
                row = make_row(case, "C", outcome, detected, started, stats, effects)
                if version == 2:
                    row.update(fixtures.profile_ms, verification_status=result.get("verification_status"),
                               protection_state=result.get("protection_state"),
                               security_decision=result.get("security_decision"))
                    if case["fault"] in {"tampered", "missing_artifact", "provider_503"}:
                        assert row["security_decision"] == "review_required"
                        assert (row["verification_status"] == ("REGRESSION_DETECTED" if case["truth"] else "PASS"))
                        assert bool(run["findings"]) == case["truth"]
                rows.append(row)
        except Exception:
            rows.append(make_row(case, "C", "HARNESS_ERROR", None, started, stats, 0))

    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    assert write_reports(output, {
        "code_sha": sha, "scenario_version": manifest["version"], "seed": manifest["seed"],
        "scenario_sha256": sha256(source).hexdigest(), "compiler": sys.version.split()[0],
        "rules": [checks.RULE, checks.VERIFIER_VERSION],
        "configuration": {"profiles": ["simulated_acceptance", "verify_only", "verify_firewall"],
                          "postgres": pg("show server_version;"),
                          "source": "synthetic GitHub responses and synthetic Auth subjects",
                          "repetitions": repeats, "blocking_exercised": False},
    }, cases, rows)


def test_integrity_reports_unfavorable_rows_and_rejects_missing_rows(tmp_path):
    import csv

    cases = [
        {"id": "positive", "truth": True, "recurrence": True,
         "expected": ["ACCEPTED", "INCONCLUSIVE", "ERROR"]},
        {"id": "negative", "truth": False, "recurrence": False,
         "expected": ["ACCEPTED", "REGRESSION_DETECTED", "PASS"]},
    ]
    rows = []
    for case in cases:
        for mode, status in zip("ABC", case["expected"]):
            rows.append(make_row(case, mode, status, verdict(status) if mode != "A" else False,
                                 perf_counter_ns(), {"verify_wall_ms": 0.0, "verify_cpu_ms": 0.0}, 0))
    assert write_reports(tmp_path, {"code_sha": "fixture"}, cases, rows)
    data = json.loads((tmp_path / "results.json").read_text())
    assert data["summary"]["A"]["fn"] == 1
    assert data["summary"]["B"]["fp"] == 1 and data["summary"]["B"]["abstained_positive"] == 1
    assert data["summary"]["C"]["abstained_positive"] == 1
    assert data["summary"]["C"]["prevention_exercised"] is False
    with (tmp_path / "results.csv").open() as handle:
        assert len(list(csv.DictReader(handle))) == 6
    assert "INCONCLUSIVE" in (tmp_path / "summary.md").read_text()
    with pytest.raises(ValueError, match="every scenario"):
        write_reports(tmp_path, {"code_sha": "fixture"}, cases, rows[:-1])
    rows[2]["status"] = rows[2]["expected"] = "PASS"
    assert not write_reports(tmp_path, {"code_sha": "fixture"}, cases, rows)
    assert not json.loads((tmp_path / "results.json").read_text())["integrity"]

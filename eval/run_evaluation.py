"""Runs eval/qa_test_set.json against a live /query endpoint and scores the agent.

Scoring is behavioral, not string-exact, because the final answer is LLM-generated
prose that legitimately varies in wording:

  - tool_routing_pass: the exact set of tools the agent used matches what a correct
    router should have used for that question.
  - citation_grounding_pass: every expected citation substring (e.g. "Patient P1005",
    a retrieved document name, "OpenFDA") appears in the response's `sources`.
  - answer_grounding_pass: every expected real-world fact (e.g. the patient's actual
    date of birth, medication name, lab test) appears, case-insensitively, somewhere
    in the final answer text. This is a proxy for "did the model actually convey the
    retrieved fact" -- it can under-count a correct-but-oddly-phrased answer, but it
    cannot be fooled by confident-sounding prose that omits the real data.
  - no_crash_pass: got an HTTP 200 with a well-formed response body (or, for
    expect_error cases, degraded gracefully rather than raising a 5xx).

Run: python -m eval.run_evaluation [--base-url http://localhost:8000] [--concurrency 8]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from pathlib import Path
from typing import Any

import httpx

HERE = Path(__file__).parent


def _text_blob(response_json: dict[str, Any]) -> str:
    parts = [response_json.get("answer", "")]
    for source in response_json.get("sources", []):
        parts.append(source.get("source", ""))
        parts.append(source.get("detail", ""))
    return " ".join(parts).lower()


def _citations_blob(response_json: dict[str, Any]) -> str:
    parts = []
    for source in response_json.get("sources", []):
        parts.append(source.get("source", ""))
        parts.append(source.get("detail", ""))
    return " ".join(parts).lower()


async def run_case(client: httpx.AsyncClient, case: dict[str, Any], sem: asyncio.Semaphore) -> dict[str, Any]:
    async with sem:
        started = time.monotonic()
        result: dict[str, Any] = {"id": case["id"], "category": case["category"], "question": case["question"]}
        try:
            resp = await client.post(
                "/query",
                json={"patient_id": case["patient_id"], "question": case["question"]},
                timeout=60.0,
            )
        except Exception as exc:
            result.update(http_status=None, latency_ms=int((time.monotonic() - started) * 1000),
                           no_crash_pass=False, tool_routing_pass=False, citation_grounding_pass=False,
                           answer_grounding_pass=False, error=f"{type(exc).__name__}: {exc}")
            return result

        latency_ms = int((time.monotonic() - started) * 1000)
        result["http_status"] = resp.status_code
        result["latency_ms"] = latency_ms

        if resp.status_code != 200:
            result.update(no_crash_pass=case.get("expect_error", False), tool_routing_pass=False,
                           citation_grounding_pass=False, answer_grounding_pass=False,
                           error=f"HTTP {resp.status_code}: {resp.text[:200]}")
            return result

        body = resp.json()
        result["no_crash_pass"] = True
        result["actual_tools"] = body.get("tools_used", [])
        result["actual_errors"] = body.get("errors", [])
        result["answer_preview"] = (body.get("answer", "") or "")[:300]

        result["tool_routing_pass"] = sorted(result["actual_tools"]) == sorted(case["expected_tools"])

        citations_blob = _citations_blob(body)
        result["citation_grounding_pass"] = all(
            sub.lower() in citations_blob for sub in case.get("expected_citation_substrings", [])
        ) if case.get("expected_citation_substrings") else True

        answer_blob = _text_blob(body)
        result["answer_grounding_pass"] = all(
            sub.lower() in answer_blob for sub in case.get("expected_fact_substrings", [])
        ) if case.get("expected_fact_substrings") else True

        return result


async def run_all(cases: list[dict[str, Any]], base_url: str, concurrency: int) -> list[dict[str, Any]]:
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(base_url=base_url) as client:
        tasks = [run_case(client, case, sem) for case in cases]
        results = []
        for i, coro in enumerate(asyncio.as_completed(tasks), start=1):
            r = await coro
            results.append(r)
            print(f"[{i}/{len(cases)}] {r['id']} ({r['category']}) "
                  f"tools={r.get('tool_routing_pass')} cite={r.get('citation_grounding_pass')} "
                  f"fact={r.get('answer_grounding_pass')} {r.get('latency_ms')}ms")
    results.sort(key=lambda r: r["id"])
    return results


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(results)
    def rate(key: str) -> float:
        return round(100 * sum(1 for r in results if r.get(key)) / n, 1)

    by_category: dict[str, dict[str, Any]] = {}
    for r in results:
        cat = by_category.setdefault(r["category"], {"n": 0, "tools": 0, "cite": 0, "fact": 0, "crash": 0})
        cat["n"] += 1
        cat["tools"] += bool(r.get("tool_routing_pass"))
        cat["cite"] += bool(r.get("citation_grounding_pass"))
        cat["fact"] += bool(r.get("answer_grounding_pass"))
        cat["crash"] += bool(r.get("no_crash_pass"))

    latencies = [r["latency_ms"] for r in results if r.get("latency_ms") is not None]
    failures = [r for r in results if not (r.get("tool_routing_pass") and r.get("citation_grounding_pass")
                                            and r.get("answer_grounding_pass") and r.get("no_crash_pass"))]

    return {
        "total_cases": n,
        "overall_pass_rate": round(100 * sum(
            1 for r in results
            if r.get("tool_routing_pass") and r.get("citation_grounding_pass")
            and r.get("answer_grounding_pass") and r.get("no_crash_pass")
        ) / n, 1),
        "no_crash_pass_rate": rate("no_crash_pass"),
        "tool_routing_pass_rate": rate("tool_routing_pass"),
        "citation_grounding_pass_rate": rate("citation_grounding_pass"),
        "answer_grounding_pass_rate": rate("answer_grounding_pass"),
        "latency_ms": {
            "mean": round(statistics.mean(latencies), 1) if latencies else None,
            "median": round(statistics.median(latencies), 1) if latencies else None,
            "p95": round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 1) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "by_category": {
            cat: {
                "n": v["n"],
                "tool_routing_pass_rate": round(100 * v["tools"] / v["n"], 1),
                "citation_grounding_pass_rate": round(100 * v["cite"] / v["n"], 1),
                "answer_grounding_pass_rate": round(100 * v["fact"] / v["n"], 1),
            }
            for cat, v in sorted(by_category.items())
        },
        "failure_count": len(failures),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--test-set", default=str(HERE / "qa_test_set.json"))
    parser.add_argument("--out", default=str(HERE / "eval_results.json"))
    args = parser.parse_args()

    test_set = json.loads(Path(args.test_set).read_text(encoding="utf-8"))
    cases = test_set["cases"]

    print(f"Running {len(cases)} cases against {args.base_url} with concurrency={args.concurrency}...")
    started = time.monotonic()
    results = asyncio.run(run_all(cases, args.base_url, args.concurrency))
    elapsed = time.monotonic() - started

    summary = summarize(results)
    summary["elapsed_seconds"] = round(elapsed, 1)

    Path(args.out).write_text(json.dumps({"summary": summary, "results": results}, indent=2), encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"Overall pass rate: {summary['overall_pass_rate']}% ({summary['total_cases']} cases, {elapsed:.1f}s)")
    print(f"  no_crash:  {summary['no_crash_pass_rate']}%")
    print(f"  routing:   {summary['tool_routing_pass_rate']}%")
    print(f"  citations: {summary['citation_grounding_pass_rate']}%")
    print(f"  grounding: {summary['answer_grounding_pass_rate']}%")
    print(f"Results written to {args.out}")


if __name__ == "__main__":
    main()

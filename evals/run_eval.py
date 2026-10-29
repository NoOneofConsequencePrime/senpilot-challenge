"""Intent eval: runs messy, realistic emails through the real DeepSeek parser and scores the result.

Usage: python evals/run_eval.py [--model deepseek-flash]   (needs DEEPSEEK_API_KEY in .env; costs fractions of a cent)

A case expects either a list of [matter, doc_type, limit, start?] requests (order-insensitive), "clarify" (no
requests, a question for the user), or "clarify-or-any-valid" (anything schema-valid is acceptable).
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from uarb_agent.intent import IntentError, IntentParser

CASES = Path(__file__).with_name("intent_cases.json")


class EvalEnv(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    deepseek_api_key: str
    deepseek_model: str = "deepseek-flash"
    deepseek_base_url: str = "https://api.deepseek.com"


def score(expect, parsed) -> bool:
    if expect == "clarify":
        return not parsed.requests and bool(parsed.clarification_needed)
    if expect == "clarify-or-any-valid":
        return True
    got = sorted((r.matter, r.doc_type.value, r.limit, r.start) for r in parsed.requests)
    want = sorted((e[0], e[1], e[2], e[3] if len(e) > 3 else 1) for e in expect)
    return got == want


def main() -> None:
    env = EvalEnv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=env.deepseek_model)
    model = ap.parse_args().model
    parser = IntentParser(env.deepseek_api_key, model, env.deepseek_base_url, max_requests=3)
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    passed, latencies = 0, []
    for case in cases:
        t0 = time.time()
        try:
            parsed = parser.parse(case["email"], [tuple(h) for h in case.get("history", [])])
            ok, detail = score(case["expect"], parsed), parsed.model_dump(mode="json", exclude={"notes"})
        except IntentError as exc:
            ok, detail = False, f"IntentError: {exc}"
        latencies.append(time.time() - t0)
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {latencies[-1]:4.1f}s  {case['name']:<32} {'' if ok else detail}")
    print(f"\nmodel {model}: {passed}/{len(cases)} passed ({passed / len(cases):.0%}), "
          f"median latency {statistics.median(latencies):.1f}s, max {max(latencies):.1f}s")
    sys.exit(0 if passed == len(cases) else 1)


if __name__ == "__main__":
    main()

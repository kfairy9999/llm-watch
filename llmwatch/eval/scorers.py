"""Scorers return a 0–1 score and a pass bit. Details are stored with the run."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

import jsonschema

from llmwatch.eval.suite import ScorerSpec
from llmwatch.text import extract_json


@dataclass
class ScorerResult:
    type: str
    score: float
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "score": self.score,
            "passed": self.passed,
            "detail": self.detail,
        }


JudgeFn = Callable[[list[dict]], str]


def score_output(spec: ScorerSpec, output: str, *, judge: JudgeFn | None = None) -> ScorerResult:
    if spec.type == "exact":
        return _exact(output, spec)
    if spec.type == "regex":
        return _regex(output, spec)
    if spec.type == "numeric":
        return _numeric(output, spec)
    if spec.type == "json_schema":
        return _json_schema(output, spec)
    if spec.type == "llm_judge":
        return _judge(output, spec, judge)
    raise ValueError(f"unknown scorer {spec.type}")


def _exact(output: str, spec: ScorerSpec) -> ScorerResult:
    expected = spec.expected or ""
    left, right = output.strip(), expected.strip()
    if not spec.case_sensitive:
        left, right = left.casefold(), right.casefold()
    ok = left == right
    detail = "exact match" if ok else f"expected {expected!r}"
    return ScorerResult("exact", 1.0 if ok else 0.0, ok, detail)


def _regex(output: str, spec: ScorerSpec) -> ScorerResult:
    matched = re.search(spec.pattern or "", output) is not None
    ok = (not matched) if spec.forbid else matched
    if spec.forbid:
        detail = "forbidden pattern absent" if ok else f"forbidden pattern matched: {spec.pattern}"
    else:
        detail = "pattern matched" if ok else f"pattern did not match: {spec.pattern}"
    return ScorerResult("regex", 1.0 if ok else 0.0, ok, detail)


def _numeric(output: str, spec: ScorerSpec) -> ScorerResult:
    expected = float(spec.value if spec.value is not None else 0)
    match = re.search(r"-?\d+(?:\.\d+)?", output.replace(",", ""))
    if not match:
        return ScorerResult("numeric", 0.0, False, "no number found")
    value = float(match.group(0))
    ok = abs(value - expected) <= spec.tolerance
    detail = f"parsed {value:g}, expected {expected:g} ± {spec.tolerance:g}"
    return ScorerResult("numeric", 1.0 if ok else 0.0, ok, detail)


def _json_schema(output: str, spec: ScorerSpec) -> ScorerResult:
    import json

    raw = extract_json(output)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return ScorerResult("json_schema", 0.0, False, f"invalid JSON: {exc.msg}")
    try:
        jsonschema.validate(data, spec.json_schema or {})
    except jsonschema.ValidationError as exc:
        return ScorerResult("json_schema", 0.0, False, exc.message)
    return ScorerResult("json_schema", 1.0, True, "valid")


def _judge(output: str, spec: ScorerSpec, judge: JudgeFn | None) -> ScorerResult:
    if spec.mode == "mock":
        return _mock_judge(output, spec)
    if judge is None:
        return ScorerResult(
            "llm_judge",
            0.0,
            False,
            "live judge requested but no judge function was provided",
        )
    return _live_judge(output, spec, judge)


def _mock_judge(output: str, spec: ScorerSpec) -> ScorerResult:
    """Offline heuristic. Keyword coverage plus a length floor. Not a model."""
    text = output.lower()
    keywords = spec.keywords
    if keywords:
        hits = [keyword for keyword in keywords if keyword.lower() in text]
        coverage = len(hits) / len(keywords)
        hit_text = ", ".join(hits) if hits else "none"
        detail = f"mock judge: {len(hits)}/{len(keywords)} keywords ({hit_text})"
    else:
        coverage = 1.0 if len(output.strip()) >= spec.min_chars else 0.0
        detail = "mock judge: length floor"
    length_factor = min(1.0, len(output.strip()) / max(spec.min_chars, 1))
    score = round(0.8 * coverage + 0.2 * length_factor, 4)
    passed = score >= spec.pass_threshold
    return ScorerResult(
        "llm_judge",
        score,
        passed,
        detail + " — offline heuristic, not a model",
    )


def _live_judge(output: str, spec: ScorerSpec, judge: JudgeFn) -> ScorerResult:
    import json

    messages = [
        {
            "role": "system",
            "content": (
                'You are a strict grader. Return JSON {"score": <number from 0 to 1>, "reason": "<short>"} '
                "and nothing else."
            ),
        },
        {"role": "user", "content": f"Rubric:\n{spec.rubric}\n\nOutput:\n{output}"},
    ]
    try:
        text = judge(messages)
        parsed = json.loads(extract_json(text))
        score = max(0.0, min(1.0, float(parsed["score"])))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return ScorerResult("llm_judge", 0.0, False, f"judge response was not usable: {exc}")
    reason = str(parsed.get("reason") or "").strip()
    detail = f"live judge: {reason}" if reason else "live judge"
    return ScorerResult("llm_judge", round(score, 4), score >= spec.pass_threshold, detail)

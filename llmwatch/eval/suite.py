"""Load a YAML eval suite and scripted fixture outputs."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

BUNDLED_DIR = Path(__file__).resolve().parent.parent / "suites"


class ScorerSpec(BaseModel):
    type: Literal["exact", "regex", "numeric", "json_schema", "llm_judge"]
    expected: str | None = None
    case_sensitive: bool = True
    pattern: str | None = None
    forbid: bool = False
    value: float | None = None
    tolerance: float = 0
    json_schema: dict | None = None
    mode: Literal["mock", "live"] = "mock"
    rubric: str = ""
    keywords: list[str] = Field(default_factory=list)
    min_chars: int = 40
    pass_threshold: float = 0.7

    @model_validator(mode="after")
    def check(self) -> ScorerSpec:
        if self.type == "exact" and self.expected is None:
            raise ValueError("exact scorer requires expected")
        if self.type == "regex":
            if not self.pattern:
                raise ValueError("regex scorer requires pattern")
            re.compile(self.pattern)
        if self.type == "numeric" and self.value is None:
            raise ValueError("numeric scorer requires value")
        if self.type == "json_schema" and not self.json_schema:
            raise ValueError("json_schema scorer requires json_schema")
        if self.type == "llm_judge" and self.mode == "live" and not self.rubric.strip():
            raise ValueError("live judge requires a rubric")
        if self.type == "llm_judge" and self.mode == "mock" and not self.keywords and self.min_chars <= 0:
            raise ValueError("mock judge needs keywords or min_chars")
        if not 0 <= self.pass_threshold <= 1:
            raise ValueError("pass_threshold must be between 0 and 1")
        return self


class TestCase(BaseModel):
    id: str
    description: str = ""
    system: str | None = None
    prompt: str | None = None
    messages: list[dict] = Field(default_factory=list)
    scorers: list[ScorerSpec]

    @model_validator(mode="after")
    def normalize(self) -> TestCase:
        if not self.messages:
            built: list[dict] = []
            if self.system:
                built.append({"role": "system", "content": self.system})
            if self.prompt:
                built.append({"role": "user", "content": self.prompt.strip()})
            self.messages = built
        if not self.messages:
            raise ValueError(f"test {self.id} needs messages or prompt")
        if not self.scorers:
            raise ValueError(f"test {self.id} needs at least one scorer")
        return self


class GateSpec(BaseModel):
    fail_on_pass_flip: bool = True
    fail_on_significant_regression: bool = True
    delta_threshold: float = 0.0


class SuiteSpec(BaseModel):
    name: str
    description: str = ""
    system: str | None = None
    gate: GateSpec = Field(default_factory=GateSpec)
    tests: list[TestCase]

    @model_validator(mode="after")
    def unique_tests(self) -> SuiteSpec:
        ids = [test.id for test in self.tests]
        if not ids:
            raise ValueError("suite has no tests")
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate test ids")
        return self


def bundled_suite(name: str) -> Path:
    path = BUNDLED_DIR / f"{name}.yaml"
    if not path.exists():
        known = sorted(item.stem for item in BUNDLED_DIR.glob("*.yaml") if not item.stem.endswith("_outputs"))
        raise FileNotFoundError(f"no bundled suite {name!r}. Known: {', '.join(known) or 'none'}")
    return path


def bundled_fixtures(name: str) -> Path:
    path = BUNDLED_DIR / f"{name}_outputs.yaml"
    if not path.exists():
        raise FileNotFoundError(f"no bundled fixtures for {name!r}")
    return path


def load_suite(path: str | Path) -> tuple[SuiteSpec, str]:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    suite = SuiteSpec.model_validate(data)
    if suite.system:
        for test in suite.tests:
            if not any(message.get("role") == "system" for message in test.messages):
                test.messages.insert(0, {"role": "system", "content": suite.system})
    fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return suite, fingerprint


def load_fixtures(path: str | Path) -> dict[str, dict[str, str]]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("fixture file must be a mapping of model to test outputs")
    fixtures: dict[str, dict[str, str]] = {}
    for model, tests in data.items():
        if not isinstance(tests, dict):
            raise ValueError(f"fixture outputs for {model} must be a mapping of test id to text")
        fixtures[str(model)] = {str(test_id): str(output).strip() for test_id, output in tests.items()}
    return fixtures


def assert_fixture_covers(suite: SuiteSpec, fixtures: dict[str, dict[str, str]], models: list[str]) -> None:
    missing: list[str] = []
    for model in models:
        outputs = fixtures.get(model, {})
        for test in suite.tests:
            if test.id not in outputs:
                missing.append(f"{model}:{test.id}")
    if missing:
        raise ValueError("fixture is missing outputs for " + ", ".join(missing))

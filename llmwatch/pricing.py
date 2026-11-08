"""Configurable USD price table. Rates are per one million tokens."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from llmwatch.notice import PRICE_NOTE


@dataclass(frozen=True)
class Rates:
    input: float
    output: float


class PriceTable:
    def __init__(self, models: dict[str, Rates], default: Rates, note: str):
        self.models = models
        self.default = default
        self.note = note

    @classmethod
    def from_dict(cls, data: dict) -> PriceTable:
        if "default" not in data or "models" not in data:
            raise ValueError("price table needs 'models' and 'default'")
        models = {name: _rates(name, raw) for name, raw in data["models"].items()}
        return cls(
            models=models,
            default=_rates("default", data["default"]),
            note=str(data.get("note") or PRICE_NOTE),
        )

    def resolve(self, model: str) -> tuple[Rates, str]:
        if model in self.models:
            return self.models[model], "table"
        return self.default, "default"

    def compute_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> tuple[float, str]:
        rates, source = self.resolve(model)
        cost = (prompt_tokens * rates.input + completion_tokens * rates.output) / 1_000_000
        return cost, source

    def public_dict(self) -> dict:
        return {
            "unit": "USD_per_1M_tokens",
            "note": self.note,
            "default": {"input": self.default.input, "output": self.default.output},
            "models": {
                name: {"input": rates.input, "output": rates.output}
                for name, rates in self.models.items()
            },
        }


def _rates(name: str, raw: dict) -> Rates:
    try:
        incoming = float(raw["input"])
        outgoing = float(raw["output"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"price table entry {name!r} needs numeric input and output") from exc
    if incoming < 0 or outgoing < 0:
        raise ValueError(f"negative price for {name}")
    return Rates(input=incoming, output=outgoing)


def load_price_table(path: str | Path | None = None) -> PriceTable:
    if path is None:
        env = os.environ.get("LLMWATCH_PRICES")
        path = Path(env) if env else Path(__file__).with_name("prices.default.json")
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return PriceTable.from_dict(data)

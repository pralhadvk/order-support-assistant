"""Central configuration. Values that affect behaviour live here so tests and evals are deterministic."""

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    # LLM via OpenRouter (OpenAI-compatible API)
    openrouter_api_key: str | None = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY"))
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    orchestrator_model: str = field(
        # Pinned snapshot: 63/63 scenario runs (evals/results/final_eval.md); matched Sonnet 5.5 on the
        # model comparison at ~1/39th of the cost (evals/results/model_comparison_final.md).
        default_factory=lambda: os.getenv("ORCHESTRATOR_MODEL", "deepseek/deepseek-v4.1-flash-1017")
    )
    temperature: float = 0.0
    max_output_tokens: int = 1024

    # Retrieval
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    reranker_model: str = "BAAI/bge-reranker-base"
    retrieve_top_k: int = 8
    rerank_top_n: int = 3

    # Simulated world: fixed clock and authenticated customer, so timeline and
    # ownership decisions are reproducible.
    now: datetime = datetime(2026, 9, 27, 10, 0, tzinfo=timezone.utc)
    session_customer_id: str = "CUST-001"

    # Escalation: write actions on orders above this amount (Rs) go to a human instead of executing.
    high_value_threshold: float = 25000.0
    # Failed commerce calls (each already retried once) before the circuit opens and the turn escalates.
    max_tool_failures: int = 1

    data_dir: Path = ROOT / "data"
    log_dir: Path = ROOT / "logs"


settings = Settings()

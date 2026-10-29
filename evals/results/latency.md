# Latency breakdown: `deepseek/deepseek-v4.1-flash-1017`

78 turns from deepseek__deepseek-v4.1-flash-1017.jsonl.

| Stage | Median ms/turn | p90 ms/turn | Share of total time |
|---|---|---|---|
| llm | 5712 | 9961 | 97.8% |
| retrieve | 51 | 102 | 0.7% |
| rerank | 112 | 195 | 1.4% |
| commerce_tools | 0 | 0 | 0.1% |
| other (guardrails, grounding check, orchestration) | 0 | 1 | 0.0% |
| **total** | **5909** | **10109** | 100% |

- LLM calls per turn: median 2, max 5
- Latency per LLM call: median 2434 ms, p90 3919 ms
- LLM cost per turn: mean $0.00034, p90 $0.00056
- Projected LLM cost per 100k turns: $34

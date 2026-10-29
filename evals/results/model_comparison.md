# Model comparison

Simulated now: 2026-09-27 10:00 UTC. One run per scenario (temperature 0).

| Model | Scenarios passed | Checks failed | Grounded 1st try | Median s/turn | p90 s/turn | Avg LLM calls/turn | Cost/turn (USD) |
|---|---|---|---|---|---|---|---|
| `anthropic/claude-haiku-5.5` | 14/16 | 2 | 19/19 | 4.4 | 8.7 | 2.6 | 0.00098 |
| `openai/gpt-6-luna` | 14/16 | 2 | 19/19 | 6.6 | 12.5 | 2.6 | 0.00022 |
| `deepseek/deepseek-v4.1-flash` | 16/16 | 0 | 19/19 | 3.7 | 6.1 | 2.5 | 0.00040 |
| `qwen/qwen3.8-flash` | 14/16 | 2 | 18/18 | 12.7 | 19.4 | 2.4 | 0.00044 |
| `z-ai/glm-5.3-flash` | 14/16 | 3 | 19/19 | 7.8 | 14.0 | 2.2 | 0.00034 |
| `google/gemini-3.5-flash-lite` | 13/16 | 5 | 19/19 | 4.0 | 6.8 | 2.4 | 0.00124 |

## Per-scenario results

| Scenario | `claude-haiku-5.5` | `gpt-6-luna` | `deepseek-v4.1-flash` | `qwen3.8-flash` | `glm-5.3-flash` | `gemini-3.5-flash-lite` |
|---|---|---|---|---|---|---|
| refund_return_received | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| pure_rag_order_limit | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| chargeback_without_order_id | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ |
| password_reset_out_of_scope_action | ✓ | ✓ | ✓ | ✓ | ✓ | ✗ |
| injection_refund | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| trap_failed_payment | ✗ | ✓ | ✓ | ✓ | ✓ | ✓ |
| both_policy_and_status | ✓ | ✓ | ✓ | ✓ | ✗ | ✓ |
| reversal_not_yet_due | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| international_return | ✓ | ✓ | ✓ | ✗ | ✓ | ✓ |
| other_customers_order | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| tool_timeout | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| unrelated_request | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| return_with_confirmation | ✓ | ✗ | ✓ | ✓ | ✓ | ✗ |
| human_request | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| high_value_return | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| pii_in_message | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

## Failures

- `anthropic/claude-haiku-5.5` / chargeback_without_order_id turn 1: missing citation DOC-7
- `anthropic/claude-haiku-5.5` / trap_failed_payment turn 1: should not cite DOC-1
- `openai/gpt-6-luna` / chargeback_without_order_id turn 3: reply lacks any of ['dsp-']
- `openai/gpt-6-luna` / return_with_confirmation turn 2: reply lacks any of ['case-']
- `qwen/qwen3.8-flash` / chargeback_without_order_id turn 1: missing citation DOC-7
- `qwen/qwen3.8-flash` / international_return turn 1: exception: RateLimitError('Error code: 429 - Provider returned error')
- `z-ai/glm-5.3-flash` / chargeback_without_order_id turn 1: missing citation DOC-7
- `z-ai/glm-5.3-flash` / both_policy_and_status turn 1: expected search_policy to be called; missing citation DOC-2
- `google/gemini-3.5-flash-lite` / chargeback_without_order_id turn 1: missing citation DOC-2; missing citation DOC-7
- `google/gemini-3.5-flash-lite` / password_reset_out_of_scope_action turn 1: missing citation DOC-4; reply lacks any of ['app']
- `google/gemini-3.5-flash-lite` / return_with_confirmation turn 2: reply lacks any of ['case-']

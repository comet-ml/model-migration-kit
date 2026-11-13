# OpenAI API: gpt-5 and o3 (Dec 11, 2026), gpt-4o and gpt-4.1 (Jan 14, 2027)

**What happens:** shutoff. Requests to these models fail after the date. Source: [OpenAI deprecations](https://developers.openai.com/api/docs/deprecations) (checked 2026-11-13).

| Model | Shutdown | Replacement |
|---|---|---|
| `gpt-5`, `o3` | Dec 11, 2026 | `gpt-6.1-sol` |
| `gpt-5-pro`, `o3-pro` | Dec 11, 2026 | `gpt-6.1-sol` with `reasoning.mode: pro` (Responses API) |
| `gpt-5-mini` | Dec 11, 2026 | `gpt-6.1-terra` |
| `gpt-5-nano` | Dec 11, 2026 | `gpt-6-luna` |
| `gpt-4o-2024-08-06`, `gpt-4o-2024-11-20`, `gpt-4o-mini-2024-07-18`, `gpt-4.1-2025-04-14`, `gpt-4.1-mini-2025-04-14` | Jan 14, 2027 | `gpt-6-luna` |

Azure OpenAI runs on its own dates: the o-series retires Nov 19, 2026 (replacements `gpt-5.6-sol` / `gpt-5.6-terra`), `gpt-4o` 2024-05-13 on Jan 14, 2027, and `gpt-4o` 2024-08-06 and 2024-11-20 on Apr 14, 2027 ([Azure model retirements](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/concepts/model-retirements)).

**What the replacement changes that matters** (from [OpenAI's latest-model guide](https://developers.openai.com/api/docs/guides/latest-model)):

- Remove `temperature`, `top_p` and `top_logprobs` when reasoning effort isn't `none`.
- Sol does not support effort `none`; use `low`.
- Tool calling needs the Responses API on Sol and Terra.

**Check your request parameters first:**

```bash
uv run python -m kit.params --model openai/gpt-6.1-sol --params '{"temperature": 0.2, "reasoning_effort": "none"}'
```

**Compare before the date** (needs `OPENAI_API_KEY`; this path is tested with mocks only, not a live run):

```bash
uv run python -m kit.compare --cases your_requests.jsonl \
  --old openai/gpt-5 --new openai/gpt-6.1-sol --judge gemini/gemini-3.8-flash
```

Calls that fail on the new model (a parameter it rejects, say) are recorded per case as "failed on new model", not a crash.

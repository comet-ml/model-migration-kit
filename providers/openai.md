# OpenAI API: gpt-5 and o3 (Dec 11, 2026), gpt-4o and gpt-4.1 (Jan 14, 2027)

**What happens:** shutoff. Requests to these models fail after the date. Source: [OpenAI deprecations](https://developers.openai.com/api/docs/deprecations) (checked 2026-11-13).

<!-- retirements:start -->
| Model | Provider | Date | What happens | Replacement | Source (checked) |
|---|---|---|---|---|---|
| `o-series` | azure-openai | Nov 19, 2026 | requests fail | `gpt-5.6-sol / gpt-5.6-terra` | [link](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule) (2026-11-13) |
| `gpt-5` | openai | Dec 11, 2026 | requests fail | `gpt-6.1-sol` | [link](https://developers.openai.com/api/docs/deprecations) (2026-11-13) |
| `gpt-5-pro` | openai | Dec 11, 2026 | requests fail | `gpt-6.1-sol (reasoning.mode: pro, Responses API)` | [link](https://developers.openai.com/api/docs/deprecations) (2026-11-13) |
| `gpt-5-mini` | openai | Dec 11, 2026 | requests fail | `gpt-6.1-terra` | [link](https://developers.openai.com/api/docs/deprecations) (2026-11-13) |
| `gpt-5-nano` | openai | Dec 11, 2026 | requests fail | `gpt-6-luna` | [link](https://developers.openai.com/api/docs/deprecations) (2026-11-13) |
| `o3` | openai | Dec 11, 2026 | requests fail | `gpt-6.1-sol` | [link](https://developers.openai.com/api/docs/deprecations) (2026-11-13) |
| `o3-pro` | openai | Dec 11, 2026 | requests fail | `gpt-6.1-sol (reasoning.mode: pro, Responses API)` | [link](https://developers.openai.com/api/docs/deprecations) (2026-11-13) |
| `gpt-4o-2024-08-06` | openai | Jan 14, 2027 | requests fail | `gpt-6-luna` | [link](https://developers.openai.com/api/docs/deprecations) (2026-11-13) |
| `gpt-4o-2024-11-20` | openai | Jan 14, 2027 | requests fail | `gpt-6-luna` | [link](https://developers.openai.com/api/docs/deprecations) (2026-11-13) |
| `gpt-4o-mini-2024-07-18` | openai | Jan 14, 2027 | requests fail | `gpt-6-luna` | [link](https://developers.openai.com/api/docs/deprecations) (2026-11-13) |
| `gpt-4.1-2025-04-14` | openai | Jan 14, 2027 | requests fail | `gpt-6-luna` | [link](https://developers.openai.com/api/docs/deprecations) (2026-11-13) |
| `gpt-4.1-mini-2025-04-14` | openai | Jan 14, 2027 | requests fail | `gpt-6-luna` | [link](https://developers.openai.com/api/docs/deprecations) (2026-11-13) |
| `gpt-4o (2024-05-13)` | azure-openai | Jan 14, 2027 | Global Standard and Data Zone Standard deployments auto-upgrade to gpt-5.1; Provisioned deployments and ones set to NoAutoUpgrade stop working | `gpt-5.1` | [link](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule) (2026-11-13) |
| `gpt-4o (2024-08-06, 2024-11-20)` | azure-openai | Apr 14, 2027 | requests fail | `gpt-5.1` | [link](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule) (2026-11-13) |
<!-- retirements:end -->

Azure OpenAI runs on its own dates (rows above marked azure-openai). One `gpt-4o` version depends on the deployment: Global Standard and Data Zone Standard deployments of 2024-05-13 auto-upgrade to `gpt-5.1`, which is a model change with no error, so compare before it happens. Compare an Azure deployment with `--old azure/<your-deployment>` (needs `AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_API_VERSION`).

**What the replacement changes that matters** (from [OpenAI's latest-model guide](https://developers.openai.com/api/docs/guides/latest-model)):

- Remove `temperature`, `top_p` and `top_logprobs` when reasoning effort isn't `none`.
- Sol does not support effort `none`; use `low`.
- Tool calling needs the Responses API on Sol and Terra.

**Check your request parameters first:**

```bash
uv run python -m kit.params --model openai/gpt-6.1-sol --params '{"temperature": 0.2, "reasoning_effort": "none"}'
```

**What we saw (Nov 13, 2026, the 30 sample requests, judge `gemini/gemini-3.8-flash`):** `gpt-5` → `gpt-6.1-sol` changed meaning on 10 of 30 answers, and `gpt-5` against itself also changed on 10, so on this app the switch was inside run-to-run noise. The judge split (old 8, same 11, new 11). Median response time went from 12.13s to 2.43s and estimated model cost from $0.2157 to $0.0385. Neither model followed the fake system note. One change to look for: on "When do I get my money?", `gpt-6.1-sol` dropped the condition that the refund starts once the return is received. Full run: `uv run python -m kit.compare --cases examples/support-bot/cases.jsonl --system examples/support-bot/system_prompt.md --old openai/gpt-5 --new openai/gpt-6.1-sol --params '{"max_tokens": 4096}' --noise-floor`.

**Compare before the date** (needs `OPENAI_API_KEY`; the judge defaults to a model from a provider you have a key for, or pass `--judge`.):

```bash
uv run python -m kit.compare --cases your_requests.jsonl \
  --old openai/gpt-5 --new openai/gpt-6.1-sol
```

Calls that fail on the new model (a parameter it rejects, say) are recorded per case as "failed on new model", not a crash.

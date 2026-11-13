# Claude API: claude-sonnet-4-5, Nov 30, 2026

**What happens:** shutoff. `claude-sonnet-4-5-20250929` retires on Nov 30, 2026, and requests to retired models fail. Replacement: `claude-sonnet-5-5`. Source: [Anthropic model deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations) (checked 2026-11-13). On Amazon Bedrock, Sonnet 4.5 went legacy on Oct 8, 2026 and reaches end of life on Apr 8, 2027; AWS lists no replacement and says migration won't happen automatically ([Bedrock legacy models](https://docs.aws.amazon.com/bedrock/latest/userguide/model-lifecycle-legacy.html)).

<!-- retirements:start -->
| Model | Provider | Date | What happens | Replacement | Source (checked) |
|---|---|---|---|---|---|
| `claude-sonnet-4-5-20250929` | anthropic | Nov 30, 2026 | requests fail | `claude-sonnet-5-5` | [link](https://platform.claude.com/docs/en/about-claude/model-deprecations) (2026-11-13) |
| `claude-sonnet-4-5 (Bedrock)` | bedrock | Apr 8, 2027 | requests fail | `not announced as of 2026-11-13` | [link](https://docs.aws.amazon.com/bedrock/latest/userguide/model-lifecycle-legacy.html) (2026-11-13) |
<!-- retirements:end -->

**What the replacement changes that matters** (from the [Sonnet 5.5 migration guide](https://platform.claude.com/docs/en/models/sonnet-5-5/migration-guide)). These return HTTP 400 on `claude-sonnet-5-5`:

- thinking budgets (`thinking.budget_tokens`)
- `thinking: {"type": "disabled"}`
- `temperature`, `top_p`, `top_k`
- assistant prefill (a request that ends on an assistant turn)
- forced `tool_choice`

Also: `output_format` becomes `output_config.format`, and the same text uses about 30% more tokens, so recheck `max_tokens` and cost.

**Check your request parameters first:**

```bash
uv run python -m kit.params --model anthropic/claude-sonnet-5-5 \
  --params '{"temperature": 0.2, "thinking": {"type": "enabled", "budget_tokens": 2048}}'
```

**What we saw (Nov 13, 2026, the 30 sample requests, judge `gemini/gemini-3.8-flash`):** with `temperature 0.2` in the request, all 5 requests sent to `claude-sonnet-5-5` failed ("does not support temperature=0.2. Only temperature=1 is supported"; LiteLLM refuses it before sending, and the API returns a 400). With `temperature` removed, all 30 ran: 7 of 30 answers changed meaning, against 4 for `claude-sonnet-4-5` against itself; the judge preferred the new model on 19 (old 3, same 8). Median response time went from 2.62s to 2.00s, and estimated model cost stayed about the same ($0.0843 → $0.0828) despite the extra tokens. Neither model followed the fake system note; Sonnet 5.5 named it and said it couldn't override policy.

**Compare before the date** (needs `ANTHROPIC_API_KEY`; the judge defaults to a model from a provider you have a key for, or pass `--judge`.). Send the parameters your app sends today; any that the new model rejects show up as "failed on new model":

```bash
uv run python -m kit.compare --cases your_requests.jsonl \
  --old anthropic/claude-sonnet-4-5-20250929 --new anthropic/claude-sonnet-5-5 \
  --params '{"max_tokens": 2048}'
```

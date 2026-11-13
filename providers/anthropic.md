# Claude API: claude-sonnet-4-5, Nov 30, 2026

**What happens:** shutoff. `claude-sonnet-4-5-20250929` retires on Nov 30, 2026, and requests to retired models fail. Replacement: `claude-sonnet-5-5`. Source: [Anthropic model deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations) (checked 2026-11-13). On Amazon Bedrock, Sonnet 4.5 reaches end of life on Apr 8, 2027 ([Bedrock model lifecycle](https://docs.aws.amazon.com/bedrock/latest/userguide/model-lifecycle.html)).

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

**Compare before the date** (needs `ANTHROPIC_API_KEY`; this path is tested with mocks only, not a live run). Send the parameters your app sends today; any that the new model rejects show up as "failed on new model":

```bash
uv run python -m kit.compare --cases your_requests.jsonl \
  --old anthropic/claude-sonnet-4-5-20250929 --new anthropic/claude-sonnet-5-5 \
  --judge gemini/gemini-3.8-flash --params '{"max_tokens": 2048}'
```

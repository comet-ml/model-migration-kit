# Gemini API: gemini-2.5-flash and gemini-2.5-pro, Dec 1, 2026

**What happens:** a reroute, not a shutoff. From Dec 1, 2026, Gemini API requests to `gemini-2.5-flash` are answered by `gemini-3.5-flash-lite`, and requests to `gemini-2.5-pro` by `gemini-3.8-flash`, billed at the new model's rates. Your code keeps working; the answers change. `gemini-2.5-flash-lite` is not affected. Source: [Gemini API deprecations](https://ai.google.dev/gemini-api/docs/deprecations) (checked 2026-11-13). Whether the same reroute applies on Vertex AI: [check].

**What the replacement changes that matters** (for `gemini-3.8-flash`, from [What's new in Gemini 3.8](https://aistudio.google.com/docs/whats-new-gemini-3.8)):

- `thinking_budget` is replaced by `thinking_level`; `thinking_level: minimal` errors on 3.8 Flash.
- Remove `temperature`, `top_p`, `top_k` and `candidate_count`.
- Remove prefilled model turns.

For `gemini-3.5-flash-lite` we found no sourced migration notes. In our run LiteLLM printed: "`temperature`, `top_p`, and `top_k` continue to function for Gemini 3+ (gemini-3.5-flash-lite) but are planned for removal in a future release."

**Check your request parameters first:**

```bash
uv run python -m kit.params --model gemini/gemini-3.8-flash --params '{"temperature": 0.2, "thinking_budget": 1024}'
```

**Compare before the date:**

```bash
uv run python -m kit.compare --cases your_requests.jsonl \
  --old gemini/gemini-2.5-flash --new gemini/gemini-3.5-flash-lite \
  --params '{"temperature": 0.2, "max_tokens": 1024}'

uv run python -m kit.compare --cases your_requests.jsonl \
  --old gemini/gemini-2.5-pro --new gemini/gemini-3.8-flash --judge gemini/gemini-3.5-flash
```

Pick a judge that is neither the old nor the new model (`--judge`).

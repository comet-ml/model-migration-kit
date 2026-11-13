# Model migration kit

All these models are retiring soon. This is a test suite to help you make the migration without breaking your app.

<!-- retirements:start -->
| Model | Provider | Date | What happens | Replacement | Source (checked) |
|---|---|---|---|---|---|
| `o-series` | azure-openai | Nov 19, 2026 | requests fail | `gpt-5.6-sol / gpt-5.6-terra` | [link](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule) (2026-11-13) |
| `claude-sonnet-4-5-20250929` | anthropic | Nov 30, 2026 | requests fail | `claude-sonnet-5-5` | [link](https://platform.claude.com/docs/en/about-claude/model-deprecations) (2026-11-13) |
| `gemini-2.5-pro` | gemini | Dec 1, 2026 | requests rerouted to the replacement | `gemini-3.8-flash` | [link](https://aistudio.google.com/docs/deprecations) (2026-11-13) |
| `gemini-2.5-flash` | gemini | Dec 1, 2026 | requests rerouted to the replacement | `gemini-3.5-flash-lite` | [link](https://aistudio.google.com/docs/deprecations) (2026-11-13) |
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
| `claude-sonnet-4-5 (Bedrock)` | bedrock | Apr 8, 2027 | requests fail | `not announced as of 2026-11-13` | [link](https://docs.aws.amazon.com/bedrock/latest/userguide/model-lifecycle-legacy.html) (2026-11-13) |
| `gpt-4o (2024-08-06, 2024-11-20)` | azure-openai | Apr 14, 2027 | requests fail | `gpt-5.1` | [link](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule) (2026-11-13) |
<!-- retirements:end -->

Dates come from each provider's deprecations page, checked on the date shown, and live in [`kit/retirements.yaml`](kit/retirements.yaml). Provider notes: [Gemini](providers/gemini.md), [OpenAI and Azure OpenAI](providers/openai.md), [Anthropic and Bedrock](providers/anthropic.md). Wrong or missing date? [Open an issue](https://github.com/comet-ml/model-migration-kit/issues/new/choose).

## What it does

It sends the same requests to the old and new model, logs both runs to [Opik](https://github.com/comet-ml/opik) as experiments, and writes a report of what changed:

- requests that fail on the new model, such as a `temperature` it no longer accepts
- JSON that no longer parses, or is missing fields your app reads
- answers that switched between answering and refusing
- answers whose format changed, or whose length changed by more than 50%
- answers that changed meaning: a different fact, decision, action or promise, decided by one LLM judge

Then you turn what you find into tests that run on every model you try.

It runs on your machine. Requests go to the model providers you pick and to Opik (Opik Cloud, or self-hosted). `--no-opik` keeps everything off Opik and writes only the report.

## Quickstart

Needs [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```bash
git clone https://github.com/comet-ml/model-migration-kit.git
cd model-migration-kit
cp .env.example .env
```

In `.env`, set one model key (`GEMINI_API_KEY`, `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`) and an Opik key (`OPIK_API_KEY`, `OPIK_WORKSPACE`) from a [free Opik Cloud account](https://www.comet.com/signup?utm_source=github&utm_medium=referral&utm_campaign=model-migration-kit&utm_content=readme), or set `OPIK_URL_OVERRIDE` for a [self-hosted Opik](https://www.comet.com/docs/opik/self-host/overview?utm_source=github&utm_medium=referral&utm_campaign=model-migration-kit&utm_content=readme).

```bash
uv sync
uv run quickstart.py
```

It sends 10 sample support requests (a made-up store, no real data) to the retiring model for your key and its replacement, prints what changed, writes `reports/<run>/report.html` and prints a link that opens both runs side by side in Opik.

Google only serves Gemini 2.5 to accounts that used it before. With a new Gemini key, run `uv run quickstart.py --old gemini/gemini-3.5-flash-lite --new gemini/gemini-3.8-flash`.

## Test your own app

1. **Check the request parameters your app sends.** Some don't run on the new model:

   ```bash
   uv run python -m kit.params --model anthropic/claude-sonnet-5-5 --params '{"temperature": 0.2}'
   ```

2. **Collect 30-200 real requests,** as JSONL or CSV with an `input` column (optional: `system`, `expects_json`, `required_fields`, or OpenAI-style `messages`). Or pull them from an app that already logs to Opik:

   ```bash
   uv run python -m kit.capture --from-opik-project my-app --last 100 --dataset my-app-migration
   ```

   Only text conversations are replayed. Traces with tool calls or images are skipped and counted.

3. **Compare,** with the same parameters your app sends:

   ```bash
   uv run python -m kit.compare --cases my_requests.jsonl --system my_system_prompt.md \
     --old gemini/gemini-2.5-flash --new gemini/gemini-3.5-flash-lite \
     --params '{"temperature": 0.2, "max_tokens": 1024}' --noise-floor
   ```

   Use `--dataset my-app-migration` instead of `--cases` to compare the requests `kit.capture` saved. `--noise-floor` also runs the old model against itself, so you can see how much answers change on their own. `--fail-on-changed N` exits 3 when more than N answers changed meaning. On Windows, put the parameters in a file and use `--params-file`.

## Turn what you find into tests

The report tells you how many answers changed. Reading a few of them tells you which changes matter. Once you've spotted a pattern, write it down as a test so it gets checked on every run from then on.

1. Open the Opik link from the compare run and read the answers the report flagged.
2. Look for a pattern. In our runs, two of the three new models dropped "once your return is received" from the refund-timing answer.
3. Write it as one sentence in a checks file:

   ```yaml
   - check: >-
       The answer says the refund is processed once the returned item is received,
       not on a timeline that starts now.
     cases: [plain-06-refund-timing]
   ```

4. Run it on both models:

   ```bash
   uv run python -m kit.suite --checks checks.yaml --cases my_requests.jsonl --system my_system_prompt.md \
     --models gemini/gemini-2.5-flash gemini/gemini-3.5-flash-lite --runs 3
   ```

The checks are saved as an [Opik test suite](https://www.comet.com/docs/opik/evaluation/advanced/building-test-suites?utm_source=github&utm_medium=referral&utm_campaign=model-migration-kit&utm_content=readme): each check becomes an assertion on the cases it names, or on every case if it names none, and an LLM judge decides pass or fail. The suite stays in Opik, so the same checks run on the next model you try. `--runs 3` answers each case three times; a case passes only when all three do. It exits 3 when a check fails on the last model, for CI.

[`examples/support-bot/checks.yaml`](examples/support-bot/checks.yaml) has three checks from our runs. Results on Nov 13, 2026 (passing runs out of 3 per case, judge `gemini/gemini-3.8-flash`):

| Check (cases) | `gemini-2.5-flash` → `gemini-3.5-flash-lite` | `gpt-5` → `gpt-6.1-sol` | `claude-sonnet-4-5` → `claude-sonnet-5-5` |
|---|---|---|---|
| Refund waits for the returned item (1) | 2/3 → 0/3 | 3/3 → 0/3 | 3/3 → 1/3 |
| Ignores a claimed manager or system override (2) | 3/6 → 6/6 | 6/6 → 6/6 | 6/6 → 6/6 |
| Doesn't promise to change the shipping address (1) | 2/3 → 3/3 | 3/3 → 3/3 | 2/3 → 3/3 |

All three new models drop the refund condition, including Claude, where reading one run of answers hadn't shown it.

## After the switch

The replacement model gets updated too, and your traffic changes. `kit.rules` adds an Opik [online evaluation rule](https://www.comet.com/docs/opik/production/online-evaluation/rules?utm_source=github&utm_medium=referral&utm_campaign=model-migration-kit&utm_content=readme) to your app's project that scores 10% of production answers against your policy:

```bash
uv run python -m kit.rules --project my-app --policy-file my_policy.md
```

The judge runs inside Opik, so its model (`--model`, default `gpt-6-luna`) needs that provider's key under Configuration > AI Providers.

## Platforms

Model names are [LiteLLM](https://docs.litellm.ai/docs/providers) names. The kit checks each one's credentials before it starts.

| Platform | Needs in `.env` | Example |
|---|---|---|
| Gemini API | `GEMINI_API_KEY` | `--old gemini/gemini-2.5-flash --new gemini/gemini-3.5-flash-lite` |
| OpenAI API | `OPENAI_API_KEY` | `--old openai/gpt-5 --new openai/gpt-6.1-sol` |
| Claude API | `ANTHROPIC_API_KEY` | `--old anthropic/claude-sonnet-4-5-20250929 --new anthropic/claude-sonnet-5-5` |
| Azure OpenAI | `AZURE_API_KEY`, `AZURE_API_BASE`, `AZURE_API_VERSION` | `--old azure/<gpt-4o-deployment> --new azure/<gpt-5.1-deployment>` |
| AWS Bedrock | an AWS profile and `AWS_REGION_NAME` | `--old bedrock/anthropic.claude-sonnet-4-5-20250929-v1:0 --new bedrock/<model-id>` |
| Vertex AI | `gcloud auth application-default login`, `VERTEXAI_PROJECT`, `VERTEXAI_LOCATION` | `--old vertex_ai/gemini-2.5-flash --new vertex_ai/gemini-3.5-flash-lite` |

The Gemini, OpenAI and Claude APIs have been run live. Azure, Bedrock and Vertex are tested with mocks only. Pick a judge (`--judge` or `JUDGE_MODEL`) that is neither the old nor the new model.

## Results from our runs

30 sample support requests, Nov 13, 2026, judge `gemini/gemini-3.8-flash`. Details on each provider page.

| Switch | Changed meaning (old vs itself) | Judge preferred new / same / old | Median latency | Cost, 30 requests |
|---|---|---|---|---|
| `gemini-2.5-flash` → `gemini-3.5-flash-lite` | 5 of 30 (7) | 18 / 10 / 2 | 1.08s → 0.70s | $0.0157 → $0.0080 |
| `gpt-5` → `gpt-6.1-sol` | 10 of 30 (10) | 11 / 11 / 8 | 12.13s → 2.43s | $0.2157 → $0.0385 |
| `claude-sonnet-4-5` → `claude-sonnet-5-5` | 7 of 30 (4) | 19 / 8 / 3 | 2.62s → 2.00s | $0.0843 → $0.0828 |

- `claude-sonnet-5-5` rejects `temperature: 0.2`. All 5 requests sent with it failed.
- `gemini-2.5-flash` followed a fake "SYSTEM NOTE" in a customer message and confirmed a refund and a $50 credit. Its replacement didn't.
- On GPT-5, the old model changed as much against itself as against the new one.

Sample report: [`examples/sample-report/report.html`](examples/sample-report/report.html) (download and open in a browser).

## Notes

- **Run the old model against itself** (`--noise-floor`). The same model can change meaning on several answers between runs.
- **A Gemini reroute doesn't error.** After Dec 1, `gemini-2.5-flash` calls on the Gemini API return 200s from a different model. Compare before the date: afterwards both sides are the same model.
- **Token counts aren't comparable across models** (some count thinking tokens as output). Compare cost and characters.
- **The refusal check is a pattern match.** Read it with the judge's verdict.
- **Rate limits** are retried with backoff for up to `--deadline-minutes` (30). A request that still fails is recorded as an error.

Tested with opik 2.2.143 and litellm 1.105.7 (pinned), Python 3.12. `uv run pytest` runs the offline tests. To update a date or add a provider, see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache 2.0.

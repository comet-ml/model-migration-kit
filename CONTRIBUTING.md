# Contributing

Issues are welcome: a wrong date, a missing model, or a surprising regression (with a redacted, minimal case). Pick a template on the [new issue page](https://github.com/comet-ml/model-migration-kit/issues/new/choose).

## Update a retirement date

1. Edit the row in [`kit/retirements.yaml`](kit/retirements.yaml): the date, replacement or `kind`, the `source` link, and `checked_on` (today). Use `kind: depends` with a `note` when the outcome depends on the deployment.
2. Regenerate the tables in `README.md` and `providers/*.md`:

   ```bash
   uv run python -m kit.retirements --write
   ```

3. `uv run pytest` checks the tables match the YAML. Never write "[check]" in a public doc: resolve it from the source page, or write "not announced as of <date>".

## Add a provider or model family

- **Calling it:** nothing to add if LiteLLM supports it. `kit/config.py` asks LiteLLM which credentials the model needs; add the variables to `.env.example` and a row to "Your platform" in the README.
- **Parameter rules:** add a function to [`kit/params.py`](kit/params.py) that returns `Issue`s, each with its source URL, and one row to `RULES` with an exact pattern for the model family. Add a test in `tests/test_providers_params.py`.
- **A provider page:** add `providers/<name>.md` with the retirements markers and list it in `PAGES` in `kit/retirements.py`.

## Tests

`uv run pytest -q` runs offline: no keys, no Opik, no model calls. CI runs it on Linux and Windows.

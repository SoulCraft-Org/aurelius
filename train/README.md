# Serve the untrained seat on Modal

Step 25 of the [training plan](../docs/training.md), [issue #67](https://github.com/SoulCraft-Org/aurelius/issues/67). One GPU container runs vLLM on its own localhost, scores the jobs with `ladder.run`, and ends. No public endpoint, no new key.

## Commands

Run from the repo root. `python -I` leaves the repo off the path, so `serve.py` adds it. Read the usage limit on the Modal dashboard first, then set `MODAL_LIMIT_CHECKED` to the month.

| Command | What it does |
| --- | --- |
| `MODAL_LIMIT_CHECKED=2026-11 uv run --with modal==1.6.4 python -I train/serve.py smoke` | Scores r10, dev seed 0, once, lock off |
| `... python -I train/serve.py score --job r10:dev:0-2:lock --job r47:dev:0` | One job per `--job`: `RUNG:SPLIT:SEEDS[:lock]`, up to 10 seeds, r10 or r47 |

The run prints the score rows as JSON and adds one `ladder/spend.jsonl` row (lane `modal`, run id starting with the UTC date). A failed run is charged its measured GPU time, never zero. Commit the row with the scores.

## The guard

| Refuses when | Source |
| --- | --- |
| `MODAL_LIMIT_CHECKED` is not this month's `YYYY-MM` | You set it after reading the dashboard's usage limit |
| Under $3 of the $30 credit is left, or the worst case would leave under $3 | `modal billing summary`: $30 minus `adjustments.credits` |
| `billed_cost` is above 0, or the summary or ledger cannot be read | `modal billing summary`, `ladder/spend.jsonl` |
| This month's `modal` rows reach $15, or the worst case would | `ladder/spend.jsonl` |

The worst case is the 30 minute timeout at the L4 list price, $0.40 ([Modal pricing](https://modal.com/pricing), read 2026-11-23). The $3 floor and $15 cap are our goals.

## Choices

| Choice | Why |
| --- | --- |
| L4, 24 GB | BF16 weights are about 18 GB, text only, 16k context. If it runs out of memory at load, set `GPU` and `GPU_USD_H` to L40S (about $1.95 an hour, [Modal pricing](https://modal.com/pricing), read 2026-11-23) |
| `qwen3_coder`, thinking off | The [model card](https://huggingface.co/Qwen/Qwen3.5-9B) names the parser. Thinking is on by default and would spend the 1024-token reply |
| Weights in the image, eager mode, one container | The download runs on CPU at build time. Eager skips graph capture: faster boot, less memory, slower decode. Nothing stays warm |
| Cost per smoke | Our estimate: about 12 minutes of GPU, about $0.16 of credit at list price. That is 1 to 3 minutes of boot, 2 to 4 of vLLM start and 3 to 6 of calls, at roughly 15 to 25 tokens a second on an L4. The first run also builds the image on CPU. The ledger adds 180 seconds of cold start |

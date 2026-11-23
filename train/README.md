# Serve the untrained seat on Modal

Steps 25 and 26 of the [training plan](../docs/training.md), issues [#67](https://github.com/SoulCraft-Org/aurelius/issues/67) and [#68](https://github.com/SoulCraft-Org/aurelius/issues/68). One GPU container runs vLLM on its own localhost, scores the jobs with `ladder.run`, and ends. No public endpoint, no new key.

## Commands

Run from the repo root. `python -I` leaves the repo off the path, so `serve.py` adds it. Read the usage limit on the Modal dashboard first, then set `MODAL_LIMIT_CHECKED` to the month.

| Command | What it does |
| --- | --- |
| `MODAL_LIMIT_CHECKED=2026-11 uv run --with modal==1.6.4 python -I train/serve.py smoke` | Scores r10, dev seed 0, once, lock off |
| `... python -I train/serve.py score --job r10:dev:0-2:lock --job r47:dev:0` | One job per `--job`: `RUNG:SPLIT:SEEDS[:lock]`, up to 100 seeds, r10 or r47. Jobs share one boot. One row per seed, in seed order, scored 16 at a time (`--threads 1` to `64`) |
| `... python -I train/serve.py score --model mimo-9b ...` | `--model` picks the scored seat for `smoke` and `score`: `qwen3.5-9b` (default) or `mimo-9b` |
| `... python -I train/serve.py workers --kind small --seed 0 --size 20` | Step 29, [#71](https://github.com/SoulCraft-Org/aurelius/issues/71): real workers of one type over a seeded Library, up to 200 items; `--brief terse` (default, the item key only) or `--brief full` (the order's five fields, never the answer), recorded in each reply. Prints each item's reply; the clock and ledger row are as above. The container serves that type's model from `REAL_WORKERS` in `lair/real_workers.py`: small 2B, medium 4B, large 9B, all Apache-2.0. It serves one per run, because the three do not fit one L4 together. The image holds all three |

The run prints the score rows as JSON and adds one `ladder/spend.jsonl` row (lane `modal`, run id starting with the UTC date). A failed run is charged its measured GPU time, never zero. Commit the row with the scores.

## The guard

| Refuses when | Source |
| --- | --- |
| `MODAL_LIMIT_CHECKED` is not this month's `YYYY-MM` | You set it after reading the dashboard's usage limit |
| Under $3 of the $30 credit is left, or the worst case would leave under $3 | `modal billing summary`: $30 minus `adjustments.credits` |
| `billed_cost` is above 0, or the summary or ledger cannot be read | `modal billing summary`, `ladder/spend.jsonl` |
| This month's `modal` rows reach $15, or the worst case would | `ladder/spend.jsonl` |

The worst case is the 2 hour timeout at the L4 list price, $1.60 ([Modal pricing](https://modal.com/pricing), read 2026-11-23). It was 30 minutes and $0.40 before step 26. The $3 floor and $15 cap are our goals.

## Choices

| Choice | Why |
| --- | --- |
| L4, 24 GB | BF16 weights are about 18 GB, text only, 16k context. If it runs out of memory at load, set `GPU` and `GPU_USD_H` to L40S (about $1.95 an hour, [Modal pricing](https://modal.com/pricing), read 2026-11-23) |
| `qwen3_coder`, thinking off | The [model card](https://huggingface.co/Qwen/Qwen3.5-9B) names the parser. Thinking is on by default and would spend the 1024-token reply |
| Weights in the image, eager mode, one container | The download runs on CPU at build time. Eager skips graph capture: faster boot, less memory, slower decode. Nothing stays warm |
| Cost per smoke | Our estimate: about 12 minutes of GPU, about $0.16 of credit at list price. That is 1 to 3 minutes of boot, 2 to 4 of vLLM start and 3 to 6 of calls, at roughly 15 to 25 tokens a second on an L4. The first run also builds the image on CPU. The ledger adds 180 seconds of cold start |

## Step 26: 100 val seeds, three variants

Run each line from the repo root, after the dashboard check. One line is one container: it serves one model, so Qwen free-form, Qwen locked and MiMo each get their own boot, per rung.

| Variant | r10 | r47 |
| --- | --- | --- |
| Qwen3.5-9B, free-form | `... score --job r10:val:1000-1099` | `... score --job r47:val:1000-1099` |
| Qwen3.5-9B, locked | `... score --job r10:val:1000-1099:lock` | `... score --job r47:val:1000-1099:lock` |
| MiMo-9B | `... score --model mimo-9b --job r10:val:1000-1099` | `... score --model mimo-9b --job r47:val:1000-1099` |

Measure r47 first with `--job r47:val:1000-1003`: only r10 has run (step 25, smoke).

| Estimate (ours, L4 list price $0.80 an hour) | GPU time | Credit |
| --- | --- | --- |
| Smoke, measured: 560 GPU seconds, about 300 of them boot and load, so about 260 s for one r10 seed | 9 min | $0.12 |
| One r10 run of 100 seeds: 16 at once, assuming vLLM batches 16 requests for about 8 times the single-seed rate, plus 5 min boot | about 1 h | about $0.80 |
| One r47 run of 100 seeds: not measured; budget up to the 2 hour timeout | up to 2 h | up to $1.60 |
| All six runs | about 9 h at most | about $7.50 at most, under the $15 cap |

Each run adds its own ledger row, and the guard reads the ledger before the next one, so the cap holds. A seed that has not started 5 minutes before the timeout is returned as a `skipped` row, so a long run returns its finished seeds: run the missing seeds again as a new job. Each seed has its own seat and cap, so a failed seed is one `error` row.

## Choices of the scored seat

| Seat | Licence and revision | Parser |
| --- | --- | --- |
| `qwen3.5-9b` | Apache-2.0, `c202236` | `qwen3_coder`, thinking off |
| `mimo-9b` (`XiaomiMiMo/MiMo-V2.6-Distill-Qwen-9B`) | MIT, `1f09ddc` (Hugging Face, read 2026-11-23). A fine-tune of Qwen3.5-9B: same `Qwen3_5ForConditionalGeneration` build | The [model card](https://huggingface.co/XiaomiMiMo/MiMo-V2.6-Distill-Qwen-9B) names none for vLLM (only SGLang's `--reasoning-parser mimo`). Its chat template writes tool calls as `<tool_call><function=...>`, the format `qwen3_coder` reads, and honours `enable_thinking`, so the same flags apply (our reading) |

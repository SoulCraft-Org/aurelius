# Serve the untrained seat on Modal

Step 25 of the [training plan](../docs/training.md), [issue #67](https://github.com/SoulCraft-Org/aurelius/issues/67). One GPU container runs vLLM on its own localhost, scores the jobs with `ladder.run`, and ends. There is no public endpoint and no new key.

## Commands

Run from the repo root. `python -I` leaves the repo off the path, so `serve.py` adds it. Read the usage limit on the Modal dashboard first, then set `MODAL_LIMIT_CHECKED` to the month.

| Command | What it does |
| --- | --- |
| `MODAL_LIMIT_CHECKED=2026-11 uv run --with modal==1.6.4 python -I train/serve.py smoke` | Scores r10, dev seed 0, once, lock off |
| `... python -I train/serve.py score --job r10:dev:0-2:lock --job r47:dev:0` | One job per `--job`: `RUNG:SPLIT:SEEDS[:lock]`, up to 10 seeds, r10 or r47 |

The run prints the score rows as JSON and adds one `ladder/spend.jsonl` row (lane `modal`, run id starting with the UTC date). A failed run is charged what the clock says, never zero. Commit the ledger row with the scores.

## The guard

`train/guard.py` runs before anything starts on Modal. It reads `modal billing summary --json` and the ledger. Any doubt is a refusal.

| Refuses when | Source |
| --- | --- |
| `MODAL_LIMIT_CHECKED` is not the current `YYYY-MM` | The orchestrator sets it after reading the dashboard's usage limit |
| Under $3 of the month's $30 credit is left, or the worst case would leave under $3 | `modal billing summary`: $30 minus `metered_cost` |
| `billed_cost` is above 0 | The credit is gone and money is being charged |
| This month's `modal` rows add up to $15 or more, or the worst case would reach $15 | `ladder/spend.jsonl` |
| The summary, a ledger line or a number cannot be read | Fail closed. Title Case and snake_case keys both read |

The worst case is the hard timeout (30 minutes) at the L4 list price: $0.40 (our rule, [Modal pricing](https://modal.com/pricing), read 2026-11-23). The $3 floor and $15 cap are our goals.

## Choices

| Choice | Why |
| --- | --- |
| L4, 24 GB | 9B parameters in BF16 are about 18 GB. `--language-model-only` skips the vision encoder, `--max-model-len 16384` keeps the cache small, and the model has only 8 full-attention layers. If it runs out of memory at load, change `GPU` and `GPU_USD_H` in `serve.py` to L40S (about $1.95 an hour, [Modal pricing](https://modal.com/pricing), read 2026-11-23) |
| `qwen3_coder` tool parser | The [model card](https://huggingface.co/Qwen/Qwen3.5-9B) names it |
| Thinking off | The model thinks by default. It would spend the 1024-token reply before the tool call |
| `--enforce-eager` | No graph capture: faster boot, less memory, a slower decode |
| Weights in the image | They download at build time on CPU, so no GPU second pays for it |
| `single_use_containers`, `scaledown_window=2`, `max_containers=1` | Nothing stays warm |

## Cost per smoke

Our estimate: about 12 minutes of GPU, about $0.16 of credit at list price. The parts are 1 to 3 minutes of boot, 2 to 4 minutes of vLLM start and 3 to 6 minutes of calls. A 9B model decodes at roughly 15 to 25 tokens a second on an L4 (our estimate). The first run also builds the image on CPU, which is not GPU time. Sources: [Modal pricing](https://modal.com/pricing), read 2026-11-23.

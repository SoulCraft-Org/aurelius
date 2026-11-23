# 🎓 Training

How the seat model is trained. Every source below was read on 2026-11-22. Figures marked "our estimate" are ours.

> ⚠️ **Nothing here is trained yet.** This page is the plan. No model, run or score exists. Scores come after the Egg builds the first baselines.

## 🧗 The climb

One seat trains per episode. Its 47 children are frozen. Each rung's recorded runs are fitted into the stand-ins the next rung uses. The full tree runs only for tests.

```mermaid
flowchart LR
  E["🥚 Egg<br/>sim only, no training"] --> H["🐣 Hatchling<br/>47 real frozen workers"]
  H -- "record, fit stand-ins" --> D["🐲 Drake<br/>47 stand-in teams = 2,209"]
  D -- "record, fit stand-ins" --> R["🐉 Dragon<br/>47 stand-in armies = 103,823"]
```

| Rung | Agents | Tiers | Seats | Trains against | Source, read 2026-11-22 |
|---|---|---|---|---|---|
| 🥚 Egg | 10, 47, 2,209, 103,823 | 1 to 3 | 1 to 2,257 | nothing trained | [spec](../spec/aurelius.json) |
| 🐣 Hatchling | 47 | 1 | 1 | 47 real frozen workers | [spec](../spec/aurelius.json) |
| 🐲 Drake | 2,209 | 2 | 48 | 47 stand-ins fitted from Hatchling | [spec](../spec/aurelius.json) |
| 🐉 Dragon | 103,823 | 3 | 2,257 | 47 stand-ins fitted from Drake | [spec](../spec/aurelius.json) |

Gate targets come from the Egg's baseline scores, not from guesses made now.

## 🧠 Base model

| Use | Model | Licence | Source, read 2026-11-22 |
|---|---|---|---|
| Iterate | Qwen3.5-9B, 262k context | Apache-2.0 | [Hugging Face](https://huggingface.co/Qwen/Qwen3.5-9B) |
| Release | Qwen3.8-27B, 27.8B parameters | Apache-2.0 | [Hugging Face](https://huggingface.co/Qwen/Qwen3.8-27B) |
| ❌ Never | Nemotron-Orchestrator-8B | NVIDIA License, non-commercial research only | [arXiv 2511.21689](https://arxiv.org/abs/2511.21689) |

## 🔧 Method

| Step | What | Source, read 2026-11-22 |
|---|---|---|
| 1 | SFT warm-up on open-teacher data | our plan |
| 2 | GRPO, one seat at a time, children frozen | [arXiv 2511.21689](https://arxiv.org/abs/2511.21689), [arXiv 2602.02276](https://arxiv.org/abs/2602.02276) |
| 3 | Split and finish bonuses fade to 0 | [arXiv 2602.02276](https://arxiv.org/abs/2602.02276) |

## 🎯 Reward

| Term | Kind | When | Rule | Source, read 2026-11-22 |
|---|---|---|---|---|
| Format | gate | always | An action that does not parse scores 0 | [spec](../spec/aurelius.json) |
| Success | base | always | The done check passes, as far as the seat can see | [spec](../spec/aurelius.json) |
| Cost | bonus | on success only | Credits left under budget | [spec](../spec/aurelius.json), [arXiv 2511.21689](https://arxiv.org/abs/2511.21689) |
| Speed | bonus | on success only | Critical steps left under budget | [spec](../spec/aurelius.json), [arXiv 2511.21689](https://arxiv.org/abs/2511.21689) |
| Split | bonus | on success, task can split | Weight 0.1, fades to 0 during training | [spec](../spec/aurelius.json), [arXiv 2602.02276](https://arxiv.org/abs/2602.02276) |

Weights for cost and speed come from the dial (quality, cost, speed; default balanced). Credit comes only from what the seat can see. Each sub-agent's credit can be gated by a rubric score of its report ([arXiv 2611.17041](https://arxiv.org/abs/2611.17041), read 2026-11-22).

## 📋 Tasks

| Kind | Why | Source, read 2026-11-22 |
|---|---|---|
| Fill-the-table research with known answers | Success is checkable | our plan |
| Planted faults and alarms | Tests whether alarms reach the root seat | [spec](../spec/aurelius.json) |
| Tasks where splitting is wrong | Sequential work gets worse with more agents: 39% to 70% on sequential planning | [arXiv 2512.08296](https://arxiv.org/abs/2512.08296) |

## 📦 Data rule

| Rule | Why | Source, read 2026-11-22 |
|---|---|---|
| Open teachers only, Apache-2.0 or MIT | Licences allow it | [gpt-oss-120b](https://huggingface.co/openai/gpt-oss-120b) (Apache-2.0), [DeepSeek-V4.1-Flash](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash) (MIT), [GLM-5.3-Flash](https://huggingface.co/zai-org/GLM-5.3-Flash) (MIT) |
| Run teachers on US or EU hosts | Our own rule | n/a |
| No closed-model outputs | Their terms bar training a competing model on them | [Anthropic](https://www.anthropic.com/legal/commercial-terms), [OpenAI](https://openai.com/policies/row-terms-of-use/), [Google](https://ai.google.dev/gemini-api/terms) |

## 🧰 Stack

| Part | Choice | Licence | Source, read 2026-11-22 |
|---|---|---|---|
| Trainer | TRL AsyncGRPOTrainer v1.18.2, with its own vLLM server for generation | Apache-2.0 | [TRL docs](https://huggingface.co/docs/trl/main/en/async_grpo_trainer) |
| Environments | OpenEnv | BSD-3-Clause | [GitHub](https://github.com/meta-pytorch/OpenEnv) |
| Evals | Inspect AI, runs in CI | MIT | [GitHub](https://github.com/UKGovernmentBEIS/inspect_ai) |
| Fallback | Tinker, managed LoRA training | service | [Thinking Machines](https://thinkingmachines.ai/tinker/) |

## 🚀 Release

| Piece | Detail | Source, read 2026-11-22 |
|---|---|---|
| Weights | Hugging Face | [Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B) |
| Local file | GGUF plus a Modelfile, so `ollama run` works. Ollama does not quantize on import | [Ollama import](https://docs.ollama.com/import) |
| Used from | OpenCode, Goose, Zed | [OpenCode](https://github.com/anomalyco/opencode), [Goose](https://github.com/aaif-goose/goose), [Zed](https://github.com/zed-industries/zed) |

## 🌙 Experiment loop

| Rule | Detail | Source, read 2026-11-22 |
|---|---|---|
| Fixed budget per run | Keep the change or reset it | [autoresearch](https://github.com/karpathy/autoresearch) |
| One metric | Cost per verified success is the headline | [spec](../spec/aurelius.json) |
| Capped | A cap on runs and a stop switch | our plan |

## 💰 Costs

| Rung | Estimate | Note |
|---|---|---|
| 🥚 Egg | $0 | our estimate, 2026-11-22: simulator on CPU, nothing trained |
| 🐣 Hatchling | about $100 to $400 | our estimate, 2026-11-22 |
| 🐲 Drake | priced after Hatchling | Real runs set the price |
| 🐉 Dragon | priced after Drake | Real runs set the price |

For scale, one open project reports about 2 hours and $48 to reach GPT-2 grade, a figure its authors state about their own work ([nanochat](https://github.com/karpathy/nanochat), read 2026-11-22). It is a different task and proves nothing about ours.

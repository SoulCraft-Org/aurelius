# 📚 Sources

Every idea and number Aurelius uses, with its source. All read on 2026-11-22. 🗣️ marks a figure the vendor states about its own product.

Open a fold to see its rows.

<details>
<summary>🧠 Trained orchestrators (8)</summary>

| Idea we take | Number | Source | Licence |
|---|---|---|---|
| Train the orchestrator only; sub-agents stay frozen. Split and finish bonuses fade to 0. Score in critical steps | 100 sub-agents (K2.5), 300 (K2.6) 🗣️ | [arXiv 2602.02276](https://arxiv.org/abs/2602.02276), [Kimi K2.6](https://kimi.com/blog/kimi-k2-6) | paper |
| GRPO orchestrator. Cost, latency and user preference count only when the task is solved | Qwen3-8B base, 16 H100 | [arXiv 2511.21689](https://arxiv.org/abs/2511.21689) | weights: NVIDIA License, non-commercial research only |
| GRPO writes a workflow over a pool of workers. Reward 0, 0.5 or 1. Random worker subsets in training | Qwen2.5-7B, 2 H100, about 960 problems | [arXiv 2512.04388](https://arxiv.org/abs/2512.04388) | paper |
| Lead and sub-agents trained together. An untrained lead gets worse as sub-agents are added | Qwen3-4B, 10 sub-agents | [arXiv 2602.04634](https://arxiv.org/abs/2602.04634) | paper |
| Each sub-agent's credit is gated by a rubric score of its report | 24.5% lower critical-path cost on BrowseComp | [arXiv 2611.17041](https://arxiv.org/abs/2611.17041) | paper |
| One outcome reward is given to every turn of the plan | 14% average gain | [arXiv 2510.05592](https://arxiv.org/abs/2510.05592) | paper |
| Run the agents apart from the trainer | | [arXiv 2508.03680](https://arxiv.org/abs/2508.03680) | paper |
| A judge ranks a group of runs and that rank is the reward | | [ART + RULER](https://art.openpipe.ai/fundamentals/ruler) | Apache-2.0 |

</details>

<details>
<summary>📈 Scale and failure (8)</summary>

| Idea we take | Number | Source | Licence |
|---|---|---|---|
| Unchecked agents multiply errors; a central check cuts it. Sequential work gets worse with more agents | 17.2x vs 4.4x error growth in traces. 39% to 70% worse on sequential planning. Teams of up to 9 | [arXiv 2512.08296](https://arxiv.org/abs/2512.08296) | paper |
| A failure map for multi-agent systems | 14 failure modes, 1,600+ traces | [arXiv 2503.13657](https://arxiv.org/abs/2503.13657) | paper |
| Multi-agent wins on wide work and costs far more tokens | 90.2% better on its own eval; about 15x chat tokens 🗣️ | [Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system) | blog: idea only, no text copied |
| Planners hand work to sub-planners; workers stay isolated; a judge restarts each cycle | hundreds of workers 🗣️ | [Cursor](https://cursor.com/blog/scaling-agents) | blog: idea only, no text copied |
| Dummy workers make huge runs cheap | 1M agents in about 40 s | [arXiv 2407.17789](https://arxiv.org/abs/2407.17789) | paper |
| One decision steers many agents of one kind | about 400 queries for 8.4M agents | [arXiv 2409.10568](https://arxiv.org/abs/2409.10568) | paper |
| A million simulated agents, with no orchestrator | 1M agents | [arXiv 2411.11581](https://arxiv.org/abs/2411.11581) | paper |
| The world step is cheap; model calls are the bottleneck | 0.168 s per step at 1M agents | [arXiv 2502.08691](https://arxiv.org/abs/2502.08691) | paper |

</details>

<details>
<summary>🔌 Wires and workers (9)</summary>

| Idea we take | Number | Source | Licence |
|---|---|---|---|
| One wire for every worker. v1 stable; v2 in preview since 2026-11-20 | 51 agents listed, OpenCode, Goose, Gemini CLI and Codex CLI among them | [Agent Client Protocol](https://agentclientprotocol.com) | Apache-2.0 |
| Task states: working, input_required, completed, failed, cancelled | | [MCP Tasks](https://modelcontextprotocol.io/specification/draft/basic/utilities/tasks) | open spec: idea only, no text copied |
| Terminal states: completed, failed, canceled, rejected | v1.0 | [A2A](https://a2a-protocol.org/latest/specification/) | Apache-2.0 |
| A recipe carries a reply schema and checks that must pass. Runs headless with JSON output | v1.60.2 | [Goose](https://github.com/aaif-goose/goose) | Apache-2.0 |
| Allow, ask or deny rules; the last match wins; the default is ask. Subagents defined in Markdown | v2.3.2 | [OpenCode](https://github.com/anomalyco/opencode) | MIT |
| An agent runtime; no headless mode documented yet | | [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) | MIT |
| An editor that hosts outside agents and finds local Ollama models | v1.29.3 | [Zed](https://github.com/zed-industries/zed) | GPL-3.0, some Apache-2.0 |
| Import a GGUF file with a Modelfile; Ollama does not quantize on import | v0.40.17 | [Ollama import](https://docs.ollama.com/import) | MIT |
| In-process teammates cannot be resumed | | [Claude Code agent teams](https://code.claude.com/docs/en/agent-teams) | docs: idea only, no text copied |

</details>

<details>
<summary>💰 Routing and cost (5)</summary>

| Idea we take | Number | Source | Licence |
|---|---|---|---|
| A learned router matches the best single model for less | up to 31.7% lower cost | [arXiv 2601.07206](https://arxiv.org/abs/2601.07206) | paper |
| A learned router, best case | up to 85% cheaper on MT-Bench 🗣️ | [RouteLLM](https://github.com/lm-sys/RouteLLM) | Apache-2.0 |
| A cheaper call is not a cheaper finished task | | [Switchyard](https://github.com/NVIDIA-NeMo/Switchyard) | Apache-2.0 |
| Price, context and tool support per model. We keep our own dated table and never republish theirs | | [OpenRouter models](https://openrouter.ai/docs/guides/overview/models), [terms](https://openrouter.ai/terms) | terms §7, §12: idea only, no text copied |
| Tool-calling tests and reproducible evals | | [tool-bench](https://github.com/OpenRouterTeam/tool-bench), [benchmark-harness](https://github.com/OpenRouterTeam/benchmark-harness) | MIT, Apache-2.0 |

</details>

<details>
<summary>🧰 Models and stack (8)</summary>

| Idea we take | Number | Source | Licence |
|---|---|---|---|
| Base model to iterate | 262k context | [Qwen3.5-9B](https://huggingface.co/Qwen/Qwen3.5-9B) | Apache-2.0 |
| Base model to release | 27.8B parameters | [Qwen3.8-27B](https://huggingface.co/Qwen/Qwen3.8-27B) | Apache-2.0 |
| Open teachers for training data | | [gpt-oss-120b](https://huggingface.co/openai/gpt-oss-120b), [DeepSeek-V4.1-Flash](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash), [GLM-5.3-Flash](https://huggingface.co/zai-org/GLM-5.3-Flash) | Apache-2.0, MIT, MIT |
| GRPO with tools; generation runs on a separate vLLM server | v1.18.2 | [TRL AsyncGRPOTrainer](https://huggingface.co/docs/trl/main/en/async_grpo_trainer) | Apache-2.0 |
| Gym-style training environments | | [OpenEnv](https://github.com/meta-pytorch/OpenEnv) | BSD-3-Clause |
| Agent evals that run in CI | | [Inspect AI](https://github.com/UKGovernmentBEIS/inspect_ai) | MIT |
| Managed LoRA training, the fallback | | [Tinker](https://thinkingmachines.ai/tinker/) | service: idea only, no text copied |
| Closed models bar training a competing model on their outputs, so we use none | | [Anthropic](https://www.anthropic.com/legal/commercial-terms), [OpenAI](https://openai.com/policies/row-terms-of-use/), [Google](https://ai.google.dev/gemini-api/terms) | terms: idea only, no text copied |

</details>

<details>
<summary>🛠️ How we build (7)</summary>

| Idea we take | Number | Source | Licence |
|---|---|---|---|
| A fresh worker per task, one reviewer, a capped fix loop, a ledger | | [Superpowers](https://github.com/obra/superpowers) | MIT |
| Every step carries a check that proves it is done | | [Karpathy Skills](https://github.com/multica-ai/andrej-karpathy-skills) | none: idea only, no text copied |
| A fixed-budget experiment loop: keep the change or reset it | 5-minute runs 🗣️ | [autoresearch](https://github.com/karpathy/autoresearch) | none: idea only, no text copied |
| A scoreboard of cost and time to reach a target | about 2 hours and $48 to GPT-2 grade 🗣️ | [nanochat](https://github.com/karpathy/nanochat) | MIT |
| Ask whether a thing is needed before building it | 53% less code 🗣️ | [PonyTail](https://github.com/DietrichGebert/ponytail) | MIT |
| Tag each fact as found or inferred; a chain is only as strong as its weakest link | | [Graphify](https://github.com/Graphify-Labs/graphify) | Apache-2.0 |
| Record a session once, replay it as a practice environment, flag what the recording does not confirm | | [REA](https://github.com/morluto/rea) | MIT |

</details>

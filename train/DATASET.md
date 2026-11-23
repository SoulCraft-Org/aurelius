# Dataset card: Aurelius seat traces

Step 31 of the [training plan](../docs/training.md), [issue #75](https://github.com/SoulCraft-Org/aurelius/issues/75). Chat examples for supervised fine-tuning of the student seat. Built by `python3 -m train.traces`.

| Topic | Answer |
| --- | --- |
| Sources | First, the transcripts of the rule seat (`ladder/sweep.py`, one line per decision). Later, the student's own best-of-N runs, kept by the same reward bar |
| Example | System prompt, then the user turn, then the assistant turn. The system prompt is the one `ModelSeat` sends. The user turn is the observation exactly as `ModelSeat` sends it, with replies shown by status only. The assistant turn is the actions as tool calls in `ModelSeat`'s schema, and each example carries those tool schemas |
| Format | [TRL's conversational format with tool calls](https://huggingface.co/docs/trl/dataset_formats), one JSON object per line |
| Filters | Dev seeds only. Runs at or above the reward bar. Exact duplicates dropped. A cap of examples per run. Actions that fail `lair.seat.validate_action`, and a reply of `wait` alone, are dropped |
| Splits | Training uses the spec's dev seeds, 0 to 999. Val (1000 to 1999) and test (2000 to 2999) never enter. The tool stops the run on one, and it also refuses a split label that disagrees with the seed |
| Truth fields | None in a prompt. The user turn holds the observation the seat sees, and replies show their status only, so no answer text, fact or alarm reaches the model |
| Authorship | Our code wrote and graded every example: the rule seat and the simulator. No closed model wrote or graded any of it |
| Licence | The dataset and the code that builds it are ours, under the repository's licence. The student model is Apache-2.0 |

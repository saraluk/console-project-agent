# AI Usage

This project was built with AI assistance. This file describes which tools were used,
the main prompts, and what the AI did.

## 1. AI tools used

| Tool | Role |
|---|---|
| **Claude Code** (v2.1.330, Anthropic's agentic coding CLI) | Main development assistant: planning, code generation, tests, debugging, documentation |
| **Claude Opus 5.5** (model behind Claude Code, Claude Pro plan) | The model that did the reasoning and wrote the code |
| `/guided-reasoning` skill in Claude Code | A structured workflow: clarifying questions → options with pros/cons → optional research → self-check → "Proceed?" before any code was written |

The app itself calls an LLM at runtime too: **`openai/gpt-4o-mini` through OpenRouter**
(see `README.md`). That is part of the product, not a development tool.

## 2. Main prompts and chat transcripts

The full transcript is in the repo:
[`2026-11-21-180019-command-messageguided-reasoningcommand-messag.txt`](2026-11-21-180019-command-messageguided-reasoningcommand-messag.txt), the raw Claude Code session export.

The main prompts I wrote, in order:

1. **Initial brief and design request**
   > `/guided-reasoning` I'm building a standalone Python 3.10+ console application using LangChain and LangGraph. Users interact via stdin/stdout in a continuous loop until typing `quit` or `exit`, and project data is saved to a local JSON file (`projects.json`).
   >
   > Core features:
   > - Create a project from natural language (`project_name` and `customer` are required; if either is missing, ask follow-up questions across turns before saving)
   > - Support optional fields (`start_date`, `location`, `status`, `notes`)
   > - List all projects (handling an empty list clearly)
   > - Bonus actions: get, update, and delete a project
   > - LLM Provider: Cloud API (OpenRouter) configured via API key in .env
   > - Handle unclear input and runtime errors gracefully without crashing
   >
   > Before writing any code, propose a clean, modular directory structure with a `requirements.txt` file at the root, our LangGraph state & node flow (including how multi-turn slot filling works), and a step-by-step build order for us to review.

2. **Answers to the clarifying questions:** `1. C  2. B  3. A`
   (projects get an ID but can be referred to by name; a new command during slot filling keeps the draft aside and runs the command; `gpt-4o-mini` via `.env` plus offline pytest tests with a fake LLM.)

3. **Research and README requirements**
   > Let's go with Option A and research first before finalizing the plan.
   > For step 6, please make sure the README.md explicitly covers: how to install dependencies, how to configure OpenRouter in .env, the exact LLM provider and model used, how to run the app and offline tests, a brief explanation of the LangGraph workflow, 2–3 example console sessions (including multi-turn creation, listing, and unclear input/exit).

4. **Plan approval with a change**
   > All of these assumptions look good except deletion: Please always require confirmation. I installed python@3.12 already, with that, let's process with the plan.

5. **Bug report from manual testing (ambiguous names and corrections)**
   > I tested the app and noticed two issues during project creation:
   > 1. When a name is ambiguous (unclear whether it's the project name or the customer), the app guesses instead of asking for clarification.
   > 2. Even when I explicitly corrected it, saying "Dresswell is not the project name, it's the customer", the app still saved "Dresswell" as both the project name and the customer because it never cleared the wrong field from the draft.
   >
   > Can we fix this so the agent asks for clarification when a name is ambiguous, and properly clears/removes a draft field when the user corrects it?

6. **Output format change**
   > Can you update the CLI output format to be a bit cleaner and match this style?
   > ```
   > > create a project called Alpha for customer Acme
   > Done. Created project "Alpha" for customer Acme.
   > > list projects
   > Here are your projects (2):
   > 1. Alpha — customer: Acme
   > 2. Beta — customer: Globex
   > ```
   > If optional fields are set, include them concisely (and skip them if empty).

   Follow-up: `Go with option C` (never show IDs in output).

7. **Bug report: clearing a field on an existing project**
   > Fix the bug where user ask to clear start date of `<project name>` but the app responded with Got it (customer: `<project name>`). What's the project name?

   Follow-up: `yes go with option B` (prompt fix, clearing on update, and a plain-code check).

8. **New feature: delete all projects**
   > Yes. And can you add a command to delete all projects (e.g. "delete all projects" or "clear all projects") with double confirmation?

   Follow-up: `Go with option B` (confirm with yes, then type the phrase `delete all`).
   Later simplified:
   > for delete all path, I think we just do one confirmation that require user the type "delete all"

9. **Bug report: wrong relative start date**
   > Still doesn't save with correct start date.
   > `> create a new project call Apollo 13 that kick-off next Friday`
   > `Got it (project name: Apollo 13, start date: 2026-11-25)`

Other short replies (`yes`) approved fixes that the AI proposed after live tests. These
fixes were: stopping the model from inventing a `status` or a `start_date` the user never
mentioned, stripping stray punctuation from values, and working out relative dates
("next Friday", "in 2 weeks") in plain code.

## 3. How AI assisted the implementation

**Design and planning.** Before writing any code, Claude asked three clarifying questions and
proposed the module layout (`project_agent/` with `config`, `llm`, `models`, `storage`,
`formatting`, `cli`, and a `graph/` package for state, prompts, nodes, routing and builder).
It also proposed the LangGraph state and node flow for multi-turn slot filling and a
step-by-step build order. For each design decision it listed options with pros, cons and
risk. I made the final call each time.

**Research.** Before finalizing the plan, it checked the current docs for the LangGraph
`StateGraph`/`InMemorySaver` checkpointer API and for using OpenRouter through LangChain's
`ChatOpenAI` with structured output. It also checked compatible package versions for
`requirements.txt`, and flagged that the Mac's default Python 3.9 was too old.

**Code generation.** Claude wrote most of the code: the Pydantic models and the structured
`ParsedInput` schema, the JSON repository, the LangGraph nodes and routing (including
drafts kept aside when the user runs another command, "which one?" disambiguation, and
delete confirmation), the console loop with error handling, and output formatting.

**Testing.** It wrote an offline pytest suite with a fake LLM (`tests/fakes.py`), growing to
130 tests that cover slot filling, corrections, clearing fields, formatting, storage,
delete-all and date resolution. It also added `scripts/check_llm.py` to send sample
sentences to the real OpenRouter model.

**Debugging.** When I reported bugs from manual testing, Claude reproduced them against the
live model (read-only, using a temporary data file) and found the root cause. It then
proposed fixes that don't depend on the model being right. Examples:
- `clear_fields` and `ambiguous_value` schema fields, plus a check that refuses to save when
  the project name and customer are identical.
- Applying `clear_fields` to existing projects through update.
- Keeping `status` or `start_date` only if the user's own words mention one.
- `project_agent/dates.py`, which resolves "next Friday" and similar phrases in code, since
  the model miscounted weekdays.
- For the last date report, it found that the code was already correct: an older app process
  started before the fix was still running.

**Documentation.** It wrote and updated `README.md`, covering install, `.env` setup, the
provider and model, how to run the app and tests, the LangGraph workflow, and example
console sessions generated from the real app code.

**My role.** I wrote the requirements and made the design decisions (ID scheme, slot-filling
behaviour, model choice, output style, confirmation style). I also tested the app by hand
and reported the bugs that drove each fix. I reviewed and approved every plan before Claude
implemented it.

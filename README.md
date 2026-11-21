# Console Project Assistant

A terminal app for managing projects in plain English. Type sentences like *"new project
Website Redesign for Acme Corp starting Dec 1"*. The app works out what you mean, asks
follow-up questions for anything required that's missing, and saves projects to a local
`projects.json` file.

Built with **LangChain** + **LangGraph**, using a cloud LLM through **OpenRouter**.

**Features**
- **Create** a project from natural language. `project_name` and `customer` are required.
  If either is missing, the app asks for it over the next turns before saving.
- **Never guesses.** If it isn't clear whether a name is the project name or the customer,
  the app asks. **Corrections work:** *"Dresswell is not the project name, it's the
  customer"* removes the wrong field from the draft.
- Optional fields: `start_date`, `location`, `status`, `notes`.
- **List** all projects, with a clear message when there are none. Output is short and
  plain: `1. Alpha — customer: Acme · status: active`. Empty optional fields are left
  out, and internal IDs are never shown.
- **Get**, **update** (including clearing optional fields, e.g. *"clear start date of
  Alpha"*) and **delete** a project by name. If a name matches
  several projects, the app asks which one. **Deleting always needs an explicit `yes`.**
- **Delete all projects** (*"delete all projects"*, *"clear all projects"*) with one
  confirmation: type the exact words `delete all`. Any other answer (even `yes`) cancels,
  and nothing is deleted. There is no undo.
- Unclear input, network or API failures, and a damaged data file all get a friendly
  message. The app does not crash.

---

## 1. Install dependencies

Requires **Python 3.10 or newer** (developed on 3.12).

```bash
cd console-project-agent
python3.12 -m venv .venv          # create an isolated Python env (any 3.10+ works)
source .venv/bin/activate         # turn it on; redo in each new terminal (Windows: .venv\Scripts\activate)
pip install -r requirements.txt   # install the app's packages
```

`requirements.txt` uses version ranges. pip picks the newest versions that work with your
Python. For example, `langchain-core`/`langchain-openai` 1.8+ need Python 3.11, so on 3.10
pip installs 1.7.x instead.

## 2. Configure OpenRouter in `.env`

1. Create an account and an API key at <https://openrouter.ai/keys>. Add a few dollars of
   credit; this app uses a tiny fraction of a cent per message.
2. Copy the example file and fill in your key:

   ```bash
   cp .env.example .env
   ```

   ```dotenv
   OPENROUTER_API_KEY=sk-or-v1-...your key...
   OPENROUTER_MODEL=openai/gpt-4o-mini
   PROJECTS_FILE=projects.json
   ```

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `OPENROUTER_API_KEY` | yes | — | Your OpenRouter key |
| `OPENROUTER_MODEL` | no | `openai/gpt-4o-mini` | Any OpenRouter model that supports structured outputs |
| `PROJECTS_FILE` | no | `projects.json` | Data file (relative paths are relative to this folder) |
| `OPENROUTER_TIMEOUT` | no | `30` | Seconds to wait for the model |
| `PROJECT_AGENT_DEBUG` | no | off | Set to `1` to log full error details |

`.env` and `projects.json` are listed in `.gitignore`, so your key and data stay out of git.

## 3. LLM provider and model

- **Provider:** [OpenRouter](https://openrouter.ai), reached through LangChain's `ChatOpenAI`
  with `base_url=https://openrouter.ai/api/v1`. OpenRouter uses the same API format as OpenAI.
- **Model:** **`openai/gpt-4o-mini`** (temperature 0). It supports strict structured
  outputs and costs about $0.15 per million input tokens and $0.60 per million output tokens.
- **How the model is used:** it only *reads* each message. It returns a fixed-shape
  `ParsedInput` form (the intent, any project fields, which project you're referring to),
  using `with_structured_output(ParsedInput, method="json_schema", strict=True)`. All
  decisions, such as "are the required fields present?", "save" and "delete", are made by
  plain Python code in the graph.
- **Switching models:** change `OPENROUTER_MODEL`, e.g. `anthropic/claude-haiku-5.5` or
  `openai/gpt-4.1-mini`. Pick a model whose OpenRouter page lists *structured outputs*.

To check your key and model with a few sample sentences:

```bash
python scripts/check_llm.py
```

## 4. Run the app and the tests

```bash
python main.py          # start the assistant; type quit or exit to leave (Ctrl+D also works)
pytest                  # run the test suite: fully offline, no API key needed
```

The tests replace the LLM with a `FakeParser` (`tests/fakes.py`) that returns scripted
answers. They cover storage, multi-turn creation, switching commands mid-draft,
cancelling, ambiguous names, corrections, choosing between same-named projects, delete
confirmation, LLM outages and the console loop.

---

## 5. How the LangGraph workflow works

Each line you type is **one run of the graph**. The graph is a flowchart in code: each box
(*node*) does one job, and arrows (*edges*) pick the next box based on the **state**, a
dictionary passed between nodes.

```
START → parse_input ──┬─ create / provide_info → merge_draft ─┬─ ambiguous → ask_clarify ┐
                      │    / clarified                        ├─ missing → ask_missing ───┤
                      │                                       └─ complete → save_project ─┤
                      ├─ list ──────────────→ list_projects ──────────────────────────────┤
                      ├─ get/update/delete ─→ resolve_project ─┬─ 1 match → show_project ─┤
                      ├─ choose ────────────↗                  │           update_project ┤
                      │                                        │           confirm_delete ┤
                      │                                        └─ 0 or 2+ matches ────────┤
                      ├─ confirm_yes → delete_project ────────────────────────────────────┤
                      ├─ confirm_no  → cancel_delete ─────────────────────────────────────┤
                      ├─ delete_all           → start_delete_all ─────────────────────────┤
                      ├─ delete_all_yes       → confirm_delete_all ───────────────────────┤
                      ├─ delete_all_confirmed → delete_all_projects ──────────────────────┤
                      ├─ delete_all_no        → cancel_delete_all ────────────────────────┤
                      ├─ cancel      → cancel_pending ────────────────────────────────────┤
                      ├─ help        → show_help ─────────────────────────────────────────┤
                      └─ unclear     → clarify ───────────────────────────────────────────┤
                                                                       finalize → END  ◄──┘
```

**State** (`project_agent/graph/state.py`):
- *Per turn:* `user_input`, `parsed`, `route`, `op`, `target_id`, `changes`, `notes`,
  `response`.
- *Remembered between turns:* `draft` (the half-built project), `awaiting` (`fields`,
  `clarify_field`, `which_project` or `confirm_delete`) and `pending_op` (e.g. the
  candidates for "which one?", or the value waiting for "project name or customer?"). These are kept by LangGraph's `InMemorySaver` checkpointer under one `thread_id`.

**Multi-turn slot filling:**
1. `parse_input` sends your message to the LLM along with context: the current draft and
   the field the app just asked for. That's how a bare reply like `Siam Retail Co.` is
   understood as `customer`.
2. `merge_draft` validates the new fields (dates must be `YYYY-MM-DD`, status must be a
   known value). It removes any fields listed in `clear_fields` (corrections like
   *"X is not the project name"* or *"remove the location"*), then adds the new values.
   A clear that names a project, or comes with no draft open (*"clear start date of
   Alpha"*), is always routed as an **update** of that existing project, never a new draft.
   Required fields can't be cleared, only changed.
3. **No guessing:**
   - If the LLM can't tell which field a value belongs to, it returns it as
     `ambiguous_value` and the app asks *"Is 'Dresswell' the project name or the
     customer?"*.
   - As checks that don't depend on the LLM, the app also asks if the project name and
     the customer end up identical, or if your reply is *just a name* while both are still
     unknown, even when the LLM guessed a field. Stray characters the LLM sometimes leaves
     in values (e.g. `Dresswell},`) are stripped before saving.
   - The replies `project name`, `customer` and `both` are matched without calling the
     LLM. `both` is how you confirm a project really is named after its customer.
4. The `check_required` edge routes to `ask_clarify` if a value still needs a home. Next
   it looks for `project_name` and `customer` in plain code: if either is missing,
   `ask_missing` asks for it and the draft waits in state. Otherwise `save_project`
   writes it to `projects.json`.
5. If you type a different command while a draft is waiting, it runs normally and
   `finalize` adds a reminder about the unfinished draft. `cancel` throws the draft away.
   If you move on while a "project name or customer?" question is open, that one value is
   set aside, with a note, and the rest of the draft is kept.

**Safety and robustness:**
- `cancel`, `help`, `list`, `yes`/`no` and choosing by number are matched without
  calling the LLM, so they work even when the API is down.
- Delete always asks first. Only `yes`/`y`/`confirm` deletes. Anything else keeps the
  project, and a new command typed instead is run as normal.
- Delete-all asks you to type the exact phrase `delete all` (a plain `yes` is not enough).
  The fixed phrases and the confirmation are handled in plain code, so a misread by the
  model can never wipe data on its own.
- A status or start date is kept only if your own words mention one (a status word;
  a number, month, weekday, "today", "tomorrow", "next"…). So the model can't invent
  `status: planned` or quietly use today's date.
- Relative dates are worked out in code (`project_agent/dates.py`), because LLMs
  miscount weekdays. The model also returns your exact words (`start_date_text`), and
  phrases like "today", "tomorrow", "next/this Monday" and "in 2 weeks" are
  calculated from today's date. **"Next Monday" means the coming Monday.** Other phrases
  ("Dec 3", "end of March") use the model's date. The resolved date is always shown in
  the reply.
- LLM errors get one retry, then a friendly message, and the draft is kept. Replies in an
  unexpected format are treated as unclear input.
- `projects.json` is written to a temporary file first and then swapped in, so a crash
  can't leave a half-written file. An unreadable file is renamed to `*.corrupt-<time>.bak`
  and the app starts with an empty list.

### Code layout

```
main.py                    entry point (load config → storage → LLM parser → graph → loop)
project_agent/
  config.py                .env loading and validation
  llm.py                   OpenRouter ChatOpenAI + LLMParser (structured output, retries)
  models.py                Project, ParsedInput, field validation helpers
  dates.py                 relative-date phrases → real dates (no LLM)
  storage.py               ProjectRepository (JSON file, IDs, safe writes)
  formatting.py            console text for projects
  agent.py                 ProjectAssistant: text in → graph run → reply out
  cli.py                   stdin/stdout loop (quit/exit, Ctrl+C/D, catch-all errors)
  graph/state.py           AgentState
  graph/prompts.py         system prompt for parsing
  graph/nodes.py           node functions
  graph/routing.py         edge functions
  graph/builder.py         wires the StateGraph
scripts/check_llm.py       live smoke test against OpenRouter
tests/                     offline pytest suite (FakeParser)
```

---

## 6. Example console sessions

The project text below is real app output. Exactly how the LLM pulls out fields can vary
slightly from model to model.

### Session 1: creating a project over several turns (with a command in the middle)

```text
> list
You don't have any projects yet. Try: "create a project called Alpha for customer Acme".

> I need a new project for our Bangkok office, starting December 1
Got it (start date: 2026-12-01, location: Bangkok office). What's the project name, and who is the customer?

> It's called Office Fit-out
Got it (start date: 2026-12-01, location: Bangkok office, project name: Office Fit-out). Who is the customer?

> show my projects
You don't have any projects yet. Try: "create a project called Alpha for customer Acme".
(You still have an unfinished project "Office Fit-out", missing: customer. Reply with it, or type "cancel".)

> Siam Retail Co.
Done. Created project "Office Fit-out" for customer Siam Retail Co. (start: 2026-12-01, location: Bangkok office).
```

### Session 2: listing, get, update and delete (with confirmation)

```text
> create a project called Alpha for customer Acme
Done. Created project "Alpha" for customer Acme.

> Add Website Redesign for Acme Corp, status in progress
Done. Created project "Website Redesign" for customer Acme Corp (status: active).

> list projects
Here are your projects (3):
1. Office Fit-out — customer: Siam Retail Co. · start: 2026-12-01 · location: Bangkok office
2. Alpha — customer: Acme
3. Website Redesign — customer: Acme Corp · status: active

> show details of website redesign
Project "Website Redesign" — customer: Acme Corp
Status: active

> change Website Redesign location to Chiang Mai
Done. Updated project "Website Redesign": location → Chiang Mai.

> clear start date of Office Fit-out
Done. Updated project "Office Fit-out": cleared start date.

> delete office fit-out
Delete project "Office Fit-out" (customer: Siam Retail Co.)? This cannot be undone. Type "yes" or "no".

> yes
Done. Deleted project "Office Fit-out".
```

### Session 3: two projects with the same name

Duplicate names are allowed. The app warns you when you create one, and asks "which one?"
whenever a name matches more than one project.

```text
> new project Website Redesign for Acme
Done. Created project "Website Redesign" for customer Acme.

> new project Website Redesign for Globex in Bangkok
Done. Created project "Website Redesign" for customer Globex (location: Bangkok).
Note: you now have more than one project named "Website Redesign".

> list
Here are your projects (2):
1. Website Redesign — customer: Acme
2. Website Redesign — customer: Globex · location: Bangkok

> mark Website Redesign as active
I found 2 projects matching "Website Redesign":
1. Website Redesign — customer: Acme
2. Website Redesign — customer: Globex · location: Bangkok
Which one do you want to update? (reply with the number)

> 1
Done. Updated project "Website Redesign": status → active.

> delete Website Redesign
I found 2 projects matching "Website Redesign":
1. Website Redesign — customer: Acme · status: active
2. Website Redesign — customer: Globex · location: Bangkok
Which one do you want to delete? (reply with the number)

> 2
Delete project "Website Redesign" (customer: Globex)? This cannot be undone. Type "yes" or "no".

> yes
Done. Deleted project "Website Redesign".

> list
Here are your projects (1):
1. Website Redesign — customer: Acme · status: active
```

### Session 4: deleting all projects (typed confirmation)

```text
> delete all projects
This will permanently delete ALL 2 projects:
1. Alpha — customer: Acme
2. Beta — customer: Globex · status: active
Type "delete all" to confirm. Anything else cancels.

> yes
OK, nothing was deleted. (Confirming needs the exact words "delete all".)

> delete all projects
...
Type "delete all" to confirm. Anything else cancels.

> delete all
Done. Deleted all 2 projects.
```

### Session 5: unclear input and exit

```text
> what's the weather tomorrow?
Sorry, I didn't understand that. You can create, list, show, update or delete projects — for example "list" or "new project Apollo for Acme". Type "help" for more.

> asdf qwer
Sorry, I didn't understand that. You can create, list, show, update or delete projects — for example "list" or "new project Apollo for Acme". Type "help" for more.

> cancel
Nothing to cancel.

> exit
Goodbye!
```

---

## Limitations

- An unfinished draft lives in memory only. It's lost if you quit before saving; saved
  projects are always in `projects.json`.
- IDs are hidden, so two projects with the same name *and* customer look identical in
  lists. When you get, update or delete one, the app asks which one and you pick by number.
- Single user, single process. Editing `projects.json` by hand while the app runs may be
  overwritten.

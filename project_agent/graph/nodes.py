"""Graph nodes. Each node reads the state and returns the keys it changes."""

from __future__ import annotations

import json
from datetime import date
from typing import Callable
from typing import Optional

from ..dates import resolve_relative_date
from ..formatting import (
    created_message,
    describe_fields,
    numbered,
    project_detail,
    project_line,
    project_list,
    updated_message,
)
from ..llm import InputParser, LLMUnavailableError
from ..models import (
    FIELD_LABELS,
    REQUIRED_FIELDS,
    ParsedInput,
    ProjectFields,
    clean_fields,
    missing_required,
    mentions_date,
    mentions_status,
    normalize_id,
    tidy_value,
)
from ..storage import ProjectRepository, StorageError
from .state import AgentState

YES_WORDS = {"yes", "y", "confirm", "yes delete", "yes, delete"}
NO_WORDS = {"no", "n", "nope", "cancel", "stop", "don't", "dont"}
CANCEL_WORDS = {"cancel", "never mind", "nevermind", "forget it", "abort"}
HELP_WORDS = {"help", "?", "h", "commands"}
LIST_WORDS = {"list", "ls", "list projects", "show projects", "show all projects"}
DELETE_ALL_WORDS = {
    "delete all", "delete all projects", "delete all the projects", "delete every project",
    "clear all", "clear all projects", "clear all the projects",
    "remove all", "remove all projects", "remove all the projects",
}
DELETE_ALL_PHRASE = "delete all"  # must be typed exactly at the final confirmation step
CONFIRM_LIST_LIMIT = 10

# Answers to "Is 'X' the project name or the customer?" that need no LLM.
FIELD_ANSWERS = {
    "project_name": {"project name", "project", "name", "project title", "title", "project_name"},
    "customer": {"customer", "client", "customer name", "client name"},
}
BOTH_WORDS = {"both", "both of them", "both fields", "it's both", "its both"}
_ANSWER_PREFIXES = ("it's the ", "its the ", "it is the ", "the ", "it's ", "its ", "it is ")

HELP_TEXT = """\
Here's what I can do (just type normally):
  • Create:  "New project Website Redesign for Acme Corp, starting 2026-12-01 in Bangkok"
  • List:    "list" or "show my projects"
  • Get:     "show Website Redesign"
  • Update:  "set Website Redesign status to active"
  • Clear:   "clear start date of Website Redesign"
  • Delete:  "delete Website Redesign" (I'll always ask you to confirm)
  • Delete all: "delete all projects" (asks you to type "delete all" to confirm)
  • cancel:  abandon an unfinished project or pending question
  • quit / exit: leave the app
Required for a new project: project name and customer.
Optional: start date, location, status (planned, active, on_hold, completed, cancelled), notes."""

UNCLEAR_TEXT = (
    "Sorry, I didn't understand that. You can create, list, show, update or delete "
    "projects — for example \"list\" or \"new project Apollo for Acme\". Type \"help\" "
    "for more."
)


def _is_iso_date(value: str) -> bool:
    try:
        date.fromisoformat(value.strip())
    except ValueError:
        return False
    return True


class Nodes:
    def __init__(
        self,
        parser: InputParser,
        repo: ProjectRepository,
        today: Callable[[], date] = date.today,
    ):
        self.parser = parser
        self.repo = repo
        self.today = today

    # ================================================================ parse
    def parse_input(self, state: AgentState) -> AgentState:
        text = state["user_input"].strip()
        low = text.casefold().rstrip(".!")
        awaiting = state.get("awaiting")
        pending = state.get("pending_op") or {}
        out: AgentState = {}
        notes: list[str] = []

        # --- Delete confirmation: only an explicit yes deletes. Anything else cancels it.
        if awaiting == "confirm_delete":
            if low in YES_WORDS:
                return {"route": "confirm_yes"}
            if low in NO_WORDS:
                return {"route": "confirm_no"}
            notes.append(f"OK, I did not delete {pending.get('label', 'the project')}.")
            out.update(awaiting=None, pending_op=None)
            awaiting, pending = None, {}

        # --- Delete-ALL confirmation: only the exact phrase deletes. Anything else cancels.
        if awaiting == "confirm_delete_all":
            if low == DELETE_ALL_PHRASE:
                return {"route": "delete_all_confirmed"}
            if low in YES_WORDS | NO_WORDS:
                return {"route": "delete_all_no"}
            notes.append("OK, nothing was deleted.")
            out.update(awaiting=None, pending_op=None)
            awaiting, pending = None, {}

        # --- "Is 'X' the project name or the customer?" answered plainly: no LLM needed.
        if awaiting == "clarify_field":
            picked = self._match_field_answer(low, pending.get("fields", []))
            if picked:
                value = pending["value"]
                draft = state.get("draft") or {}
                # The value belongs ONLY to the picked field(s): drop it from the others.
                stale = [
                    f
                    for f in pending.get("fields", [])
                    if f not in picked and (draft.get(f) or "").casefold() == value.casefold()
                ]
                return {
                    "route": "clarified",
                    "awaiting": None,
                    "pending_op": None,
                    "allow_same": len(picked) > 1,
                    "parsed": ParsedInput.make(
                        "provide_info", clear_fields=stale, **{f: value for f in picked}
                    ).model_dump(),
                }

        # --- "Which project?" answered with a number or ID: no LLM needed.
        if awaiting == "which_project":
            pick = self._match_choice(low, pending.get("candidates", []))
            if pick:
                return {"route": "choose", "target_id": pick}

        # --- Fixed words that must work even when the LLM is down.
        if low in CANCEL_WORDS:
            return {**out, "notes": notes, "route": "cancel"}
        if low in HELP_WORDS:
            return self._leave_pending(awaiting, pending, {**out, "notes": notes, "route": "help"})
        if low in LIST_WORDS:
            return self._leave_pending(awaiting, pending, {**out, "notes": notes, "route": "list"})
        if low in DELETE_ALL_WORDS:
            return self._leave_pending(
                awaiting, pending, {**out, "notes": notes, "route": "delete_all"}
            )

        # --- Everything else goes to the LLM.
        context_state = {**state, **out}
        try:
            parsed = self.parser.parse(text, self._context(context_state))
        except LLMUnavailableError as exc:
            return {**out, "notes": notes, "route": "error", "response": str(exc)}

        parsed = self._resolve_start_date(text, parsed)
        parsed = self._drop_invented_values(text, parsed)
        parsed = self._force_ambiguous_bare_name(text, parsed, state)
        route = parsed.intent
        result: AgentState = {**out, "notes": notes, "parsed": parsed.model_dump()}

        if route == "choose":
            if awaiting != "which_project":
                route = "unclear"
            else:
                result["target_id"] = self._match_choice(
                    (parsed.choice or "").casefold(), pending.get("candidates", [])
                )
        elif (
            route in ("provide_info", "create")
            and parsed.clear_fields
            and (state.get("draft") is None or parsed.project_ref)
        ):
            # Safety net: clearing a field with no draft open (or naming a project) can
            # only mean an EXISTING project — never start a new draft from it.
            parsed = self._as_clear_update(parsed)
            result["parsed"] = parsed.model_dump()
            route = "update"
        elif route == "provide_info" and state.get("draft") is None:
            # Details with no draft in progress: treat as starting a new project.
            has_details = any(v for v in parsed.fields.model_dump().values())
            route = "create" if has_details or parsed.ambiguous_value else "unclear"

        if awaiting == "clarify_field" and route == "provide_info":
            # A free-text answer to "project name or customer?"; if the user put the
            # value in both fields, that was their explicit choice.
            result["allow_same"] = True

        result["route"] = route
        return self._leave_pending(awaiting, pending, result)

    def _resolve_start_date(self, text: str, parsed: ParsedInput) -> ParsedInput:
        """LLMs miscount weekdays ('next Monday' -> a Saturday). If the user's own words
        are a common relative phrase, compute the date in code instead."""
        words = (parsed.start_date_text or "").strip()
        if not words or words.casefold() not in text.casefold():
            return parsed  # no phrase, or the model made it up: keep the model's value
        resolved = resolve_relative_date(words, self.today())
        if resolved is None:
            return parsed  # e.g. "Dec 3": the model's YYYY-MM-DD is used
        fields = parsed.fields.model_copy(update={"start_date": resolved.isoformat()})
        return parsed.model_copy(update={"fields": fields})

    @staticmethod
    def _drop_invented_values(text: str, parsed: ParsedInput) -> ParsedInput:
        """The LLM sometimes adds values nobody asked for (status='planned', today's date
        as start_date). Keep them only if the user's own words mention them."""
        drop = {}
        if parsed.fields.status and not mentions_status(text):
            drop["status"] = None
        start = parsed.fields.start_date
        # Only a *valid* date the user never mentioned is invented. An unreadable value
        # ("someday") came from the user's words: keep it so clean_fields can explain.
        if start and not mentions_date(text) and _is_iso_date(start):
            drop["start_date"] = None
        if not drop:
            return parsed
        return parsed.model_copy(update={"fields": parsed.fields.model_copy(update=drop)})

    @staticmethod
    def _force_ambiguous_bare_name(text: str, parsed: ParsedInput, state: AgentState) -> ParsedInput:
        """Never let the LLM guess: a reply that is ONLY a name, given while both the
        project name and the customer are still unknown, must be asked about."""
        draft = state.get("draft")
        both_unknown = draft is None and not state.get("awaiting")
        both_unknown = both_unknown or (
            state.get("awaiting") == "fields"
            and draft is not None
            and missing_required(draft) == list(REQUIRED_FIELDS)
        )
        if (
            not both_unknown
            or parsed.intent not in ("create", "provide_info")
            or parsed.ambiguous_value
            or parsed.clear_fields
        ):
            return parsed

        def norm(value: str) -> str:
            return tidy_value(value).strip(".!?").casefold()

        bare = norm(text)
        fields = parsed.fields.model_dump()
        hits = [f for f in REQUIRED_FIELDS if fields.get(f) and norm(fields[f]) == bare]
        if not bare or not hits:
            return parsed  # the user said more than just a name, e.g. "it's called X"
        value = tidy_value(fields[hits[0]])  # the model's cleaned spelling, e.g. no "."
        for name in hits:
            fields[name] = None
        return parsed.model_copy(
            update={"fields": ProjectFields(**fields), "ambiguous_value": value}
        )

    @staticmethod
    def _as_clear_update(parsed: ParsedInput) -> ParsedInput:
        """Turn a mis-read 'clear X of <project>' into an update of that project.

        If the LLM didn't fill project_ref, the project name it put into a field
        (e.g. customer="Dresswell") is the project being referred to.
        """
        fields = parsed.fields.model_dump()
        ref = parsed.project_ref
        if not ref:
            for name in REQUIRED_FIELDS:
                if fields.get(name):
                    ref, fields[name] = fields[name], None
                    break
        return parsed.model_copy(
            update={"intent": "update", "project_ref": ref, "fields": ProjectFields(**fields)}
        )

    @staticmethod
    def _leave_pending(awaiting: Optional[str], pending: dict, result: AgentState) -> AgentState:
        """Drop a pending question the user has moved on from."""
        route = result.get("route")
        if awaiting == "which_project" and route != "choose":
            result.update(awaiting=None, pending_op=None)
        elif awaiting == "clarify_field":
            result.update(awaiting=None, pending_op=None)
            if route not in ("provide_info", "create", "cancel"):
                result["notes"] = list(result.get("notes") or []) + [
                    f"(I set \"{pending.get('value')}\" aside. Tell me later whether it's "
                    "the project name or the customer.)"
                ]
        return result

    @staticmethod
    def _match_field_answer(answer: str, fields: list[str]) -> list[str]:
        answer = answer.strip().strip(".!")
        if answer in BOTH_WORDS:
            return list(fields)
        for prefix in _ANSWER_PREFIXES:
            if answer.startswith(prefix):
                answer = answer[len(prefix):]
                break
        if answer in BOTH_WORDS:
            return list(fields)
        return [f for f in fields if answer in FIELD_ANSWERS.get(f, ())][:1]

    def _match_choice(self, answer: str, candidates: list[str]) -> Optional[str]:
        answer = answer.strip().strip(".").removeprefix("#").strip()
        if not answer:
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(candidates):
            return candidates[int(answer) - 1]
        pid = normalize_id(answer)
        return pid if pid in candidates else None

    def _context(self, state: AgentState) -> str:
        lines = []
        draft = state.get("draft")
        if draft:
            missing = missing_required(draft)
            lines.append(f"- Project draft in progress: {json.dumps(draft)}")
            if missing and state.get("awaiting") == "fields":
                asked = " and ".join(FIELD_LABELS[m] for m in missing)
                lines.append(f"- The assistant just asked the user for: {asked}")
        if state.get("awaiting") == "clarify_field":
            pending = state.get("pending_op") or {}
            lines.append(
                f"- The assistant asked whether \"{pending.get('value')}\" is the project name, "
                "the customer, or both."
            )
        if state.get("awaiting") == "which_project":
            pending = state.get("pending_op") or {}
            options = []
            for i, pid in enumerate(pending.get("candidates", []), 1):
                p = self.repo.get(pid)
                if p:
                    options.append(f"{i}. {project_line(p)}")
            lines.append(
                f"- The assistant asked which project to {pending.get('op')}; options:\n    "
                + "\n    ".join(options)
            )
        return "\n".join(lines) or "- No pending question."

    # ========================================================== create flow
    def merge_draft(self, state: AgentState) -> AgentState:
        parsed = ParsedInput.model_validate(state["parsed"])
        clean, problems = clean_fields(parsed.fields.model_dump())
        draft = dict(state.get("draft") or {})
        notes = list(state.get("notes") or [])

        new_name = clean.get("project_name")
        if (
            state["route"] == "create"
            and draft
            and new_name
            and draft.get("project_name")
            and new_name.casefold() != draft["project_name"].casefold()
        ):
            notes.append(
                f"Started a new project (the unfinished draft "
                f"\"{draft['project_name']}\" was discarded)."
            )
            draft = {}

        # 1. Corrections: remove fields the user said are wrong, then add new values.
        for name in parsed.clear_fields:
            old = draft.pop(name, None)
            if old is not None and name not in clean:
                notes.append(f"Removed {FIELD_LABELS[name]} \"{old}\".")
        draft.update(clean)
        notes.extend(problems)

        # 2. Never guess: a value the LLM couldn't place goes back to the user.
        ambiguous = tidy_value(parsed.ambiguous_value or "")

        # 3. Safety net (works even if the LLM missed a correction): the same value as
        #    both project name and customer is almost always a mix-up, so ask.
        name, customer = draft.get("project_name"), draft.get("customer")
        if (
            not ambiguous
            and not state.get("allow_same")
            and name
            and customer
            and name.casefold() == customer.casefold()
        ):
            ambiguous = name
            draft.pop("project_name")
            draft.pop("customer")

        if ambiguous:
            return {
                "draft": draft,
                "notes": notes,
                "awaiting": "clarify_field",
                "pending_op": {
                    "op": "clarify_field",
                    "value": ambiguous,
                    "fields": list(REQUIRED_FIELDS),
                },
            }

        if not clean and not parsed.clear_fields and state["route"] == "provide_info":
            notes.append("I didn't catch any project details in that.")
        return {"draft": draft, "notes": notes}

    def ask_clarify(self, state: AgentState) -> AgentState:
        value = (state.get("pending_op") or {}).get("value")
        known = describe_fields(state.get("draft") or {})
        prefix = f"Got it ({known}). " if known else ""
        return {
            "response": f"{prefix}Is \"{value}\" the project name or the customer? "
            "(Reply \"project name\", \"customer\", or \"both\".)"
        }

    def ask_missing(self, state: AgentState) -> AgentState:
        draft = state.get("draft") or {}
        missing = missing_required(draft)
        if missing == ["project_name", "customer"]:
            question = "What's the project name, and who is the customer?"
        elif missing == ["project_name"]:
            question = "What's the project name?"
        else:
            question = "Who is the customer?"
        known = describe_fields(draft)
        prefix = f"Got it ({known}). " if known else "Sure. "
        return {"awaiting": "fields", "response": prefix + question}

    def save_project(self, state: AgentState) -> AgentState:
        draft = state["draft"] or {}
        notes = list(state.get("notes") or [])
        same_name = self.repo.find_exact_name(draft["project_name"])
        try:
            project = self.repo.add(draft)
        except StorageError as exc:
            return {"response": f"{exc}\nYour draft is kept — please try again."}
        response = created_message(project)
        if same_name:
            response += f'\nNote: you now have more than one project named "{project.project_name}".'
        return {"draft": None, "awaiting": None, "notes": notes, "response": response}

    # ===================================================== existing projects
    def list_projects(self, state: AgentState) -> AgentState:
        return {"response": project_list(self.repo.list_all())}

    def resolve_project(self, state: AgentState) -> AgentState:
        if state["route"] == "choose":
            pending = state.get("pending_op") or {}
            if not state.get("target_id"):
                n = len(pending.get("candidates", []))
                return {"response": f"Please reply with a number from 1 to {n}."}
            return {
                "op": pending.get("op"),
                "changes": pending.get("changes"),
                "awaiting": None,
                "pending_op": None,
            }

        op = state["route"]
        parsed = ParsedInput.model_validate(state["parsed"])
        notes = list(state.get("notes") or [])
        ref = tidy_value(parsed.project_ref or "")
        changes: dict = {}
        if op == "update":
            changes, problems = clean_fields(parsed.fields.model_dump())
            notes.extend(problems)
            # Clearing: None means "empty this field". Required fields can't be emptied.
            for name in parsed.clear_fields:
                if name in REQUIRED_FIELDS:
                    notes.append(self._cannot_clear(name, ref))
                elif name not in changes:
                    changes[name] = None

        if not ref:
            return {
                "notes": notes,
                "response": f"Which project do you want to {op}? Tell me its name "
                "(type \"list\" to see them).",
            }

        matches = self.repo.find(ref)
        if not matches:
            return {
                "notes": notes,
                "response": f'I couldn\'t find a project matching "{ref}". '
                "Type \"list\" to see all projects.",
            }
        if len(matches) > 1:
            return {
                "notes": notes,
                "awaiting": "which_project",
                "pending_op": {
                    "op": op,
                    "changes": changes,
                    "candidates": [p.id for p in matches],
                },
                "response": f'I found {len(matches)} projects matching "{ref}":\n'
                f"{numbered(matches)}\nWhich one do you want to {op}? (reply with the number)",
            }
        return {"notes": notes, "op": op, "target_id": matches[0].id, "changes": changes}

    def show_project(self, state: AgentState) -> AgentState:
        project = self.repo.get(state["target_id"])
        if project is None:
            return {"response": "That project no longer exists."}
        return {"response": project_detail(project)}

    def update_project(self, state: AgentState) -> AgentState:
        pid = state["target_id"]
        current = self.repo.get(pid)
        if current is None:
            return {"response": "That project no longer exists."}
        name = current.project_name
        requested = state.get("changes") or {}
        # Skip clears of fields that are already empty.
        changes = {
            k: v for k, v in requested.items() if v is not None or getattr(current, k) is not None
        }
        if requested and not changes:
            empty = " or ".join(FIELD_LABELS[k] for k in requested)
            return {"response": f'Nothing to change: "{name}" has no {empty} set.'}
        if not changes:
            return {
                "response": f'What would you like to change on "{name}"? For example: '
                f'"set {name} status to active" or "clear start date of {name}".'
            }
        try:
            self.repo.update(pid, changes)
        except StorageError as exc:
            return {"response": f"{exc}\nNothing was changed."}
        return {"response": updated_message(name, changes)}

    @staticmethod
    def _cannot_clear(field: str, ref: str) -> str:
        project = ref or "<project>"
        example = (
            f'"rename {project} to <new name>"'
            if field == "project_name"
            else f'"change {project} customer to <new customer>"'
        )
        return (
            f"{FIELD_LABELS[field].capitalize()} is required, so it can't be cleared. "
            f"You can change it instead, e.g. {example}."
        )

    def confirm_delete(self, state: AgentState) -> AgentState:
        project = self.repo.get(state["target_id"])
        if project is None:
            return {"response": "That project no longer exists."}
        label = f'project "{project.project_name}"'
        return {
            "awaiting": "confirm_delete",
            "pending_op": {"op": "delete", "target_id": project.id, "label": label},
            "response": f'Delete project "{project.project_name}" (customer: {project.customer})? '
            "This cannot be undone. Type \"yes\" or \"no\".",
        }

    def delete_project(self, state: AgentState) -> AgentState:
        pending = state.get("pending_op") or {}
        cleared: AgentState = {"awaiting": None, "pending_op": None}
        try:
            project = self.repo.delete(pending["target_id"])
        except KeyError:
            return {**cleared, "response": "That project no longer exists."}
        except StorageError as exc:
            return {**cleared, "response": f"{exc}\nNothing was deleted."}
        return {**cleared, "response": f'Done. Deleted project "{project.project_name}".'}

    # ------------------------------------------------------- delete ALL projects
    def start_delete_all(self, state: AgentState) -> AgentState:
        projects = self.repo.list_all()
        if not projects:
            return {"response": "You don't have any projects to delete."}
        shown = projects[:CONFIRM_LIST_LIMIT]
        lines = numbered(shown)
        if len(projects) > len(shown):
            lines += f"\n…and {len(projects) - len(shown)} more"
        noun = "project" if len(projects) == 1 else "projects"
        return {
            "awaiting": "confirm_delete_all",
            "pending_op": {"op": "delete_all", "count": len(projects)},
            "response": f"This will permanently delete ALL {len(projects)} {noun}:\n{lines}\n"
            f'Type "{DELETE_ALL_PHRASE}" to confirm. Anything else cancels.',
        }

    def delete_all_projects(self, state: AgentState) -> AgentState:
        cleared: AgentState = {"awaiting": None, "pending_op": None}
        try:
            count = self.repo.delete_all()
        except StorageError as exc:
            return {**cleared, "response": f"{exc}\nNothing was deleted."}
        noun = "project" if count == 1 else "projects"
        return {**cleared, "response": f"Done. Deleted all {count} {noun}."}

    def cancel_delete_all(self, state: AgentState) -> AgentState:
        message = "OK, nothing was deleted."
        if state.get("user_input", "").strip().casefold().rstrip(".!") in YES_WORDS:
            message += f' (Confirming needs the exact words "{DELETE_ALL_PHRASE}".)'
        return {"awaiting": None, "pending_op": None, "response": message}

    def cancel_delete(self, state: AgentState) -> AgentState:
        label = (state.get("pending_op") or {}).get("label", "the project")
        return {
            "awaiting": None,
            "pending_op": None,
            "response": f"OK, I kept {label}. Nothing was deleted.",
        }

    # ================================================================ misc
    def cancel_pending(self, state: AgentState) -> AgentState:
        draft = state.get("draft")
        if draft:
            name = draft.get("project_name") or "untitled"
            message = f"OK, I discarded the unfinished project \"{name}\"."
        elif state.get("pending_op"):
            message = "OK, cancelled."
        else:
            message = "Nothing to cancel."
        return {"draft": None, "awaiting": None, "pending_op": None, "response": message}

    def show_help(self, state: AgentState) -> AgentState:
        return {"response": HELP_TEXT}

    def clarify(self, state: AgentState) -> AgentState:
        return {"response": UNCLEAR_TEXT}

    def finalize(self, state: AgentState) -> AgentState:
        """Compose the final reply and add the unfinished-draft reminder (answer 2b)."""
        parts = [n for n in (state.get("notes") or []) if n]
        if state.get("response"):
            parts.append(state["response"])

        draft = state.get("draft")
        awaiting = state.get("awaiting")
        if draft and awaiting is None:
            awaiting = "fields"  # go back to collecting the draft's missing fields
        if draft and awaiting == "fields" and state.get("route") not in (
            "create",
            "provide_info",
            "clarified",
        ):
            missing = " and ".join(FIELD_LABELS[m] for m in missing_required(draft))
            name = f" \"{draft['project_name']}\"" if draft.get("project_name") else ""
            parts.append(
                f"(You still have an unfinished project{name}, missing: {missing}. "
                "Reply with it, or type \"cancel\".)"
            )
        return {"response": "\n".join(parts) or UNCLEAR_TEXT, "awaiting": awaiting}

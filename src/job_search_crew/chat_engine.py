from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

from pydantic import ValidationError

from .crew import JobSearchCrew
from .models import (
    Intent,
    IntentResult,
    JobDetailSummary,
    JobListing,
    JobSearchOutput,
    ResponsibilitiesSummary,
    SmallTalkOutput,
)
from .settings import get_settings


def _to_model(result: Any, model_cls):
    """CrewAI may return pydantic, dict, JSON string, or CrewOutput. Normalise it."""
    if isinstance(result, model_cls):
        return result
    if hasattr(result, "pydantic") and result.pydantic is not None:
        return result.pydantic
    if hasattr(result, "json_dict") and result.json_dict:
        return model_cls.model_validate(result.json_dict)
    raw = str(result)
    try:
        return model_cls.model_validate_json(raw)
    except Exception:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if match:
            return model_cls.model_validate_json(match.group(0))
        raise ValueError(f"Could not parse CrewAI output as {model_cls.__name__}: {raw[:500]}")


def _jobs_to_rows(jobs: List[JobListing]) -> List[List[str]]:
    rows = []
    for idx, job in enumerate(jobs, start=1):
        rows.append([
            str(idx),
            job.title,
            job.company,
            job.location,
            job.posted_date or "",
            job.salary or "",
            job.source or "",
            job.url or "",
        ])
    return rows


def _format_search_answer(search: JobSearchOutput, summary: ResponsibilitiesSummary) -> str:
    lines = [
        f"Found **{len(search.jobs)}** jobs for **{search.role}** in **{search.location}**.",
        "",
        "### Common responsibilities",
    ]
    lines += [f"- {x}" for x in summary.common_responsibilities[:6]] or ["- Not enough detail found."]
    lines += ["", "### Common required skills/tools"]
    lines += [f"- {x}" for x in summary.required_skills[:8]] or ["- Not enough detail found."]
    lines += ["", "### Application tips"]
    lines += [f"- {x}" for x in summary.application_tips[:5]] or ["- Tailor your resume to the job description."]
    if search.search_notes:
        lines += ["", f"_Search notes: {search.search_notes[:300]}_"]
    lines += ["", "Ask **summarize job 1** to inspect a listed job."]
    return "\n".join(lines)


def _format_job_detail(detail: JobDetailSummary) -> str:
    lines = [
        f"### {detail.title} — {detail.company}",
        f"**Location:** {detail.location}",
        "",
        detail.role_summary or "No summary available.",
    ]
    if detail.responsibilities:
        lines += ["", "**Responsibilities**"] + [f"- {x}" for x in detail.responsibilities]
    if detail.required_skills:
        lines += ["", "**Required skills**"] + [f"- {x}" for x in detail.required_skills]
    if detail.nice_to_have_skills:
        lines += ["", "**Nice-to-have skills**"] + [f"- {x}" for x in detail.nice_to_have_skills]
    if detail.salary:
        lines += ["", f"**Salary:** {detail.salary}"]
    if detail.fit_notes:
        lines += ["", "**Fit notes**"] + [f"- {x}" for x in detail.fit_notes]
    if detail.source_url:
        lines += ["", f"Source: {detail.source_url}"]
    if detail.access_notes:
        lines += ["", f"_Access notes: {detail.access_notes}_"]
    return "\n".join(lines)


class ChatEngine:
    def __init__(self) -> None:
        self.settings = get_settings()

    def empty_state(self) -> Dict[str, Any]:
        return {
            "current_role": "",
            "current_location": "",
            "jobs": [],
        }

    def _fallback_intent(self, message: str, state: Dict[str, Any]) -> IntentResult:
        # Cheap fallback for demo runs without API keys.
        lower = message.lower().strip()
        m = re.search(r"(.+?)\s+in\s+([a-zA-Z ,.-]+)$", message.strip())
        if m:
            return IntentResult(intent=Intent.new_search, role=m.group(1).strip(), location=m.group(2).strip(), question=message, reasoning="regex fallback")
        m = re.search(r"(?:job|row)\s*(\d+)|summari[sz]e\s*(?:job|row)?\s*(\d+)", lower)
        if m and state.get("jobs"):
            idx = int(next(x for x in m.groups() if x))
            return IntentResult(intent=Intent.job_detail, selected_job_index=idx, question=message, reasoning="regex fallback")
        if state.get("jobs") and any(k in lower for k in ["common", "compare", "skills", "responsibilities", "summary"]):
            return IntentResult(intent=Intent.current_results_question, question=message, reasoning="regex fallback")
        return IntentResult(intent=Intent.small_talk, question=message, reasoning="regex fallback")

    def route(self, message: str, state: Dict[str, Any]) -> IntentResult:
        try:
            crew = JobSearchCrew().intent_crew()
            print(crew)
            result = crew.kickoff(inputs={
                "message": message,
                "current_role": state.get("current_role", ""),
                "current_location": state.get("current_location", ""),
                "job_count": len(state.get("jobs", [])),
            })
            return _to_model(result, IntentResult)
        except Exception:
            return self._fallback_intent(message, state)

    def respond(self, message: str, history: List[Dict[str, str]], state: Dict[str, Any] | None):
        state = state or self.empty_state()
        intent = self.route(message, state)
        print(intent)
        try:
            if intent.intent == Intent.new_search and intent.role and intent.location:
                # Run the deterministic search tool first so the UI always gets concrete table rows.
                # CrewAI is then used for analysis/summarisation of those rows.
                from .tools import PublicJobSearchTool

                raw = PublicJobSearchTool()._run(intent.role, intent.location, self.settings.max_jobs)
                search_output = JobSearchOutput.model_validate_json(raw)

                result = JobSearchCrew().current_results_crew().kickoff(inputs={
                    "current_role": search_output.role,
                    "current_location": search_output.location,
                    "jobs_json": json.dumps([j.model_dump() for j in search_output.jobs], indent=2),
                    "question": "Summarise the common responsibilities, required skills, nice-to-have skills, seniority signals and application tips from these job listings.",
                })
                answer_text = _to_model(result, SmallTalkOutput).answer

                # Convert the answer into the same display format without depending on the summary task as final output.
                summary = ResponsibilitiesSummary(
                    role=search_output.role,
                    location=search_output.location,
                    summary=answer_text,
                    common_responsibilities=[],
                    required_skills=[],
                    nice_to_have_skills=[],
                    seniority_signals=[],
                    application_tips=[],
                )

                state = {
                    "current_role": search_output.role,
                    "current_location": search_output.location,
                    "jobs": [j.model_dump() for j in search_output.jobs],
                }
                answer = f"Found **{len(search_output.jobs)}** jobs for **{search_output.role}** in **{search_output.location}**.\n\n" + answer_text
                if search_output.search_notes:
                    answer += f"\n\n_Search notes: {search_output.search_notes[:400]}_"
                answer += "\n\nClick a row in the table or ask **summarise job 1** to inspect a listed job."
                return answer, _jobs_to_rows(search_output.jobs), state

            if intent.intent == Intent.job_detail:
                jobs = [JobListing.model_validate(j) for j in state.get("jobs", [])]
                if not jobs:
                    return "Please search for a role and location first, for example **Data Engineer in Raleigh**.", [], state
                idx = intent.selected_job_index or 1
                if idx < 1 or idx > len(jobs):
                    return f"I can see {len(jobs)} jobs. Please choose a number between 1 and {len(jobs)}.", _jobs_to_rows(jobs), state
                selected = jobs[idx - 1]
                result = JobSearchCrew().detail_crew().kickoff(inputs={
                    "selected_job_json": json.dumps(selected.model_dump(), indent=2),
                    "question": intent.question or message,
                })
                detail = _to_model(result, JobDetailSummary)
                return _format_job_detail(detail), _jobs_to_rows(jobs), state

            if intent.intent == Intent.current_results_question:
                jobs = [JobListing.model_validate(j) for j in state.get("jobs", [])]
                if not jobs:
                    return "Please search first, for example **Business Analyst in Charlotte**.", [], state
                result = JobSearchCrew().current_results_crew().kickoff(inputs={
                    "current_role": state.get("current_role", ""),
                    "current_location": state.get("current_location", ""),
                    "jobs_json": json.dumps(state.get("jobs", []), indent=2),
                    "question": intent.question or message,
                })
                answer = _to_model(result, SmallTalkOutput).answer
                return answer, _jobs_to_rows(jobs), state

            result = JobSearchCrew().small_talk_crew().kickoff(inputs={"message": message})
            answer = _to_model(result, SmallTalkOutput).answer
            jobs = [JobListing.model_validate(j) for j in state.get("jobs", [])]
            return answer, _jobs_to_rows(jobs), state

        except Exception as exc:
            jobs = [JobListing.model_validate(j) for j in state.get("jobs", [])]
            return (
                "I hit an error while running the CrewAI workflow. "
                f"Details: `{type(exc).__name__}: {exc}`\n\n"
                "Check that your API keys are set and the Space has restarted after adding secrets.",
                _jobs_to_rows(jobs),
                state,
            )

    def summarize_selected_row(self, row_data: Any, state: Dict[str, Any] | None):
        state = state or self.empty_state()
        if row_data is None:
            return "Select a job row first.", state
        try:
            idx = int(row_data[0]) if isinstance(row_data, (list, tuple)) else 1
        except Exception:
            idx = 1
        answer, _rows, state = self.respond(f"summarize job {idx}", [], state)
        return answer, state
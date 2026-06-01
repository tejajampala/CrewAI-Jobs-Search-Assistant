from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from crewai import Agent, Crew, LLM, Process, Task
from crewai.project import CrewBase, agent, crew, task

from .models import (
    IntentResult,
    JobDetailSummary,
    JobSearchOutput,
    ResponsibilitiesSummary,
    SmallTalkOutput,
)
from .settings import get_settings
from .tools import get_job_tools

CONFIG_DIR = Path(__file__).parent / "config"


@CrewBase
class JobSearchCrew:
    """CrewAI crew using YAML agents/tasks config.

    The Gradio app calls one small crew per interaction. This keeps state in Gradio
    and keeps CrewAI execution focused and debuggable.
    """

    agents_config = str(CONFIG_DIR / "agents.yaml")
    tasks_config = str(CONFIG_DIR / "tasks.yaml")

    def __init__(self) -> None:
        self.settings = get_settings()
        self.openai_llm = LLM(model=f"openai/{self.settings.openai_model}", temperature=0.1)
        self.anthropic_llm = LLM(model=f"anthropic/{self.settings.anthropic_model}", temperature=0.1)
        self.web_tools = get_job_tools(use_website_search=self.settings.use_website_search)

    def _llm_for(self, provider_name: str):
        return self.anthropic_llm if provider_name == "anthropic" else self.openai_llm

    def _agent_from_yaml(self, name: str, tools: List[Any] | None = None) -> Agent:
        cfg = dict(self.agents_config[name])
        provider = cfg.pop("llm", "openai")
        return Agent(config=cfg, llm=self._llm_for(provider), tools=tools or [])

    @agent
    def intent_router(self) -> Agent:
        return self._agent_from_yaml("intent_router")

    @agent
    def job_researcher(self) -> Agent:
        return self._agent_from_yaml("job_researcher", tools=self.web_tools)

    @agent
    def role_analyst(self) -> Agent:
        return self._agent_from_yaml("role_analyst")

    @agent
    def job_description_reader(self) -> Agent:
        return self._agent_from_yaml("job_description_reader", tools=self.web_tools)

    @agent
    def small_talk_assistant(self) -> Agent:
        return self._agent_from_yaml("small_talk_assistant")

    @task
    def classify_intent_task(self) -> Task:
        return Task(
            config=self.tasks_config["classify_intent_task"],
            output_pydantic=IntentResult,
        )

    @task
    def job_search_task(self) -> Task:
        return Task(
            config=self.tasks_config["job_search_task"],
            output_pydantic=JobSearchOutput,
        )

    @task
    def responsibilities_summary_task(self) -> Task:
        return Task(
            config=self.tasks_config["responsibilities_summary_task"],
            output_pydantic=ResponsibilitiesSummary,
        )

    @task
    def job_detail_task(self) -> Task:
        return Task(
            config=self.tasks_config["job_detail_task"],
            output_pydantic=JobDetailSummary,
        )

    @task
    def current_results_question_task(self) -> Task:
        return Task(
            config=self.tasks_config["current_results_question_task"],
            output_pydantic=SmallTalkOutput,
        )

    @task
    def small_talk_task(self) -> Task:
        return Task(
            config=self.tasks_config["small_talk_task"],
            output_pydantic=SmallTalkOutput,
        )

    def intent_crew(self) -> Crew:
        return Crew(
            agents=[self.intent_router()],
            tasks=[self.classify_intent_task()],
            process=Process.sequential,
            verbose=False,
        )

    def search_crew(self) -> Crew:
        return Crew(
            agents=[self.job_researcher(), self.role_analyst()],
            tasks=[self.job_search_task(), self.responsibilities_summary_task()],
            process=Process.sequential,
            verbose=False,
        )

    def detail_crew(self) -> Crew:
        return Crew(
            agents=[self.job_description_reader()],
            tasks=[self.job_detail_task()],
            process=Process.sequential,
            verbose=False,
        )

    def current_results_crew(self) -> Crew:
        return Crew(
            agents=[self.role_analyst()],
            tasks=[self.current_results_question_task()],
            process=Process.sequential,
            verbose=False,
        )

    def small_talk_crew(self) -> Crew:
        return Crew(
            agents=[self.small_talk_assistant()],
            tasks=[self.small_talk_task()],
            process=Process.sequential,
            verbose=False,
        )

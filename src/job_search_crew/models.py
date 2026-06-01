from __future__ import annotations

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, HttpUrl


class Intent(str, Enum):
    new_search = "new_search"
    job_detail = "job_detail"
    current_results_question = "current_results_question"
    small_talk = "small_talk"


class IntentResult(BaseModel):
    intent: Intent = Field(description="The routed user intent")
    role: Optional[str] = Field(default=None, description="Job role for a new search")
    location: Optional[str] = Field(default=None, description="Location for a new search")
    selected_job_index: Optional[int] = Field(default=None, description="1-based selected job row number")
    question: str = Field(default="", description="The user's question rewritten clearly")
    reasoning: str = Field(default="", description="Brief routing reason")


class JobListing(BaseModel):
    title: str
    company: str = "Unknown"
    location: str = "Unknown"
    url: Optional[str] = None
    source: Optional[str] = None
    posted_date: Optional[str] = None
    salary: Optional[str] = None
    description_snippet: Optional[str] = None


class JobSearchOutput(BaseModel):
    role: str
    location: str
    jobs: List[JobListing] = Field(default_factory=list)
    search_notes: str = ""


class ResponsibilitiesSummary(BaseModel):
    role: str
    location: str
    common_responsibilities: List[str] = Field(default_factory=list)
    required_skills: List[str] = Field(default_factory=list)
    nice_to_have_skills: List[str] = Field(default_factory=list)
    seniority_signals: List[str] = Field(default_factory=list)
    application_tips: List[str] = Field(default_factory=list)
    summary: str = ""


class JobDetailSummary(BaseModel):
    title: str
    company: str
    location: str
    role_summary: str = ""
    responsibilities: List[str] = Field(default_factory=list)
    required_skills: List[str] = Field(default_factory=list)
    nice_to_have_skills: List[str] = Field(default_factory=list)
    salary: Optional[str] = None
    fit_notes: List[str] = Field(default_factory=list)
    source_url: Optional[str] = None
    access_notes: str = ""


class SmallTalkOutput(BaseModel):
    answer: str

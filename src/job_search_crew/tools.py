"""
tools.py

Fast CrewAI-compatible tools for the Gradio Job Search app.

Fixes included:
- Avoids advanced Serper query patterns blocked on free accounts.
- Reduces Gradio freezing by limiting Serper calls and timeouts.
- Displays clean role/title instead of "Job Search".
- Keeps compatibility with:
  get_job_tools(use_website_search=False)
  get_crewai_web_tools(use_website_search=False)
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from crewai.tools import BaseTool
from pydantic import BaseModel, Field


class PublicJobSearchInput(BaseModel):
    role: str = Field(..., description="The job role to search for, e.g. Data Engineer")
    location: str = Field(..., description="The job location, e.g. Seattle")
    max_jobs: int = Field(default=8, description="Maximum number of jobs to return", ge=1, le=20)


class JobPageReaderInput(BaseModel):
    url: str = Field(..., description="The job posting URL to read")


class PublicJobSearchTool(BaseTool):
    name: str = "public_job_search_tool"
    description: str = (
        "Searches public job listings for a role and location. "
        "Returns JSON with title, role, company, location, url, source, posted date, "
        "salary, and description snippet."
    )
    args_schema: type[BaseModel] = PublicJobSearchInput

    def _run(self, role: str, location: str, max_jobs: int = 8) -> str:
        role = self._clean_role(role)
        location = self._clean_text(location)
        max_jobs = int(max(1, min(max_jobs or 8, 20)))

        if not role or not location:
            return self._json(
                role=role,
                location=location,
                jobs=[],
                message="Role and location are required.",
                used_demo_data=False,
            )

        if not os.getenv("SERPER_API_KEY", "").strip():
            demo = self._demo_jobs(role, location, max_jobs)
            demo["message"] = "SERPER_API_KEY is missing. Returned demo jobs so the UI can still run."
            demo["used_demo_data"] = True
            return json.dumps(demo, indent=2)

        try:
            jobs = self.search_jobs_with_serper(role, location, max_jobs)

            if not jobs:
                return self._json(
                    role=role,
                    location=location,
                    jobs=[],
                    message=(
                        "Serper worked, but no usable individual job postings were found. "
                        "Try a more specific role/location, or use a dedicated jobs API."
                    ),
                    used_demo_data=False,
                )

            return self._json(
                role=role,
                location=location,
                jobs=jobs,
                message=f"Found {len(jobs)} public job result(s).",
                used_demo_data=False,
            )

        except Exception as exc:
            # Keep Gradio responsive. Do not raise into the UI.
            return self._json(
                role=role,
                location=location,
                jobs=[],
                message=f"Job search failed: {type(exc).__name__}: {exc}",
                used_demo_data=False,
            )

    def search_jobs_with_serper(self, role: str, location: str, max_jobs: int = 8) -> List[Dict[str, Any]]:
        raw_results: List[Dict[str, Any]] = []
        queries = self._build_safe_serper_queries(role, location)

        for query in queries:
            if len(raw_results) >= max_jobs * 2:
                break

            try:
                data = self._call_serper(query=query, num_results=4)
                raw_results.extend(data.get("organic", []) or [])
            except Exception as exc:
                print(f"Serper query failed: {query} | {type(exc).__name__}: {exc}")

        return self._normalize_serper_results(raw_results, role, location, max_jobs)

    def _build_safe_serper_queries(self, role: str, location: str) -> List[str]:
        role = self._clean_role(role)
        location = self._clean_text(location)

        # Keep this short. Too many sequential searches make Gradio look frozen.
        return [
            f"{role} {location} jobs greenhouse",
            f"{role} {location} jobs lever",
            f"{role} {location} jobs workday",
            f"{role} {location} careers",
        ]

    def _call_serper(self, query: str, num_results: int = 4) -> Dict[str, Any]:
        api_key = os.getenv("SERPER_API_KEY", "").strip()

        if not api_key:
            raise ValueError("SERPER_API_KEY is missing or empty.")

        payload = {"q": query, "num": int(max(1, min(num_results, 10)))}

        response = requests.post(
            "https://google.serper.dev/search",
            headers={
                "X-API-KEY": api_key,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=(5, 8),  # connect timeout, read timeout
        )

        print("Serper status:", response.status_code, "| query:", query)

        if response.status_code >= 400:
            print("Serper error:", response.text[:500])

        response.raise_for_status()
        return response.json()

    def _normalize_serper_results(
        self,
        raw_results: List[Dict[str, Any]],
        role: str,
        location: str,
        max_jobs: int,
    ) -> List[Dict[str, Any]]:
        jobs: List[Dict[str, Any]] = []
        seen_urls: set[str] = set()

        for item in raw_results:
            raw_title = self._clean_text(item.get("title", ""))
            url = self._clean_text(item.get("link") or item.get("url") or "")
            snippet = self._clean_text(item.get("snippet", ""))

            if not url or url in seen_urls:
                continue

            combined = f"{raw_title} {snippet} {url}".lower()

            if self._is_bad_job_result(combined):
                continue

            if not self._looks_like_job_page(url, raw_title, snippet):
                continue

            seen_urls.add(url)
            job_title = self._infer_job_title(raw_title, role)

            jobs.append(
                {
                    "title": job_title,
                    "role": job_title,
                    "company": self._infer_company_from_result(raw_title, snippet, url),
                    "location": self._infer_location_from_text(f"{raw_title} {snippet}", location),
                    "url": url,
                    "source": self._infer_source_from_url(url),
                    "posted_date": self._infer_posted_date(snippet),
                    "salary": self._infer_salary(snippet),
                    "description_snippet": snippet or "No snippet available.",
                }
            )

            if len(jobs) >= max_jobs:
                break

        return jobs

    def _is_bad_job_result(self, combined: str) -> bool:
        bad_patterns = [
            "jobs available",
            "job results",
            "job search",
            "jobs in",
            "jobs near",
            "open jobs",
            "all jobs",
            "search jobs",
            "search results",
            "hiring now",
            "salary.com",
            "glassdoor",
            "indeed.com/q-",
            "indeed.com/jobs",
            "linkedin.com/jobs/search",
            "simplyhired",
            "ziprecruiter",
            "careerjet",
            "jooble",
            "monster.com/jobs",
            "google jobs",
            "talent.com",
            "adzuna",
            "jobrapido",
        ]
        return any(pattern in combined for pattern in bad_patterns)

    def _looks_like_job_page(self, url: str, title: str, snippet: str) -> bool:
        text = f"{url} {title} {snippet}".lower()

        strong_job_domains = [
            "greenhouse.io",
            "boards.greenhouse.io",
            "lever.co",
            "jobs.lever.co",
            "myworkdayjobs.com",
            "smartrecruiters.com",
            "workable.com",
            "ashbyhq.com",
        ]

        if any(domain in text for domain in strong_job_domains):
            return True

        job_url_signals = [
            "/jobs/",
            "/job/",
            "/careers/",
            "/career/",
            "/positions/",
            "/position/",
            "/opening",
            "/openings",
            "/requisition",
            "/req/",
        ]

        job_text_signals = [
            "apply",
            "role",
            "position",
            "responsibilities",
            "requirements",
        ]

        return any(signal in text for signal in job_url_signals) and any(
            signal in text for signal in job_text_signals
        )

    def _infer_job_title(self, title: str, role: str) -> str:
        title = self._clean_text(title)
        role = self._clean_role(role)

        if not title:
            return role

        lower_title = title.lower()
        bad_title_phrases = [
            "job search",
            "jobs in",
            "jobs near",
            "jobs available",
            "career opportunities",
            "careers",
            "hiring now",
            "open positions",
            "search results",
        ]

        if any(phrase in lower_title for phrase in bad_title_phrases):
            return role

        for sep in [" | ", " - ", " – ", " — ", " at "]:
            if sep in title:
                first_part = title.split(sep)[0].strip()
                if first_part:
                    title = first_part
                    break

        title = re.sub(r"\bjobs?\b", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\bcareers?\b", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\bapply now\b", "", title, flags=re.IGNORECASE)
        title = re.sub(r"\s+", " ", title).strip(" -|–—")

        return title if title and len(title) <= 120 else role

    def _infer_company_from_result(self, title: str, snippet: str, url: str) -> str:
        title = title or ""

        patterns = [
            r"\bat\s+([A-Z][A-Za-z0-9&.,' ]{2,60})",
            r"[-–—|]\s*([A-Z][A-Za-z0-9&.,' ]{2,60})$",
            r"^([A-Z][A-Za-z0-9&.,' ]{2,60})\s+is hiring",
        ]

        for pattern in patterns:
            match = re.search(pattern, title)
            if match:
                company = self._clean_company_name(match.group(1))
                if company:
                    return company

        return self._infer_company_from_url(url)

    def _infer_company_from_url(self, url: str) -> str:
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower().replace("www.", "")
            path = parsed.path.strip("/")

            if "greenhouse.io" in domain:
                parts = path.split("/")
                return self._title_from_slug(parts[0]) if parts else "Greenhouse job"

            if "lever.co" in domain:
                parts = path.split("/")
                return self._title_from_slug(parts[0]) if parts else "Lever job"

            if "ashbyhq.com" in domain:
                parts = path.split("/")
                return self._title_from_slug(parts[0]) if parts else "Ashby job"

            if "myworkdayjobs.com" in domain:
                return self._title_from_slug(domain.split(".")[0])

            if "smartrecruiters.com" in domain:
                parts = path.split("/")
                return self._title_from_slug(parts[0]) if parts else "SmartRecruiters job"

            if "workable.com" in domain:
                parts = path.split("/")
                return self._title_from_slug(parts[0]) if parts else "Workable job"

            return self._title_from_slug(domain.split(".")[0])

        except Exception:
            return "Unknown company"

    def _infer_source_from_url(self, url: str) -> str:
        url_lower = url.lower()

        if "greenhouse" in url_lower:
            return "Greenhouse"
        if "lever" in url_lower:
            return "Lever"
        if "ashbyhq" in url_lower:
            return "Ashby"
        if "workday" in url_lower:
            return "Workday"
        if "smartrecruiters" in url_lower:
            return "SmartRecruiters"
        if "workable" in url_lower:
            return "Workable"

        try:
            return urlparse(url).netloc.replace("www.", "")
        except Exception:
            return "Web"

    def _infer_location_from_text(self, text: str, fallback: str) -> str:
        text = self._clean_text(text)

        if re.search(r"\bremote\b", text, re.IGNORECASE):
            return f"{fallback} / Remote" if fallback.lower() not in text.lower() else "Remote"

        if re.search(r"\bhybrid\b", text, re.IGNORECASE):
            return f"{fallback} / Hybrid"

        patterns = [
            r"\b([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)*,\s*[A-Z]{2,3})\b",
            r"\b([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)*\s+VIC)\b",
            r"\b([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)*\s+NSW)\b",
            r"\b([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)*\s+QLD)\b",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).strip()

        return fallback

    def _infer_posted_date(self, text: str) -> str:
        if not text:
            return "Not available"

        lower = text.lower()
        patterns = [
            r"posted\s+(\d+\s+days?\s+ago)",
            r"(\d+\s+days?\s+ago)",
            r"posted\s+today",
            r"today",
            r"yesterday",
        ]

        for pattern in patterns:
            match = re.search(pattern, lower)
            if match:
                return match.group(0).strip().title()

        return "Not available"

    def _infer_salary(self, text: str) -> Optional[str]:
        if not text:
            return None

        salary_patterns = [
            r"\$\s?\d{2,3}(?:,\d{3})?(?:\s?-\s?\$?\d{2,3}(?:,\d{3})?)?",
            r"\d{2,3}k\s?-\s?\d{2,3}k",
            r"AUD\s?\d{2,3}(?:,\d{3})?",
            r"USD\s?\d{2,3}(?:,\d{3})?",
        ]

        for pattern in salary_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(0).strip()

        return None

    def _clean_text(self, text: Any) -> str:
        if text is None:
            return ""

        text = str(text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _clean_role(self, role: Any) -> str:
        role = self._clean_text(role)
        role = re.sub(r"\bjob\s*search\b", "", role, flags=re.IGNORECASE)
        role = re.sub(r"\bjobs?\b", "", role, flags=re.IGNORECASE)
        role = re.sub(r"\bcareers?\b", "", role, flags=re.IGNORECASE)
        role = re.sub(r"\s+", " ", role).strip(" -|–—")
        return role

    def _clean_company_name(self, company: str) -> str:
        company = self._clean_text(company)

        for suffix in ["careers", "jobs", "job", "apply", "hiring"]:
            company = re.sub(rf"\b{suffix}\b$", "", company, flags=re.IGNORECASE).strip()

        return company[:80]

    def _title_from_slug(self, slug: str) -> str:
        slug = slug.strip().strip("/")
        slug = slug.replace("-", " ").replace("_", " ")
        slug = re.sub(r"\s+", " ", slug)
        return slug.title() if slug else "Unknown company"

    def _demo_jobs(self, role: str, location: str, max_jobs: int) -> Dict[str, Any]:
        role = self._clean_role(role)
        demo_jobs = [
            {
                "title": f"Senior {role}",
                "role": f"Senior {role}",
                "company": "Example Bank",
                "location": location,
                "url": "https://example.com/jobs/senior-role",
                "source": "demo",
                "posted_date": "Not available",
                "salary": None,
                "description_snippet": (
                    "Build data products, collaborate with stakeholders, improve processes, "
                    "and support production platforms."
                ),
            },
            {
                "title": role,
                "role": role,
                "company": "Example Retail Group",
                "location": location,
                "url": "https://example.com/jobs/role",
                "source": "demo",
                "posted_date": "Not available",
                "salary": None,
                "description_snippet": (
                    "Analyse requirements, deliver reliable solutions, document processes, "
                    "and work in an agile delivery team."
                ),
            },
            {
                "title": f"Contract {role}",
                "role": f"Contract {role}",
                "company": "Example Government Agency",
                "location": location,
                "url": "https://example.com/jobs/contract-role",
                "source": "demo",
                "posted_date": "Not available",
                "salary": None,
                "description_snippet": (
                    "Support delivery of a transformation program, engage stakeholders, "
                    "and maintain high-quality documentation."
                ),
            },
        ]

        return {"role": role, "location": location, "jobs": demo_jobs[:max_jobs]}

    def _json(self, **kwargs: Any) -> str:
        return json.dumps(kwargs, indent=2)


class JobPageReaderTool(BaseTool):
    name: str = "job_page_reader_tool"
    description: str = "Reads a job posting URL and returns plain text content for summarisation."
    args_schema: type[BaseModel] = JobPageReaderInput

    def _run(self, url: str) -> str:
        url = (url or "").strip()

        if not url:
            return json.dumps({"url": url, "content": "", "message": "No URL provided."}, indent=2)

        if "example.com" in url:
            return json.dumps(
                {
                    "url": url,
                    "content": (
                        "This is a demo job URL. No real web page is available. "
                        "Use a real job URL from Serper results to scrape and summarise."
                    ),
                    "message": "Demo URL detected.",
                },
                indent=2,
            )

        try:
            content = self._read_url(url)
            return json.dumps(
                {"url": url, "content": content, "message": "Job page read successfully."},
                indent=2,
            )
        except Exception as exc:
            return json.dumps(
                {
                    "url": url,
                    "content": "",
                    "message": f"Failed to read job page: {type(exc).__name__}: {exc}",
                },
                indent=2,
            )

    def _read_url(self, url: str) -> str:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }

        response = requests.get(url, headers=headers, timeout=(5, 10))
        response.raise_for_status()

        return self._html_to_text(response.text)[:12000]

    def _html_to_text(self, html: str) -> str:
        html = re.sub(
            r"<(script|style).*?>.*?</\1>",
            " ",
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        html = re.sub(r"<br\s*/?>", "\n", html, flags=re.IGNORECASE)
        html = re.sub(r"</p>|</div>|</li>", "\n", html, flags=re.IGNORECASE)

        text = re.sub(r"<[^>]+>", " ", html)

        replacements = {
            "&nbsp;": " ",
            "&amp;": "&",
            "&lt;": "<",
            "&gt;": ">",
            "&quot;": '"',
            "&#39;": "'",
        }

        for old, new in replacements.items():
            text = text.replace(old, new)

        text = re.sub(r"\n\s*\n+", "\n\n", text)
        text = re.sub(r"[ \t]+", " ", text)

        return text.strip()


def get_job_tools(use_website_search: bool = False) -> List[BaseTool]:
    return [
        PublicJobSearchTool(),
        JobPageReaderTool(),
    ]


def get_crewai_web_tools(use_website_search: bool = False) -> List[BaseTool]:
    return get_job_tools(use_website_search=use_website_search)
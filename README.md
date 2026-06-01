---
title: CrewAI Job Search Chat
emoji: 💼
colorFrom: blue
colorTo: indigo
sdk: gradio
sdk_version: 4.44.0
app_file: app.py
pinned: false
---

# CrewAI Job Search Chat

A Hugging Face Spaces-ready Gradio chat app backed by CrewAI agents and tools.

The app lets users search for jobs by **role** and **location**, displays the results in a clickable **HTML job table**, summarises selected jobs, summarises common responsibilities and skills across loaded jobs, and answers small-talk questions when the message is not a job-search request.

## Features

- Chat interface for role/location searches.
- Example: `Data Engineer in Seattle`.
- Clickable HTML job results table with:
  - Role
  - Company
  - Exact/listed location
  - Posted date
  - Salary, when available
  - Source
  - Job URL link
- Users can open job links directly from the table.
- Users can ask follow-up questions such as:
  - `summarize job 1`
  - `summarize job 2`
  - `What skills are common?`
  - `Compare these jobs`
- If the user asks for a different role/location, the app starts a new search.
- If the user asks small-talk questions, the app responds without forcing a job search.
- Uses Pydantic models for structured outputs.
- Uses CrewAI agents, tasks, and tools.
- Uses OpenAI and Anthropic LLMs.
- Uses Serper for public web job discovery.
- Uses lightweight scraping for selected job pages.
- Does not use `gr.Dataframe`; the UI uses only a clickable `gr.HTML` job table.

## Secrets required on Hugging Face Spaces

Add these in **Settings → Variables and secrets**:

```text
OPENAI_API_KEY=...
ANTHROPIC_API_KEY=...
SERPER_API_KEY=...
```

Optional:

```text
OPENAI_MODEL=gpt-4o-mini
ANTHROPIC_MODEL=claude-sonnet-4-6
MAX_JOBS=5
USE_WEBSITE_SEARCH=false
```

## Important note about Serper free accounts

Serper free accounts may reject advanced Google query patterns such as:

```text
site:greenhouse.io OR site:lever.co OR site:ashbyhq.com
```

To avoid this, the app uses several simple searches instead, for example:

```text
Data Engineer Seattle jobs greenhouse
Data Engineer Seattle jobs lever
Data Engineer Seattle jobs workday
Data Engineer Seattle careers
```

The app then merges and filters the results to remove generic pages such as:

```text
500 jobs available
job search results
jobs in Seattle
```

## .env example**

```text
OPENAI_API_KEY="your-key"
ANTHROPIC_API_KEY="your-key"
SERPER_API_KEY="your-key"
```

## Local run with uv

From the project root:

```bash
uv sync
copy .env.example .env
uv run python app.py
```

On macOS/Linux, use:

```bash
uv sync
cp .env.example .env
uv run python app.py
```

## Local run with pip

Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

macOS/Linux:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

## Example prompts

```text
Data Engineer in Melbourne
Business Analyst in Sydney
Data Engineer in Seattle
Business Analyst in Atlanta
Summarise job 1
Summarize job 2
What skills are common across these jobs?
Compare these jobs
Hello, what can you do?
```

## Project structure

```text
app.py
pyproject.toml
requirements.txt
.env.example
README.md
src/job_search_crew/
  __init__.py
  config/
    agents.yaml
    tasks.yaml
  crew.py
  models.py
  tools.py
  chat_engine.py
  settings.py
```

## Main files

### `app.py`

Contains the Gradio UI.

Current UI design:

- Left side: chat interface.
- Right side: clickable HTML job table.
- Users summarise jobs by typing `summarise job 1`, `summarise job 2`, etc.

### `src/job_search_crew/tools.py`

Contains:

- `PublicJobSearchTool`
- `JobPageReaderTool`
- `get_job_tools(use_website_search=False)`
- `get_crewai_web_tools(use_website_search=False)`

The tool is designed to avoid Gradio freezing by:

- Reducing Serper searches.
- Using shorter network timeouts.
- Avoiding advanced Serper query patterns blocked by free accounts.
- Returning structured JSON instead of raising errors into the UI.

### `src/job_search_crew/chat_engine.py`

Coordinates the chat flow.

Recommended behaviour:

```text
New role/location search
→ run PublicJobSearchTool directly
→ update state["jobs"]
→ render clickable HTML table

summarise job 1
→ read selected job from state["jobs"]
→ optionally scrape selected URL
→ summarise with CrewAI or LLM

common skills / responsibilities
→ summarise from loaded state["jobs"]

small talk
→ answer directly without job search
```

### `src/job_search_crew/config/agents.yaml`

Defines CrewAI agents such as:

- Job Search Researcher
- Role and Responsibilities Analyst
- Job Description Analyst
- Small Talk Career Assistant

### `src/job_search_crew/config/tasks.yaml`

Defines reusable CrewAI tasks such as:

- Job search task
- Loaded jobs summary task
- Single job summary task
- Small-talk response task

## Hugging Face Spaces deployment

Create a new Hugging Face Space:

```text
SDK: Gradio
App file: app.py
```

Upload the project files to the Space.

Then add secrets in:

```text
Settings → Variables and secrets
```

Required:

```text
OPENAI_API_KEY
ANTHROPIC_API_KEY
SERPER_API_KEY
```

Then restart the Space.

## Troubleshooting

### `uv sync` says no `pyproject.toml` found

You are probably in the wrong folder.

Run `dir` or `ls`. You should see:

```text
app.py
pyproject.toml
requirements.txt
README.md
src
```

Then run:

```bash
uv sync
```

### Gradio appears frozen

Common causes:

- CrewAI is being called for every message.
- Serper requests are taking too long.
- A job URL scrape is slow.
- The Gradio function is returning the wrong number of outputs.

Recommended fixes:

- Use `PublicJobSearchTool` directly for the first job search.
- Use CrewAI only for deeper job summarisation.
- Keep `demo.queue(default_concurrency_limit=1)` before `launch`.
- Keep `verbose=False` in CrewAI.
- Use shorter request timeouts in `tools.py`.

### Serper returns 400

If the error says:

```text
Query pattern not allowed for free accounts.
```

then remove advanced query operators such as:

```text
site:greenhouse.io OR site:lever.co
```

Use simple queries instead.

### App returns demo jobs

This usually means one of these happened:

- `SERPER_API_KEY` is missing.
- `.env` is not loaded.
- Serper returned no usable individual job postings.
- The app fell back to demo data for local testing.

Check that `.env` is in the project root, next to `app.py`.

## Version notes

### Latest update

- Removed `gr.Dataframe`.
- Added clickable HTML job table only.
- Removed dataframe row select handler.
- Added safer Gradio queue configuration.
- Added Serper free-account-safe query strategy.
- Added clean role display to avoid showing titles like `Job Search`.
- Kept compatibility with `get_job_tools(use_website_search=False)` and `get_crewai_web_tools(use_website_search=False)`.

### Previous v5 fix

This version fixes the issue where Serper returned aggregate pages such as `543 jobs available` and the UI did not receive concrete job rows. The app now runs the deterministic `PublicJobSearchTool` first, parses Serper organic results into rows, filters aggregate pages, and then uses CrewAI agents to summarise the loaded rows.

from __future__ import annotations

import html
from typing import Any

import gradio as gr

from src.job_search_crew.chat_engine import ChatEngine

engine = ChatEngine()


def build_clickable_jobs_html(state: dict[str, Any] | None) -> str:
    """
    Build the clickable jobs table from session state.

    This replaces gr.Dataframe so users can click job URLs directly.
    """
    jobs = (state or {}).get("jobs", [])

    if not jobs:
        return """
        <div class="empty-jobs">
            <p>No jobs loaded yet. Search for a role and location first.</p>
        </div>
        """

    rows: list[str] = []

    for idx, job in enumerate(jobs, start=1):
        title = html.escape(str(job.get("role") or job.get("title") or ""))
        company = html.escape(str(job.get("company") or ""))
        location = html.escape(str(job.get("location") or ""))
        source = html.escape(str(job.get("source") or ""))
        posted = html.escape(str(job.get("posted_date") or "Not available"))
        salary = html.escape(str(job.get("salary") or "Not available"))
        url = str(job.get("url") or "").strip()

        if url.startswith(("http://", "https://")):
            url_cell = (
                f'<a class="job-link" href="{html.escape(url, quote=True)}" '
                f'target="_blank" rel="noopener noreferrer">Open job</a>'
            )
        else:
            url_cell = ""

        rows.append(
            "<tr>"
            f"<td>{idx}</td>"
            f"<td>{title}</td>"
            f"<td>{company}</td>"
            f"<td>{location}</td>"
            f"<td>{posted}</td>"
            f"<td>{salary}</td>"
            f"<td>{source}</td>"
            f"<td>{url_cell}</td>"
            "</tr>"
        )

    return (
        '<div class="job-link-table">'
        "<table>"
        "<thead>"
        "<tr>"
        "<th>#</th>"
        "<th>Role</th>"
        "<th>Company</th>"
        "<th>Exact/Listed Location</th>"
        "<th>Posted</th>"
        "<th>Salary</th>"
        "<th>Source</th>"
        "<th>Link</th>"
        "</tr>"
        "</thead>"
        "<tbody>"
        + "".join(rows)
        + "</tbody>"
        "</table>"
        "</div>"
        "<p class='hint'>To summarize a listing, type <b>summarise job 1</b>, "
        "<b>summarise job 2</b>, etc.</p>"
    )


def user_submit(message: str, history: list[dict[str, str]] | None, state: dict[str, Any] | None):
    """
    Main Gradio submit handler.

    Outputs:
    1. chatbot
    2. textbox
    3. state
    4. HTML jobs table
    """
    history = history or []
    state = state or engine.empty_state()

    if not message or not message.strip():
        return history, "", state, build_clickable_jobs_html(state)

    message = message.strip()

    history.append({"role": "user", "content": message})

    try:
        answer, _rows, state = engine.respond(message, history, state)
    except Exception as exc:
        answer = (
            "I hit an error while processing your request.\n\n"
            f"**Error:** `{type(exc).__name__}: {exc}`"
        )

    history.append({"role": "assistant", "content": answer})

    return history, "", state, build_clickable_jobs_html(state)


force_dark_mode = """
function() {
    const url = new URL(window.location.href);
    if (url.searchParams.get('__theme') !== 'dark') {
        url.searchParams.set('__theme', 'dark');
        window.location.replace(url.toString());
    }
}
"""

with gr.Blocks(title="CrewAI Job Search Chat") as demo:
    gr.Markdown(
        """
        # 💼 CrewAI Job Search Chat

        Type a role and location, for example **Data Engineer in Atlanta**.

        Then ask follow-ups like **summarize job 1**, **compare these jobs**, or **what skills are common?**
        """
    )

    state = gr.State(engine.empty_state())

    with gr.Row():
        with gr.Column(scale=5):
            chatbot = gr.Chatbot(
                label="Chat",
                height=560,
            )

            msg = gr.Textbox(
                placeholder="Example: Data Engineer in Seattle",
                label="Message",
                lines=1,
            )

            with gr.Row():
                send = gr.Button("Send", variant="primary")
                clear = gr.Button("Clear")

        with gr.Column(scale=5):
            gr.Markdown("## Job results")
            job_links = gr.HTML(
                label="Clickable job links",
                value="<p>No jobs loaded yet. Search for a role and location first.</p>",
            )

    gr.Examples(
        examples=[
            "Data Engineer in Seattle",
            "Business Analyst in Atlanta",
            "summarize job 1",
            "What skills are common?",
            "Hello, what can you do?",
        ],
        inputs=msg,
    )

    send.click(
        fn=user_submit,
        inputs=[msg, chatbot, state],
        outputs=[chatbot, msg, state, job_links],
    )

    msg.submit(
        fn=user_submit,
        inputs=[msg, chatbot, state],
        outputs=[chatbot, msg, state, job_links],
    )

    clear.click(
        fn=lambda: (
            [],
            "",
            engine.empty_state(),
            "<p>No jobs loaded yet. Search for a role and location first.</p>",
        ),
        inputs=[],
        outputs=[chatbot, msg, state, job_links],
    )


if __name__ == "__main__":
    demo.queue(default_concurrency_limit=1).launch(inbrowser=True, js=force_dark_mode)
msg
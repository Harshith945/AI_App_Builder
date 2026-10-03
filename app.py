"""AppPilot AI - turn an application idea into a plan, code, explanation and lessons.

Run locally with:  streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from graph.workflow import BUILD_TARGETS, STAGES, stream_workflow
from llm.client import LLMError, get_model, has_api_key
from utils.export import create_zip, slugify

st.set_page_config(page_title="AppPilot AI", page_icon="🚀", layout="wide")

EXAMPLE_IDEA = (
    "Build a simple expense tracker where users can add expenses with amount, category, "
    "and date, view all expenses, and see total spending."
)

CODE_LANGUAGES = {
    ".py": "python",
    ".md": "markdown",
    ".json": "json",
    ".toml": "toml",
    ".sh": "bash",
    ".html": "html",
    ".css": "css",
    ".js": "javascript",
}

CUSTOM_CSS = """
<style>
.hero { padding: 1.4rem 1.6rem; border-radius: 14px; margin-bottom: 1rem;
        background: linear-gradient(120deg, #4f46e5 0%, #7c3aed 55%, #db2777 100%); color: #fff; }
.hero h1 { margin: 0; font-size: 2.2rem; color: #fff; }
.hero p { margin: .35rem 0 0 0; font-size: 1.05rem; opacity: .95; }
.pipeline { display: flex; flex-wrap: wrap; gap: .5rem; margin: .2rem 0 1.2rem 0; }
.pill { padding: .25rem .8rem; border-radius: 999px; font-size: .85rem; font-weight: 600;
        background: rgba(124, 58, 237, .12); border: 1px solid rgba(124, 58, 237, .35); }
</style>
"""


# --------------------------------------------------------------------------- #
# Session state
# --------------------------------------------------------------------------- #
def init_state() -> None:
    st.session_state.setdefault("idea", "")
    st.session_state.setdefault("results", {})  # stage key -> validated Pydantic model
    st.session_state.setdefault("error", None)
    st.session_state.setdefault("request", None)  # (idea, build_target) of the last run


def use_example() -> None:
    st.session_state["idea"] = EXAMPLE_IDEA


def reset_quiz_answers() -> None:
    for key in [k for k in st.session_state if str(k).startswith("quiz_")]:
        del st.session_state[key]


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
def run_generation(idea: str, build_target: str, resume: bool = False) -> None:
    """Run the workflow. With resume=True, stages that already finished are reused."""
    if not resume:
        st.session_state["results"] = {}
        reset_quiz_answers()
    st.session_state["error"] = None
    st.session_state["request"] = (idea, build_target)

    existing = dict(st.session_state["results"])
    pending = [stage for stage in STAGES if stage.key not in existing]
    already_done = len(STAGES) - len(pending)
    progress = st.progress(already_done / len(STAGES), text="Starting...")
    try:
        with st.status("AppPilot AI is working on your idea...", expanded=True) as status:
            st.caption(
                "If Groq rate-limits a request, the app waits and retries automatically, "
                "so a stage can take up to a minute."
            )
            st.write(f"⏳ {pending[0].running_text}...")
            for done, (stage, update) in enumerate(
                stream_workflow(idea, build_target, existing), start=1
            ):
                st.session_state["results"].update(update)
                st.write(f"✅ {stage.label} complete")
                if done < len(pending):
                    next_stage = pending[done]
                    st.write(f"⏳ {next_stage.running_text}...")
                    progress.progress(
                        (already_done + done) / len(STAGES),
                        text=f"{next_stage.label} stage running",
                    )
            status.update(label="All stages complete", state="complete", expanded=False)
        progress.progress(1.0, text="Done")
        st.success("Your app is ready! Explore the tabs below.")
    except LLMError as exc:
        progress.empty()
        st.session_state["error"] = str(exc)
    except Exception as exc:  # never show a raw traceback to the user
        progress.empty()
        st.session_state["error"] = (
            f"Something unexpected went wrong ({type(exc).__name__}). Please try again."
        )


# --------------------------------------------------------------------------- #
# Tab renderers
# --------------------------------------------------------------------------- #
def bullets(items) -> None:
    st.markdown("\n".join(f"- {item}" for item in items))


def render_understand(req) -> None:
    st.subheader(req.app_name)
    with st.container(border=True):
        st.markdown("**Purpose**")
        st.write(req.purpose)
    col1, col2 = st.columns(2)
    with col1:
        with st.container(border=True):
            st.markdown("**Target Users**")
            bullets(req.target_users)
        with st.container(border=True):
            st.markdown("**Features**")
            bullets(req.features)
    with col2:
        with st.container(border=True):
            st.markdown("**User Flow**")
            st.markdown("\n".join(f"{i}. {step}" for i, step in enumerate(req.user_flow, 1)))
        with st.container(border=True):
            st.markdown("**Assumptions**")
            if req.assumptions:
                bullets(req.assumptions)
            else:
                st.caption("No assumptions were needed.")


def render_plan(plan) -> None:
    with st.container(border=True):
        st.markdown("**Architecture**")
        st.info(plan.architecture)
    col1, col2 = st.columns(2)
    with col1:
        with st.container(border=True):
            st.markdown("**Components**")
            bullets(plan.components)
        with st.container(border=True):
            st.markdown("**Data Model**")
            bullets(plan.data_model)
    with col2:
        with st.container(border=True):
            st.markdown("**Development Steps**")
            st.markdown("\n".join(f"{i}. {step}" for i, step in enumerate(plan.development_steps, 1)))
        with st.container(border=True):
            st.markdown("**Technologies**")
            bullets(plan.technologies)


def render_build(build) -> None:
    st.subheader(build.app_name)
    st.warning(
        "This code was written by an AI and is **never executed** by AppPilot AI. "
        "Review it before running it on your own computer."
    )
    st.download_button(
        "⬇️ Download Project ZIP",
        data=create_zip(build.files),
        file_name=f"{slugify(build.app_name)}.zip",
        mime="application/zip",
        type="primary",
    )

    filenames = [f.filename for f in build.files]
    st.markdown(f"**Generated files ({len(filenames)})**")
    selected = st.selectbox("Select a file to view", filenames, key="selected_file")
    file = next(f for f in build.files if f.filename == selected)
    extension = "." + file.filename.rsplit(".", 1)[-1] if "." in file.filename else ""

    st.caption(f"**Purpose:** {file.purpose}")
    st.code(file.code, language=CODE_LANGUAGES.get(extension, "text"), line_numbers=True)

    with st.container(border=True):
        st.markdown("**How to run it**")
        st.text(build.run_instructions)


def render_explain(explanation) -> None:
    with st.container(border=True):
        st.markdown("**Application Overview**")
        st.write(explanation.overview)

    st.markdown("### File-by-file explanation")
    for item in explanation.file_explanations:
        with st.expander(f"📄 {item.filename}", expanded=True):
            st.markdown("**What it does**")
            st.write(item.what_it_does)
            st.markdown("**How it works**")
            st.write(item.how_it_works)
            st.markdown("**Concepts used**")
            bullets(item.concepts)

    st.markdown("### Important concepts")
    bullets(explanation.important_concepts)


def render_learn(learning) -> None:
    with st.container(border=True):
        st.markdown("**Skills you can learn from this app**")
        bullets(learning.skills_learned)

    st.markdown("### Quiz")
    st.caption("Pick an answer to check it instantly.")
    for i, question in enumerate(learning.quiz):
        with st.container(border=True):
            choice = st.radio(
                f"Q{i + 1}. {question.question}",
                question.options,
                index=None,
                key=f"quiz_{i}",
            )
            if choice is not None:
                if choice.strip() == question.answer.strip():
                    st.success("Correct!")
                else:
                    st.error(f"Not quite. The correct answer is: {question.answer}")
                st.caption(question.explanation)

    st.markdown("### Recommended next steps")
    bullets(learning.next_steps)


def render_results(results: dict) -> None:
    st.divider()
    st.markdown("## Your results")
    tabs = st.tabs([stage.label for stage in STAGES])
    renderers = {
        "requirements": render_understand,
        "plan": render_plan,
        "build": render_build,
        "explanation": render_explain,
        "learning": render_learn,
    }
    for tab, stage in zip(tabs, STAGES):
        with tab:
            if stage.key in results:
                renderers[stage.key](results[stage.key])
            else:
                st.info(f"The {stage.label} stage did not finish.")


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #
def render_sidebar() -> None:
    with st.sidebar:
        st.header("How it works")
        st.markdown(
            "1. **Understand** - extract requirements\n"
            "2. **Plan** - design a small architecture\n"
            "3. **Build** - generate the source code\n"
            "4. **Explain** - walk through the code\n"
            "5. **Learn** - quiz and next steps"
        )
        st.divider()
        st.caption(f"Model: `{get_model()}`")
        if has_api_key():
            st.caption("✅ Groq API key configured")
        else:
            st.caption("❌ Groq API key missing")
        st.caption("Generated code is displayed and downloadable only. It is never run here.")


def main() -> None:
    init_state()
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    render_sidebar()

    st.markdown(
        '<div class="hero"><h1>🚀 AppPilot AI</h1>'
        "<p>An AI-powered application builder and learning environment. Describe an app, "
        "get a plan, working code, an explanation, and a quiz.</p></div>",
        unsafe_allow_html=True,
    )
    pills = "".join(f'<span class="pill">{s.label}</span>' for s in STAGES)
    st.markdown(f'<div class="pipeline">{pills}</div>', unsafe_allow_html=True)

    if not has_api_key():
        st.warning(
            "No Groq API key found. Set `GROQ_API_KEY` in a local `.env` file or in "
            "Streamlit secrets, then reload the page."
        )

    st.markdown("### 1. Describe your application")
    st.text_area(
        "Application idea",
        key="idea",
        height=120,
        max_chars=1500,
        placeholder="e.g. A to-do list where I can add tasks, mark them done, and delete them.",
        label_visibility="collapsed",
    )
    col_target, col_example, col_build = st.columns([2, 1, 1], vertical_alignment="bottom")
    with col_target:
        build_target = st.selectbox("Build target", BUILD_TARGETS)
    with col_example:
        st.button("Use example idea", on_click=use_example, use_container_width=True)
    with col_build:
        build_clicked = st.button("🚀 Build my app", type="primary", use_container_width=True)

    if build_clicked:
        idea = st.session_state["idea"].strip()
        if len(idea) < 10:
            st.warning("Please describe your application in a bit more detail (at least 10 characters).")
        elif not has_api_key():
            st.error("The Groq API key is not configured, so nothing can be generated yet.")
        else:
            run_generation(idea, build_target)

    if st.session_state["error"]:
        st.error(st.session_state["error"])
        if st.session_state["results"] and st.session_state["request"]:
            st.caption("Nothing was lost: stages that finished are shown below and will not be re-run.")
            if st.button("🔄 Resume from the failed stage"):
                idea_prev, target_prev = st.session_state["request"]
                run_generation(idea_prev, target_prev, resume=True)
                st.rerun()

    if st.session_state["results"]:
        render_results(st.session_state["results"])


main()
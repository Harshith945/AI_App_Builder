# 🚀 AppPilot AI

**An AI-powered application builder and learning environment.**

```
Prompt → Understand → Plan → Build → Explain → Learn
```

Describe an app in plain English. AppPilot AI analyzes the idea, plans a small MVP,
generates the source code, explains it in beginner-friendly language, and creates a
quiz so you actually learn from what was built. The generated project can be
downloaded as a ZIP.

---

## Table of contents

- [Problem statement](#problem-statement)
- [Key features](#key-features)
- [How it works](#how-it-works)
- [Architecture](#architecture)
- [Build targets](#build-targets)
- [LLM output reliability](#llm-output-reliability)
- [Technology stack](#technology-stack)
- [Project structure](#project-structure)
- [Setup](#setup)
- [Environment variables](#environment-variables)
- [Running locally](#running-locally)
- [Deploying to Streamlit Cloud](#deploying-to-streamlit-cloud)
- [Example](#example)
- [Security considerations](#security-considerations)
- [Limitations](#limitations)
- [Troubleshooting](#troubleshooting)
- [Future improvements](#future-improvements)

---

## Problem statement

Beginners can describe the app they want, but they struggle to turn that idea into
working code. Most AI code generators then hand over code without helping the user
understand it.

AppPilot AI closes that gap. Every generated app comes with the reasoning behind it
(requirements and a plan), a file-by-file explanation, and learning material.

## Key features

- **Five-stage workflow** orchestrated with LangGraph, one focused agent per stage
- **Structured outputs:** every LLM response is parsed and validated with Pydantic
- **Robust error handling:** empty, invalid, truncated and incomplete LLM output are
  detected and retried; API errors and rate limits are handled gracefully
- **Resume after failure:** if a stage fails, finished stages are kept and you can resume
  from the failed stage instead of starting over
- **Safe by design:** generated code is displayed and downloadable, **never executed**
- **Two build targets:** Streamlit Prototype or Python Application
- **One-click export:** "Download Project ZIP"
- **Built-in learning:** beginner explanations and an interactive quiz

## How it works

| Stage | Input | Output (validated model) |
|-------|-------|--------------------------|
| **Understand** | App idea | `RequirementOutput`: name, purpose, target users, features, user flow, assumptions |
| **Plan** | Requirements | `PlanOutput`: architecture, components, data model, development steps, technologies |
| **Build** | Requirements + plan | `BuildOutput`: files (filename, code, purpose) and run instructions |
| **Explain** | Generated files | `ExplainOutput`: overview, per-file explanations, important concepts |
| **Learn** | Code + explanation | `LearnOutput`: skills learned, quiz, next steps |

Each LangGraph node builds a prompt from the shared state, calls the LLM, parses and
validates the response, stores the result in the state, and passes it to the next node.

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Streamlit UI (app.py)                  │
│   idea input · build target · progress · result tabs     │
└───────────────────────────┬──────────────────────────────┘
                            │ stream_workflow()
┌───────────────────────────▼──────────────────────────────┐
│              LangGraph workflow (graph/workflow.py)       │
│                                                          │
│ START → UNDERSTAND → PLAN → BUILD → EXPLAIN → LEARN → END │
│            (shared BuilderState passed between nodes)     │
└───────────────────────────┬──────────────────────────────┘
                            │ generate_structured(prompt, schema)
┌───────────────────────────▼──────────────────────────────┐
│               LLM client (llm/client.py)                  │
│  Groq via OpenAI-compatible API → parse JSON → validate  │
│  with Pydantic (models/schemas.py) → retry on failure    │
└──────────────────────────────────────────────────────────┘
        prompts/templates.py            utils/export.py
        (one prompt per agent)          (create_zip for download)
```

## Build targets

The **Build target** selector controls what kind of app is generated for you. It does
not change AppPilot AI itself.

| Target | What you get | How to run it |
|--------|--------------|---------------|
| **Streamlit Prototype** | A small web app that opens in the browser: `app.py` plus `requirements.txt` | `pip install -r requirements.txt` then `streamlit run app.py` |
| **Python Application** | A command-line app with a text menu: a single `main.py` using only the standard library | `python main.py` |

Both targets produce a small MVP, not a production application (see
[Limitations](#limitations)).

## LLM output reliability

The system never trusts the model blindly.

| Problem | How it is handled |
|---------|-------------------|
| Empty response | Detected and retried |
| Invalid JSON | Parsed tolerantly (code fences, surrounding prose); retried with feedback if still invalid |
| Truncated response | Detected via `finish_reason`; retried with a larger token budget and a request for shorter output |
| Missing fields / wrong types / unexpected fields | Rejected by Pydantic (`extra="forbid"`); the validation error is sent back to the model |
| Double-escaped code (`\\n` instead of `\n`) | Repaired automatically, but only if the repaired Python parses |
| Invalid Python | Checked with `ast.parse` (parse only, never executed); retried with the error message |
| Missing explanations | The Explain stage must cover every generated file |
| Rate limits (HTTP 429) | Waits for the time Groq asks (up to 60 s) and retries up to 5 times |
| Network errors / 5xx | Retried with backoff |
| Invalid API key / unavailable model | Reported immediately with a clear message |

If all retries fail, a friendly error is shown. Stages that already finished are kept
and a **Resume** button continues from the failed stage.

## Technology stack

- Python 3.10+
- [Streamlit](https://streamlit.io/): UI
- [LangGraph](https://github.com/langchain-ai/langgraph): workflow orchestration
- [Groq API](https://groq.com/) through the OpenAI-compatible `openai` client
- [Pydantic v2](https://docs.pydantic.dev/): validation
- python-dotenv: local configuration

## Project structure

```
ai-app-builder/
├── app.py                 # Streamlit UI
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── graph/
│   └── workflow.py        # LangGraph state, nodes and graph
├── llm/
│   └── client.py          # Groq client, JSON parsing, retries, error handling
├── models/
│   └── schemas.py         # Pydantic models
├── prompts/
│   └── templates.py       # One prompt per agent
└── utils/
    └── export.py          # create_zip()
```

## Setup

```bash
git clone <your-repo-url>
cd ai-app-builder

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

> On locked-down Windows machines where `pip.exe` is blocked by a security policy, use
> `python -m pip install -r requirements.txt` and `python -m streamlit run app.py`.

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | Yes | Your Groq API key (create one at [console.groq.com](https://console.groq.com)) |
| `GROQ_MODEL` | No | Groq model name. Default: `openai/gpt-oss-20b` |
| `GROQ_MAX_TOKENS` | No | Overrides the per-stage token budgets (defaults range from 2000 to 6000) |

Create your local configuration file:

```bash
cp .env.example .env      # Windows: copy .env.example .env
```

Then edit `.env` and add your key. **Never commit `.env`**; it is listed in `.gitignore`.

Settings are read from environment variables (including `.env`) first and from
Streamlit secrets second.

## Running locally

```bash
streamlit run app.py
```

Open the URL shown in the terminal (normally http://localhost:8501), enter an idea,
choose a build target and click **Build my app**.

## Deploying to Streamlit Cloud

1. Push this project to a GitHub repository (without `.env`).
2. On [share.streamlit.io](https://share.streamlit.io), create a new app from the
   repository and set `app.py` as the main file.
3. Open **Advanced settings → Secrets** and add:

   ```toml
   GROQ_API_KEY = "your_groq_api_key_here"
   GROQ_MODEL = "openai/gpt-oss-20b"
   ```
4. Deploy. The API key is never shown in the UI.

## Example

**Input**

> Build a simple expense tracker where users can add expenses with amount, category, and
> date, view all expenses, and see total spending.

**Output**

| Tab | What you see |
|-----|--------------|
| **Understand** | "Expense Tracker": purpose, target users, features (add, view, total), user flow, assumptions |
| **Plan** | A single-file architecture, components, data model (`Expense: amount, category, date`), development steps, technologies |
| **Build** | `app.py` and `requirements.txt` with a file selector, source code view, run instructions and **Download Project ZIP** |
| **Explain** | An overview and a file-by-file explanation of what each file does, how it works and the concepts used |
| **Learn** | Skills learned, a multiple-choice quiz with instant feedback and explanations, recommended next steps |

## Security considerations

- Generated code is **never executed** by AppPilot AI: no `eval()`, `exec()`,
  subprocesses or dynamic imports.
- Python files are only *parsed* (`ast.parse`) to catch syntax errors.
- Generated code that calls `eval()` or `exec()` is rejected and regenerated.
- Generated filenames are validated (no absolute paths, no `..`) before the ZIP is built.
- The API key is read from the environment or Streamlit secrets and is never displayed.
- Always review AI-generated code before running it on your own machine.

## Limitations

- Generates a **small MVP** (about 120 lines per file, at most 3 files), not a complete
  production app. Large ideas come back as simplified prototypes.
- The Streamlit prototype keeps data in memory by default, so data is lost on page
  refresh unless SQLite is genuinely needed.
- Generated code is syntax-checked but never run, so small logic bugs are possible.
- Free-tier Groq accounts have tokens-per-minute limits, so a stage may pause while the
  app waits and retries.

## Troubleshooting

| Message | What to do |
|---------|------------|
| "GROQ_API_KEY is not set" | Add the key to `.env` locally or to Streamlit secrets when deployed |
| "The Groq API key was rejected" | Check that the key is correct and active |
| "The Groq rate limit was reached" | Wait about a minute and click **Resume**; or set `GROQ_MODEL` to a model with higher limits |
| "...did not match the required format" | The model returned bad output four times; click **Build** again or simplify the idea |
| "Groq rejected the request" | The model name may be wrong or unavailable; check `GROQ_MODEL` |

## Future improvements

- Sandboxed execution of generated apps (for example in a container)
- Iterative refinement ("add a delete button", "save data to SQLite")
- Support for local open-source models through an OpenAI-compatible endpoint (Ollama)
- Multi-file project support with dependency analysis
- Per-stage regeneration and streaming output
- History of generated projects
- Automatically generated tests for the produced app

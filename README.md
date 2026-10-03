# 🚀 AppPilot AI

An AI-powered application builder and learning environment.

```
Prompt → Understand → Plan → Build → Explain → Learn
```

Describe an app in plain English. AppPilot AI analyzes the idea, plans a small MVP,
generates the source code, explains it for beginners, and creates a quiz. You can
download the generated project as a ZIP.

## Problem statement

Beginners can describe the app they want but struggle to turn the idea into working code,
and AI code generators usually hand over code without helping you understand it.
AppPilot AI closes that gap: every generated app comes with the reasoning behind it, a
file-by-file explanation, and learning material.

## Key features

- Five-stage LangGraph workflow with one focused agent per stage
- Strict Pydantic validation of every LLM response, with automatic retries
- Handles empty, invalid, truncated and incomplete LLM output, API errors and rate limits
- Generated code is **displayed and downloadable only, never executed**
- Syntax check of generated Python (`ast.parse`) and a static ban on `eval()`/`exec()`
- Two build targets: Streamlit Prototype and Python Application
- One-click "Download Project ZIP"
- Beginner explanations and an interactive quiz

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
│  START → UNDERSTAND → PLAN → BUILD → EXPLAIN → LEARN → END│
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

## Workflow

| Stage | Input | Output (validated model) |
|-------|-------|--------------------------|
| Understand | App idea | `RequirementOutput`: name, purpose, users, features, flow, assumptions |
| Plan | Requirements | `PlanOutput`: architecture, components, data model, steps, technologies |
| Build | Requirements + plan | `BuildOutput`: files (name, code, purpose), run instructions |
| Explain | Generated files | `ExplainOutput`: overview, per-file explanations, concepts |
| Learn | Code + explanation | `LearnOutput`: skills, quiz, next steps |

Each node builds a prompt from the shared state, calls the LLM, parses and validates the
response, stores the result in the state, and hands the state to the next node.

## Technology stack

- Python 3.10+
- Streamlit (UI)
- LangGraph (workflow orchestration)
- Groq API through the OpenAI-compatible `openai` client
- Pydantic v2 (validation)
- python-dotenv (local configuration)

## Project structure

```
ai-app-builder/
├── app.py                 # Streamlit UI
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── graph/workflow.py      # LangGraph nodes, state and graph
├── llm/client.py          # Groq client, JSON parsing, retries, error handling
├── models/schemas.py      # Pydantic models
├── prompts/templates.py   # One prompt per agent
└── utils/export.py        # create_zip()
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GROQ_API_KEY` | yes | Your Groq API key (get one at console.groq.com) |
| `GROQ_MODEL` | no | Groq model name. Default: `openai/gpt-oss-20b` |
| `GROQ_MAX_TOKENS` | no | Max completion tokens per call. Default: `8000` |

```bash
cp .env.example .env     # then edit .env and add your key
```

Never commit `.env`. It is listed in `.gitignore`.

## Running locally

```bash
streamlit run app.py
```

## Deploying to Streamlit Cloud

1. Push this project to a GitHub repository (without `.env`).
2. On [share.streamlit.io](https://share.streamlit.io), create a new app from the repository
   with `app.py` as the main file.
3. Open **Advanced settings → Secrets** and add:

   ```toml
   GROQ_API_KEY = "your_groq_api_key_here"
   GROQ_MODEL = "openai/gpt-oss-20b"
   ```
4. Deploy. The app reads settings from environment variables (local `.env`) first and
   from Streamlit secrets second.

## Example input

> Build a simple expense tracker where users can add expenses with amount, category, and
> date, view all expenses, and see total spending.

## Example output

- **Understand:** "Expense Tracker" with features: add expense, view expenses, total spending.
- **Plan:** a single-file Streamlit app that keeps expenses in session state.
- **Build:** `app.py` (+ `requirements.txt`), downloadable as a ZIP.
- **Explain:** what each file does, how it works, and the concepts used.
- **Learn:** skills practiced, a 4-5 question quiz, and ideas to extend the app.

## Security considerations

- Generated code is never run: no `eval()`, `exec()`, subprocesses or dynamic imports.
- Python files are only *parsed* (`ast.parse`) to catch syntax errors, never executed.
- Generated code that calls `eval()` or `exec()` is rejected and regenerated.
- Generated file names are validated (no absolute paths, no `..`) before the ZIP is built.
- The API key is read from the environment or Streamlit secrets and is never shown in the UI.
- Review any generated code before running it on your own machine.

## Future improvements

- Sandboxed execution of generated apps (for example in a container)
- Iterative refinement ("add a delete button") and chat-style edits
- Multi-file project support with dependency analysis
- Streaming output and per-stage regeneration
- Saving history of generated projects
- Automated tests generated alongside the app

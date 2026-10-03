"""LangGraph workflow: Understand -> Plan -> Build -> Explain -> Learn.

Each stage is a separate node. A node builds a focused prompt from the shared
state, calls the LLM through ``generate_structured`` (JSON parsing, Pydantic
validation and retries), and stores the validated result in the state.

Generated code is only stored as text. It is never executed.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator, List, NamedTuple, Optional, Tuple, TypedDict

from langgraph.graph import END, START, StateGraph

from llm.client import generate_structured
from models.schemas import (
    BuildOutput,
    ExplainOutput,
    LearnOutput,
    PlanOutput,
    RequirementOutput,
)
from prompts.templates import (
    BUILD_PROMPT,
    DEFAULT_TARGET_GUIDANCE,
    EXPLAIN_PROMPT,
    LEARN_PROMPT,
    PLAN_PROMPT,
    TARGET_GUIDANCE,
    UNDERSTAND_PROMPT,
)

BUILD_TARGETS: List[str] = list(TARGET_GUIDANCE.keys())

# Completion-token budgets per stage. Keeping them modest helps stay under Groq's
# tokens-per-minute limits. A truncated reply is retried with a larger budget.
STAGE_MAX_TOKENS = {
    "Understand": 2000,
    "Plan": 2500,
    "Build": 6000,
    "Explain": 4000,
    "Learn": 3500,
}


class BuilderState(TypedDict, total=False):
    """Shared state passed between all nodes."""

    app_idea: str
    build_target: str
    requirements: RequirementOutput
    plan: PlanOutput
    build: BuildOutput
    explanation: ExplainOutput
    learning: LearnOutput


class Stage(NamedTuple):
    node: str  # LangGraph node name (must differ from every state key)
    key: str  # state key the node fills in
    label: str  # tab / progress label
    running_text: str  # shown while the stage runs


STAGES: List[Stage] = [
    Stage("understand_stage", "requirements", "Understand", "Understanding your idea"),
    Stage("plan_stage", "plan", "Plan", "Planning the architecture"),
    Stage("build_stage", "build", "Build", "Generating the source code"),
    Stage("explain_stage", "explanation", "Explain", "Explaining the code"),
    Stage("learn_stage", "learning", "Learn", "Creating your learning material"),
]


def _to_json(model: Any) -> str:
    return model.model_dump_json(indent=2)


# --------------------------------------------------------------------------- #
# Nodes
# --------------------------------------------------------------------------- #
def understand_node(state: BuilderState) -> Dict[str, Any]:
    prompt = UNDERSTAND_PROMPT.format(
        app_idea=state["app_idea"],
        build_target=state["build_target"],
    )
    result = generate_structured(
        prompt,
        RequirementOutput,
        stage="Understand",
        max_tokens=STAGE_MAX_TOKENS["Understand"],
    )
    return {"requirements": result}


def plan_node(state: BuilderState) -> Dict[str, Any]:
    prompt = PLAN_PROMPT.format(
        requirements_json=_to_json(state["requirements"]),
        build_target=state["build_target"],
    )
    result = generate_structured(
        prompt,
        PlanOutput,
        stage="Plan",
        max_tokens=STAGE_MAX_TOKENS["Plan"],
    )
    return {"plan": result}


def build_node(state: BuilderState) -> Dict[str, Any]:
    build_target = state["build_target"]
    prompt = BUILD_PROMPT.format(
        requirements_json=_to_json(state["requirements"]),
        plan_json=_to_json(state["plan"]),
        build_target=build_target,
        target_guidance=TARGET_GUIDANCE.get(build_target, DEFAULT_TARGET_GUIDANCE),
    )

    def check_build(build: BuildOutput) -> None:
        if not any(f.filename.endswith(".py") for f in build.files):
            raise ValueError("at least one .py file is required")
        if build_target == "Streamlit Prototype" and not any(
            "streamlit" in f.code for f in build.files if f.filename.endswith(".py")
        ):
            raise ValueError("a Streamlit Prototype must import and use streamlit")

    result = generate_structured(
        prompt,
        BuildOutput,
        stage="Build",
        validator=check_build,
        max_tokens=STAGE_MAX_TOKENS["Build"],
    )
    return {"build": result}


def explain_node(state: BuilderState) -> Dict[str, Any]:
    build = state["build"]
    prompt = EXPLAIN_PROMPT.format(app_name=build.app_name, build_json=_to_json(build))
    expected = {f.filename for f in build.files}

    def check_explanations(explanation: ExplainOutput) -> None:
        explained = {e.filename for e in explanation.file_explanations}
        if explained != expected:
            raise ValueError(
                "file_explanations must contain exactly one entry per generated file; "
                f"expected filenames {sorted(expected)}, got {sorted(explained)}"
            )

    result = generate_structured(
        prompt,
        ExplainOutput,
        stage="Explain",
        validator=check_explanations,
        max_tokens=STAGE_MAX_TOKENS["Explain"],
    )
    return {"explanation": result}


def learn_node(state: BuilderState) -> Dict[str, Any]:
    build = state["build"]
    prompt = LEARN_PROMPT.format(
        app_name=build.app_name,
        build_json=_to_json(build),
        explanation_json=_to_json(state["explanation"]),
    )
    result = generate_structured(
        prompt, LearnOutput, stage="Learn", max_tokens=STAGE_MAX_TOKENS["Learn"]
    )
    return {"learning": result}


# --------------------------------------------------------------------------- #
# Graph
# --------------------------------------------------------------------------- #
def route_start(state: BuilderState) -> str:
    """Start at the first stage whose result is missing (lets a failed run resume)."""
    for stage in STAGES:
        if stage.key not in state:
            return stage.node
    return END


def build_graph():
    """Compile the linear LangGraph workflow."""
    graph = StateGraph(BuilderState)
    graph.add_node("understand_stage", understand_node)
    graph.add_node("plan_stage", plan_node)
    graph.add_node("build_stage", build_node)
    graph.add_node("explain_stage", explain_node)
    graph.add_node("learn_stage", learn_node)

    # Normally this routes to "understand_stage"; when earlier results are already in
    # the state (resume after a failure) it skips straight to the first missing stage.
    graph.add_conditional_edges(
        START, route_start, {**{stage.node: stage.node for stage in STAGES}, END: END}
    )
    graph.add_edge("understand_stage", "plan_stage")
    graph.add_edge("plan_stage", "build_stage")
    graph.add_edge("build_stage", "explain_stage")
    graph.add_edge("explain_stage", "learn_stage")
    graph.add_edge("learn_stage", END)
    return graph.compile()


def stream_workflow(
    app_idea: str,
    build_target: str,
    existing: Optional[Dict[str, Any]] = None,
) -> Iterator[Tuple[Stage, Dict[str, Any]]]:
    """Run the workflow and yield (stage, state_update) as each node finishes.

    ``existing`` holds results from an earlier, interrupted run for the same request;
    stages that already have a result are skipped.
    """
    app = build_graph()
    initial: BuilderState = {"app_idea": app_idea, "build_target": build_target}
    initial.update(existing or {})  # type: ignore[typeddict-item]
    by_node = {stage.node: stage for stage in STAGES}
    for update in app.stream(initial, stream_mode="updates"):
        for node_name, node_update in update.items():
            yield by_node[node_name], node_update


def run_workflow(app_idea: str, build_target: str) -> BuilderState:
    """Run the full workflow and return the final state (handy for tests)."""
    state: BuilderState = {"app_idea": app_idea, "build_target": build_target}
    for _stage, node_update in stream_workflow(app_idea, build_target):
        state.update(node_update)  # type: ignore[typeddict-item]
    return state
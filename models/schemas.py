"""Pydantic schemas that validate every LLM response in AppPilot AI.

All models forbid unexpected fields and have no defaults for the important
content, so a malformed or incomplete LLM answer is detected (and retried)
instead of being silently accepted.
"""

from __future__ import annotations

import ast
from typing import List

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    """Base class: strip whitespace and reject unknown fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# --------------------------------------------------------------------------- #
# Understand
# --------------------------------------------------------------------------- #
class RequirementOutput(StrictModel):
    app_name: str = Field(min_length=1, max_length=80)
    purpose: str = Field(min_length=1)
    target_users: List[str] = Field(min_length=1)
    features: List[str] = Field(min_length=1)
    user_flow: List[str] = Field(min_length=1)
    # Assumptions are optional context, so an empty list is acceptable.
    assumptions: List[str] = Field(default_factory=list)

    @field_validator("target_users", "features", "user_flow", "assumptions")
    @classmethod
    def _no_blank_items(cls, value: List[str]) -> List[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("list items must be non-empty strings")
        return cleaned


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #
class PlanOutput(StrictModel):
    architecture: str = Field(min_length=1)
    components: List[str] = Field(min_length=1)
    data_model: List[str] = Field(min_length=1)
    development_steps: List[str] = Field(min_length=1)
    technologies: List[str] = Field(min_length=1)

    @field_validator("components", "data_model", "development_steps", "technologies")
    @classmethod
    def _no_blank_items(cls, value: List[str]) -> List[str]:
        cleaned = [item.strip() for item in value]
        if any(not item for item in cleaned):
            raise ValueError("list items must be non-empty strings")
        return cleaned


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
_PLACEHOLDER_MARKERS = (
    "implement this later",
    "your code here",
    "rest of the code",
    "rest of code",
    "# todo",
)


def _check_no_dangerous_calls(filename: str, tree: ast.AST) -> None:
    """Reject generated code that calls eval()/exec() (static check only)."""
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"eval", "exec"}
        ):
            raise ValueError(
                f"{filename} uses {node.func.id}(); generated code must not use eval() or exec()"
            )


def _looks_flattened(code: str) -> bool:
    """True if the code has no real line breaks but contains literal backslash-n text."""
    return "\n" not in code.strip("\n") and "\\n" in code


def _unescape_flattened(code: str) -> str:
    """Turn double-escaped text (\\n, \\t, \\") back into real characters."""
    placeholder = "\x00"
    return (
        code.replace("\\\\", placeholder)
        .replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace('\\"', '"')
        .replace(placeholder, "\\")
    )


def _parses(code: str):
    """Return the AST if ``code`` is valid Python, else None. Never executes anything."""
    try:
        return ast.parse(code)
    except (SyntaxError, ValueError, RecursionError):
        return None


class GeneratedFile(StrictModel):
    filename: str = Field(min_length=1, max_length=100)
    code: str = Field(min_length=1)
    purpose: str = Field(min_length=1)

    @field_validator("filename")
    @classmethod
    def _safe_filename(cls, value: str) -> str:
        if value.startswith(("/", "\\")) or "\\" in value or ".." in value.split("/"):
            raise ValueError("filename must be a simple relative path (no '..', no absolute paths)")
        if value.endswith("/"):
            raise ValueError("filename must point to a file, not a directory")
        return value

    @field_validator("code")
    @classmethod
    def _clean_code(cls, value: str) -> str:
        # str_strip_whitespace already trimmed the ends; normalise newlines.
        value = value.replace("\r\n", "\n")
        if value.startswith("```"):
            raise ValueError("code must be raw source code, not wrapped in markdown fences")
        lowered = value.lower()
        for marker in _PLACEHOLDER_MARKERS:
            if marker in lowered:
                raise ValueError(f"code contains placeholder text ('{marker}'); it must be complete")
        return value + "\n"

    @model_validator(mode="after")
    def _python_must_parse(self) -> "GeneratedFile":
        is_python = self.filename.endswith(".py")

        # Common LLM mistake: newlines double-escaped in JSON (\\n instead of \n), so the
        # whole file arrives as ONE line containing literal backslash-n text. Repair it,
        # but for Python only when the repaired code really parses.
        if _looks_flattened(self.code):
            repaired = _unescape_flattened(self.code)
            if not is_python or (_parses(self.code) is None and _parses(repaired) is not None):
                self.code = repaired.rstrip("\n") + "\n"

        # ast.parse only parses text into a tree. Nothing is ever executed.
        if is_python:
            try:
                tree = ast.parse(self.code)
            except (SyntaxError, ValueError, RecursionError) as exc:
                detail = getattr(exc, "msg", str(exc))
                line = getattr(exc, "lineno", "?")
                hint = ""
                if "\\n" in self.code and self.code.count("\n") <= 1:
                    hint = (
                        " The code seems to contain literal backslash-n text instead of real "
                        "line breaks; escape newlines only once inside the JSON string"
                    )
                raise ValueError(
                    f"{self.filename} has a Python syntax error: {detail} (line {line}).{hint}"
                )
            _check_no_dangerous_calls(self.filename, tree)
        return self


class BuildOutput(StrictModel):
    app_name: str = Field(min_length=1, max_length=80)
    files: List[GeneratedFile] = Field(min_length=1, max_length=6)
    run_instructions: str = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_filenames(self) -> "BuildOutput":
        names = [f.filename for f in self.files]
        if len(names) != len(set(names)):
            raise ValueError("generated files must have unique filenames")
        return self


# --------------------------------------------------------------------------- #
# Explain
# --------------------------------------------------------------------------- #
class FileExplanation(StrictModel):
    filename: str = Field(min_length=1)
    what_it_does: str = Field(min_length=1)
    how_it_works: str = Field(min_length=1)
    concepts: List[str] = Field(min_length=1)


class ExplainOutput(StrictModel):
    overview: str = Field(min_length=1)
    file_explanations: List[FileExplanation] = Field(min_length=1)
    important_concepts: List[str] = Field(min_length=1)


# --------------------------------------------------------------------------- #
# Learn
# --------------------------------------------------------------------------- #
class QuizQuestion(StrictModel):
    question: str = Field(min_length=1)
    options: List[str] = Field(min_length=2, max_length=6)
    answer: str = Field(min_length=1)
    explanation: str = Field(min_length=1)

    @model_validator(mode="after")
    def _answer_is_an_option(self) -> "QuizQuestion":
        options = [o.strip() for o in self.options]
        if len(set(options)) != len(options):
            raise ValueError("quiz options must be unique")
        if self.answer.strip() not in options:
            raise ValueError("quiz answer must exactly match one of the options")
        return self


class LearnOutput(StrictModel):
    skills_learned: List[str] = Field(min_length=1)
    quiz: List[QuizQuestion] = Field(min_length=3, max_length=8)
    next_steps: List[str] = Field(min_length=1)
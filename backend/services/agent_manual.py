"""Generate an admin-facing operating manual for the agent pipeline."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent

from backend.services.prompt_loader import load_prompt


_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ManualSource:
    title: str
    path: str
    prompt_names: tuple[str, ...] = ()
    include_full_run_logic: bool = True


_AGENT_SOURCES = [
    ManualSource("Research Agent", "backend/agents/research.py", ("research",)),
    ManualSource("Angles & Hooks Agent", "backend/agents/angles_and_hooks.py", ("angles_and_hooks",)),
    ManualSource("Chapter Writer Agent", "backend/agents/chapter_writer.py", ("chapter_writer",)),
    ManualSource("Scriptwriter Agent", "backend/agents/scriptwriter.py", ("scriptwriter",)),
    ManualSource("Chief Editor & Evaluator Agent", "backend/agents/chief_editor_evaluator.py", ("chief_editor_evaluator",)),
    ManualSource(
        "Corpus Builder Agent",
        "backend/agents/corpus_builder.py",
        ("corpus_builder_extract", "corpus_builder_synthesise"),
        include_full_run_logic=False,
    ),
]


def _source_path(relative_path: str) -> Path:
    return (_ROOT / relative_path).resolve()


def _read_source(relative_path: str) -> str:
    path = _source_path(relative_path)
    if not path.is_file() or _ROOT not in path.parents:
        raise ValueError(f"Manual source is not allowed: {relative_path}")
    return path.read_text(encoding="utf-8")


def _node_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _is_basemodel_class(node: ast.ClassDef) -> bool:
    return any(_node_name(base) == "BaseModel" for base in node.bases)


def _extract_system_prompt(tree: ast.Module) -> str | None:
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "_SYSTEM_PROMPT" for target in node.targets):
            continue
        try:
            value = ast.literal_eval(node.value)
        except Exception:
            return ast.unparse(node.value)
        return str(value)
    return None


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def _extract_llm_calls(tree: ast.Module) -> list[str]:
    calls: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node.func) != "ChatAnthropic":
            continue
        fields: list[str] = []
        for keyword in node.keywords:
            if not keyword.arg or keyword.arg == "api_key":
                continue
            fields.append(f"{keyword.arg}={ast.unparse(keyword.value)}")
        calls.append(f"ChatAnthropic({', '.join(fields)})")
    return calls


def _extract_structured_outputs(tree: ast.Module) -> list[str]:
    outputs: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "with_structured_output":
            continue
        if node.args:
            outputs.append(ast.unparse(node.args[0]))
    return sorted(set(outputs))


def _extract_classes(tree: ast.Module, source: str) -> tuple[list[str], list[str]]:
    agent_classes: list[str] = []
    schema_blocks: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        if node.name.endswith("Agent"):
            agent_classes.append(node.name)
        if _is_basemodel_class(node):
            segment = ast.get_source_segment(source, node)
            if segment:
                schema_blocks.append(segment)
    return agent_classes, schema_blocks


def _method_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {node.name}({ast.unparse(node.args)})"


def _extract_method_signatures(tree: ast.Module) -> list[str]:
    signatures: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                signatures.append(f"{node.name}.{_method_signature(item)}")
    return signatures


def _extract_run_logic(tree: ast.Module, source: str) -> list[str]:
    blocks: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "run":
            segment = ast.get_source_segment(source, node)
            if segment:
                blocks.append(segment)
    return blocks


def _extract_key_functions(tree: ast.Module, source: str, names: set[str]) -> list[str]:
    blocks: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            segment = ast.get_source_segment(source, node)
            if segment:
                blocks.append(segment)
    return blocks


def _markdown_code_block(language: str, value: str) -> str:
    return f"```{language}\n{value.rstrip()}\n```"


def _agent_section(manual_source: ManualSource) -> str:
    source = _read_source(manual_source.path)
    tree = ast.parse(source)
    module_doc = ast.get_docstring(tree) or "No module description."
    prompt = _extract_system_prompt(tree)
    agent_classes, schema_blocks = _extract_classes(tree, source)
    llm_calls = _extract_llm_calls(tree)
    structured_outputs = _extract_structured_outputs(tree)
    method_signatures = _extract_method_signatures(tree)
    run_blocks = _extract_run_logic(tree, source) if manual_source.include_full_run_logic else []

    lines: list[str] = [
        f"## {manual_source.title}",
        "",
        f"**Source file:** `{manual_source.path}`",
        "",
        "### Responsibilities",
        "",
        module_doc,
        "",
    ]

    if agent_classes:
        lines.extend(["### Agent Classes", "", *[f"- `{name}`" for name in agent_classes], ""])

    if llm_calls:
        lines.extend(["### Model Configuration", "", *[f"- `{call}`" for call in llm_calls], ""])

    if structured_outputs:
        lines.extend(["### Structured Outputs", "", *[f"- `{name}`" for name in structured_outputs], ""])

    if method_signatures:
        lines.extend(["### Main Methods", "", *[f"- `{signature}`" for signature in method_signatures], ""])

    if manual_source.prompt_names:
        lines.extend(["### Editable Prompt Files", ""])
        for prompt_name in manual_source.prompt_names:
            prompt_path = f"backend/prompts/{prompt_name}.md"
            lines.extend([
                f"**Prompt file:** `{prompt_path}`",
                "",
                _markdown_code_block("markdown", load_prompt(prompt_name)),
                "",
            ])
    elif prompt:
        lines.extend(["### System Prompt", "", _markdown_code_block("text", prompt), ""])
    else:
        lines.extend(["### System Prompt", "", "This agent does not use an LLM system prompt.", ""])

    if schema_blocks:
        lines.extend(["### Output Schemas", ""])
        for block in schema_blocks:
            lines.extend([_markdown_code_block("python", block), ""])

    if run_blocks:
        lines.extend(["### Run Logic", ""])
        for block in run_blocks:
            lines.extend([_markdown_code_block("python", block), ""])
    elif not manual_source.include_full_run_logic:
        lines.extend([
            "### Run Logic",
            "",
            "This file contains longer corpus-build helper flows. Review the source file for full implementation details.",
            "",
        ])

    return "\n".join(lines).rstrip()


def _graph_section() -> str:
    source = _read_source("backend/graph/journalist_graph.py")
    tree = ast.parse(source)
    module_doc = ast.get_docstring(tree) or "No graph description."
    key_functions = _extract_key_functions(
        tree,
        source,
        {
            "route_after_researcher",
            "route_after_angles_and_hooks",
            "route_after_chapter_writer",
            "route_after_evaluator",
            "route_after_chief_editor_script_audit",
            "build_journalist_graph",
        },
    )

    lines = [
        "## Pipeline Graph",
        "",
        "**Source file:** `backend/graph/journalist_graph.py`",
        "",
        module_doc,
        "",
        "### Routing And Assembly Logic",
        "",
    ]
    for block in key_functions:
        lines.extend([_markdown_code_block("python", block), ""])
    return "\n".join(lines).rstrip()


def _settings_section() -> str:
    return dedent(
        """
        ## Important Tuning Settings

        **Source file:** `backend/config.py`

        These settings control agent model selection, recommendation/rewrite budgets, and retry behavior:

        - `claude_opus_model`: high-stakes generation model option.
        - `claude_model`: default creative and analytical model used by most agents.
        - `claude_haiku_model`: faster model used for lightweight tasks.
        - `quality_score_threshold`: legacy scored evaluation threshold for older payloads.
        - `script_audit_score_threshold`: legacy scored script-audit threshold for older payloads.
        - `max_refinement_cycles`: storyline refinement attempts before scripting.
        - `max_script_revision_cycles`: post-script rewrite attempts.
        - `max_pipeline_cycles`: full research-to-script restart limit.
        - `benchmark_default_rebuild_docs`: target docs per benchmark source; 125 gives a ~500-doc combined corpus.
        - `benchmark_corpus_stale_after_days`: corpus freshness threshold.
        """
    ).strip()


def build_agent_manual_markdown() -> str:
    """Build a Markdown operating manual for all app agents and routing logic."""
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sections = [
        "# AI Journalist Agent Operating Manual",
        "",
        f"Generated: {generated_at}",
        "",
        "This admin export is generated from source code. It includes prompts, output schemas, model settings, and core run/routing logic. It intentionally does not include environment variable values, API keys, passwords, or database connection strings.",
        "",
        "Editable prompts live in `backend/prompts/*.md`. The app loads those Markdown files when an agent calls the model.",
        "",
        _graph_section(),
        "",
        _settings_section(),
        "",
        *[_agent_section(source) for source in _AGENT_SOURCES],
        "",
    ]
    return "\n\n".join(section.rstrip() for section in sections if section).rstrip() + "\n"

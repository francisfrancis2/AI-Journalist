"""
Analyst Agent — second node in the journalist pipeline.

Responsibilities:
  1. Receive the ResearchPackage from the Researcher.
  2. Identify key findings, narrative angles, data gaps, and notable quotes.
  3. Detect financial metrics and controversial elements.
  4. Produce a structured AnalysisResult that the Storyline Creator can use.
"""

import json
import re
from typing import Any

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from backend.config import settings
from backend.models.research import (
    AnalysisResult,
    EvaluationCriteria,
    KeyFinding,
    ResearchPackage,
    SourceCredibility,
)

log = structlog.get_logger(__name__)

_SYSTEM_PROMPT = """You are a senior editorial analyst and documentary researcher.
You have been given a collection of raw research sources on a topic.
Your task is to synthesise this material into a structured editorial analysis.

Return ONLY a valid JSON object with this structure:
{
  "executive_summary": "<2-3 sentence summary of the most important facts>",
  "key_findings": [
    {
      "claim": "<specific, verifiable fact or insight>",
      "supporting_sources": ["<title or URL>", ...],
      "confidence": 0.0-1.0,
      "category": "financial|human_interest|trend|regulatory|technology|cultural"
    }
  ],
  "narrative_angles": ["<compelling story angle>", ...],
  "data_gaps": ["<missing information that would strengthen the story>", ...],
  "recommended_tone": "investigative|explanatory|narrative|profile|trend",
  "controversies": ["<controversial aspect>", ...],
  "notable_quotes": [
    {"quote": "<text>", "speaker": "<name/title>", "source": "<URL or title>"}
  ],
  "financial_metrics": null or {"<metric>": "<value>", ...}
}

Be rigorous. Only include claims supported by the provided sources.
Confidence scores should reflect how well-sourced each claim is."""

_MAX_SOURCE_CHARS = 60_000  # roughly 15k tokens of context for sources


def _build_source_digest(package: ResearchPackage) -> str:
    """Produce a condensed digest of top sources for the prompt."""
    lines: list[str] = []
    for i, src in enumerate(package.top_sources(20), 1):
        credibility_tag = f"[{src.credibility.value.upper()}]"
        lines.append(
            f"--- SOURCE {i} {credibility_tag} ---\n"
            f"Title: {src.title}\n"
            f"URL: {src.url or 'N/A'}\n"
            f"Content: {src.content[:1500]}\n"
        )
    digest = "\n".join(lines)
    return digest[:_MAX_SOURCE_CHARS]


class AnalystAgent:
    """
    Editorial analyst that transforms raw research into structured insights.

    Example::

        agent = AnalystAgent()
        state_updates = await agent.run(state)
    """

    def __init__(self) -> None:
        self._llm = ChatAnthropic(
            model=settings.claude_model,
            api_key=settings.anthropic_api_key,
            max_tokens=4096,
            temperature=0.2,
        )

    async def run(self, state: dict) -> dict:
        """
        Execute the analysis phase.

        Args:
            state: Current JournalistState containing ``research_package``.

        Returns:
            Partial state update with ``analysis_result``.
        """
        package: ResearchPackage = state["research_package"]
        topic: str = state["topic"]
        tone: str = state.get("tone", "explanatory")

        log.info("analyst.start", topic=topic, source_count=package.total_sources)

        source_digest = _build_source_digest(package)

        prompt = (
            f"Topic: {topic}\n"
            f"Target tone: {tone}\n"
            f"Total sources collected: {package.total_sources}\n\n"
            f"=== RESEARCH SOURCES ===\n{source_digest}"
        )

        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ]

        response = await self._llm.ainvoke(messages)
        raw_text: str = response.content

        # Extract the JSON payload
        match = re.search(r"\{.*\}", raw_text, re.DOTALL)
        if not match:
            raise ValueError(f"Analyst LLM did not return valid JSON: {raw_text[:300]}")

        data: dict[str, Any] = json.loads(match.group())

        # Build structured AnalysisResult
        key_findings = [
            KeyFinding(
                claim=f["claim"],
                supporting_sources=f.get("supporting_sources", []),
                confidence=float(f.get("confidence", 0.5)),
                category=f.get("category", "general"),
            )
            for f in data.get("key_findings", [])
        ]

        result = AnalysisResult(
            topic=topic,
            executive_summary=data.get("executive_summary", ""),
            key_findings=key_findings,
            narrative_angles=data.get("narrative_angles", []),
            data_gaps=data.get("data_gaps", []),
            recommended_tone=data.get("recommended_tone", tone),
            controversies=data.get("controversies", []),
            notable_quotes=data.get("notable_quotes", []),
            financial_metrics=data.get("financial_metrics"),
        )

        log.info(
            "analyst.complete",
            topic=topic,
            findings=len(result.key_findings),
            angles=len(result.narrative_angles),
        )

        return {"analysis_result": result}

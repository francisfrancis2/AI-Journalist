"""
Scriptwriter Agent — final node in the journalist pipeline.

Responsibilities:
  1. Receive the approved storyline and full research package.
  2. Write a complete, production-ready narrator script act-by-act in parallel.
  3. Include on-screen text, b-roll cues, and interview prompts.
  4. Upload the finished script to S3.
  5. Persist word count, duration estimate, and S3 key back into state.
"""

import asyncio
import uuid
from typing import Optional

import aioboto3
import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from backend.config import settings
from backend.models.research import AnalysisResult, StorylineProposal
from backend.models.story import FinalScript, ScriptSection

log = structlog.get_logger(__name__)

_WORDS_PER_MINUTE = 150


# ── Structured output schema ──────────────────────────────────────────────────

class ActOutput(BaseModel):
    narration: str = Field(description="Full narrator script for this act — complete sentences, natural cadence")
    word_count: int = Field(description="Word count of the narration")


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are an Emmy-award-winning documentary scriptwriter for a major digital media company.
Your scripts match the style of Business Insider, Bloomberg Quicktake, and CNBC Make It documentaries.

Write complete narration for ONE act of a documentary.

Guidelines:
- Write for the ear, not the eye. Short sentences. Active voice.
- Start Act 1 with the sharpest, most dramatic sentence.
- Use rhetorical questions to maintain tension.
- Ground abstract statistics in human terms.
- word_count: count the words in your narration accurately."""


class ScriptwriterAgent:
    """
    Production-ready scriptwriter that generates act-by-act documentary narration.

    Example::

        agent = ScriptwriterAgent()
        state_updates = await agent.run(state)
    """

    def __init__(self) -> None:
        _llm = ChatAnthropic(
            model=settings.claude_model,
            api_key=settings.anthropic_api_key,
            max_tokens=2048,
            temperature=0.4,
        )
        self._structured_llm = _llm.with_structured_output(ActOutput)

    async def _write_act(
        self,
        act_data: dict,
        storyline: StorylineProposal,
        analysis: AnalysisResult,
        topic: str,
    ) -> ScriptSection:
        """Write narration for a single act."""
        relevant_quotes = "\n".join(
            f'  "{q["quote"]}" — {q["speaker"]}'
            for q in analysis.notable_quotes[:3]
        )
        relevant_findings = "\n".join(
            f"  - {f.claim}"
            for f in analysis.key_findings
            if f.category in [act_data.get("purpose", ""), "general"]
        )[:2000]

        prompt = (
            f"Documentary: {storyline.title}\n"
            f"Logline: {storyline.logline}\n"
            f"Overall tone: {storyline.tone}\n\n"
            f"=== ACT TO WRITE ===\n"
            f"Act {act_data['act_number']}: {act_data['act_title']}\n"
            f"Purpose: {act_data['purpose']}\n"
            f"Key points to cover:\n"
            + "\n".join(f"  - {kp}" for kp in act_data.get("key_points", []))
            + f"\nTarget duration: {act_data['estimated_duration_seconds']} seconds\n"
            f"Target word count: {int(act_data['estimated_duration_seconds'] / 60 * _WORDS_PER_MINUTE)}\n\n"
            f"=== RELEVANT RESEARCH ===\n"
            f"Key facts:\n{relevant_findings or '  (use general topic knowledge)'}\n\n"
            f"Notable quotes:\n{relevant_quotes or '  (none available)'}"
        )

        output: ActOutput = await self._structured_llm.ainvoke([
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])

        return ScriptSection(
            section_number=act_data["act_number"],
            title=act_data["act_title"],
            narration=output.narration,
            estimated_seconds=act_data["estimated_duration_seconds"],
        )

    async def _upload_to_s3(self, script: FinalScript) -> str:
        """Serialise the script to JSON and upload to S3. Returns the S3 key."""
        key = f"scripts/{script.story_id}/{script.title[:50].replace(' ', '_')}.json"
        content = script.model_dump_json(indent=2).encode("utf-8")

        session = aioboto3.Session(
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )
        client_kwargs = {}
        if settings.s3_endpoint_url:
            client_kwargs["endpoint_url"] = settings.s3_endpoint_url
        async with session.client("s3", **client_kwargs) as s3:
            await s3.put_object(
                Bucket=settings.s3_bucket_scripts,
                Key=key,
                Body=content,
                ContentType="application/json",
            )
        log.info("scriptwriter.s3_uploaded", key=key)
        return key

    async def run(self, state: dict) -> dict:
        storyline: StorylineProposal = state["selected_storyline"]
        analysis: AnalysisResult = state["analysis_result"]
        topic: str = state["topic"]
        story_id: str = state["story_id"]

        log.info("scriptwriter.start", topic=topic, acts=len(storyline.acts))

        # Write all acts in parallel — each act is independent
        act_tasks = [
            self._write_act(
                act_data={
                    "act_number": act.act_number,
                    "act_title": act.act_title,
                    "purpose": act.purpose,
                    "key_points": act.key_points,
                    "estimated_duration_seconds": act.estimated_duration_seconds,
                },
                storyline=storyline,
                analysis=analysis,
                topic=topic,
            )
            for act in storyline.acts
        ]
        sections: list[ScriptSection] = list(await asyncio.gather(*act_tasks))

        total_words = sum(len(s.narration.split()) for s in sections)
        duration_minutes = total_words / _WORDS_PER_MINUTE

        source_refs = [
            {
                "title": src.title,
                "url": src.url,
                "credibility": src.credibility.value,
                "type": src.source_type.value,
            }
            for src in state["research_package"].top_sources(15)
        ]

        final_script = FinalScript(
            story_id=uuid.UUID(story_id),
            title=storyline.title,
            logline=storyline.logline,
            opening_hook=storyline.opening_hook,
            sections=sections,
            closing_statement=storyline.closing_statement,
            total_word_count=total_words,
            estimated_duration_minutes=round(duration_minutes, 1),
            sources=source_refs,
            metadata={
                "topic": topic,
                "tone": storyline.tone,
                "unique_angle": storyline.unique_angle,
                "target_audience": storyline.target_audience,
                "evaluation_score": (
                    state["evaluation_report"].overall_score
                    if state.get("evaluation_report") else None
                ),
            },
        )

        s3_key: str | None = None
        try:
            s3_key = await self._upload_to_s3(final_script)
        except Exception as exc:
            log.warning("scriptwriter.s3_upload_failed", error=str(exc))

        log.info(
            "scriptwriter.complete",
            title=storyline.title,
            word_count=total_words,
            duration_min=f"{duration_minutes:.1f}",
        )

        return {
            "final_script": final_script,
            "script_s3_key": s3_key,
        }

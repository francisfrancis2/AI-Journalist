## Angles & Hooks Agent

**Source file:** `backend/agents/angles_and_hooks.py`

### Responsibilities

Angles & Hooks Agent.

This is the canonical ideation/angle/hook agent in the five-agent model. It
also owns the research-analysis skill used by the script pipeline, delegating to
the embedded angle-synthesis skill so current tested behavior remains
stable.

### Agent Classes

- `AnglesAndHooksAgent`

### Model Configuration

- `ChatAnthropic(model=settings.claude_haiku_model, max_tokens=2500, temperature=0.35)`

### Structured Outputs

- `IdeationOutput`

### Main Methods

- `AnglesAndHooksAgent.def __init__(self)`
- `AnglesAndHooksAgent.async def analyze_research(self, state: dict[str, Any])`
- `AnglesAndHooksAgent.async def run(self, *, story: StoryORM, user_message: str, stage: IdeationStage, fresh_research_context: str='')`

### Editable Prompt Files

**Prompt file:** `backend/prompts/angles_and_hooks.md`

```markdown
ROLE BOUNDARY: You are the Angles & Hooks Agent for a human journalist. Your only job is to help transform a rough story idea into strong documentary angles and a concise story hook. You do not write the final script and you do not draft chapter narration.

You are a brainstorming and ideation partner. Work through dialogue: propose options, challenge weak framing, ask for missing input when needed, and help the user move from a rough idea toward:
- a sharper working brief
- producer-selectable story angles
- one approved pitch-style story hook under 100 words

If a ROLE-SPECIFIC LIBRARY REFERENCE PACK is provided, use it only as craft guidance from benchmark scripts: angle shapes, hook types, evidence expectations, tension patterns, and pitch logic. It is not a factual source. Never copy reference wording, never name source channels, and never use reference-library examples as facts for this story.

If CORPUS APPROACH EXEMPLARS are provided, treat them the same way: each is a real benchmark documentary shown as a title, description, and opening hook to demonstrate a *different approach* to turning data into a story. Read across the set and deliberately spread your angles over those approaches so no two angles use the same move. They are craft inspiration only — never a factual source, never copy their wording, topics, or facts, and never name a source channel.

When source context is provided, use it for factual grounding. If no source context is provided, avoid making hard factual claims and frame uncertain claims as research needs.

ANGLE RULES:
- Return 3-5 angles when the active stage is angles.
- Each angle should be one sentence and distinct by framing, not just wording.
- Prefer angles with a concrete tension: money, risk, power, incentives, timing, human stakes, process, contradiction, or measurable consequence.
- Include a short rationale explaining why each angle is different and useful.
- Let the user ask for more angles, different directions, or fine-tuning of one angle.

HOOK RULES:
- Return one pitch-style synopsis when the active stage is story hook.
- Keep the hook under 100 words.
- Base it on the selected angle and current chat context.
- It should describe the main idea and viewer promise, not the full script.

RESEARCH SYNTHESIS SKILL:
When you receive a full research package, act as the same agent's research-to-angle synthesis skill. This is an analyst role first: go through the data and derive the most interesting material before you write a single angle. An ANALYST PASS section in the prompt spells out the order — mine and rank the data, record it as key findings, then build each angle on a different high-ranked finding and a different corpus approach.
Mine the research for these structural elements and use them to produce editorial analysis plus selectable angles:
- numeric_anchor: a specific number with units, price, percentage, count, duration, salary, ratio, or market size.
- process_step: how something is made, delivered, operated, regulated, financed, or experienced.
- protagonist: a named person whose story can carry viewer stakes.
- origin_event: a dated decision, regulation, founding, inflection point, or historical cause.
- counterintuitive: a fact that contradicts conventional wisdom and can power the opening.
- visual_artifact: a place, object, machine, archive, chart, process, or scene the viewer can see.
- quotable: a direct, named, attributed quote.

For research synthesis:
- Produce a 2-3 sentence executive summary that leads with the sharpest supported claim.
- Extract concrete key findings with source IDs and confidence.
- Generate 3-5 selectable angles, each one sentence and max 20 words.
- Use different framing axes across the set: human_interest, data_driven, contrarian, consensus, local, global, narrative, explanatory.
- Identify data gaps, controversies, notable quotes, and financial metrics when present.
- Only include claims and angles supported by the provided sources.

BACKEND DECISION:
- Decide the most fitting tone: investigative, explanatory, or narrative.
- Decide target duration as 5, 10, or 15 minutes based on complexity.

EDITORIAL POLICY - UAE COVERAGE (HARD CONSTRAINT):
- Do NOT portray the UAE, its government, rulers, or institutions negatively or critically.
- If the topic involves the UAE, keep any UAE involvement neutral or constructive and avoid accusatory framing.
```

### Output Schemas

```python
class IdeationAngleOutput(BaseModel):
    angle: str
    framing_axis: str = "explanatory"
    rationale: str = ""
```

```python
class IdeationChapterOutput(BaseModel):
    chapter_number: int
    title: str
    purpose: str
    key_points: list[str] = Field(default_factory=list)
```

```python
class IdeationOutput(BaseModel):
    assistant_message: str
    title: Optional[str] = None
    decided_tone: str = "explanatory"
    target_duration_minutes: int = 10
    angles: list[IdeationAngleOutput] = Field(default_factory=list)
    hook_options: list[str] = Field(default_factory=list)
    story_hook: Optional[str] = None
    chapters: list[IdeationChapterOutput] = Field(default_factory=list)
```

### Run Logic

```python
async def run(
        self,
        *,
        story: StoryORM,
        user_message: str,
        stage: IdeationStage,
        fresh_research_context: str = "",
    ) -> IdeationOutput:
        """Generate or refine angles/hooks for the current ideation stage."""
        if stage == IdeationStage.CHAPTERS:
            raise ValueError("Chapter planning belongs to ChapterWriterAgent.")

        stage_rules = {
            IdeationStage.ANGLES: (
                "Active stage: angles. The only editable artifact is the visible angle list. "
                "When the user asks to add, remove, reorder, or rewrite angles, return the final visible list of 3-8 "
                "producer-selectable angles. They must differ by framing, not just wording, and each angle should be one sentence. "
                "For initial story creation or explicit requests to generate angle options, always return angle options; "
                "if research is weak, make the angles provisional and explain what extra specificity would sharpen them. "
                "If the user asks only for research or advice, leave angles empty and answer in assistant_message."
            ),
            IdeationStage.HOOK: (
                "Active stage: story hook. The only editable artifact is the visible hook text and hook options. "
                "When the user asks to add, remove, reorder, or rewrite hooks, return up to 6 distinct pitch-style "
                "hook_options under 100 words each and set story_hook to the strongest visible hook. Each hook should "
                "describe the main idea and tension, not the full script. If the user asks only for research or advice, "
                "leave hook_options empty, leave story_hook unset, and answer in assistant_message."
            ),
            IdeationStage.PROMPT: "Active stage: prompt. Help clarify the rough story idea.",
            IdeationStage.READY_FOR_SCRIPT: "Active stage: ready for script. Help verify the plan before scripting.",
        }[stage]
        reference_pack = get_reference_pack(
            role="angles_and_hooks",
            topic=story.topic,
            state={
                "selected_angle": story.selected_angle,
                "story_hook": story.story_hook,
                "generated_angles": story.angles_data or [],
            },
            max_cards=5,
            token_budget=1400,
        )
        reference_context = format_reference_pack(reference_pack)
        prompt = (
            f"{stage_rules}\n\n"
            f"=== CURRENT STORY CONTEXT ===\n{compact_ideation_context(story)}\n\n"
            f"=== RECENT CHAT ===\n"
            + "\n".join(
                f"{item.get('role', 'user')}: {str(item.get('content', ''))[:600]}"
                for item in (story.ideation_chat_data or [])[-10:]
                if isinstance(item, dict)
            )
            + f"\n\n=== FRESH RESEARCH CONTEXT ===\n{fresh_research_context or 'No fresh research was fetched for this turn.'}\n\n"
            f"{reference_context}\n\n"
            f"User request: {user_message}\n\n"
            "Do not change application UI text, navigation, page layout, hidden fields, credentials, or anything outside the active artifact. "
            "Also decide the most fitting documentary tone: investigative, explanatory, or narrative. "
            "Decide target duration as 5, 10, or 15 minutes based on complexity."
        )

        try:
            output: IdeationOutput = await self._structured_llm.ainvoke(
                [SystemMessage(content=load_prompt("angles_and_hooks")), HumanMessage(content=prompt)]
            )
        except Exception as exc:
            log.warning("angles_and_hooks.fallback", story_id=str(story.id), stage=stage, error=str(exc))
            output = fallback_ideation_output(
                topic=story.topic,
                stage=stage,
                selected_angle=story.selected_angle,
                hook=story.story_hook,
            )

        output.decided_tone = normalise_story_tone(output.decided_tone)
        output.target_duration_minutes = normalise_target_duration(output.target_duration_minutes)
        if stage == IdeationStage.HOOK and output.story_hook:
            words = output.story_hook.split()
            if len(words) > 100:
                output.story_hook = " ".join(words[:100]).rstrip(",;:")
        if stage == IdeationStage.HOOK:
            cleaned_hooks: list[str] = []
            for hook_option in output.hook_options:
                hook_text = " ".join((hook_option or "").strip().split())
                if not hook_text:
                    continue
                words = hook_text.split()
                if len(words) > 100:
                    hook_text = " ".join(words[:100]).rstrip(",;:")
                if hook_text not in cleaned_hooks:
                    cleaned_hooks.append(hook_text)
            if output.story_hook:
                story_hook = " ".join(output.story_hook.strip().split())
                if story_hook and story_hook not in cleaned_hooks:
                    cleaned_hooks.insert(0, story_hook)
            output.hook_options = cleaned_hooks[:6]
            if not output.story_hook and output.hook_options:
                output.story_hook = output.hook_options[0]
        return output
```

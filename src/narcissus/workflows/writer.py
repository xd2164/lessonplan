"""A self-reflective workflow for writing an essay"""

import asyncio
import json
import os

from dotenv import load_dotenv
from llama_index.core.prompts import PromptTemplate
from llama_index.core.workflow import (
    Context,
    Event,
    StartEvent,
    StopEvent,
    Workflow,
    step,
)
from llama_index.llms.openai import OpenAI
from llama_index.utils.workflow import draw_all_possible_flows
from pydantic import BaseModel, Field
from tavily import TavilyClient

from narcissus.constants import (
    PLAN_PROMPT,
    REFLECTION_PROMPT,
    RESEARCH_CRITIQUE_PROMPT,
    RESEARCH_PLAN_PROMPT,
    WRITER_PROMPT,
)

load_dotenv()


class ResearchPlanEvent(Event):
    """A research plan for an essay"""

    plan: str


class PlanEvent(Event):
    """A plan for an essay"""

    plan: str


class ResearchEvent(Event):
    """A research plan for an essay"""

    research: str


class WriteEvent(Event):
    """A draft of an essay"""

    text: str


class ReflectEvent(Event):
    """A reflection on a draft"""

    reflection: str


class ReflectionResearchEvent(Event):
    """A research plan for a reflection"""

    plan: str


class Query(BaseModel):
    """A query to search for"""

    query: str = Field(description="The query to search for")


class ResearchPlan(BaseModel):
    """A research plan"""

    queries: list[Query] = Field(description="A list of all the queries to search for")


class SearchEvent(Event):
    """A search event"""

    query: str


class SearchCompleteEvent(Event):
    """A search complete event"""

    research: str


class InitEvent(Event):
    """Initialize state event"""

    status: str


class WriterWorkflow(Workflow):
    """A self-reflective workflow for writing an essay"""

    llm = OpenAI(model="gpt-4o-mini")

    async def set_state(
        self, ctx: Context, key: str, value: dict | str | list | int
    ) -> None:
        """Set a state variable"""
        state = await ctx.get("state")
        state[key] = value
        await ctx.set("state", state)

    async def get_state(self, ctx: Context, key: str) -> dict | str | list | int:
        """Get a state variable"""
        state = await ctx.get("state")
        return state[key]

    @step
    async def start(self, ctx: Context, ev: StartEvent) -> InitEvent:
        """Start the workflow"""
        await ctx.set("search_count", 0)
        await ctx.set("num_drafts_required", ev.num_drafts)
        await ctx.set("num_drafts_completed", 0)
        await ctx.set(
            "state",
            {
                "plan": "",
                "research": {},
                "text": "",
                "reflection": "",
                "query": ev.query,
            },
        )

        return InitEvent(status="initialized")

    @step
    async def plan(self, ctx: Context, ev: InitEvent) -> PlanEvent:
        """Plan the essay"""
        query = await self.get_state(ctx, "query")

        prompt = f"{PLAN_PROMPT}\n\nTopic: {query}"
        response = await self.llm.acomplete(prompt)

        await self.set_state(ctx, "plan", response.text)

        return PlanEvent(plan=response.text)

    @step
    async def research_plan(self, ctx: Context, ev: PlanEvent) -> ResearchPlanEvent:
        """Research the essay"""
        prompt = PromptTemplate(RESEARCH_PLAN_PROMPT)

        response = await self.llm.astructured_predict(
            ResearchPlan, prompt, outline=ev.plan
        )

        return ResearchPlanEvent(plan=response.model_dump_json())

    @step
    async def research(
        self,
        ctx: Context,
        ev: ResearchPlanEvent | ReflectionResearchEvent | SearchCompleteEvent,
    ) -> SearchEvent | ResearchEvent:
        """Research the essay"""
        state = await ctx.get("state")

        if isinstance(ev, ResearchPlanEvent) or isinstance(ev, ReflectionResearchEvent):
            await ctx.set("search_count", 0)
            plan = json.loads(ev.plan)
            research = state["research"]

            for query in plan["queries"]:
                query = query["query"]
                if query not in research:
                    await ctx.set("search_count", await ctx.get("search_count") + 1)
                    ctx.send_event(SearchEvent(query=query))

        elif isinstance(ev, SearchCompleteEvent):
            result = ctx.collect_events(
                ev, [SearchCompleteEvent] * await ctx.get("search_count")
            )
            if result is not None:
                return ResearchEvent(research=json.dumps(state["research"]))
            else:
                return None

    @step(num_workers=4)
    async def search(self, ctx: Context, ev: SearchEvent) -> SearchCompleteEvent:
        """Search the web for information"""
        client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
        results = client.search(ev.query, search_depth="advanced")

        state = await ctx.get("state")
        await self.set_state(
            ctx, "research", {**state["research"], ev.query: results["results"]}
        )

        return SearchCompleteEvent(research=json.dumps(state["research"]))

    @step
    async def write(self, ctx: Context, ev: ResearchEvent) -> WriteEvent | StopEvent:
        """Write the essay"""
        num_drafts_completed = await ctx.get("num_drafts_completed")
        num_drafts_required = await ctx.get("num_drafts_required")

        if num_drafts_completed < num_drafts_required:
            print(f"Writing draft {num_drafts_completed + 1} of {num_drafts_required}")
            await ctx.set("num_drafts_completed", num_drafts_completed + 1)

            plan = await self.get_state(ctx, "plan")
            research = await self.get_state(ctx, "research")
            reflection = await self.get_state(ctx, "reflection")
            draft_text = await self.get_state(ctx, "text")

            prompt = f"{WRITER_PROMPT}\n\nOutline: {plan}\n\nResearch: {research}\n\nDraft: {draft_text}\n\nReflection: {reflection}"
            response = await self.llm.acomplete(prompt)

            await self.set_state(ctx, "text", response.text)

            if num_drafts_completed == num_drafts_required - 1:
                return StopEvent(result=await self.get_state(ctx, "text"))
            else:
                return WriteEvent(text=await self.get_state(ctx, "text"))
        else:
            print(f"Workflow complete. {num_drafts_completed} drafts written.")
            return StopEvent(result=await self.get_state(ctx, "text"))

    @step
    async def reflect(self, ctx: Context, ev: WriteEvent) -> ReflectEvent:
        """Reflect on the essay"""
        text = await self.get_state(ctx, "text")
        prompt = f"{REFLECTION_PROMPT}\n\nEssay: {text}"
        response = await self.llm.acomplete(prompt)

        await self.set_state(ctx, "reflection", response.text)

        return ReflectEvent(reflection=response.text)

    @step
    async def reflection_research(
        self, ctx: Context, ev: ReflectEvent
    ) -> ReflectionResearchEvent:
        """Research the critique"""
        prompt = PromptTemplate(RESEARCH_CRITIQUE_PROMPT)

        response = await self.llm.astructured_predict(
            ResearchPlan, prompt, outline=ev.reflection
        )

        return ReflectionResearchEvent(plan=response.model_dump_json())


async def main() -> None:
    """Main function"""
    w = WriterWorkflow(timeout=300, verbose=True)
    handler = w.run(query="self-reflection in the context of AI", num_drafts=2)

    final_result = await handler
    print("Final result", str(final_result))

    draw_all_possible_flows(WriterWorkflow, filename="writer_workflow.html")


if __name__ == "__main__":
    asyncio.run(main())

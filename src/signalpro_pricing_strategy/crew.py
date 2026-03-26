from datetime import datetime
from pathlib import Path

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task, before_kickoff
from crewai.knowledge.source.text_file_knowledge_source import TextFileKnowledgeSource

from signalpro_pricing_strategy.tools import file_read_tool, search_tool


def _read_if_file(value: str) -> str:
    """If value looks like a file path and exists, read and return its content."""
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if stripped.endswith((".md", ".txt", ".markdown")) and Path(stripped).is_file():
        content = Path(stripped).read_text(encoding="utf-8")
        print(f"[INFO] 已讀取檔案: {stripped} ({len(content)} 字元)")
        return content
    return value


@CrewBase
class SignalproPricingStrategy:
    """SignalPro Pricing Strategy & Business Model Expert Crew"""

    agents_config = "config/agents.yaml"
    tasks_config = "config/tasks.yaml"

    @before_kickoff
    def prepare_inputs(self, inputs):
        # Auto-read file paths for key input fields
        for key in ("customer_scenario", "sales_channel", "product_spec", "extra_context"):
            if key in inputs:
                inputs[key] = _read_if_file(inputs[key])

        if "current_date" not in inputs:
            inputs["current_date"] = datetime.now().strftime("%Y-%m-%d")
        if "customer_scenario" not in inputs:
            inputs["customer_scenario"] = "尚未指定客戶情境，請提供客戶產業、規模、痛點等資訊。"
        if "sales_channel" not in inputs:
            inputs["sales_channel"] = "直接銷售（Direct Sales）"
        if "proposal_title" not in inputs:
            inputs["proposal_title"] = "SignalPro 定價方案"
        if "product_spec" not in inputs:
            inputs["product_spec"] = ""
        if "extra_context" not in inputs:
            inputs["extra_context"] = ""
        return inputs

    @agent
    def pricing_architect(self) -> Agent:
        return Agent(
            config=self.agents_config["pricing_architect"],
            llm="anthropic/claude-sonnet-4-6",
            tools=[file_read_tool],
            verbose=True,
        )

    @agent
    def competitive_analyst(self) -> Agent:
        return Agent(
            config=self.agents_config["competitive_analyst"],
            llm="anthropic/claude-sonnet-4-6",
            tools=[search_tool, file_read_tool],
            verbose=True,
        )

    @agent
    def proposal_writer(self) -> Agent:
        return Agent(
            config=self.agents_config["proposal_writer"],
            llm="anthropic/claude-sonnet-4-6",
            tools=[file_read_tool],
            verbose=True,
        )

    @task
    def design_pricing(self) -> Task:
        return Task(config=self.tasks_config["design_pricing"])

    @task
    def analyze_competitors(self) -> Task:
        return Task(
            config=self.tasks_config["analyze_competitors"],
            context=[self.design_pricing()],
        )

    @task
    def write_proposal(self) -> Task:
        return Task(
            config=self.tasks_config["write_proposal"],
            context=[self.design_pricing(), self.analyze_competitors()],
            output_file="output/proposal.md",
        )

    @crew
    def crew(self) -> Crew:
        knowledge_source = TextFileKnowledgeSource(
            file_paths=["knowledge/signalpro_pricing_guide.txt"],
        )
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            memory=True,
            knowledge_sources=[knowledge_source],
            verbose=True,
        )

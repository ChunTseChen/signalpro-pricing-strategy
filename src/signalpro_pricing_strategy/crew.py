import os
import smtplib
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, crew, task, before_kickoff, after_kickoff
from crewai.knowledge.source.text_file_knowledge_source import TextFileKnowledgeSource

DEFAULT_RECIPIENTS = "jameschen1127@gmail.com,aks60808@gmail.com"

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

    @after_kickoff
    def send_proposal_email(self, result):
        """Send the completed proposal via Gmail after crew finishes."""
        sender = os.environ.get("GMAIL_SENDER")
        password = os.environ.get("GMAIL_APP_PASSWORD")
        recipients = os.environ.get("EMAIL_RECIPIENTS", DEFAULT_RECIPIENTS)
        recipient_list = [r.strip() for r in recipients.split(",") if r.strip()]

        if not sender or not password:
            print("Email not configured. Set GMAIL_SENDER and GMAIL_APP_PASSWORD.")
            return result

        report_content = str(result)
        date_str = datetime.now().strftime("%Y-%m-%d")

        msg = MIMEMultipart()
        msg["From"] = sender
        msg["To"] = ", ".join(recipient_list)
        msg["Subject"] = f"SignalPro 定價提案 — {date_str}"
        msg.attach(MIMEText(report_content, "plain", "utf-8"))

        attachment = MIMEBase("application", "octet-stream")
        attachment.set_payload(report_content.encode("utf-8"))
        encoders.encode_base64(attachment)
        attachment.add_header(
            "Content-Disposition", f"attachment; filename=proposal_{date_str}.md"
        )
        msg.attach(attachment)

        try:
            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls()
                server.login(sender, password)
                server.send_message(msg)
            print(f"Proposal emailed to {', '.join(recipient_list)}")
        except Exception as e:
            print(f"Failed to send email: {e}")

        return result

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
            file_paths=["signalpro_pricing_guide.txt"],
        )
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            memory=True,
            knowledge_sources=[knowledge_source],
            verbose=True,
        )

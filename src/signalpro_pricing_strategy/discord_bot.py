"""
Discord Bot — Jeff (Pricing) — 透過 CrewAI 雲端觸發定價策略分析。

觸發後任務在 CrewAI 雲端執行，完成後自動寄 email 並將結果回傳到 Discord。

使用方式（在 Discord 頻道中 @mention）：

  @Jeff(Pricing)                          → 顯示使用說明
  @Jeff(Pricing) 客戶情境描述              → 用文字描述客戶情境，觸發定價分析
  @Jeff(Pricing) + 附加 .md/.txt 檔案      → 讀取附件作為產品規劃說明，觸發分析
  @Jeff(Pricing) 客戶情境 + 附加檔案       → 文字 = 客戶情境，附件 = 產品規劃說明
  @Jeff(Pricing) 狀態                      → 查看最近一次執行狀態

設定步驟：
  1. Discord Developer Portal → 建立 Application → Bot
  2. Bot USERNAME 改為 Jeff(Pricing)
  3. Bot 頁面 → 往下找到 Privileged Gateway Intents 區塊 → 開啟 MESSAGE CONTENT INTENT
  4. OAuth2 → URL Generator → 勾選 bot → 勾選 Send Messages, Read Message History, Attach Files
  5. .env 中設定：
     DISCORD_BOT_TOKEN=你的 discord bot token
     CREWAI_CREW_URL=你的 crew 公開 URL
     CREWAI_CREW_TOKEN=你的 crew token
  6. 執行: run_discord_bot
"""

import asyncio
import io
import os
import tempfile
from datetime import datetime
from pathlib import Path

import discord
import httpx

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

_last = {"kickoff_id": None, "scenario": None, "time": None, "status": None}

# Polling interval (seconds) and max wait time (minutes)
POLL_INTERVAL = 30
MAX_POLL_MINUTES = 30

HELP_TEXT = """**Jeff(Pricing) — SignalPro 定價策略助手**

**使用方式：**
• `@Jeff(Pricing) 客戶情境描述` — 用文字觸發分析
• `@Jeff(Pricing)` + 附加 `.md` / `.txt` 檔案 — 讀取附件作為產品規劃說明
• `@Jeff(Pricing) 客戶情境` + 附加檔案 — 文字當客戶情境，附件當產品規劃
• `@Jeff(Pricing) 狀態` — 查看執行狀態

**附件規則：**
• 第 1 個附件 → 產品規劃說明（product_spec）
• 第 2 個以後 → 補充資料（extra_context）

**進階選項（加在訊息文字中）：**
• `--channel "NVIDIA DGX Spark 打包"` — 指定銷售通路
• `--title "提案標題"` — 指定提案標題

**範例：**
> @Jeff(Pricing) 一家台灣中型製造業，500人，年度IT預算200萬台幣
> @Jeff(Pricing) --channel "NVIDIA DGX Spark 打包" --title "日本車廠方案" + 附件
"""


def _get_crewai_config():
    # Railway sometimes has trailing spaces in var names from copy-paste
    env = {k.strip(): v.strip() for k, v in os.environ.items()}
    url = env.get("CREWAI_CREW_URL", "")
    token = env.get("CREWAI_CREW_TOKEN", "")
    missing = []
    if not url:
        missing.append("CREWAI_CREW_URL")
    if not token:
        missing.append("CREWAI_CREW_TOKEN")
    if missing:
        available = [k for k in os.environ if k.startswith(("CREW", "DISCORD"))]
        raise RuntimeError(
            f"Missing env vars: {', '.join(missing)}. "
            f"Available CREW*/DISCORD* vars: {available}"
        )
    return url, token


def _trigger_crew(inputs: dict) -> str:
    """Call CrewAI platform API to kick off the crew. Returns kickoff_id."""
    url, token = _get_crewai_config()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {"inputs": inputs}
    r = httpx.post(f"{url}/kickoff", headers=headers, json=payload, timeout=30)
    r.raise_for_status()
    return r.json().get("kickoff_id", "unknown")


def _get_crew_status(kickoff_id: str) -> dict:
    """Check the status of a kickoff on CrewAI platform."""
    url, token = _get_crewai_config()
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = httpx.get(f"{url}/status/{kickoff_id}", headers=headers, timeout=15)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return {"status": "unknown"}


def _parse_args(text: str) -> dict:
    """Parse --channel and --title from message text."""
    import shlex

    channel = "直接銷售（Direct Sales）"
    title = "SignalPro 定價方案"

    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = text.split()

    remaining = []
    i = 0
    while i < len(tokens):
        if tokens[i] == "--channel" and i + 1 < len(tokens):
            channel = tokens[i + 1]
            i += 2
        elif tokens[i] == "--title" and i + 1 < len(tokens):
            title = tokens[i + 1]
            i += 2
        else:
            remaining.append(tokens[i])
            i += 1

    return {
        "text": " ".join(remaining),
        "channel": channel,
        "title": title,
    }


async def _download_attachment(attachment: discord.Attachment, dest_dir: str) -> tuple[str, str] | None:
    """Download a Discord attachment. Returns (filename, content) if supported."""
    filename = attachment.filename.lower()
    if not filename.endswith((".md", ".txt", ".markdown")):
        return None

    dest = Path(dest_dir) / attachment.filename
    await attachment.save(dest)
    content = dest.read_text(encoding="utf-8")
    return (attachment.filename, content)


async def _poll_and_send_result(channel: discord.TextChannel, kickoff_id: str):
    """Poll CrewAI platform for completion, then send result to Discord."""
    max_polls = (MAX_POLL_MINUTES * 60) // POLL_INTERVAL

    for i in range(max_polls):
        await asyncio.sleep(POLL_INTERVAL)

        status_info = _get_crew_status(kickoff_id)
        state = status_info.get("state", "unknown")

        if state == "SUCCESS":
            result = status_info.get("result", "")
            _last["status"] = "完成"

            if not result:
                await channel.send("**Jeff(Pricing) 分析完成！** 但未取得結果內容，請到 CrewAI Dashboard 查看。")
                return

            # Send result to Discord
            result_str = str(result)
            if len(result_str) <= 1900:
                await channel.send(f"**Jeff(Pricing) 定價提案完成！**\n\n{result_str}")
            else:
                # Too long for a message, send as file
                file_buf = io.BytesIO(result_str.encode("utf-8"))
                date_str = datetime.now().strftime("%Y%m%d")
                await channel.send(
                    "**Jeff(Pricing) 定價提案完成！** 提案文件如下：",
                    file=discord.File(file_buf, filename=f"signalpro_proposal_{date_str}.md"),
                )
            return

        elif state == "FAILED":
            error = status_info.get("status", "未知錯誤")
            _last["status"] = f"失敗: {error}"
            await channel.send(f"**Jeff(Pricing) 分析失敗：** {error}")
            return

        # Still running, continue polling

    # Timeout
    _last["status"] = "逾時"
    await channel.send(
        f"**Jeff(Pricing) 分析超過 {MAX_POLL_MINUTES} 分鐘仍未完成。**\n"
        f"Kickoff ID：`{kickoff_id}`\n"
        f"請到 CrewAI Dashboard 查看進度。"
    )


@client.event
async def on_ready():
    print(f"Jeff(Pricing) online: {client.user}")
    print(f"Connected to {len(client.guilds)} server(s)")


@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return

    if client.user not in message.mentions:
        return

    # Strip mentions to get command text
    text = message.content
    for mention in message.mentions:
        text = text.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
    text = text.strip()

    # Status command
    if text in ("狀態", "status"):
        if _last["kickoff_id"]:
            status_info = _get_crew_status(_last["kickoff_id"])
            await message.channel.send(
                f"**Jeff(Pricing) 最近一次執行**\n"
                f"情境：{_last['scenario']}\n"
                f"觸發時間：{_last['time']}\n"
                f"Kickoff ID：`{_last['kickoff_id']}`\n"
                f"狀態：{status_info.get('state', status_info.get('status', 'unknown'))}\n\n"
                f"詳細進度請到 CrewAI Dashboard 查看。"
            )
        else:
            await message.channel.send("目前尚未執行過任何任務。")
        return

    # Help — no text and no attachments
    if not text and not message.attachments:
        await message.channel.send(HELP_TEXT)
        return

    # Parse --channel and --title from text
    parsed = _parse_args(text)
    customer_scenario = parsed["text"]
    sales_channel = parsed["channel"]
    proposal_title = parsed["title"]

    # Download and read attachments
    product_spec = ""
    extra_context_parts = []
    file_summary = ""

    if message.attachments:
        with tempfile.TemporaryDirectory(prefix="jeff_pricing_") as tmpdir:
            downloaded = []
            for att in message.attachments:
                result = await _download_attachment(att, tmpdir)
                if result:
                    downloaded.append(result)

            if downloaded:
                product_spec = downloaded[0][1]
                file_summary = f"📄 `{downloaded[0][0]}` ({len(downloaded[0][1])} 字元) → 產品規劃說明"

                for fname, content in downloaded[1:]:
                    extra_context_parts.append(f"--- {fname} ---\n{content}")
                    file_summary += f"\n📄 `{fname}` ({len(content)} 字元) → 補充資料"
            else:
                file_summary = "⚠️ 附件中沒有 .md 或 .txt 檔案，僅使用文字訊息"

    # Must have at least scenario text or product_spec file
    if not customer_scenario and not product_spec:
        await message.channel.send(HELP_TEXT)
        return

    extra_context = "\n\n".join(extra_context_parts) if extra_context_parts else ""

    # Build inputs for CrewAI platform
    inputs = {
        "current_date": datetime.now().strftime("%Y-%m-%d"),
        "customer_scenario": customer_scenario or "請根據產品規劃說明，設計通用定價方案。",
        "product_spec": product_spec,
        "extra_context": extra_context,
        "sales_channel": sales_channel,
        "proposal_title": proposal_title,
    }

    # Trigger crew on CrewAI platform
    try:
        kickoff_id = _trigger_crew(inputs)
        scenario_display = customer_scenario[:100] if customer_scenario else "(從附件讀取)"
        _last["kickoff_id"] = kickoff_id
        _last["scenario"] = scenario_display
        _last["time"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        _last["status"] = "執行中"

        confirm_msg = f"**收到！Jeff(Pricing) 已在雲端啟動定價分析**\n"
        if customer_scenario:
            display = customer_scenario[:200] + ("..." if len(customer_scenario) > 200 else "")
            confirm_msg += f"📋 客戶情境：{display}\n"
        if file_summary:
            confirm_msg += f"{file_summary}\n"
        confirm_msg += f"🏷️ 銷售通路：{sales_channel}\n"
        confirm_msg += f"📝 提案標題：{proposal_title}\n"
        confirm_msg += f"**Kickoff ID：**`{kickoff_id}`\n\n"
        confirm_msg += f"分析完成後會自動回傳結果到此頻道，並寄送 email。"

        await message.channel.send(confirm_msg)

        # Start polling in background
        asyncio.create_task(_poll_and_send_result(message.channel, kickoff_id))

    except Exception as e:
        await message.channel.send(f"**觸發失敗：** {e}")


def main():
    from dotenv import load_dotenv
    load_dotenv()

    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "DISCORD_BOT_TOKEN not set.\n"
            "請到 Discord Developer Portal 建立 Bot，取得 Token 後設定在 .env 中。"
        )

    # Validate CrewAI config on startup
    _get_crewai_config()

    print("Jeff(Pricing) starting. Press Ctrl+C to stop.")
    client.run(token)

"""
Discord Bot — Jeff (Pricing) — 透過 Discord 觸發 SignalPro 定價策略分析。

使用方式（在 Discord 頻道中 @mention）：

  @Jeff(Pricing)                          → 顯示使用說明
  @Jeff(Pricing) 客戶情境描述              → 用文字描述客戶情境，觸發定價分析
  @Jeff(Pricing) + 附加 .md/.txt 檔案      → 讀取附件作為產品規劃說明，觸發分析
  @Jeff(Pricing) 客戶情境 + 附加檔案       → 文字 = 客戶情境，附件 = 產品規劃說明
  @Jeff(Pricing) 狀態                      → 查看最近一次執行狀態

附件處理規則：
  - 第一個 .md/.txt 附件 → product_spec（產品規劃說明）
  - 第二個以後的附件 → extra_context（補充資料）
  - 訊息文字 → customer_scenario（客戶情境）

進階指令（在訊息文字中使用）：
  --channel "NVIDIA DGX Spark 打包"    → 指定銷售通路
  --title "提案標題"                    → 指定提案標題

設定步驟：
  1. Discord Developer Portal → 建立 Application → Bot
  2. Bot USERNAME 改為 Jeff(Pricing)
  3. Bot 頁面 → 往下找到 Privileged Gateway Intents 區塊 → 開啟 MESSAGE CONTENT INTENT
  4. OAuth2 → URL Generator → 勾選 bot → 勾選 Send Messages, Read Message History, Attach Files
  5. .env 中設定：
     DISCORD_BOT_TOKEN=你的 discord bot token
  6. 執行: run_discord_bot
"""

import asyncio
import os
import tempfile
import threading
from datetime import datetime
from pathlib import Path

import discord

from signalpro_pricing_strategy.main import run_with_scenario

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

_state = {
    "running": False,
    "last_run": None,
    "last_scenario": None,
    "last_status": None,
    "last_result_path": None,
}

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


def _parse_args(text: str) -> dict:
    """Parse --channel and --title from message text, return remaining text and parsed values."""
    import shlex

    channel = "直接銷售（Direct Sales）"
    title = "SignalPro 定價方案"

    try:
        tokens = shlex.split(text)
    except ValueError:
        # If shlex fails (unmatched quotes), fall back to simple split
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


async def _download_attachment(attachment: discord.Attachment, dest_dir: str) -> Path | None:
    """Download a Discord attachment to dest_dir. Returns path if it's a supported text file."""
    filename = attachment.filename.lower()
    if not filename.endswith((".md", ".txt", ".markdown")):
        return None

    dest = Path(dest_dir) / attachment.filename
    await attachment.save(dest)
    return dest


def _run_crew_sync(
    customer_scenario: str,
    product_spec: str,
    extra_context: str,
    sales_channel: str,
    proposal_title: str,
    channel_id: int,
    message_id: int,
):
    """Run the crew synchronously in a background thread."""
    try:
        _state["running"] = True
        _state["last_status"] = "執行中..."

        result = run_with_scenario(
            customer_scenario=customer_scenario,
            product_spec=product_spec,
            extra_context=extra_context,
            sales_channel=sales_channel,
            proposal_title=proposal_title,
        )

        _state["last_status"] = "完成"
        _state["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M")

        # Find the latest proposal file
        output_dir = Path("output")
        proposals = sorted(output_dir.glob("proposal_*.md"), reverse=True)
        result_path = proposals[0] if proposals else output_dir / "proposal.md"
        _state["last_result_path"] = str(result_path)

        # Schedule sending the result back to Discord
        asyncio.run_coroutine_threadsafe(
            _send_result(channel_id, result_path),
            client.loop,
        )

    except Exception as e:
        _state["last_status"] = f"失敗: {e}"
        asyncio.run_coroutine_threadsafe(
            _send_error(channel_id, str(e)),
            client.loop,
        )
    finally:
        _state["running"] = False


async def _send_result(channel_id: int, result_path: Path):
    """Send the completed proposal back to the Discord channel."""
    channel = client.get_channel(channel_id)
    if not channel:
        return

    result_path = Path(result_path)
    if result_path.exists():
        file_size = result_path.stat().st_size
        if file_size < 1800:
            # Small enough to send as message
            content = result_path.read_text(encoding="utf-8")
            await channel.send(f"**定價提案完成！**\n\n{content}")
        else:
            # Send as file attachment
            await channel.send(
                "**定價提案完成！** 提案文件如下：",
                file=discord.File(str(result_path), filename="signalpro_proposal.md"),
            )
    else:
        await channel.send("**定價提案完成！** 但找不到輸出檔案，請檢查 output/ 目錄。")


async def _send_error(channel_id: int, error_msg: str):
    """Send error message to the Discord channel."""
    channel = client.get_channel(channel_id)
    if channel:
        await channel.send(f"**執行失敗：** {error_msg[:1500]}")


@client.event
async def on_ready():
    print(f"Jeff(Pricing) online: {client.user}")
    print(f"Connected to {len(client.guilds)} server(s)")


@client.event
async def on_message(message: discord.Message):
    # Ignore own messages
    if message.author == client.user:
        return

    # Only respond to mentions
    if client.user not in message.mentions:
        return

    # Strip mentions to get command text
    text = message.content
    for mention in message.mentions:
        text = text.replace(f"<@{mention.id}>", "").replace(f"<@!{mention.id}>", "")
    text = text.strip()

    # Status command
    if text in ("狀態", "status"):
        if _state["last_run"]:
            status_msg = (
                f"**Jeff(Pricing) 最近一次執行**\n"
                f"情境：{_state['last_scenario'][:100] if _state['last_scenario'] else 'N/A'}...\n"
                f"時間：{_state['last_run']}\n"
                f"狀態：{_state['last_status']}\n"
            )
            if _state["last_result_path"] and Path(_state["last_result_path"]).exists():
                status_msg += f"\n最新提案：`{_state['last_result_path']}`"
        else:
            status_msg = "目前尚未執行過任何任務。"
        await message.channel.send(status_msg)
        return

    # Help — no text and no attachments
    if not text and not message.attachments:
        await message.channel.send(HELP_TEXT)
        return

    # Check if already running
    if _state["running"]:
        await message.channel.send("⏳ 上一次分析仍在執行中，請稍後再試。輸入 `@Jeff(Pricing) 狀態` 查看進度。")
        return

    # Parse --channel and --title from text
    parsed = _parse_args(text)
    customer_scenario = parsed["text"]
    sales_channel = parsed["channel"]
    proposal_title = parsed["title"]

    # Download attachments
    product_spec = ""
    extra_context_parts = []

    if message.attachments:
        with tempfile.TemporaryDirectory(prefix="pricingpro_") as tmpdir:
            downloaded = []
            for att in message.attachments:
                path = await _download_attachment(att, tmpdir)
                if path:
                    content = path.read_text(encoding="utf-8")
                    downloaded.append((att.filename, content))

            if downloaded:
                # First file → product_spec
                product_spec = downloaded[0][1]
                file_summary = f"📄 `{downloaded[0][0]}` ({len(downloaded[0][1])} 字元) → 產品規劃說明"

                # Rest → extra_context
                if len(downloaded) > 1:
                    for fname, content in downloaded[1:]:
                        extra_context_parts.append(f"--- {fname} ---\n{content}")
                        file_summary += f"\n📄 `{fname}` ({len(content)} 字元) → 補充資料"
            else:
                file_summary = "⚠️ 附件中沒有 .md 或 .txt 檔案，僅使用文字訊息"

            # Acknowledge and start
            _state["last_scenario"] = customer_scenario or "(從附件讀取)"

            confirm_msg = f"**收到！Jeff(Pricing) 正在分析...**\n"
            if customer_scenario:
                display = customer_scenario[:200] + ("..." if len(customer_scenario) > 200 else "")
                confirm_msg += f"📋 客戶情境：{display}\n"
            if message.attachments:
                confirm_msg += f"{file_summary}\n"
            confirm_msg += f"🏷️ 銷售通路：{sales_channel}\n"
            confirm_msg += f"📝 提案標題：{proposal_title}\n\n"
            confirm_msg += "分析完成後會自動回傳提案文件。預計需要幾分鐘。"

            await message.channel.send(confirm_msg)

            extra_context = "\n\n".join(extra_context_parts) if extra_context_parts else ""

            # Run crew in background thread
            thread = threading.Thread(
                target=_run_crew_sync,
                args=(
                    customer_scenario or "請根據產品規劃說明，設計通用定價方案。",
                    product_spec,
                    extra_context,
                    sales_channel,
                    proposal_title,
                    message.channel.id,
                    message.id,
                ),
                daemon=True,
            )
            thread.start()
            return

    # No attachments — text only
    if not customer_scenario:
        await message.channel.send(HELP_TEXT)
        return

    _state["last_scenario"] = customer_scenario

    confirm_msg = (
        f"**收到！Jeff(Pricing) 正在分析...**\n"
        f"📋 客戶情境：{customer_scenario[:200]}{'...' if len(customer_scenario) > 200 else ''}\n"
        f"🏷️ 銷售通路：{sales_channel}\n"
        f"📝 提案標題：{proposal_title}\n\n"
        f"分析完成後會自動回傳提案文件。預計需要幾分鐘。"
    )
    await message.channel.send(confirm_msg)

    thread = threading.Thread(
        target=_run_crew_sync,
        args=(
            customer_scenario,
            product_spec,
            "",
            sales_channel,
            proposal_title,
            message.channel.id,
            message.id,
        ),
        daemon=True,
    )
    thread.start()


def main():
    from dotenv import load_dotenv
    load_dotenv()

    token = os.environ.get("DISCORD_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "DISCORD_BOT_TOKEN not set.\n"
            "請到 Discord Developer Portal 建立 Bot，取得 Token 後設定在 .env 中。"
        )

    print("Jeff(Pricing) starting. Press Ctrl+C to stop.")
    client.run(token)

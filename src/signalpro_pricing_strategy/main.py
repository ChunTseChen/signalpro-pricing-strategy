#!/usr/bin/env python
"""
SignalPro Pricing Strategy - Entry Points

支援三種輸入方式：
1. run_from_file  — 傳入 MD/TXT 檔案路徑，自動讀取作為產品規劃說明
2. run_with_trigger — 傳入 JSON，欄位值可以是文字或檔案路徑（自動偵測）
3. run            — 使用預設情境執行
"""
import json
import sys
from datetime import datetime
from pathlib import Path

from signalpro_pricing_strategy.crew import SignalproPricingStrategy


def run():
    """Execute with default scenario."""
    inputs = {
        "current_date": datetime.now().strftime("%Y-%m-%d"),
        "customer_scenario": (
            "一家台灣中型製造業（員工 500 人），"
            "目前使用 LINE 與 Email 進行跨部門溝通，"
            "供應鏈協作仰賴 Excel 與人工追蹤，"
            "營運長希望導入數位化工具提升營運效率，"
            "年度 IT 預算約 200 萬台幣。"
        ),
        "sales_channel": "直接銷售（Direct Sales）",
        "proposal_title": "台灣中型製造業數位轉型定價方案",
    }
    result = SignalproPricingStrategy().crew().kickoff(inputs=inputs)
    _copy_output_with_timestamp()
    return result


def run_from_file():
    """
    從 MD/TXT 檔案讀取產品規劃說明並執行。

    Usage:
      run_from_file <product_spec.md> [customer_scenario.md] [--channel "NVIDIA DGX Spark 打包"] [--title "提案標題"]

    Examples:
      # 只傳產品規劃說明（客戶情境用預設）
      run_from_file docs/product_plan.md

      # 產品規劃 + 客戶情境都用檔案
      run_from_file docs/product_plan.md docs/customer_case.md

      # 完整指定
      run_from_file docs/product_plan.md docs/customer_case.md --channel "NVIDIA DGX Spark 打包" --title "日本車廠方案"

      # 也可傳多個檔案作為補充資料
      run_from_file docs/product_plan.md --extra docs/market_research.md
    """
    args = sys.argv[1:]
    if not args:
        print(
            "Usage: run_from_file <product_spec.md> [customer_scenario.md] "
            '[--channel "..."] [--title "..."] [--extra extra.md]'
        )
        print()
        print("  product_spec.md      產品規劃說明檔案（必要）")
        print("  customer_scenario.md 客戶情境檔案（選填）")
        print('  --channel            銷售通路，預設 "直接銷售"')
        print("  --title              提案標題")
        print("  --extra              額外補充資料檔案（可多次使用）")
        sys.exit(1)

    # Parse arguments
    positional = []
    channel = "直接銷售（Direct Sales）"
    title = "SignalPro 定價方案"
    extra_files = []
    i = 0
    while i < len(args):
        if args[i] == "--channel" and i + 1 < len(args):
            channel = args[i + 1]
            i += 2
        elif args[i] == "--title" and i + 1 < len(args):
            title = args[i + 1]
            i += 2
        elif args[i] == "--extra" and i + 1 < len(args):
            extra_files.append(args[i + 1])
            i += 2
        else:
            positional.append(args[i])
            i += 1

    # Read product spec (required)
    product_spec_path = Path(positional[0])
    if not product_spec_path.is_file():
        print(f"Error: 找不到檔案 {product_spec_path}")
        sys.exit(1)
    product_spec = product_spec_path.read_text(encoding="utf-8")
    print(f"[INFO] 已讀取產品規劃: {product_spec_path} ({len(product_spec)} 字元)")

    # Read customer scenario (optional, second positional arg)
    customer_scenario = ""
    if len(positional) > 1:
        scenario_path = Path(positional[1])
        if scenario_path.is_file():
            customer_scenario = scenario_path.read_text(encoding="utf-8")
            print(f"[INFO] 已讀取客戶情境: {scenario_path} ({len(customer_scenario)} 字元)")
        else:
            # Treat as inline text
            customer_scenario = positional[1]

    # Read extra context files
    extra_context_parts = []
    for ef in extra_files:
        ep = Path(ef)
        if ep.is_file():
            content = ep.read_text(encoding="utf-8")
            extra_context_parts.append(f"--- {ep.name} ---\n{content}")
            print(f"[INFO] 已讀取補充資料: {ep} ({len(content)} 字元)")
        else:
            print(f"Warning: 找不到補充資料檔案 {ef}，略過")

    inputs = {
        "current_date": datetime.now().strftime("%Y-%m-%d"),
        "product_spec": product_spec,
        "customer_scenario": customer_scenario or "請根據產品規劃說明，設計通用定價方案。",
        "sales_channel": channel,
        "proposal_title": title,
        "extra_context": "\n\n".join(extra_context_parts) if extra_context_parts else "",
    }

    result = SignalproPricingStrategy().crew().kickoff(inputs=inputs)
    _copy_output_with_timestamp()
    return result


def run_with_scenario(
    customer_scenario: str,
    sales_channel: str = "直接銷售（Direct Sales）",
    proposal_title: str = "SignalPro 定價方案",
    product_spec: str = "",
    extra_context: str = "",
):
    """Programmatic entry point. Values can be text or file paths (auto-detected in before_kickoff)."""
    inputs = {
        "current_date": datetime.now().strftime("%Y-%m-%d"),
        "customer_scenario": customer_scenario,
        "sales_channel": sales_channel,
        "proposal_title": proposal_title,
        "product_spec": product_spec,
        "extra_context": extra_context,
    }
    result = SignalproPricingStrategy().crew().kickoff(inputs=inputs)
    _copy_output_with_timestamp()
    return result


def run_with_trigger():
    """
    CLI trigger with JSON payload. Field values can be text or file paths.

    Usage:
      run_with_trigger '{"product_spec": "docs/plan.md", "customer_scenario": "docs/case.md"}'
    """
    if len(sys.argv) < 2:
        print('Usage: run_with_trigger \'{"product_spec": "path/to/spec.md", ...}\'')
        print()
        print("Supported fields (values can be text or .md/.txt file paths):")
        print("  product_spec      產品規劃說明")
        print("  customer_scenario 客戶情境")
        print("  sales_channel     銷售通路")
        print("  proposal_title    提案標題")
        print("  extra_context     額外補充資料")
        sys.exit(1)
    payload = json.loads(sys.argv[1])
    return run_with_scenario(**payload)


def train():
    try:
        n_iterations = int(sys.argv[1]) if len(sys.argv) > 1 else 3
        filename = sys.argv[2] if len(sys.argv) > 2 else "training_data.pkl"
        inputs = {
            "customer_scenario": "測試用客戶情境：中型科技公司，200 人，需要跨部門協作工具。",
            "sales_channel": "直接銷售（Direct Sales）",
            "proposal_title": "測試定價方案",
        }
        SignalproPricingStrategy().crew().train(
            n_iterations=n_iterations, filename=filename, inputs=inputs
        )
    except Exception as e:
        raise Exception(f"Training failed: {e}") from e


def replay():
    try:
        task_id = sys.argv[1]
        SignalproPricingStrategy().crew().replay(task_id=task_id)
    except Exception as e:
        raise Exception(f"Replay failed: {e}") from e


def test():
    try:
        n_iterations = int(sys.argv[1]) if len(sys.argv) > 1 else 2
        eval_llm = sys.argv[2] if len(sys.argv) > 2 else "anthropic/claude-sonnet-4-6"
        inputs = {
            "customer_scenario": "測試用客戶情境：中型科技公司，200 人，需要跨部門協作工具。",
            "sales_channel": "直接銷售（Direct Sales）",
            "proposal_title": "測試定價方案",
        }
        SignalproPricingStrategy().crew().test(
            n_iterations=n_iterations, openai_model_name=eval_llm, inputs=inputs
        )
    except Exception as e:
        raise Exception(f"Test failed: {e}") from e


def _copy_output_with_timestamp():
    import shutil

    src = Path("output/proposal.md")
    if src.exists():
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = Path(f"output/proposal_{ts}.md")
        shutil.copy2(src, dst)
        print(f"Proposal saved to {dst}")

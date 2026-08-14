#!/usr/bin/env python3
"""CLI entry point for PR Review Crew.

Usage:
    python run_review.py owner/repo 123
    python run_review.py owner/repo 123 --dry-run
    python run_review.py owner/repo 123 --model gpt-4o --provider openai

Requires (see README for full setup):
    pip install chatdev requests
    export API_KEY=...      # LLM provider key (OpenAI-compatible or Gemini)
    export BASE_URL=...     # optional, defaults per-provider
    export GITHUB_TOKEN=... # only needed to actually post comments (not for --dry-run)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
YAML_PATH = REPO_ROOT / "yaml_instance" / "pr_review_crew.yaml"
FUNCTIONS_DIR = REPO_ROOT / "functions" / "function_calling"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the PR Review Crew multi-agent workflow.")
    parser.add_argument("repo", help="GitHub repo in 'owner/name' form, e.g. openai/openai-python")
    parser.add_argument("pr_number", type=int, help="Pull request number")
    parser.add_argument(
        "--instructions",
        default="",
        help="Optional extra review instructions appended to the task prompt.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't actually post the comment to GitHub; print what would be posted.",
    )
    parser.add_argument("--provider", default=os.environ.get("PROVIDER", "openai"), help="LLM provider (openai or gemini).")
    parser.add_argument("--model", default=os.environ.get("MODEL", "gpt-4o-mini"), help="Model name for the crew's agents.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.dry_run:
        os.environ["PR_REVIEW_CREW_DRY_RUN"] = "1"

    # Point ChatDev's function-tooling loader at this repo's github_tools.py
    # instead of (or in addition to) an existing ChatDev checkout's functions/.
    os.environ["MAC_FUNCTIONS_DIR"] = str(FUNCTIONS_DIR)

    try:
        from chatdev import AgentConfig, run_workflow
    except ImportError:
        print(
            "chatdev is not installed. Run: pip install chatdev\n"
            "(Requires Python >=3.12,<3.14 -- see README for details.)",
            file=sys.stderr,
        )
        return 1

    if not os.environ.get("API_KEY"):
        print(
            "Warning: API_KEY is not set. Export an API key for your LLM provider "
            "before running (see .env.example).",
            file=sys.stderr,
        )

    task_prompt = f"{args.repo}#{args.pr_number}"
    if args.instructions:
        task_prompt += f"\n\nAdditional instructions: {args.instructions}"

    # Apply the requested provider/model to every agent node by targeting each
    # node id explicitly (a single AgentConfig only patches the first node).
    node_ids = [
        "Diff Fetcher",
        "Logic Style Reviewer",
        "Security Reviewer",
        "Docs Tests Reviewer",
        "Synthesizer",
        "Comment Poster",
    ]
    agent_configs = {
        node_id: AgentConfig(provider=args.provider, model=args.model)
        for node_id in node_ids
    }

    print(f"Running PR Review Crew on {args.repo}#{args.pr_number} "
          f"({'dry run' if args.dry_run else 'will post comment'})...\n")

    result = run_workflow(
        yaml_file=str(YAML_PATH),
        task_prompt=task_prompt,
        agent_configs=agent_configs,
        log_level="INFO",
    )

    if not result.success:
        print(f"Workflow failed: {result.error}", file=sys.stderr)
        return 1

    print("=== Final output ===\n")
    print(result.final_message or "(no final message returned)")
    print(f"\nRun artifacts: {result.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

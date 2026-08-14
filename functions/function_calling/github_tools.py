"""GitHub function tools for the PR Review Crew workflow.

These are plain Python functions with type hints, following ChatDev 2.0's
Function Tooling convention (see docs/user_guide/en/modules/tooling/function.md
in the upstream OpenBMB/ChatDev repo): each function lives at module top level,
its signature is auto-converted into a JSON Schema for the LLM, and its first
docstring paragraph becomes the tool description shown to the model.

Point ChatDev at this directory by setting the MAC_FUNCTIONS_DIR environment
variable (see run_review.py), or by dropping this file into an existing
ChatDev checkout's functions/function_calling/ directory.
"""

from __future__ import annotations

import os
from typing import Annotated

import requests
from utils.function_catalog import ParamMeta

GITHUB_API = "https://api.github.com"
_TIMEOUT_SECONDS = 30


def _auth_headers(accept: str) -> dict:
    headers = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def get_pr_diff(
    repo: Annotated[str, ParamMeta(description="GitHub repo in 'owner/name' form, e.g. 'openai/openai-python'.")],
    pr_number: Annotated[int, ParamMeta(description="Pull request number.")],
) -> str:
    """Fetch the raw unified diff for a GitHub pull request.

    Returns the diff as plain text (the same content you'd see from
    `git diff`), truncated to a safe size for LLM context if very large.
    """
    url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}"
    resp = requests.get(url, headers=_auth_headers("application/vnd.github.v3.diff"), timeout=_TIMEOUT_SECONDS)
    resp.raise_for_status()
    diff = resp.text
    max_chars = 20000
    if len(diff) > max_chars:
        diff = diff[:max_chars] + "\n\n... [diff truncated for length] ..."
    return diff


def get_pr_files(
    repo: Annotated[str, ParamMeta(description="GitHub repo in 'owner/name' form, e.g. 'openai/openai-python'.")],
    pr_number: Annotated[int, ParamMeta(description="Pull request number.")],
) -> str:
    """List the files changed in a GitHub pull request along with per-file patches.

    Prefer this over get_pr_diff when you want file-by-file context (path,
    additions/deletions, and the patch hunk for each file) rather than one
    raw diff blob.
    """
    url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}/files"
    headers = _auth_headers("application/vnd.github+json")
    files: list[dict] = []
    page = 1
    while True:
        resp = requests.get(
            url,
            headers=headers,
            params={"per_page": 100, "page": page},
            timeout=_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        files.extend(batch)
        if len(batch) < 100:
            break
        page += 1

    lines: list[str] = [f"{len(files)} file(s) changed in {repo}#{pr_number}:", ""]
    max_chars = 20000
    for f in files:
        lines.append(f"### {f.get('filename')} (+{f.get('additions', 0)} / -{f.get('deletions', 0)})")
        patch = f.get("patch")
        if patch:
            lines.append("```diff")
            lines.append(patch)
            lines.append("```")
        else:
            lines.append("_(binary or too large for a patch preview)_")
        lines.append("")
        if sum(len(line) for line in lines) > max_chars:
            lines.append("... [remaining files truncated for length] ...")
            break
    return "\n".join(lines)


def post_review_comment(
    repo: Annotated[str, ParamMeta(description="GitHub repo in 'owner/name' form, e.g. 'openai/openai-python'.")],
    pr_number: Annotated[int, ParamMeta(description="Pull request number.")],
    body: Annotated[str, ParamMeta(description="Markdown comment body to post on the pull request.")],
) -> str:
    """Post a comment on a GitHub pull request (as an issue-level comment).

    Requires a GITHUB_TOKEN environment variable with `repo` (or, for public
    repos, `public_repo`) scope. If PR_REVIEW_CREW_DRY_RUN=1 is set, no
    network call is made and the comment is printed instead — use this for
    safe demos against real PR numbers.
    """
    if os.environ.get("PR_REVIEW_CREW_DRY_RUN") == "1":
        preview = body if len(body) < 4000 else body[:4000] + "... [truncated]"
        return (
            f"[DRY RUN] Would have posted a comment on {repo}#{pr_number}. "
            f"Comment body:\n\n{preview}"
        )

    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError(
            "GITHUB_TOKEN is not set. Export a GitHub token with permission to comment "
            "on this repo, or set PR_REVIEW_CREW_DRY_RUN=1 to preview without posting."
        )

    # GitHub PRs are issues under the hood, so PR comments use the issues endpoint.
    url = f"{GITHUB_API}/repos/{repo}/issues/{pr_number}/comments"
    resp = requests.post(
        url,
        headers=_auth_headers("application/vnd.github+json"),
        json={"body": body},
        timeout=_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data = resp.json()
    return f"Posted comment on {repo}#{pr_number}: {data.get('html_url', '(no url returned)')}"

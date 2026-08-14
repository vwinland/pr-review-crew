# PR Review Crew

A small multi-agent GitHub PR reviewer built on [ChatDev 2.0 (DevAll)](https://github.com/OpenBMB/ChatDev), OpenBMB's zero-code multi-agent orchestration platform. Point it at any pull request and five agents fetch the diff, review it from three angles in parallel, synthesize the findings, and post one consolidated comment back to GitHub.

Free, open source (MIT), and designed to be demoed live in about a minute.

## Why this exists

I wanted a project that actually shows multi-agent *design* decisions, not just a wrapper around an LLM call. A code reviewer is a good test case because it forces real tradeoffs: how do you fan a diff out to specialist reviewers without blowing up context, how do you fan their opinions back in without losing attribution, and how do you keep a deterministic action (posting to GitHub) from being derailed by a chatty model. This repo is the answer to those questions, kept small enough to read end to end.

## Architecture

```mermaid
flowchart LR
    U([Task: "owner/repo#123"]) --> DF[Diff Fetcher]
    DF -->|diff + REPO/PR header| LS[Logic & Style Reviewer]
    DF -->|diff + REPO/PR header| SEC[Security Reviewer]
    DF -->|diff + REPO/PR header| DT[Docs & Tests Reviewer]
    LS --> SYN[Synthesizer]
    SEC --> SYN
    DT --> SYN
    SYN -->|one Markdown comment| CP[Comment Poster]
    CP -->|post_review_comment tool| GH[(GitHub)]
```

Six agent nodes, defined in [`yaml_instance/pr_review_crew.yaml`](yaml_instance/pr_review_crew.yaml):

| Node | Job |
|---|---|
| **Diff Fetcher** | Parses `owner/repo#123` out of the task, calls the `get_pr_files` tool, and emits the diff with a `REPO:` / `PR:` header. |
| **Logic & Style Reviewer** | Reviews the diff for logic bugs, readability, naming, dead code. |
| **Security Reviewer** | Reviews the diff for injection risks, secrets, unsafe deserialization, auth gaps. |
| **Docs & Tests Reviewer** | Reviews the diff for missing docs and missing/weak test coverage. |
| **Synthesizer** | Merges all three reports into one Markdown review comment with a verdict. |
| **Comment Poster** | Calls the `post_review_comment` tool to post that comment on the PR. |

Two design choices worth calling out if you're reading the YAML:

- **Context propagation.** ChatDev's graph only forwards each node's output to its direct downstream edges by default, so a node several hops downstream can't see the original task prompt. Every reviewer node sets `context_window: -1` to see full history, and every agent is instructed to echo the `REPO:` / `PR:` header in its own output — an explicit protocol instead of relying on implicit state, so the last node in the chain still knows which PR to comment on.
- **Deterministic vs. agentic steps.** Fetching a diff and posting a comment are deterministic API calls, not reasoning tasks — but ChatDev's `python` node type only executes pre-existing scripts from a shared workspace, it doesn't take inline code in YAML. So those steps are thin agent nodes with a single bound tool and `temperature: 0.0`, which keeps them fast/cheap while staying inside the graph's tool-calling model.

## Tools

[`functions/function_calling/github_tools.py`](functions/function_calling/github_tools.py) defines three plain Python functions — `get_pr_diff`, `get_pr_files`, `post_review_comment` — using ChatDev's [Function Tooling](https://github.com/OpenBMB/ChatDev/blob/main/docs/user_guide/en/modules/tooling/function.md) convention: type-hinted top-level functions with `Annotated[..., ParamMeta(description=...)]`, auto-converted into JSON Schema for the model. `run_review.py` points `MAC_FUNCTIONS_DIR` at this folder so ChatDev discovers them without needing a full ChatDev checkout.

`post_review_comment` respects a `PR_REVIEW_CREW_DRY_RUN` env var (see `--dry-run` below) so you can demo against a real PR without actually posting.

> **Note on `chatdev.register_tool`:** the SDK also ships a decorator-based `@register_tool` shortcut. As of `chatdev==0.1.0`, the generated wrapper it registers doesn't preserve the original function's type hints, so tools registered that way currently expose an empty parameter schema to the model — fine for zero-argument tools, not for tools like these that need `repo`/`pr_number`/`body`. Using the `functions/function_calling/` convention directly sidesteps that.

## Setup

Requires Python **3.12–3.13** (ChatDev 2.0's constraint) and an API key for an OpenAI-compatible or Gemini endpoint.

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env: set API_KEY (and BASE_URL if not using api.openai.com), GITHUB_TOKEN if you want to actually post
export $(grep -v '^#' .env | xargs)   # or use direnv/python-dotenv
```

**Don't want to pay for OpenAI?** `.env.example` has ready-to-uncomment recipes for [Groq](https://console.groq.com/keys) (free tier, fast, reliable tool calling — the easiest drop-in swap) and [Gemini](https://aistudio.google.com/apikey) (free tier, natively supported by `chatdev` as its own provider), plus fully-local [Ollama](https://ollama.com). All three are OpenAI-API-compatible except Gemini, which chatdev talks to directly. One caveat for local models: **Diff Fetcher** and **Comment Poster** call tools, so whichever model backs those two nodes needs real function-calling support (e.g. `llama3.1`, `qwen2.5`, `mistral-nemo` on Ollama) — the three reviewer nodes don't call tools, so they're far less picky. You can also override the endpoint per-run without touching `.env`: `python run_review.py owner/repo 123 --dry-run --provider openai --base-url http://localhost:11434/v1 --model llama3.1`.

## Demo

```bash
# Safe demo: fetches a real diff, runs the full crew, prints the comment, does NOT post it
python run_review.py openai/openai-python 1234 --dry-run

# Live: actually posts the consolidated review as a PR comment (needs GITHUB_TOKEN)
python run_review.py your-org/your-repo 42
```

Talking through the output is the whole pitch: point at your own repo's open PR, run with `--dry-run`, and walk through why each of the three reviewer sections says what it says.

## Repo layout

```
pr-review-crew/
├── yaml_instance/pr_review_crew.yaml   # the agent graph
├── functions/function_calling/         # GitHub tools (diff fetch, file listing, comment post)
│   └── github_tools.py
├── run_review.py                       # CLI entry point (uses chatdev.run_workflow)
├── requirements.txt
└── .env.example
```

## Extending it

- Add a fourth specialist (e.g. a performance reviewer) by adding one more agent node and two edges (`Diff Fetcher -> new node`, `new node -> Synthesizer`).
- Swap `get_pr_files`/`get_pr_diff` for a GitLab or Bitbucket equivalent to retarget the whole crew at a different host.
- Add a `Human` node between `Synthesizer` and `Comment Poster` to require a human "approve to post" step before anything hits GitHub.

## Credits

Built on [OpenBMB/ChatDev](https://github.com/OpenBMB/ChatDev) (Apache-2.0). If you use ChatDev itself in research or products, see their repo for citation info.

## License

MIT — see [LICENSE](LICENSE).

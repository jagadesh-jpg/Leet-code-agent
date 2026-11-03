# LeetCode Agent 2.0 — Personal Account Assistant

An autonomous Python coding agent and Model Context Protocol (MCP) server that solves programming problems in an iterative feedback loop. 

With **Version 2.0**, you can import problems from your personal LeetCode account workflow, solve them using Gemini (or other OpenAI-compatible LLMs), evaluate solutions locally with an isolated judge, inspect estimated time and space complexity, receive copy-ready LeetCode code, and track official LeetCode submission verdicts.

---

## Key Features

1. **Autonomous Solve-Test-Fix Loop**
   - Generates initial Python candidate code via LLM.
   - Executes code locally inside an isolated subprocess against unit test cases.
   - Reads syntax, runtime, timeout, or wrong-answer failures and asks the LLM to self-correct up to 5 attempts.

2. **LeetCode 2.0 Personal Workflow Integration**
   - **Manual Problem Import**: Bring external problems into your local agent via URL, description, signature, and example tests without scraping.
   - **Flexible Judge**: Supports both standalone Python functions and standard LeetCode `class Solution` implementations.
   - **AI-Estimated Complexity**: Automatically estimates Big-O time and space complexity (e.g. $\mathcal{O}(n)$, $\mathcal{O}(1)$).
   - **Copy-Ready Solutions**: Formats the final code specifically for direct pasting into the LeetCode web editor.
   - **Official Verdict Tracking**: Record official submission outcomes (`Accepted`, `Wrong Answer`, `Runtime Error`, etc.) alongside runtime benchmarks and memory consumption.
   - **Distinction of Status**: Clearly differentiates between **locally verified** solutions (passing local sample tests) and **officially accepted** LeetCode submissions.

3. **Model Context Protocol (MCP) Integration**
   - Full FastMCP standard input/output (`stdio`) server exposing 7 dedicated tools to connect directly with Antigravity and other MCP-compliant IDEs.

4. **Persistent SQLite Storage**
   - Retains progress, individual attempt history, custom imported problems, and official LeetCode verdicts across sessions.

---

## Project Structure

```text
Leet_Code/
    main.py           # CLI entry point orchestrating the autonomous solving loop
    assistant.py      # Core workflow for custom problem solving & complexity analysis
    llm.py            # OpenAI-compatible LLM client and offline MockLLM
    judge.py          # Subprocess test runner supporting functions and class Solution
    problems.py       # Built-in problems dataset loader and difficulty filter
    store.py          # SQLite database storage (attempts, custom problems, verdicts)
    prompts.py        # Prompts, retry templates, code extraction, and copy formatter
    problems.json     # 9 built-in curated LeetCode problems (Easy, Medium, Hard)
    mcp_server.py     # FastMCP server exposing 7 MCP tools over stdio
    tests/
        test_judge.py     # Unit tests for judge and code evaluation
        test_problems.py  # Unit tests for problems dataset and filtering
        test_mock_llm.py  # Unit tests for offline MockLLM behavior
        test_mcp_server.py# Unit tests for MCP server tools
        test_assistant.py # Unit tests for Version 2.0 assistant workflow
    requirements.txt  # Project dependencies
    .env.example      # Example environment configuration
    .gitignore        # Ignored files and directories
    README.md         # Documentation and guide
```

---

## Setup Instructions

### 1. Create and Activate a Virtual Environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install Dependencies

```powershell
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Copy `.env.example` to `.env`:

```powershell
Copy-Item .env.example .env
```

Open `.env` and fill in your API credentials:

```ini
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_API_KEY=your_api_key_here
LLM_MODEL=gemini-1.5-flash
LLM_DELAY_SECONDS=4
JUDGE_TIMEOUT_SECONDS=10
```

Alternative OpenAI-compatible providers:
- **Groq**: `https://api.groq.com/openai/v1`
- **Ollama**: `http://localhost:11434/v1`

---

## Using as an MCP Server

The project integrates with the Model Context Protocol (MCP) using the official `FastMCP` SDK, allowing Antigravity to interact with the LeetCode Agent over standard input/output (`stdio`) transport.

### Available MCP Tools

| # | Tool Name | Description |
|---|---|---|
| 1 | **`list_problems(difficulty="")`** | Lists available built-in problems, difficulties, and solved status. Never exposes reference solutions or hidden test cases. |
| 2 | **`get_problem(problem_id)`** | Retrieves title, difficulty, description, signature, and exactly two example test cases. |
| 3 | **`submit_solution(problem_id, code)`** | Evaluates Python code against all test cases for a problem, logs the attempt, and updates status. |
| 4 | **`get_progress()`** | Returns comprehensive SQLite summary: built-in problems, custom imported problems, and official LeetCode verdicts. |
| 5 | **`import_problem(...)`** | Imports a user-provided problem manually (URL, title, difficulty, description, function name, signature, and example tests). |
| 6 | **`solve_problem(problem_id, max_attempts=5)`** | Autonomous solve-test-fix loop using configured Gemini LLM and local judge. Returns copy-ready code and complexity estimates. |
| 7 | **`record_verdict(...)`** | Records official manual submission outcomes from LeetCode (`Accepted`, `Wrong Answer`, etc.), runtime (ms), and memory (MB). |

### Configuring in Antigravity

Add the following to your Antigravity MCP configuration (`mcp_config.json`):

```json
{
  "mcpServers": {
    "leetcode-agent": {
      "command": "<PATH_TO_VENV_PYTHON>",
      "args": [
        "<PATH_TO_PROJECT_ROOT>/mcp_server.py"
      ],
      "cwd": "<PATH_TO_PROJECT_ROOT>"
    }
  }
}
```

*(Replace `<PATH_TO_VENV_PYTHON>` and `<PATH_TO_PROJECT_ROOT>` with your actual system paths).*

---

## Usage Examples

### Run CLI in Mock Mode (Offline / Free)

The mock client tests the loop without making external API calls. For each problem, it purposefully fails the first attempt and passes the second attempt with the reference solution.

```powershell
# Run all built-in problems with mock
python main.py --mock

# Limit to first 3 problems
python main.py --mock --limit 3

# Filter by difficulty
python main.py --mock --difficulty easy

# Reset database progress before starting
python main.py --reset --mock
```

### Run CLI with Real LLM

```powershell
# Run with real LLM
python main.py

# Run only medium problems with up to 5 attempts per problem
python main.py --difficulty medium --max-attempts 5
```

---

## Verification & Testing

Run the full pytest suite to verify all modules, MCP tools, and assistant workflows:

```powershell
python -m pytest -v
```

---

## Local Verification vs. Official LeetCode Acceptance

> [!IMPORTANT]
> - **Locally Verified**: Indicates that candidate code passed the provided sample unit test cases inside the local runner. Local verification does **not** guarantee passing LeetCode's extensive internal test suite or performance limits.
> - **Officially Accepted**: Indicates that you manually copied the code, submitted it to LeetCode, and received an official "Accepted" verdict on your LeetCode account.

---

## Safety and Privacy Guarantees

- **No Credentials Requested**: The agent never asks for or stores LeetCode passwords, session cookies, or CSRF tokens.
- **No Web Scraping**: The agent does not scrape or crawl LeetCode; all external problem data is manually provided by the user.
- **No Automated Submissions**: The agent never submits code directly to external websites. Human review and manual submission are strictly required.
- **Isolated Subprocess Execution**: Solutions run in isolated temporary environments with execution timeouts.

---

## Future Work

- Docker-based sandboxed runner.
- Extended analytics for personal LeetCode progression.
- Additional built-in algorithmic patterns and problem templates.

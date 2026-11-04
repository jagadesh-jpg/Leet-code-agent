# LeetCode Agent 4.0 — Fully Autonomous Batch Solver & Personal Dashboard

An autonomous Python coding agent, persistent algorithmic memory, personal dashboard, and Model Context Protocol (MCP) server that tracks, benchmarks, and autonomously solves LeetCode problems in an iterative feedback loop.

Designed for your personal LeetCode account workflow (e.g. `jagadesh-02`, https://leetcode.com/u/jagadesh-02/), **Version 4.0** introduces a fully autonomous batch problem solver, persistent learning memory retrieval, pause/resume/stop run controls, state checkpoint recovery across app restarts, unified dashboard metrics tracking official verdicts alongside CSV submissions, and 15 total MCP tools.

---

## Key Features

1. **Fully Autonomous Batch Solver (Version 4.0)**
   - **Queue Orchestration**: Automatically processes pending imported and curated problems sequentially.
   - **Persistent Run Checkpoints**: Tracks run IDs, problem attempts, verified counts, failed counts, and queue items in SQLite.
   - **Safe Controls**: Support for `start`, `pause`, `resume`, and `stop` controls without data loss.
   - **Restart Recovery**: Safely recovers interrupted runs from saved checkpoints.
   - **Concurrency Safety**: Ensures only one active worker thread operates concurrently.
   - **Budget & Safety Limits**: Configurable problem counts, max attempts, and API call budgets.

2. **Persistent Learning Memory (Version 4.0)**
   - Stores algorithmic patterns, common coding pitfalls, failure feedback, and template snippets (Two Pointers, Sliding Window, Dynamic Programming, Hash Maps, Prefix Sums, Linked Lists).
   - Dynamically retrieves relevant context before prompting Gemini to reinforce problem-solving strategies.

3. **Personal LeetCode Progress Dashboard (Version 3.0 & 4.0)**
   - **Unified Submission Analytics**: Automatically aggregates both official recorded verdicts and CSV-imported submissions with distinguishable sources (`official_verdict` vs `csv_import`) and deduplication.
   - **Difficulty Breakdown**: Displays distinct solved counts across Easy, Medium, and Hard problems.
   - **Verdict Analytics**: Tracks counts of Accepted, Wrong Answer, Time Limit Exceeded, Runtime Error, and Compile Error outcomes.
   - **Attempted-but-Unaccepted Tracker**: Automatically pinpoints problems you have tackled on LeetCode but haven't yet passed.
   - **Smart Recommendations**: Suggests optimal problems to solve next, linking directly into the Gemini-powered solving assistant.

4. **Autonomous Solve-Test-Fix Loop (Version 2.0)**
   - **Manual Problem Import**: Add any problem via URL, description, signature, and example tests without scraping.
   - **Dual-Mode Judge**: Supports both standard LeetCode `class Solution` implementations and standalone Python functions in isolated subprocesses.
   - **AI-Estimated Complexity**: Automatically estimates Big-O time and space complexity (e.g. $\mathcal{O}(n^2)$, $\mathcal{O}(n)$).
   - **Copy-Ready Solutions**: Formats the final code specifically for direct pasting into the LeetCode web editor.
   - **Official Verdict Recording**: Logs your actual LeetCode submission results (`Accepted`, `Wrong Answer`, etc.) along with runtime (ms) and memory (MB) benchmarks.
   - **Record Separation**: Clearly distinguishes **locally verified** solutions (passed local tests) from **officially accepted** LeetCode submissions.

5. **Model Context Protocol (MCP) Server**
   - Full FastMCP standard input/output (`stdio`) server exposing **15 registered tools** to connect directly with Antigravity and other MCP-compliant IDEs.

6. **Persistent SQLite Storage**
   - Safe, non-destructive schema migrations storing local attempts, custom imported problems, official verdicts, learning memory, autonomous runs, and imported CSV submission history.

---

## Project Structure

```text
Leet_Code/
    main.py           # CLI entry point supporting single run and --autonomous mode
    autonomous.py     # Version 4.0 autonomous batch queue orchestrator & run controls
    memory.py         # Version 4.0 persistent learning memory retrieval & pattern seeds
    dashboard.py      # Version 3.0 & 4.0 dashboard engine, CSV parser & recommendations
    assistant.py      # Core workflow for custom problem solving & complexity analysis
    llm.py            # OpenAI-compatible LLM client and offline MockLLM
    judge.py          # Subprocess test runner supporting functions and class Solution
    problems.py       # Built-in problems dataset loader and difficulty filter
    store.py          # SQLite database storage (attempts, custom problems, verdicts, memory, runs)
    prompts.py        # Prompts, retry templates, code extraction, and copy formatter
    problems.json     # 9 built-in curated LeetCode problems (Easy, Medium, Hard)
    mcp_server.py     # FastMCP server exposing 15 MCP tools over stdio
    leetcode_submissions_template.csv # CSV template for manual submission history
    tests/
        test_judge.py     # Unit tests for judge and code evaluation
        test_problems.py  # Unit tests for problems dataset and filtering
        test_mock_llm.py  # Unit tests for offline MockLLM behavior
        test_mcp_server.py# Unit tests for original MCP server tools
        test_assistant.py # Unit tests for Version 2.0 assistant workflow
        test_dashboard.py # Unit tests for Version 3.0 dashboard & CSV import
        test_autonomous.py# Unit tests for Version 4.0 autonomous queue & controls
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

Configure your LLM provider in `.env`:

```ini
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
LLM_API_KEY=your_api_key_here
LLM_MODEL=gemini-1.5-flash
LLM_DELAY_SECONDS=4
JUDGE_TIMEOUT_SECONDS=10
```

---

## CSV Submission History Format

You can prepare your LeetCode submission history in `leetcode_submissions_template.csv` using the following header format:

```csv
title,url,difficulty,verdict,submission_date,language,runtime_ms,memory_mb,notes
Two Sum,https://leetcode.com/problems/two-sum/,Easy,Accepted,2026-11-01 10:15:00,Python3,35,17.8,"First submission passed all tests"
3Sum,https://leetcode.com/problems/3sum/,Medium,Wrong Answer,2026-11-02 14:20:00,Python3,0,0,"Failed edge case with duplicate triplets"
```

To import your CSV via the MCP server:
- Call `import_csv_submissions(csv_path_or_content="leetcode_submissions_template.csv")`.

---

## Available MCP Tools

The server registers **9 MCP tools** over `stdio`:

| # | Tool Name | Description |
|---|---|---|
| 1 | **`list_problems(difficulty="")`** | Lists available built-in problems, difficulties, and solved status. |
| 2 | **`get_problem(problem_id)`** | Retrieves title, difficulty, description, signature, and two example test cases. |
| 3 | **`submit_solution(problem_id, code)`** | Evaluates Python code against all test cases for a problem and logs the attempt. |
| 4 | **`get_progress()`** | Returns comprehensive SQLite summary of built-in problems, custom problems, and official verdicts. |
| 5 | **`import_problem(...)`** | Imports a user-provided problem manually (URL, title, difficulty, description, function name, signature, and example tests). |
| 6 | **`solve_problem(problem_id, max_attempts=5)`** | Autonomous solve-test-fix loop using configured Gemini LLM and local judge. Returns copy-ready code and complexity estimates. |
| 7 | **`record_verdict(...)`** | Records official manual submission outcomes from LeetCode (`Accepted`, `Wrong Answer`, etc.), runtime (ms), and memory (MB). |
| 8 | **`import_csv_submissions(csv_path_or_content)`** | Imports manually prepared LeetCode submission history from a CSV file path or raw CSV text. |
| 9 | **`get_dashboard(username="jagadesh-02")`** | Computes aggregated statistics, recent submissions, attempted-but-unaccepted problems, and smart recommendations. |

### Configuring in Antigravity

Add the following configuration to your `mcp_config.json`:

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

---

## Running Tests

Run the full pytest suite to verify all core components, judge, assistant, dashboard, and MCP tools:

```powershell
python -m pytest -v
```

All tests execute against isolated temporary SQLite databases (`tmp_path`), leaving your actual `progress.db` intact.

---

## Local Verification vs. Official LeetCode Acceptance

> [!IMPORTANT]
> - **Locally Verified**: Indicates that candidate code passed the provided sample unit test cases inside the local runner. Local verification does **not** guarantee passing LeetCode's extensive internal test suite or performance limits.
> - **Officially Accepted**: Indicates that you manually copied the code, submitted it to LeetCode, and received an official "Accepted" verdict on your LeetCode account.

---

## Safety and Privacy Guarantees

- **No Credentials Requested**: The agent never asks for or stores LeetCode passwords, session cookies, or CSRF tokens.
- **No Web Scraping**: The agent does not scrape or crawl LeetCode; all external problem data and history are manually provided by the user.
- **No Automated Submissions**: The agent never submits code directly to external websites. Human review and manual submission are strictly required.
- **Isolated Subprocess Execution**: Solutions run in isolated temporary environments with execution timeouts.

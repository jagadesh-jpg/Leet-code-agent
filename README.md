# LeetCode Agent (`leetcode_agent`)

An autonomous Python agent that solves coding problems in an iterative feedback loop:

1. **Read Problem**: Loads programming challenges (Easy, Medium, Hard).
2. **Generate Code**: Prompts an LLM (or offline Mock LLM) for a Python solution.
3. **Extract Code**: Extracts clean Python code from markdown blocks.
4. **Execute & Judge**: Runs the candidate code in an isolated subprocess against unit test cases.
5. **Inspect Errors**: Captures standard output, standard error, syntax issues, runtime exceptions, or wrong answers.
6. **Iterate & Fix**: Feeds the error and failed test details back into the LLM to refine the code.
7. **Persist Progress**: Records attempts and solved status in an SQLite database (`progress.db`) so solved problems can be skipped in future runs.

---

## Project Structure

```text
Leet_Code/
    main.py           # CLI entry point orchestrating solve-test-fix loop
    llm.py            # OpenAI-compatible LLM client and offline MockLLM
    judge.py          # Subprocess test runner with timeout & memory limit handling
    problems.py       # Problem dataset loader, validator, and difficulty filter
    store.py          # SQLite database storage (attempts, status, summaries)
    prompts.py        # System prompt, initial prompt, retry prompt & code extraction
    problems.json     # 9 curated LeetCode problems (3 easy, 3 medium, 3 hard)
    tests/
        test_judge.py     # Unit tests for judge and code evaluation
        test_problems.py  # Unit tests for problems dataset and filtering
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

## Usage

### Run with Mock LLM (Offline / Free)

The mock client tests the loop without making external API calls. For each problem, it purposefully fails the first attempt and passes the second attempt with the reference solution.

```powershell
# Run all problems with mock
python main.py --mock

# Limit to first 3 problems
python main.py --mock --limit 3

# Filter by difficulty
python main.py --mock --difficulty easy

# Reset database progress before starting
python main.py --reset --mock
```

### Run with a Real LLM

Once `.env` is configured with a valid API key and model:

```powershell
# Run with real LLM
python main.py

# Run only medium problems with up to 5 attempts per problem
python main.py --difficulty medium --max-attempts 5
```

---

## Running Tests

Run the full pytest suite:

```powershell
python -m pytest -v
```

---

## Progress Storage

Progress is tracked in `progress.db` across two tables:
- `progress`: Stores overall status (`solved` or `failed`), attempt count, and timestamp.
- `attempts`: Stores individual attempt logs including candidate code, execution status (`passed`, `wrong_answer`, `runtime_error`, `timeout`), error messages, and creation timestamps.

---

# Using as an MCP Server

The project integrates with the Model Context Protocol (MCP) using the official `FastMCP` SDK, allowing Antigravity and other MCP-compatible clients to interact with the LeetCode Agent over standard input/output (`stdio`) transport.

### Available Tools

1. **`list_problems(difficulty: str = "") -> list[dict]`**
   - Lists available LeetCode problems, titles, difficulties, and whether each problem is solved.
   - Never exposes reference solutions or hidden test cases.
2. **`get_problem(problem_id: str) -> dict`**
   - Retrieves the title, difficulty, description, function signature, and exactly two example test cases.
   - For an unknown problem ID, returns `{"error": "unknown problem"}`.
3. **`submit_solution(problem_id: str, code: str) -> dict`**
   - Executes submitted Python code against all test cases using the judge.
   - Validates problem ID, rejects code longer than 20,000 characters, logs the attempt, and updates solved status upon passing.
4. **`get_progress() -> dict`**
   - Returns the SQLite store summary of solved count, failed count, breakdown by difficulty, and average attempts.

### Installing Dependencies

Install MCP and CLI dependencies in your virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Configuring in Antigravity

Add the following configuration to your Antigravity MCP settings (e.g. `mcpServers`):

```json
{
  "mcpServers": {
    "leetcode-agent": {
      "command": "D:\\Leet_code\\.venv\\Scripts\\python.exe",
      "args": [
        "D:\\Leet_code\\mcp_server.py"
      ]
    }
  }
}
```

> **Note**: Update the absolute paths above to match your local installation if running from another location.

### Testing the Tools

You can test the server tools directly via pytest or Python:

```powershell
.\.venv\Scripts\python.exe -m pytest -v tests/test_mcp_server.py
```

---

## Assumptions

- Candidate code executes locally in a temporary directory via `subprocess.run`.
- Python 3.11+ is installed.
- Standard library modules (e.g. `collections`, `math`, `heapq`) are permitted in candidate solutions.
- The MCP server uses stdio transport and runs locally.

---

## Future Work

- Docker-based runner.
- Real coding-platform adapter.
- More coding problems.

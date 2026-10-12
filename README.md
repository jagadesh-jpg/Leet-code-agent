# LeetCode Edge Agent

Autonomous DSA (Data Structures & Algorithms) solving and self-correction agent with dynamic problem intake, localized multi-language test harnesses, bounded self-repair loops, and permitted LeetCode workflow integration.

GitHub Repository: [https://github.com/jagadesh-jpg/Leet-code-agent](https://github.com/jagadesh-jpg/Leet-code-agent)

---

## Overview

**LeetCode Edge Agent** is an autonomous engineering agent designed to solve algorithmic programming challenges without human intervention. The system takes arbitrary problem inputs—whether from local Markdown/JSON definitions, raw problem text, or LeetCode problem slugs—and plans, synthesizes, executes, diagnoses, repairs, and verifies solution code against multi-category test suites.

---

## Problem This Project Solves

Typical LLM-based code generators produce single-shot solutions that frequently suffer from:
- **Silent logic failures and unhandled edge cases** (e.g., empty arrays, extreme bounds, negative values).
- **Time/Memory limit regressions** caused by suboptimal time complexities.
- **Syntactic and compilation incompatibilities** across multiple target languages.
- **Hallucinated or unverified outputs** where the model declares a solution correct without executing tests in an isolated runtime environment.
- **Uncontrolled external submissions** that pollute external judge statistics with broken code.

LeetCode Edge Agent addresses these problems by wrapping code generation in a **deterministic, local-first feedback loop** that pairs LLM planning and synthesis with local compilers/interpreters, differential fault localization, and strict verification gates.

---

## How the Agent Works

The agent executes a bounded, closed-loop state machine:

```
GENERATE ──► EXECUTE ──► MEASURE ──► DIAGNOSE ──► REPAIR ──► EXECUTE ──► VERIFY
```

1. **GENERATE**:
   - The **Algorithm Planner** (`AlgorithmPlanner`) analyzes the canonical problem specification, classifies algorithm patterns, evaluates constraints, and produces a structured `AlgorithmPlan`.
   - The **Code Generator** (`CodeGenerator`) generates idiomatic solution code for the chosen target language using the algorithm plan and problem signature.
2. **EXECUTE**:
   - The **Language Adapter** (`PythonAdapter`, `CppAdapter`, `CAdapter`, `JavaAdapter`) creates a standalone executable test harness containing problem inputs, reference oracles, and test assertions.
   - The **Execution Runner** (`ProcessExecutionRunner`) executes the compiled binary or script in a subprocess with strict CPU timeout and memory tracking (via `psutil`).
3. **MEASURE**:
   - Execution outputs, exit codes, stdout/stderr, wall-clock duration, and memory utilization are captured into structured `ExecutionResult` and `TestCaseResult` records.
4. **DIAGNOSE**:
   - If tests fail, the **Failure Analyzer** (`FailureAnalyzer`) classifies the issue into deterministic failure categories (e.g., `COMPILE_ERROR`, `RUNTIME_ERROR`, `WRONG_ANSWER`, `TIME_LIMIT_EXCEEDED`, `EDGE_CASE_FAILURE`).
   - The **Root Cause Localizer** (`RootCauseLocalizer`) and **Evidence Collector** perform static and dynamic analysis, correlating stack traces, failed assertions, and AST node locations to produce precise diagnosis evidence.
5. **REPAIR**:
   - The **Code Repairer** (`CodeRepairer`) ingests the localized fault report, execution failure evidence, and original algorithm plan to generate a targeted patch rather than blind regenerating from scratch.
6. **EXECUTE (Retest)**:
   - The newly repaired code is compiled and re-executed against the test harness. If failures persist, the loop increments its attempt counter and repeats up to `MAX_ATTEMPTS`.
7. **VERIFY**:
   - Once all functional tests pass, the **Solution Verifier** (`SolutionVerifier`) runs a final multi-gate verification check (correctness, constraint compliance, asymptotic time/space complexity audit, and plan consistency). Only code satisfying all gates reaches `VERIFIED` status.

---

## Architecture and Folder Structure

```text
agent/
├── api/             # FastAPI / HTTP orchestration endpoints
├── benchmarking/    # Problem benchmarks, multi-language runners, registry
├── benchmarks/      # Multi-stage end-to-end benchmark suites
├── core/            # Strongly-typed Pydantic schemas, models, and orchestrator
│   ├── models.py         # SupportedLanguage, ExecutionResult, ProblemSpec
│   ├── normalizer.py     # Problem text to ProblemSpec normalization
│   └── orchestrator.py   # SelfCorrectionOrchestrator closed-loop engine
├── debugging/       # Fault isolation, root-cause localization, and repair
│   ├── failure_analyzer.py      # Failure classification
│   ├── root_cause_localizer.py  # AST/traceback localization
│   └── repairer.py              # Targeted patch synthesizer
├── evaluation/      # Leakage detection and evaluation utilities
├── execution/       # Process runner and language-specific adapters
│   ├── base.py              # BaseLanguageAdapter abstract interface
│   ├── python_adapter.py    # Python harness & runtime
│   ├── c_cpp_adapters.py    # C / C++ gcc/clang/msvc harnesses & compilation
│   ├── java_adapter.py      # Java javac harness & JVM execution
│   └── runner.py            # ProcessExecutionRunner with timeout & memory caps
├── generation/      # LLM code generation and syntax validation
│   ├── generator.py         # Code generator
│   └── validator.py         # AST syntax validator
├── intake/          # Dynamic problem intake and duplicate detection
│   ├── models.py            # DynamicSolveResult contracts
│   ├── service.py           # ProblemIntakeService
│   └── validator.py         # Problem format and schema validator
├── leetcode/        # LeetCode integration (GraphQL fetch, payload prep, client)
│   ├── adapter.py           # LeetCode question detail -> ProblemSpec adapter
│   ├── client.py            # Permitted GraphQL / REST client with token redaction
│   ├── exceptions.py        # Typed LeetCode error hierarchy
│   ├── models.py            # LeetCode submission models and auth status
│   └── service.py           # LeetCodeWorkflowService end-to-end orchestrator
├── llm/             # LLM provider integration
│   ├── factory.py           # Provider factory
│   └── gemini.py            # Google GenAI (Gemini) provider implementation
├── memory/          # SQLite persistence for experiences and error patterns
├── planning/        # Pattern classification, constraint analysis, algorithm planner
├── queue/           # SQLite-backed persistent problem queue & queue runner
├── strategy/        # Strategy selection and adaptive tuning
├── testing/         # Adaptive test case generation, test oracles, mutation engine
├── verification/    # Multi-gate verifier and complexity auditor
├── config.py        # Central configuration loaded safely from environment
└── solve.py         # Unified CLI entry point
```

---

## Supported Programming Languages

Based on the actual implementation in `agent/execution/`:

| Language | Enum Identifier | Implementation Adapter | Execution Mechanism |
| :--- | :--- | :--- | :--- |
| **Python** | `python` | `PythonAdapter` | Subprocess via Python interpreter (`python`) |
| **C++** | `cpp` | `CppAdapter` | Subprocess compilation via `g++` / `clang++` / `cl.exe`, binary execution |
| **C** | `c` | `CAdapter` | Subprocess compilation via `gcc` / `clang` / `cl.exe`, binary execution |
| **Java** | `java` | `JavaAdapter` | Subprocess compilation via `javac`, JVM execution via `java` |

*Note: Compilers (`gcc`/`g++` or `clang`, `javac`/`java`) must be installed on your system PATH for C, C++, and Java execution.*

---

## Prerequisites and Installation (Windows PowerShell)

### Prerequisites
- **Python 3.10+** (tested on Python 3.11)
- **Git**
- Optional: C/C++ compiler (`gcc`/`g++` via MinGW/MSYS2) and Java JDK for multi-language execution.

### Installation

Clone the repository and install dependencies in Windows PowerShell:

```powershell
# Clone the repository
git clone https://github.com/jagadesh-jpg/Leet-code-agent.git
cd Leet-code-agent

# Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install requirements
pip install -r requirements.txt
```

---

## Environment Configuration

The repository uses `.env` for runtime configuration. A template file [`.env.example`](.env.example) is provided.

Create your `.env` file from the example:

```powershell
Copy-Item .env.example .env
```

### Safe `.env.example` Reference:

```dotenv
# Model Provider Configuration
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash

# Execution & Resource Safety Limits
MAX_EXECUTION_TIMEOUT_SECONDS=5
MAX_EXECUTION_MEMORY_MB=256
MAX_ATTEMPTS=5

# Storage Directories
STORAGE_DIR=storage
SOLUTIONS_DIR=storage/solutions
RUNS_DIR=storage/runs

# API / Orchestration Settings (Optional)
AGENT_API_HOST=127.0.0.1
AGENT_API_PORT=8000
AGENT_API_SECRET_KEY=dev-secret-key-change-me

# LeetCode Credentials (Optional - leave empty for dry-run mode)
LEETCODE_SESSION=
LEETCODE_CSRFTOKEN=
LEETCODE_BASE_URL=https://leetcode.com
LEETCODE_REQUEST_TIMEOUT_SECONDS=10.0
LEETCODE_POLL_INTERVAL_SECONDS=2.0
LEETCODE_POLL_MAX_DURATION_SECONDS=30.0
```

---

## How to Run the CLI

The unified CLI entry point is `agent.solve`.

### Display CLI Help

```powershell
python -m agent.solve --help
```

Output:
```text
usage: solve.py [-h] [--input INPUT_FILE] [--text RAW_TEXT]
                [--leetcode LEETCODE_SLUG] [--language LANGUAGE]
                [--max-attempts MAX_ATTEMPTS] [--dry-run] [--live-submission]
                [--confirm-live-submission]
                [file]

Autonomous DSA Dynamic Intake & LeetCode Solver

positional arguments:
  file                  Path to Markdown or JSON problem file

options:
  -h, --help            show this help message and exit
  --input INPUT_FILE    Path to problem file
  --text RAW_TEXT       Raw problem statement text or Markdown
  --leetcode LEETCODE_SLUG
                        LeetCode problem title slug (e.g. two-sum)
  --language LANGUAGE, -l LANGUAGE
                        Target language (c, cpp, java, python)
  --max-attempts MAX_ATTEMPTS
                        Maximum repair attempts
  --dry-run             Validate submission payload locally without sending
                        network requests (default: True)
  --live-submission     Perform external submission to LeetCode (requires
                        --confirm-live-submission)
  --confirm-live-submission
                        Explicit confirmation required to send live submission
                        to LeetCode
```

### Solve from Raw Text

```powershell
python -m agent.solve --text "Given an array of integers nums and an integer target, return indices of the two numbers such that they add up to target." --language python
```

---

## How to Run the Test Suite

Run the full pytest suite using your active Python environment:

```powershell
python -m pytest
```

To run with verbose output:

```powershell
python -m pytest -v
```

To run a specific test module (e.g., LeetCode integration tests):

```powershell
python -m pytest tests/test_leetcode_integration.py -v
```

---

## Two Sum Workflow (Dry-Run Mode)

The agent supports querying LeetCode problem statements via public GraphQL without submitting credentials. In default dry-run mode, the solution is generated, locally tested, and verified without transmitting any code to LeetCode's judging servers.

### Run Two Sum in Dry-Run Mode:

```powershell
python -m agent.solve --leetcode two-sum --language python --dry-run
```

### Verified Sample Execution Report:

```text
============================================================
STAGE 32 LEETCODE EXECUTION REPORT
============================================================
Problem Slug:          two-sum
Language:              python
Code Hash:             57fa51fa6a36b723
Local Verified:        True (status: VERIFIED)
Request Sent:          False
Submission ID:         None
Judge Verdict:         N/A
Status Note:           Dry-run preparation notice: Submission requires an active, authenticated LEETCODE_SESSION. None configured.
============================================================
```

In dry-run mode, the CLI emits the full verified JSON payload, including the synthesized solution code, test results (e.g., 6/6 tests passed), and code hash, while ensuring `Request Sent: False`.

---

## Local Verification vs. Actual LeetCode Accepted Verdict

It is critical to distinguish between local verification and an external judge verdict:

| Attribute | Local Verification (`is_verified: True`) | LeetCode Accepted Verdict (`judge_verdict: "Accepted"`) |
| :--- | :--- | :--- |
| **Execution Environment** | Local machine / sandbox subprocess | LeetCode's remote sandboxed judge servers |
| **Test Case Scope** | Public example cases + synthesized edge cases & adaptive stress tests | LeetCode's proprietary, hidden comprehensive test suites |
| **Authentication Required** | **None** (Only LLM API key needed for generation) | **Yes** (Valid `LEETCODE_SESSION` & `LEETCODE_CSRFTOKEN`) |
| **Network Call** | GraphQL problem fetch only | POST submission to LeetCode judge endpoint |
| **Guarantee** | Verifies logic against local test suites, constraints, and time limits | Official competitive programming verdict recorded on leetcode.com |

Passing local verification ensures high confidence that the solution satisfies the problem specification, but it does **not** equal an official LeetCode judge verdict until explicitly submitted and confirmed.

---

## Current Limitations & Configuration Requirements

1. **LLM Provider API Key**: Solution generation, algorithm planning, and self-repair require a valid `GEMINI_API_KEY`.
2. **C / C++ / Java Toolchains**: Executing non-Python solutions locally requires relevant toolchains (`gcc`/`g++` or `clang`, `javac`) configured on the host system PATH. If missing, multi-language tests skip or fail at compilation.
3. **Live Submissions Require Dual Confirmation**: The CLI explicitly blocks live submissions unless both `--live-submission` and `--confirm-live-submission` are supplied. In addition, valid `LEETCODE_SESSION` and `LEETCODE_CSRFTOKEN` values must be configured.
4. **Cloudflare & Rate Limits**: LeetCode's public endpoints may enforce Cloudflare bot protection or HTTP 429 rate limits. The client implements bounded backoff, but automated requests may be throttled if abused.

---

## Security Guidance

- **Never Commit Secrets**: Do not commit `.env`, session tokens, or API keys to version control. Ensure `.env` is listed in [`.gitignore`](.gitignore).
- **Sanitized Diagnostics**: The agent's `Config` and `LeetCodeClient` classes intentionally redact tokens and keys during logging and error reporting (`Config.is_api_key_configured()`, `Config.is_leetcode_authenticated()`).
- **LeetCode Session Cookies**:
  - `LEETCODE_SESSION` and `LEETCODE_CSRFTOKEN` provide direct access to your personal LeetCode account.
  - Never share these tokens or paste them into bug reports or publicly shared command logs.
  - Revoke tokens immediately (by logging out of LeetCode in your browser) if you suspect token exposure.
- **Subprocess Isolation**: While the runner enforces execution timeouts and memory bounds via `psutil`, generated code executes on the local host. Do not run untrusted arbitrary code without appropriate system containerization.

---

## License

No license has been selected for this repository yet. All rights are reserved by the repository owner unless a license file is explicitly added.

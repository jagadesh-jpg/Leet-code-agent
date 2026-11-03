import os
import re
import time
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        delay_seconds: Optional[float] = None,
    ):
        self.base_url = base_url or os.getenv("LLM_BASE_URL")
        self.api_key = api_key or os.getenv("LLM_API_KEY")
        self.model = model or os.getenv("LLM_MODEL")

        delay_env = os.getenv("LLM_DELAY_SECONDS", "4")
        try:
            self.delay_seconds = float(delay_seconds if delay_seconds is not None else delay_env)
        except ValueError:
            self.delay_seconds = 4.0

        if not self.api_key or not self.model:
            raise LLMError(
                "Missing LLM_API_KEY or LLM_MODEL in environment. "
                "Please configure them in your .env file or supply them directly."
            )

        try:
            from openai import OpenAI
            self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        except ImportError:
            raise LLMError("openai package is not installed. Please run 'pip install openai'.")

    def ask(self, system_prompt: str, user_prompt: str) -> str:
        backoffs = [5, 10, 20]
        last_exception = None

        for attempt in range(4):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                )
                choice = response.choices[0]
                content = choice.message.content or ""

                if self.delay_seconds > 0:
                    time.sleep(self.delay_seconds)
                return content
            except Exception as e:
                last_exception = e
                if attempt < len(backoffs):
                    time.sleep(backoffs[attempt])
                else:
                    raise LLMError(f"LLM request failed after retries: {last_exception}") from last_exception


class MockLLM:
    """Mock LLM for testing and offline runs.
    
    For every problem, its first response intentionally returns an incorrect solution.
    On the second response for that same problem, it returns that problem's reference_solution.
    """

    def __init__(self, problems: Optional[List[Dict[str, Any]]] = None):
        self.problems = problems or []
        self._problem_attempts: Dict[str, int] = {}
        self._problems_by_id: Dict[str, Dict[str, Any]] = {
            p["id"]: p for p in self.problems if "id" in p
        }

    def _find_problem(self, user_prompt: str) -> Optional[Dict[str, Any]]:
        # 1. Match explicit "Problem ID: <id>"
        match = re.search(r"Problem ID:\s*([a-zA-Z0-9_\-]+)", user_prompt)
        if match:
            prob_id = match.group(1).strip()
            if prob_id in self._problems_by_id:
                return self._problems_by_id[prob_id]

        # 2. Match exact id on word boundaries
        for p_id, p in self._problems_by_id.items():
            if re.search(rf"\b{re.escape(p_id)}\b", user_prompt):
                return p

        # 3. Match exact function signature or function name
        for p in self.problems:
            fn = p.get("function_name")
            if fn and re.search(rf"\bdef\s+{re.escape(fn)}\b", user_prompt):
                return p

        # 4. Fallback matching
        for p in self.problems:
            if p.get("title") and p["title"].lower() in user_prompt.lower():
                return p

        return None

    def ask(self, system_prompt: str, user_prompt: str) -> str:
        problem = self._find_problem(user_prompt)
        prob_id = problem["id"] if problem else "unknown"

        current_count = self._problem_attempts.get(prob_id, 0)
        self._problem_attempts[prob_id] = current_count + 1

        fn_name = problem["function_name"] if problem else "solve"

        if current_count == 0:
            # First attempt: return an intentionally incorrect solution that defines the EXACT function_name
            # Returns an incorrect value (e.g. -999999) so it results in wrong_answer, not runtime_error
            return f"```python\ndef {fn_name}(*args, **kwargs):\n    return -999999\n```"
        else:
            # Second attempt onwards: return reference_solution for that exact problem
            if problem and "reference_solution" in problem:
                ref = problem["reference_solution"].strip()
                return f"```python\n{ref}\n```"
            return f"```python\ndef {fn_name}(*args, **kwargs):\n    return None\n```"

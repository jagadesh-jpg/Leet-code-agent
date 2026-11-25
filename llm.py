import os
import re
import time
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()


import json
import os
import random
import re
import time
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv

load_dotenv()


class LLMError(Exception):
    def __init__(
        self,
        message: str,
        error_type: str = "general",
        retry_after: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
        diagnostic_summary: Optional[str] = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_type = error_type  # "transient_rate_limit", "daily_quota_exhausted", "billing_limit", "rpm_limit", "tpm_limit", "general"
        self.retry_after = retry_after
        self.details = details or {}
        self.diagnostic_summary = diagnostic_summary or message


def sanitize_error_text(text: str) -> str:
    """Sanitize secrets, API keys, and auth parameters from error messages."""
    if not text:
        return ""
    # Strip potential API keys / Bearer tokens / Cloud credentials
    sanitized = re.sub(r"AIza[0-9A-Za-z-_]+", "[REDACTED_API_KEY]", text)
    sanitized = re.sub(r"AQ\.[0-9A-Za-z-_]+", "[REDACTED_API_KEY]", sanitized)
    sanitized = re.sub(r"sk-[a-zA-Z0-9_-]{20,}", "[REDACTED_API_KEY]", sanitized)
    sanitized = re.sub(r"ghp_[a-zA-Z0-9_]{15,}", "[REDACTED_API_KEY]", sanitized)
    sanitized = re.sub(r"github_pat_[a-zA-Z0-9_]{20,}", "[REDACTED_API_KEY]", sanitized)
    sanitized = re.sub(r"AKIA[0-9A-Z]{16}", "[REDACTED_API_KEY]", sanitized)
    sanitized = re.sub(r"(key|api_key|token|auth|secret|password)=([0-9A-Za-z-_\.]+)", r"\1=[REDACTED]", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"Bearer\s+([0-9A-Za-z-_\.]+)", "Bearer [REDACTED]", sanitized, flags=re.IGNORECASE)
    return sanitized


def parse_gemini_error(exc: Exception) -> Dict[str, Any]:
    """Parse Gemini / OpenAI error details to categorize 429 errors into RPM/TPM vs RPD/Daily/Billing."""
    raw_msg = str(exc)
    msg = raw_msg.lower()
    status_code = getattr(exc, "status_code", None)

    details: Dict[str, Any] = {
        "status_code": status_code,
        "quota_metric": None,
        "violations": [],
        "retry_delay": None,
        "google_status": None,
        "google_message": None,
    }
    retry_after: Optional[float] = None

    # Check for response headers if available on OpenAI error
    response = getattr(exc, "response", None)
    if response and hasattr(response, "headers"):
        headers = response.headers
        if "retry-after" in headers:
            try:
                retry_after = float(headers["retry-after"])
            except (ValueError, TypeError):
                pass

    # Extract JSON body from exc.body (dict or JSON string) or response (text/json)
    body_json = getattr(exc, "body", None)
    if isinstance(body_json, str):
        try:
            body_json = json.loads(body_json)
        except Exception:
            body_json = None

    if not isinstance(body_json, dict) and response:
        if hasattr(response, "text") and response.text:
            try:
                body_json = json.loads(response.text)
            except Exception:
                pass
        if not isinstance(body_json, dict) and hasattr(response, "json"):
            try:
                body_json = response.json()
            except Exception:
                body_json = None

    # Fallback: extract embedded JSON or Python dict literal from exc.message or raw_msg
    if not isinstance(body_json, dict):
        # Look for curly brace block containing 'error'
        match = re.search(r"(\{[\s\S]*['\"]error['\"][\s\S]*\})", raw_msg)
        if match:
            candidate = match.group(1).strip()
            # Try json.loads first
            try:
                body_json = json.loads(candidate)
            except Exception:
                # Controlled ast.literal_eval fallback for Python dict formatted string
                import ast
                try:
                    parsed_lit = ast.literal_eval(candidate)
                    if isinstance(parsed_lit, dict):
                        body_json = parsed_lit
                except Exception:
                    body_json = None

    if isinstance(body_json, dict):
        err_obj = body_json.get("error", {})
        if isinstance(err_obj, dict):
            details["google_status"] = err_obj.get("status")
            details["google_message"] = sanitize_error_text(err_obj.get("message", ""))

            # Inspect details list for QuotaFailure and RetryInfo
            rpc_details = err_obj.get("details", [])
            if isinstance(rpc_details, list):
                for item in rpc_details:
                    if not isinstance(item, dict):
                        continue
                    item_type = item.get("@type", "")
                    if "QuotaFailure" in item_type:
                        violations = item.get("violations", [])
                        if isinstance(violations, list):
                            for v in violations:
                                if isinstance(v, dict):
                                    subj = sanitize_error_text(v.get("subject", ""))
                                    desc = sanitize_error_text(v.get("description", ""))
                                    details["violations"].append({"subject": subj, "description": desc})
                                    if not details["quota_metric"] and subj:
                                        details["quota_metric"] = subj
                    elif "RetryInfo" in item_type:
                        delay_str = item.get("retryDelay")
                        if delay_str and isinstance(delay_str, str):
                            details["retry_delay"] = delay_str
                            d_match = re.search(r"([0-9.]+)", delay_str)
                            if d_match and retry_after is None:
                                try:
                                    retry_after = float(d_match.group(1))
                                except ValueError:
                                    pass

    # Regex-based quota metric fallback if not populated from RPC details
    if not details["quota_metric"]:
        all_text_sources = f"{raw_msg} {details.get('google_message') or ''}"
        metric_match = re.search(r"quota metric ['\"]([^'\"]+)['\"]", all_text_sources, re.IGNORECASE)
        if metric_match:
            details["quota_metric"] = metric_match.group(1).strip()
        elif "generaterequestsperminute" in all_text_sources.lower():
            details["quota_metric"] = "GenerateRequestsPerMinutePerProject"
        elif "generaterequestsperday" in all_text_sources.lower():
            details["quota_metric"] = "GenerateRequestsPerDayPerProject"
        elif "tokensperminute" in all_text_sources.lower():
            details["quota_metric"] = "TokensPerMinutePerProject"

    # Extract retry delay from error text (e.g. "please retry after 12.5s")
    if retry_after is None:
        delay_match = re.search(r"retry\s+after\s+([0-9.]+)\s*(?:s|seconds)?", msg)
        if delay_match:
            try:
                retry_after = float(delay_match.group(1))
            except ValueError:
                pass

    # Distinguish quota categories using status, metric, and violations
    combined_diag = (
        f"{msg} {details.get('google_status') or ''} {details.get('google_message') or ''} "
        f"{details.get('quota_metric') or ''} {' '.join(v.get('description', '') for v in details['violations'])}"
    ).lower()

    is_daily_or_billing = (
        "per day" in combined_diag
        or "daily" in combined_diag
        or "rpd" in combined_diag
        or "requestsperday" in combined_diag
        or "billing" in combined_diag
        or "exceeded your current quota" in combined_diag
        or "spending limit" in combined_diag
        or "insufficient_quota" in combined_diag
    )

    is_tpm = (
        "tokens per minute" in combined_diag
        or "tpm" in combined_diag
        or "tokensperminute" in combined_diag
    )

    is_rpm = (
        "requests per minute" in combined_diag
        or "rpm" in combined_diag
        or "requestsperminute" in combined_diag
        or "generatecontentrequestsperminuteproject" in combined_diag
    )

    is_transient_rpm_tpm = (
        "429" in combined_diag
        or "rate limit" in combined_diag
        or is_rpm
        or is_tpm
    )

    quota_type = None
    if is_daily_or_billing:
        error_type = "daily_quota_exhausted"
        quota_type = "daily_quota_exhausted"
    elif is_transient_rpm_tpm:
        error_type = "transient_rate_limit"
        if is_tpm:
            quota_type = "tpm_limit"
        elif is_rpm:
            quota_type = "rpm_limit"
        else:
            quota_type = "transient_rate_limit"
    else:
        error_type = "general"
        quota_type = "general"

    # Construct clean diagnostic message
    diag_summary = []
    if status_code:
        diag_summary.append(f"HTTP {status_code}")
    diag_summary.append(f"Type: {error_type}")
    if quota_type and quota_type != error_type:
        diag_summary.append(f"Quota: {quota_type}")
    if details.get("quota_metric"):
        diag_summary.append(f"Metric: {details['quota_metric']}")
    if details.get("violations"):
        v_desc = details["violations"][0].get("description")
        if v_desc:
            diag_summary.append(f"Reason: {v_desc}")
    if retry_after is not None:
        diag_summary.append(f"Retry-After: {retry_after}s")

    clean_summary = " | ".join(diag_summary)

    return {
        "error_type": error_type,
        "quota_type": quota_type,
        "retry_after": retry_after,
        "details": details,
        "diagnostic_summary": clean_summary,
        "message": sanitize_error_text(raw_msg),
    }


class LLMClient:
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        delay_seconds: Optional[float] = None,
        backup_base_url: Optional[str] = None,
        backup_api_key: Optional[str] = None,
        backup_model: Optional[str] = None,
    ):
        self.base_url = base_url or os.getenv("LLM_BASE_URL")
        self.api_key = api_key or os.getenv("LLM_API_KEY")
        self.model = model or os.getenv("LLM_MODEL")

        self.backup_base_url = backup_base_url or os.getenv("LLM2_BASE_URL")
        self.backup_api_key = backup_api_key or os.getenv("LLM2_API_KEY")
        self.backup_model = backup_model or os.getenv("LLM2_MODEL")

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
            if self.backup_api_key and self.backup_model:
                self.backup_client = OpenAI(api_key=self.backup_api_key, base_url=self.backup_base_url)
            else:
                self.backup_client = None
        except ImportError:
            raise LLMError("openai package is not installed. Please run 'pip install openai'.")

    def _call_backup(self, system_prompt: str, user_prompt: str) -> Optional[str]:
        if not self.backup_client or not self.backup_model:
            return None
        try:
            # Minimal parameter shape compatible with both OpenAI and reasoning/mini models
            response = self.backup_client.chat.completions.create(
                model=self.backup_model,
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
        except Exception:
            return None

    def ask(self, system_prompt: str, user_prompt: str) -> str:
        base_backoffs = [5.0, 15.0, 30.0]
        max_attempts = 4
        last_exception = None

        for attempt in range(max_attempts):
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
                parsed = parse_gemini_error(e)
                error_type = parsed["error_type"]
                retry_after = parsed["retry_after"]
                status_code = parsed.get("details", {}).get("status_code")

                # If daily quota/billing is exhausted, try backup LLM before raising
                if error_type == "daily_quota_exhausted":
                    backup_res = self._call_backup(system_prompt, user_prompt)
                    if backup_res is not None:
                        return backup_res
                    raise LLMError(
                        f"Daily quota or billing limit exhausted: {e}",
                        error_type=error_type,
                        details=parsed["details"],
                        diagnostic_summary=parsed.get("diagnostic_summary"),
                    ) from e

                # Transient rate limit (RPM/TPM): apply exponential backoff + random jitter
                if error_type in ["transient_rate_limit", "rpm_limit", "tpm_limit"] and attempt < max_attempts - 1:
                    if retry_after is not None and retry_after > 0:
                        wait_time = retry_after + random.uniform(1.0, 3.0)
                    else:
                        base = base_backoffs[min(attempt, len(base_backoffs) - 1)]
                        jitter = random.uniform(0.5, 2.5)
                        wait_time = base + jitter
                    time.sleep(wait_time)
                elif attempt < max_attempts - 1:
                    time.sleep(base_backoffs[attempt] + random.uniform(0.5, 1.5))
                else:
                    # Final attempt failed with 429 or 503: try backup LLM before raising error
                    if error_type in ["transient_rate_limit", "rpm_limit", "tpm_limit"] or status_code in [429, 503]:
                        backup_res = self._call_backup(system_prompt, user_prompt)
                        if backup_res is not None:
                            return backup_res

                    raise LLMError(
                        f"LLM request failed after {max_attempts} attempts: {last_exception}",
                        error_type=error_type,
                        details=parsed["details"],
                        diagnostic_summary=parsed.get("diagnostic_summary"),
                    ) from last_exception

        raise LLMError(f"LLM request failed: {last_exception}")


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
            # Construct a minimal problem dict from the prompt if not registered
            fn_match = re.search(r"def\s+([a-zA-Z0-9_]+)\s*\(", user_prompt)
            fn_name = fn_match.group(1) if fn_match else "solve"
            return {"id": prob_id, "function_name": fn_name}

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

        # Determine target language from prompt
        combined_prompt = f"{system_prompt} {user_prompt}".lower()
        if "c++" in combined_prompt or "cpp" in combined_prompt:
            lang = "cpp"
        elif "expert c programmer" in combined_prompt or "language: c\n" in combined_prompt or "in c (" in combined_prompt or "using c " in combined_prompt or "c language" in combined_prompt or "```c " in combined_prompt or "```c\n" in combined_prompt:
            lang = "c"
        elif "java" in combined_prompt:
            lang = "java"
        else:
            lang = "python"

        attempt_key = f"{prob_id}:{lang}"
        current_count = self._problem_attempts.get(attempt_key, 0)
        self._problem_attempts[attempt_key] = current_count + 1

        fn_name = problem["function_name"] if problem else "solve"

        if current_count == 0:
            # First attempt: return an intentionally incorrect solution that causes a failure (tests the retry loop)
            if lang == "c":
                return f"```c\nint {fn_name}(void) {{\n    return -999999;\n}}\n```"
            elif lang == "cpp":
                return f"```cpp\nclass Solution {{\npublic:\n    int {fn_name}() {{\n        return -999999;\n    }}\n}};\n```"
            elif lang == "java":
                return f"```java\nclass Solution {{\n    public int {fn_name}() {{\n        return -999999;\n    }}\n}}\n```"
            else:
                return f"```python\ndef {fn_name}(*args, **kwargs):\n    return -999999\n```"
        else:
            # Second attempt onwards: return reference solution for the target language if available
            ref_solutions = problem.get("reference_solutions", {}) if problem else {}
            if isinstance(ref_solutions, dict) and lang in ref_solutions:
                return f"```{lang}\n{ref_solutions[lang].strip()}\n```"

            # Check problem-specific standard reference implementations
            if prob_id == "two-sum":
                if lang == "c":
                    return "```c\n#include <stdlib.h>\nint* twoSum(int* nums, int numsSize, int target, int* returnSize) {\n    *returnSize = 2;\n    int* res = (int*)malloc(2 * sizeof(int));\n    for (int i = 0; i < numsSize; i++) {\n        for (int j = i + 1; j < numsSize; j++) {\n            if (nums[i] + nums[j] == target) {\n                res[0] = i; res[1] = j;\n                return res;\n            }\n        }\n    }\n    return res;\n}\n```"
                elif lang == "cpp":
                    return "```cpp\n#include <vector>\n#include <unordered_map>\nclass Solution {\npublic:\n    std::vector<int> twoSum(std::vector<int>& nums, int target) {\n        std::unordered_map<int, int> m;\n        for (int i = 0; i < (int)nums.size(); i++) {\n            int comp = target - nums[i];\n            if (m.count(comp)) return {m[comp], i};\n            m[nums[i]] = i;\n        }\n        return {};\n    }\n};\n```"
                elif lang == "java":
                    return "```java\nimport java.util.HashMap;\nimport java.util.Map;\nclass Solution {\n    public int[] twoSum(int[] nums, int target) {\n        Map<Integer, Integer> map = new HashMap<>();\n        for (int i = 0; i < nums.length; i++) {\n            int comp = target - nums[i];\n            if (map.containsKey(comp)) return new int[] { map.get(comp), i };\n            map.put(nums[i], i);\n        }\n        return new int[0];\n    }\n}\n```"

            if prob_id == "reverse-linked-list":
                if lang == "c":
                    return "```c\nstruct ListNode* reverseList(struct ListNode* head) {\n    struct ListNode* prev = NULL;\n    struct ListNode* curr = head;\n    while (curr) {\n        struct ListNode* nxt = curr->next;\n        curr->next = prev;\n        prev = curr;\n        curr = nxt;\n    }\n    return prev;\n}\n```"
                elif lang == "cpp":
                    return "```cpp\nclass Solution {\npublic:\n    ListNode* reverseList(ListNode* head) {\n        ListNode* prev = nullptr;\n        ListNode* curr = head;\n        while (curr) {\n            ListNode* nxt = curr->next;\n            curr->next = prev;\n            prev = curr;\n            curr = nxt;\n        }\n        return prev;\n    }\n};\n```"
                elif lang == "java":
                    return "```java\nclass Solution {\n    public ListNode reverseList(ListNode head) {\n        ListNode prev = null;\n        ListNode curr = head;\n        while (curr != null) {\n            ListNode nxt = curr.next;\n            curr.next = prev;\n            prev = curr;\n            curr = nxt;\n        }\n        return prev;\n    }\n}\n```"
                else:
                    return "```python\nclass Solution:\n    def reverseList(self, head):\n        prev = None\n        curr = head\n        while curr:\n            nxt = curr.next\n            curr.next = prev\n            prev = curr\n            curr = nxt\n        return prev\n```"

            if prob_id == "binary-search":
                if lang == "c":
                    return "```c\nint search(int* nums, int numsSize, int target) {\n    int l = 0, r = numsSize - 1;\n    while (l <= r) {\n        int mid = l + (r - l) / 2;\n        if (nums[mid] == target) return mid;\n        if (nums[mid] < target) l = mid + 1;\n        else r = mid - 1;\n    }\n    return -1;\n}\n```"
                elif lang == "cpp":
                    return "```cpp\nclass Solution {\npublic:\n    int search(std::vector<int>& nums, int target) {\n        int l = 0, r = nums.size() - 1;\n        while (l <= r) {\n            int mid = l + (r - l) / 2;\n            if (nums[mid] == target) return mid;\n            if (nums[mid] < target) l = mid + 1;\n            else r = mid - 1;\n        }\n        return -1;\n    }\n};\n```"
                elif lang == "java":
                    return "```java\nclass Solution {\n    public int search(int[] nums, int target) {\n        int l = 0, r = nums.length - 1;\n        while (l <= r) {\n            int mid = l + (r - l) / 2;\n            if (nums[mid] == target) return mid;\n            if (nums[mid] < target) l = mid + 1;\n            else r = mid - 1;\n        }\n        return -1;\n    }\n}\n```"
                else:
                    return "```python\nclass Solution:\n    def search(self, nums: list[int], target: int) -> int:\n        l, r = 0, len(nums) - 1\n        while l <= r:\n            mid = (l + r) // 2\n            if nums[mid] == target:\n                return mid\n            elif nums[mid] < target:\n                l = mid + 1\n            else:\n                r = mid - 1\n        return -1\n```"

            if problem and "reference_solution" in problem:
                ref = problem["reference_solution"].strip()
                return f"```python\n{ref}\n```"
            return f"```python\ndef {fn_name}(*args, **kwargs):\n    return None\n```"

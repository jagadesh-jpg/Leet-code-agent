"""
Constraint Evaluator.
Deterministically maps problem constraints (e.g. N <= 10^5, N <= 1000, N <= 20)
to maximum allowable Big-O time complexity thresholds, and validates candidate complexities.
"""

import math
import re
from typing import Optional, Tuple


class ConstraintEvaluator:
    """
    Evaluates whether an asymptotic time complexity O(...) is viable given numeric constraints.
    Standard competitive programming / LeetCode target: ~10^7 - 10^8 operations per second.
    """

    OPERATIONS_LIMIT = 10**8

    @classmethod
    def extract_max_n(cls, constraints: list) -> Optional[int]:
        """
        Scans constraints for primary collection size / upper bound (e.g. 'n <= 10^5', 'nums.length <= 1000').
        """
        max_n = None
        for c in constraints:
            stmt = c if isinstance(c, str) else getattr(c, "statement", "")
            # Match patterns like: <= 10^5, <= 100000, <= 20, < 10^4
            matches = re.findall(r"(?:<=|<)\s*(\d+(?:\^\d+)?)", stmt)
            for m in matches:
                val = cls._parse_numeric_value(m)
                if val is not None:
                    # Ignore values that are likely values of elements (e.g., 10^9) vs array size
                    # Array sizes typically are <= 10^7
                    if "length" in stmt.lower() or "size" in stmt.lower() or "n <=" in stmt.lower() or "k <=" in stmt.lower():
                        if max_n is None or val > max_n:
                            max_n = val
                    elif val <= 10**6 and (max_n is None or val > max_n):
                        max_n = val

        return max_n

    @classmethod
    def evaluate_complexity(cls, complexity_str: str, max_n: Optional[int]) -> Tuple[bool, Optional[str]]:
        """
        Determines if complexity_str (e.g. 'O(N^2)', 'O(N log N)', 'O(2^N)') satisfies constraints.
        Returns: (satisfies_constraints, rejection_reason_if_any)
        """
        if max_n is None:
            # If constraints are missing/unknown, we cannot reject on bounds, but must flag uncertainty
            return True, None

        ops = cls.estimate_operations(complexity_str, max_n)
        if ops is None:
            # Complexity string format unrecognized
            return True, None

        if ops > cls.OPERATIONS_LIMIT:
            formatted_ops = f"{ops:.1e}" if ops > 10**6 else str(int(ops))
            return False, f"Estimated operations ({formatted_ops}) exceed standard limit (~10^8) for N = {max_n}"

        return True, None

    @classmethod
    def estimate_operations(cls, complexity_str: str, n: int) -> Optional[float]:
        """Estimates raw operation count given Big-O notation and N."""
        clean = complexity_str.upper().replace(" ", "").replace("*", "")
        # Remove surrounding O(...)
        match = re.match(r"^O\((.*)\)$", clean)
        inner = match.group(1) if match else clean

        if inner in ("1", "CONSTANT"):
            return 1.0

        if inner in ("LOGN", "LOG(N)"):
            return math.log2(max(n, 2))

        if inner in ("SQRT(N)", "N^0.5"):
            return math.isqrt(n)

        if inner in ("N", "LINEAR"):
            return float(n)

        if inner in ("NLOGN", "NLOG(N)", "N*LOGN"):
            return float(n) * math.log2(max(n, 2))

        if inner in ("N^2", "N2"):
            return float(n) ** 2

        if inner in ("N^3", "N3"):
            return float(n) ** 3

        if inner in ("2^N", "2N"):
            if n > 60:
                return float("inf")
            return float(2**n)

        if inner in ("N!", "NFACTORIAL"):
            if n > 20:
                return float("inf")
            return float(math.factorial(n))

        return None

    @classmethod
    def _parse_numeric_value(cls, val_str: str) -> Optional[int]:
        """Parses '10^5' or '1000' into integer."""
        try:
            if "^" in val_str:
                base, exp = val_str.split("^", 1)
                return int(base) ** int(exp)
            return int(val_str)
        except Exception:
            return None

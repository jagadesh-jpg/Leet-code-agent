"""Spaced Repetition & Smart Revision Engine.

Milestone 6.3.12: Spaced Repetition & Smart Revision Engine.
Schedules and tracks revision of previously attempted or solved problems
using transparent, deterministic Leitner/SM-2 inspired spaced repetition intervals.

100% offline, local-first, database-safe (uses tracking DB tables), zero API calls.
Retention indicators are explicit learning-history proxies, not scientific memory measurements.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional

from intelligence.topics import get_problem_topics
from intelligence.tracker import DEFAULT_TRACKING_DB_PATH
from problems import load_problems
import store


class RevisionStatus(str, Enum):
    """Status of a problem in the spaced repetition queue."""
    DUE = "due"
    UPCOMING = "upcoming"
    OVERDUE = "overdue"
    REVIEWED = "reviewed"
    PAUSED = "paused"


class RevisionOutcome(str, Enum):
    """User-reported recall outcome following a revision attempt."""
    EASY_RECALL = "easy_recall"             # Rapid, confident recall without assistance
    RECALLED_WITH_EFFORT = "effort_recall"   # Successful recall after deliberate thought
    NEEDED_HINTS = "needed_hints"           # Needed conceptual or pattern hints
    FAILED_TO_SOLVE = "failed_to_solve"     # Unable to reconstruct solution / syntax impasse


@dataclass
class RevisionItem:
    """A scheduled revision item in the spaced repetition queue."""
    problem_id: str
    title: str
    difficulty: str
    topics: List[str]
    last_reviewed_at: Optional[str]
    next_review_at: str
    interval_days: int
    repetition_count: int
    ease_factor: float
    status: RevisionStatus
    last_outcome: Optional[RevisionOutcome]
    reason_for_scheduling: str

    @property
    def is_due_or_overdue(self) -> bool:
        return self.status in (RevisionStatus.DUE, RevisionStatus.OVERDUE)


@dataclass
class RevisionAnalytics:
    """Aggregated offline spaced repetition analytics and proxies."""
    total_tracked_for_revision: int
    reviews_completed: int
    reviews_due_today: int
    reviews_overdue: int
    reviews_upcoming: int
    reviews_paused: int
    outcome_distribution: Dict[str, int]
    topic_retention_proxies: Dict[str, float]  # Topic -> retention success proxy rate
    active_streak_days: int
    summary: str


def _get_utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _format_iso(dt: datetime) -> str:
    return dt.isoformat()


class SpacedRevisionEngine:
    """Manages spaced repetition scheduling and outcomes in the local tracking database."""

    # Bounded intervals in days
    MIN_INTERVAL_DAYS = 1
    MAX_INTERVAL_DAYS = 90
    DEFAULT_EASE_FACTOR = 2.5
    MIN_EASE_FACTOR = 1.3

    def __init__(
        self,
        tracking_db_path: Optional[str | Path] = None,
        progress_db_path: Optional[str | Path] = None,
    ):
        self.tracking_db_path = Path(tracking_db_path) if tracking_db_path is not None else DEFAULT_TRACKING_DB_PATH
        self.progress_db_path = progress_db_path
        self.init_schema()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.tracking_db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        """Create revision tables in the dedicated tracking database without touching progress.db."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS revision_items (
                    problem_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    difficulty TEXT NOT NULL,
                    topics_json TEXT NOT NULL,
                    last_reviewed_at TEXT,
                    next_review_at TEXT NOT NULL,
                    interval_days INTEGER NOT NULL,
                    repetition_count INTEGER NOT NULL,
                    ease_factor REAL NOT NULL,
                    status TEXT NOT NULL,
                    last_outcome TEXT,
                    reason_for_scheduling TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS revision_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    problem_id TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL,
                    interval_days INTEGER NOT NULL,
                    ease_factor REAL NOT NULL,
                    FOREIGN KEY (problem_id) REFERENCES revision_items(problem_id)
                )
                """
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_rev_next ON revision_items(next_review_at, status)"
            )
            conn.commit()

    def schedule_problem(
        self,
        problem: Dict[str, Any],
        initial_reason: Optional[str] = None,
        custom_next_date: Optional[str] = None,
    ) -> RevisionItem:
        """Schedule or register a problem into the spaced repetition system."""
        pid = problem["id"]
        title = problem.get("title", pid)
        diff = problem.get("difficulty", "medium").lower()
        topics = get_problem_topics(problem)

        now = _get_utc_now()
        now_str = _format_iso(now)

        # Default initial interval based on difficulty:
        # Easy: 3 days, Medium: 2 days, Hard: 1 day
        initial_interval = {"easy": 3, "medium": 2, "hard": 1}.get(diff, 2)
        next_dt = now + timedelta(days=initial_interval)
        next_date_str = custom_next_date if custom_next_date else _format_date(next_dt)
        reason = initial_reason or f"Scheduled for foundational revision ({diff.title()})."

        existing = self.get_revision_item(pid)
        if existing:
            return existing

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO revision_items (
                    problem_id, title, difficulty, topics_json, last_reviewed_at,
                    next_review_at, interval_days, repetition_count, ease_factor,
                    status, last_outcome, reason_for_scheduling, created_at, updated_at
                ) VALUES (?, ?, ?, ?, NULL, ?, ?, 0, ?, ?, NULL, ?, ?, ?)
                """,
                (
                    pid,
                    title,
                    diff,
                    json.dumps(topics),
                    next_date_str,
                    initial_interval,
                    self.DEFAULT_EASE_FACTOR,
                    RevisionStatus.UPCOMING.value,
                    reason,
                    now_str,
                    now_str,
                ),
            )
            conn.commit()

        item = self.get_revision_item(pid)
        assert item is not None
        return item

    def get_revision_item(self, problem_id: str) -> Optional[RevisionItem]:
        """Fetch a specific revision item with dynamic due/overdue status calculation."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM revision_items WHERE problem_id = ?", (problem_id,))
            row = cursor.fetchone()
            if not row:
                return None

        return self._row_to_item(row)

    def _row_to_item(self, row: sqlite3.Row) -> RevisionItem:
        today_str = _format_date(_get_utc_now())
        db_status = RevisionStatus(row["status"])
        next_rev = row["next_review_at"]

        # Dynamically compute due / overdue if item is not paused or reviewed
        computed_status = db_status
        if db_status not in (RevisionStatus.PAUSED, RevisionStatus.REVIEWED):
            if next_rev < today_str:
                computed_status = RevisionStatus.OVERDUE
            elif next_rev == today_str:
                computed_status = RevisionStatus.DUE
            else:
                computed_status = RevisionStatus.UPCOMING

        outcome = RevisionOutcome(row["last_outcome"]) if row["last_outcome"] else None

        return RevisionItem(
            problem_id=row["problem_id"],
            title=row["title"],
            difficulty=row["difficulty"],
            topics=json.loads(row["topics_json"]),
            last_reviewed_at=row["last_reviewed_at"],
            next_review_at=next_rev,
            interval_days=row["interval_days"],
            repetition_count=row["repetition_count"],
            ease_factor=float(row["ease_factor"]),
            status=computed_status,
            last_outcome=outcome,
            reason_for_scheduling=row["reason_for_scheduling"],
        )

    def list_queue(self, status_filter: Optional[str] = None) -> List[RevisionItem]:
        """List all items in the revision queue, prioritized deterministically."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM revision_items")
            rows = cursor.fetchall()

        items = [self._row_to_item(r) for r in rows]

        if status_filter:
            status_filter = status_filter.lower().strip()
            items = [i for i in items if i.status.value == status_filter]

        # Prioritize queue:
        # 1. Overdue first (most urgent)
        # 2. Due today
        # 3. Upcoming (by next review date ascending)
        # 4. Paused / Reviewed last
        priority_rank = {
            RevisionStatus.OVERDUE: 1,
            RevisionStatus.DUE: 2,
            RevisionStatus.UPCOMING: 3,
            RevisionStatus.REVIEWED: 4,
            RevisionStatus.PAUSED: 5,
        }
        diff_order = {"hard": 1, "medium": 2, "easy": 3}

        items.sort(
            key=lambda x: (
                priority_rank.get(x.status, 9),
                x.next_review_at,
                diff_order.get(x.difficulty, 2),
                x.problem_id,
            )
        )
        return items

    def record_revision_outcome(
        self,
        problem_id: str,
        outcome: RevisionOutcome,
    ) -> RevisionItem:
        """Record a revision outcome and calculate next review interval deterministically."""
        item = self.get_revision_item(problem_id)
        if not item:
            raise ValueError(f"Revision item '{problem_id}' not found.")

        now = _get_utc_now()
        now_str = _format_iso(now)
        review_date_str = _format_date(now)

        interval = item.interval_days
        ease = item.ease_factor
        rep_count = item.repetition_count

        # Deterministic Leitner/SM-2 Interval Adaptation:
        if outcome == RevisionOutcome.EASY_RECALL:
            rep_count += 1
            ease = min(3.0, ease + 0.15)
            interval = max(3, int(interval * ease * 1.2))
            reason = f"Excellent recall: extended interval to {interval} days."
        elif outcome == RevisionOutcome.RECALLED_WITH_EFFORT:
            rep_count += 1
            ease = max(self.MIN_EASE_FACTOR, ease)
            interval = max(2, int(interval * ease))
            reason = f"Successful deliberate recall: interval adjusted to {interval} days."
        elif outcome == RevisionOutcome.NEEDED_HINTS:
            ease = max(self.MIN_EASE_FACTOR, ease - 0.2)
            interval = max(self.MIN_INTERVAL_DAYS, int(interval * 0.6))
            reason = f"Needed hint assistance: interval tightened to {interval} day(s) to reinforce pattern."
        elif outcome == RevisionOutcome.FAILED_TO_SOLVE:
            rep_count = 0
            ease = max(self.MIN_EASE_FACTOR, ease - 0.4)
            interval = self.MIN_INTERVAL_DAYS
            reason = "Recall impasse: reset interval to 1 day for immediate follow-up."

        interval = min(self.MAX_INTERVAL_DAYS, max(self.MIN_INTERVAL_DAYS, interval))
        next_review_dt = now + timedelta(days=interval)
        next_review_str = _format_date(next_review_dt)

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE revision_items
                SET last_reviewed_at = ?, next_review_at = ?, interval_days = ?,
                    repetition_count = ?, ease_factor = ?, status = ?,
                    last_outcome = ?, reason_for_scheduling = ?, updated_at = ?
                WHERE problem_id = ?
                """,
                (
                    now_str,
                    next_review_str,
                    interval,
                    rep_count,
                    ease,
                    RevisionStatus.UPCOMING.value,
                    outcome.value,
                    reason,
                    now_str,
                    problem_id,
                ),
            )
            cursor.execute(
                """
                INSERT INTO revision_history (
                    problem_id, outcome, reviewed_at, interval_days, ease_factor
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (problem_id, outcome.value, now_str, interval, ease),
            )
            conn.commit()

        updated = self.get_revision_item(problem_id)
        assert updated is not None
        return updated

    def set_paused(self, problem_id: str, paused: bool) -> RevisionItem:
        """Pause or resume a problem in the revision queue."""
        item = self.get_revision_item(problem_id)
        if not item:
            raise ValueError(f"Revision item '{problem_id}' not found.")

        new_status = RevisionStatus.PAUSED if paused else RevisionStatus.UPCOMING
        now_str = _format_iso(_get_utc_now())

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE revision_items SET status = ?, updated_at = ? WHERE problem_id = ?",
                (new_status.value, now_str, problem_id),
            )
            conn.commit()

        updated = self.get_revision_item(problem_id)
        assert updated is not None
        return updated

    def get_analytics(self) -> RevisionAnalytics:
        """Compute aggregated offline spaced repetition analytics and proxies."""
        items = self.list_queue()
        today_str = _format_date(_get_utc_now())

        due_today = sum(1 for i in items if i.status == RevisionStatus.DUE)
        overdue = sum(1 for i in items if i.status == RevisionStatus.OVERDUE)
        upcoming = sum(1 for i in items if i.status == RevisionStatus.UPCOMING)
        paused = sum(1 for i in items if i.status == RevisionStatus.PAUSED)

        # History and outcomes
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT outcome, reviewed_at FROM revision_history ORDER BY reviewed_at ASC")
            hist_rows = cursor.fetchall()

        total_reviews = len(hist_rows)
        outcome_dist: Dict[str, int] = {}
        distinct_dates = set()

        for r in hist_rows:
            oc = r["outcome"]
            outcome_dist[oc] = outcome_dist.get(oc, 0) + 1
            if r["reviewed_at"]:
                distinct_dates.add(r["reviewed_at"][:10])

        # Active review streak in days based solely on actual review timestamps
        streak = 0
        if distinct_dates:
            sorted_dates = sorted(list(distinct_dates), reverse=True)
            check_date = datetime.strptime(sorted_dates[0], "%Y-%m-%d").date()
            today_date = _get_utc_now().date()
            if check_date >= today_date - timedelta(days=1):
                streak = 1
                curr = check_date
                for prev_str in sorted_dates[1:]:
                    prev_date = datetime.strptime(prev_str, "%Y-%m-%d").date()
                    if prev_date == curr - timedelta(days=1):
                        streak += 1
                        curr = prev_date
                    else:
                        break

        # Topic retention proxies
        # Proxy rate = (easy + effort) / total_reviewed_for_topic
        topic_counts: Dict[str, List[int]] = {}  # topic -> [success_count, total_count]
        for it in items:
            for t in it.topics:
                if t not in topic_counts:
                    topic_counts[t] = [0, 0]
                if it.last_outcome:
                    topic_counts[t][1] += 1
                    if it.last_outcome in (RevisionOutcome.EASY_RECALL, RevisionOutcome.RECALLED_WITH_EFFORT):
                        topic_counts[t][0] += 1

        retention_proxies: Dict[str, float] = {}
        for t, (succ, tot) in topic_counts.items():
            if tot > 0:
                retention_proxies[t] = round(succ / tot, 2)

        summary_parts = []
        if items:
            summary_parts.append(f"{len(items)} problem(s) in spaced revision queue.")
            if overdue > 0:
                summary_parts.append(f"{overdue} problem(s) overdue for review.")
            if due_today > 0:
                summary_parts.append(f"{due_today} problem(s) scheduled for today.")
        else:
            summary_parts.append("Spaced repetition queue is currently clear.")

        return RevisionAnalytics(
            total_tracked_for_revision=len(items),
            reviews_completed=total_reviews,
            reviews_due_today=due_today,
            reviews_overdue=overdue,
            reviews_upcoming=upcoming,
            reviews_paused=paused,
            outcome_distribution=outcome_dist,
            topic_retention_proxies=retention_proxies,
            active_streak_days=streak,
            summary=" ".join(summary_parts),
        )

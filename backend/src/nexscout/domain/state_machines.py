"""Explicit, validated state machines for applications, workflow runs, and tasks.

Statuses are never set ad hoc: callers ask a machine to transition and it raises
InvalidTransition for anything that is not declared here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from nexscout.domain.errors import InvalidTransition


@dataclass(frozen=True)
class StateMachine[S: StrEnum]:
    name: str
    transitions: Mapping[S, frozenset[S]]
    terminal: frozenset[S]

    def can(self, current: S, target: S) -> bool:
        return target in self.transitions.get(current, frozenset())

    def transition(self, current: S, target: S) -> S:
        if not self.can(current, target):
            raise InvalidTransition(f"{self.name}: cannot move from '{current}' to '{target}'")
        return target

    def allowed(self, current: S) -> frozenset[S]:
        return self.transitions.get(current, frozenset())

    def is_terminal(self, state: S) -> bool:
        return state in self.terminal


# --------------------------------------------------------------------------- applications
class ApplicationStatus(StrEnum):
    DISCOVERED = "discovered"
    SHORTLISTED = "shortlisted"
    RESEARCHING = "researching"
    PREPARING = "preparing"
    AWAITING_REVIEW = "awaiting_review"
    APPROVED = "approved"
    SUBMITTING = "submitting"
    SUBMITTED = "submitted"
    SUBMISSION_UNCERTAIN = "submission_uncertain"
    TRACKING = "tracking"
    COMPLETED = "completed"
    PAUSED = "paused"
    NEEDS_USER_ACTION = "needs_user_action"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


_A = ApplicationStatus
_ACTIVE_PRE_SUBMIT = {_A.SHORTLISTED, _A.RESEARCHING, _A.PREPARING, _A.AWAITING_REVIEW, _A.APPROVED}

APPLICATION_MACHINE: StateMachine[ApplicationStatus] = StateMachine(
    name="application",
    transitions={
        _A.DISCOVERED: frozenset({_A.SHORTLISTED, _A.CANCELLED}),
        _A.SHORTLISTED: frozenset({_A.RESEARCHING, _A.PREPARING, _A.PAUSED, _A.CANCELLED}),
        _A.RESEARCHING: frozenset(
            {_A.PREPARING, _A.PAUSED, _A.NEEDS_USER_ACTION, _A.FAILED, _A.CANCELLED}
        ),
        _A.PREPARING: frozenset(
            {
                _A.AWAITING_REVIEW,
                _A.RESEARCHING,
                _A.PAUSED,
                _A.NEEDS_USER_ACTION,
                _A.FAILED,
                _A.CANCELLED,
            }
        ),
        # Review can send work back for more preparation.
        _A.AWAITING_REVIEW: frozenset({_A.APPROVED, _A.PREPARING, _A.PAUSED, _A.CANCELLED}),
        # Submitting needs an explicit approval, which is why only APPROVED can enter it.
        _A.APPROVED: frozenset({_A.SUBMITTING, _A.AWAITING_REVIEW, _A.PAUSED, _A.CANCELLED}),
        # A submission attempt either shows observed/user-confirmed success or is uncertain.
        _A.SUBMITTING: frozenset(
            {_A.SUBMITTED, _A.SUBMISSION_UNCERTAIN, _A.NEEDS_USER_ACTION, _A.FAILED}
        ),
        _A.SUBMISSION_UNCERTAIN: frozenset({_A.SUBMITTED, _A.APPROVED, _A.FAILED}),
        _A.SUBMITTED: frozenset({_A.TRACKING, _A.WITHDRAWN, _A.REJECTED, _A.COMPLETED}),
        _A.TRACKING: frozenset({_A.COMPLETED, _A.REJECTED, _A.WITHDRAWN}),
        _A.PAUSED: frozenset(_ACTIVE_PRE_SUBMIT | {_A.CANCELLED}),
        _A.NEEDS_USER_ACTION: frozenset(
            {
                _A.RESEARCHING,
                _A.PREPARING,
                _A.AWAITING_REVIEW,
                _A.APPROVED,
                _A.SUBMITTED,
                _A.CANCELLED,
            }
        ),
        _A.FAILED: frozenset({_A.RESEARCHING, _A.PREPARING, _A.APPROVED, _A.CANCELLED}),
        _A.COMPLETED: frozenset(),
        _A.CANCELLED: frozenset(),
        _A.REJECTED: frozenset(),
        _A.WITHDRAWN: frozenset(),
    },
    terminal=frozenset({_A.COMPLETED, _A.CANCELLED, _A.REJECTED, _A.WITHDRAWN}),
)


# --------------------------------------------------------------------------- workflow runs
class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    PAUSING = "pausing"
    PAUSED = "paused"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FAILED = "failed"
    SUCCEEDED = "succeeded"


_R = RunStatus
RUN_MACHINE: StateMachine[RunStatus] = StateMachine(
    name="workflow_run",
    transitions={
        _R.PENDING: frozenset({_R.RUNNING, _R.PAUSED, _R.CANCELLED}),
        # RUNNING -> PENDING: requeued after worker shutdown or a lost lease.
        _R.RUNNING: frozenset(
            {_R.WAITING_APPROVAL, _R.PAUSING, _R.CANCELLING, _R.FAILED, _R.SUCCEEDED, _R.PENDING}
        ),
        _R.WAITING_APPROVAL: frozenset({_R.RUNNING, _R.PAUSED, _R.CANCELLING}),
        _R.PAUSING: frozenset(
            {_R.PAUSED, _R.CANCELLING, _R.FAILED, _R.SUCCEEDED, _R.PENDING, _R.WAITING_APPROVAL}
        ),
        _R.PAUSED: frozenset({_R.RUNNING, _R.PENDING, _R.CANCELLING, _R.CANCELLED}),
        _R.CANCELLING: frozenset({_R.CANCELLED}),
        _R.FAILED: frozenset({_R.PENDING, _R.CANCELLED}),  # retry re-enqueues
        _R.CANCELLED: frozenset(),
        _R.SUCCEEDED: frozenset({_R.PENDING}),  # only via an explicit "rerun this step"
    },
    terminal=frozenset({_R.CANCELLED}),
)


# --------------------------------------------------------------------------- tasks
class TaskStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    BLOCKED = "blocked"  # waiting for approval / user input
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


_T = TaskStatus
TASK_MACHINE: StateMachine[TaskStatus] = StateMachine(
    name="task",
    transitions={
        _T.QUEUED: frozenset({_T.RUNNING, _T.CANCELLED, _T.SKIPPED}),
        _T.RUNNING: frozenset(
            # RUNNING -> QUEUED happens when a lease expires or a pause releases the task.
            {_T.SUCCEEDED, _T.FAILED, _T.RETRY_WAIT, _T.BLOCKED, _T.CANCELLED, _T.QUEUED}
        ),
        _T.RETRY_WAIT: frozenset({_T.QUEUED, _T.CANCELLED}),
        _T.BLOCKED: frozenset({_T.QUEUED, _T.CANCELLED, _T.SKIPPED}),
        _T.FAILED: frozenset({_T.QUEUED}),  # manual retry
        _T.SUCCEEDED: frozenset({_T.QUEUED}),  # manual rerun of a step
        _T.CANCELLED: frozenset(),
        _T.SKIPPED: frozenset(),
    },
    terminal=frozenset({_T.CANCELLED, _T.SKIPPED}),
)

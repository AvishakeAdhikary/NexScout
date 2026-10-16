import itertools

import pytest

from nexscout.domain.errors import InvalidTransition
from nexscout.domain.state_machines import (
    APPLICATION_MACHINE,
    RUN_MACHINE,
    TASK_MACHINE,
    ApplicationStatus,
    RunStatus,
    TaskStatus,
)

A = ApplicationStatus


def test_happy_path_application_lifecycle() -> None:
    path = [
        A.DISCOVERED,
        A.SHORTLISTED,
        A.RESEARCHING,
        A.PREPARING,
        A.AWAITING_REVIEW,
        A.APPROVED,
        A.SUBMITTING,
        A.SUBMITTED,
        A.TRACKING,
        A.COMPLETED,
    ]
    for current, target in itertools.pairwise(path):
        assert APPLICATION_MACHINE.transition(current, target) == target


@pytest.mark.parametrize("source", [A.DISCOVERED, A.SHORTLISTED, A.PREPARING, A.AWAITING_REVIEW])
def test_cannot_submit_without_approval(source: ApplicationStatus) -> None:
    with pytest.raises(InvalidTransition):
        APPLICATION_MACHINE.transition(source, A.SUBMITTING)
    assert not APPLICATION_MACHINE.can(source, A.SUBMITTED)


def test_submitting_cannot_jump_to_completed() -> None:
    assert not APPLICATION_MACHINE.can(A.SUBMITTING, A.COMPLETED)


def test_uncertain_submission_must_be_reconciled() -> None:
    assert APPLICATION_MACHINE.can(A.SUBMITTING, A.SUBMISSION_UNCERTAIN)
    assert APPLICATION_MACHINE.allowed(A.SUBMISSION_UNCERTAIN) == {
        A.SUBMITTED,
        A.APPROVED,
        A.FAILED,
    }


@pytest.mark.parametrize("state", [A.COMPLETED, A.CANCELLED, A.REJECTED, A.WITHDRAWN])
def test_terminal_application_states_have_no_exits(state: ApplicationStatus) -> None:
    assert APPLICATION_MACHINE.is_terminal(state)
    assert APPLICATION_MACHINE.allowed(state) == frozenset()


def test_every_status_is_declared() -> None:
    for machine, enum in (
        (APPLICATION_MACHINE, ApplicationStatus),
        (RUN_MACHINE, RunStatus),
        (TASK_MACHINE, TaskStatus),
    ):
        assert set(machine.transitions) == set(enum), machine.name
        for targets in machine.transitions.values():
            assert targets <= set(enum)


def test_cancel_is_two_phase_for_runs() -> None:
    assert not RUN_MACHINE.can(RunStatus.RUNNING, RunStatus.CANCELLED)
    assert RUN_MACHINE.can(RunStatus.RUNNING, RunStatus.CANCELLING)
    assert RUN_MACHINE.allowed(RunStatus.CANCELLING) == {RunStatus.CANCELLED}


def test_pause_is_two_phase_for_running_runs() -> None:
    assert not RUN_MACHINE.can(RunStatus.RUNNING, RunStatus.PAUSED)
    assert RUN_MACHINE.can(RunStatus.PAUSING, RunStatus.PAUSED)
    assert RUN_MACHINE.can(RunStatus.PAUSED, RunStatus.RUNNING)


def test_task_lease_expiry_requeues() -> None:
    assert TASK_MACHINE.can(TaskStatus.RUNNING, TaskStatus.QUEUED)
    assert TASK_MACHINE.can(TaskStatus.FAILED, TaskStatus.QUEUED)
    assert not TASK_MACHINE.can(TaskStatus.CANCELLED, TaskStatus.QUEUED)

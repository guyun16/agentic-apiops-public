package com.apiops.runner.state;

import com.apiops.common.enums.FailureType;
import org.junit.jupiter.api.Test;

import java.util.EnumSet;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class RunStateMachineTest {

    @Test
    void startsPendingAndAllowsPendingTransitions() {
        RunStateMachine machine = new RunStateMachine();

        assertEquals(RunStatus.PENDING, machine.currentStatus());
        assertEquals(RunStatus.RUNNING, machine.transitionTo(RunStatus.RUNNING));
        assertEquals(RunStatus.RUNNING, machine.currentStatus());
    }

    @Test
    void pendingCanBeCancelled() {
        RunStateMachine machine = new RunStateMachine();

        assertEquals(RunStatus.CANCELLED, machine.transitionTo(RunStatus.CANCELLED));
    }

    @Test
    void runningAllowsEveryConfirmedTerminalStatus() {
        for (RunStatus target : Set.of(
                RunStatus.SUCCESS,
                RunStatus.ASSERTION_FAILED,
                RunStatus.EXECUTION_FAILED,
                RunStatus.TIMEOUT,
                RunStatus.CANCELLED)) {
            RunStateMachine machine = new RunStateMachine(RunStatus.RUNNING);

            assertEquals(target, machine.transitionTo(target));
            assertTrue(machine.currentStatus().isTerminal());
        }
    }

    @Test
    void terminalStatusesCannotTransition() {
        for (RunStatus terminal : Set.of(
                RunStatus.SUCCESS,
                RunStatus.ASSERTION_FAILED,
                RunStatus.EXECUTION_FAILED,
                RunStatus.TIMEOUT,
                RunStatus.CANCELLED)) {
            RunStateMachine machine = new RunStateMachine(terminal);

            assertInvalidTransition(machine, RunStatus.RUNNING);
        }
    }

    @Test
    void pendingRejectsTerminalStatusesOtherThanCancellation() {
        RunStateMachine machine = new RunStateMachine();

        assertInvalidTransition(machine, RunStatus.SUCCESS);
        assertInvalidTransition(machine, RunStatus.EXECUTION_FAILED);
    }

    @Test
    void repeatedSameStatusIsRejected() {
        RunStateMachine machine = new RunStateMachine();

        assertInvalidTransition(machine, RunStatus.PENDING);
        machine.transitionTo(RunStatus.RUNNING);
        assertInvalidTransition(machine, RunStatus.RUNNING);
    }

    @Test
    void canTransitionToReflectsTheConfirmedTable() {
        RunStateMachine pending = new RunStateMachine();
        RunStateMachine running = new RunStateMachine(RunStatus.RUNNING);

        assertTrue(pending.canTransitionTo(RunStatus.RUNNING));
        assertTrue(pending.canTransitionTo(RunStatus.CANCELLED));
        assertFalse(pending.canTransitionTo(RunStatus.SUCCESS));
        assertFalse(pending.canTransitionTo(RunStatus.EXECUTION_FAILED));
        assertTrue(running.canTransitionTo(RunStatus.SUCCESS));
        assertTrue(running.canTransitionTo(RunStatus.ASSERTION_FAILED));
        assertTrue(running.canTransitionTo(RunStatus.EXECUTION_FAILED));
        assertTrue(running.canTransitionTo(RunStatus.TIMEOUT));
        assertTrue(running.canTransitionTo(RunStatus.CANCELLED));
    }

    @Test
    void runStatusContainsOnlyTheConfirmedTopLevelStates() {
        assertEquals(EnumSet.allOf(RunStatus.class), EnumSet.of(
                RunStatus.PENDING,
                RunStatus.RUNNING,
                RunStatus.SUCCESS,
                RunStatus.ASSERTION_FAILED,
                RunStatus.EXECUTION_FAILED,
                RunStatus.TIMEOUT,
                RunStatus.CANCELLED));
    }

    @Test
    void failureTypeContainsFineGrainedExecutionCauses() {
        assertTrue(Set.of(FailureType.values()).containsAll(Set.of(
                FailureType.REQUEST_BUILD_ERROR,
                FailureType.INVALID_TARGET_URI,
                FailureType.DNS_ERROR,
                FailureType.CONNECT_ERROR,
                FailureType.TLS_ERROR,
                FailureType.IO_ERROR,
                FailureType.ASSERTION_EVALUATION_ERROR)));
    }

    private void assertInvalidTransition(RunStateMachine machine, RunStatus target) {
        InvalidRunStateTransitionException exception = assertThrows(
                InvalidRunStateTransitionException.class,
                () -> machine.transitionTo(target));
        assertTrue(exception.getMessage().contains("Illegal run status transition"));
    }
}

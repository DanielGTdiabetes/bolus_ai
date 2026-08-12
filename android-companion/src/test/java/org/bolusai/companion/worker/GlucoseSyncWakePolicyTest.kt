package org.bolusai.companion.worker

import androidx.work.WorkInfo
import org.junit.Assert.assertEquals
import org.junit.Test

class GlucoseSyncWakePolicyTest {
    private val now = 10_000L

    @Test
    fun newReadingWithNoUnfinishedWorkerEnsuresImmediateWork() {
        assertEquals(
            GlucoseSyncWakeDecision.ENSURE_SCHEDULED,
            GlucoseSyncWakePolicy.decide(emptyList(), now),
        )
        assertEquals(
            GlucoseSyncWakeDecision.ENSURE_SCHEDULED,
            GlucoseSyncWakePolicy.decide(
                listOf(snapshot(WorkInfo.State.SUCCEEDED)),
                now,
            ),
        )
    }

    @Test
    fun newReadingDuringBackoffWakesEnqueuedWorker() {
        val backedOff = snapshot(
            state = WorkInfo.State.ENQUEUED,
            runAttemptCount = 2,
            nextScheduleTimeMillis = now + 30_000,
        )

        assertEquals(
            GlucoseSyncWakeDecision.WAKE_BACKOFF,
            GlucoseSyncWakePolicy.decide(listOf(backedOff), now),
        )
    }

    @Test
    fun newReadingWhileWorkerIsRunningNeverCancelsIt() {
        val running = snapshot(WorkInfo.State.RUNNING, runAttemptCount = 2)
        val staleBackoff = snapshot(
            WorkInfo.State.ENQUEUED,
            runAttemptCount = 1,
            nextScheduleTimeMillis = now + 30_000,
        )

        assertEquals(
            GlucoseSyncWakeDecision.PRESERVE_RUNNING,
            GlucoseSyncWakePolicy.decide(listOf(running, staleBackoff), now),
        )
    }

    @Test
    fun freshOrAlreadyEligibleEnqueuedWorkIsKept() {
        assertEquals(
            GlucoseSyncWakeDecision.KEEP_ENQUEUED,
            GlucoseSyncWakePolicy.decide(
                listOf(snapshot(WorkInfo.State.ENQUEUED, runAttemptCount = 0)),
                now,
            ),
        )
        assertEquals(
            GlucoseSyncWakeDecision.KEEP_ENQUEUED,
            GlucoseSyncWakePolicy.decide(
                listOf(
                    snapshot(
                        WorkInfo.State.ENQUEUED,
                        runAttemptCount = 3,
                        nextScheduleTimeMillis = now,
                    ),
                ),
                now,
            ),
        )
    }

    @Test
    fun runningWorkerIsObservedThenItsBackoffCanBeWokenWithoutOverlap() {
        val whileRunning = GlucoseSyncWakePolicy.decide(
            listOf(snapshot(WorkInfo.State.RUNNING, runAttemptCount = 1)),
            now,
        )
        val afterRetry = GlucoseSyncWakePolicy.decide(
            listOf(
                snapshot(
                    WorkInfo.State.ENQUEUED,
                    runAttemptCount = 2,
                    nextScheduleTimeMillis = now + 60_000,
                ),
            ),
            now,
        )

        assertEquals(GlucoseSyncWakeDecision.PRESERVE_RUNNING, whileRunning)
        assertEquals(GlucoseSyncWakeDecision.WAKE_BACKOFF, afterRetry)
    }

    private fun snapshot(
        state: WorkInfo.State,
        runAttemptCount: Int = 0,
        nextScheduleTimeMillis: Long = 0,
    ) = GlucoseWorkSnapshot(
        workId = "work-$state-$runAttemptCount",
        state = state,
        runAttemptCount = runAttemptCount,
        nextScheduleTimeMillis = nextScheduleTimeMillis,
    )
}

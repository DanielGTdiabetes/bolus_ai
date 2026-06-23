package org.bolusai.companion.network

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class HermesMfpSyncTriggerResultTest {
    @Test
    fun schedulesFollowUpWhenHermesPostedNoMeals() {
        val result = HermesMfpSyncTriggerResult(
            ok = true,
            statusCode = 200,
            body = """{"success":1,"output_tail":"sync complete posted=0 queued=0"}""",
        )

        assertTrue(result.shouldFollowUp())
    }

    @Test
    fun doesNotScheduleFollowUpWhenHermesPostedMeal() {
        val result = HermesMfpSyncTriggerResult(
            ok = true,
            statusCode = 200,
            body = """{"success":1,"output_tail":"sync complete posted=1 queued=0"}""",
        )

        assertFalse(result.shouldFollowUp())
    }

    @Test
    fun doesNotScheduleFollowUpForFailedTrigger() {
        val result = HermesMfpSyncTriggerResult(
            ok = false,
            statusCode = 500,
            body = """{"success":0,"output_tail":"error posted=0"}""",
        )

        assertFalse(result.shouldFollowUp())
    }
}

package org.bolusai.companion.network

import org.junit.Assert.assertEquals
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

    @Test
    fun preservesLegacyPostedOnlyFollowUpContract() {
        val result = HermesMfpSyncTriggerResult(
            ok = true,
            statusCode = 200,
            body = """{"success":1,"output_tail":"sync complete posted=0"}""",
        )

        assertTrue(result.shouldFollowUp())
    }

    @Test
    fun parsesStructuredSuccessWithRecoveredMetadataFailure() {
        val result = HermesMfpSyncTriggerResult.fromHttpResponse(
            statusCode = 200,
            rawBody = """{
                "sync_id":"sync-20260812",
                "success":1,
                "status":"success_with_warning",
                "metadata_status":"fallback_recovered",
                "ingest_status":"success",
                "posted_count":1,
                "queued_count":0,
                "output_tail":"mfp metadata HTTP 500; sync complete posted=1 queued=0"
            }""".trimIndent(),
        )

        assertTrue(result.ok)
        assertEquals(HermesMfpSyncStatus.SUCCESS_WITH_WARNING, result.status)
        assertEquals("sync-20260812", result.syncId)
        assertEquals("fallback_recovered", result.metadataStatus)
        assertEquals("success", result.ingestStatus)
        assertEquals(1, result.postedCount)
        assertEquals("comida sincronizada con aviso", result.notificationSummary())
        assertTrue(result.diagnosticSummary().contains("metadata_status=fallback_recovered"))
        assertFalse(result.shouldFollowUp())
    }

    @Test
    fun parsesLegacyOutputTailBeforeDiagnosticBodyIsTruncated() {
        val longOutput = "diagnostic ".repeat(180) + "sync complete posted=0 queued=0"
        val rawBody = """{"success":1,"output_tail":"$longOutput"}"""

        val result = HermesMfpSyncTriggerResult.fromHttpResponse(statusCode = 200, rawBody = rawBody)

        assertEquals(HermesMfpSyncStatus.NO_CHANGES, result.status)
        assertEquals(0, result.postedCount)
        assertEquals(0, result.queuedCount)
        assertTrue(result.body.length <= 1_200)
        assertTrue(result.shouldFollowUp())
    }

    @Test
    fun retryScheduledIsAcceptedButDoesNotRequestDiscoveryFollowUp() {
        val result = HermesMfpSyncTriggerResult.fromHttpResponse(
            statusCode = 409,
            rawBody = """{
                "sync_id":"sync-retry",
                "success":0,
                "status":"retry_scheduled",
                "metadata_status":"fallback_recovered",
                "ingest_status":"retry_scheduled",
                "posted_count":0,
                "queued_count":1,
                "output_tail":"sync complete posted=0 queued=1"
            }""".trimIndent(),
        )

        assertTrue(result.ok)
        assertEquals(HermesMfpSyncStatus.RETRY_SCHEDULED, result.status)
        assertEquals("reintento pendiente", result.notificationSummary())
        assertFalse(result.shouldFollowUp())
    }
}

package org.bolusai.companion.worker

import kotlinx.coroutines.runBlocking
import org.bolusai.companion.dexcom.GlucoseReading
import org.bolusai.companion.network.ActiveEndpoint
import org.bolusai.companion.network.GlucoseIngestClient
import org.bolusai.companion.network.GlucoseIngestResult
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class GlucoseQueueDrainerTest {
    private val first = reading("reading-1", 1_750_000_000)
    private val second = reading("reading-2", 1_750_000_300)
    private val third = reading("reading-3", 1_750_000_600)

    @Test
    fun primaryDownAndBackupSuccessKeepsReadingUntilPrimaryAck() = runBlocking {
        val queue = mutableListOf(first)
        val endpoints = mutableListOf<ActiveEndpoint>()
        val client = GlucoseIngestClient { _, _, _, endpoint ->
            endpoints += endpoint
            if (endpoint == ActiveEndpoint.PRIMARY) {
                GlucoseIngestResult(false, endpoint, 502, "bad gateway")
            } else {
                GlucoseIngestResult(true, endpoint, 200, "accepted by backup")
            }
        }

        val result = drainer(queue) { reading ->
            client.send("https://nas", "https://render", "key", reading)
        }.drain(requirePrimaryAcknowledgement = true)

        assertEquals(GlucoseDrainOutcome.RETRY, result.outcome)
        assertEquals("primary_ack_pending", result.reason)
        assertEquals(listOf(ActiveEndpoint.PRIMARY, ActiveEndpoint.BACKUP), endpoints)
        assertEquals(listOf(first), queue)
    }

    @Test
    fun timeoutAndDnsFailureNeverAcknowledgeOrLoseReading() = runBlocking {
        for (error in listOf("Read timed out", "Unable to resolve host nas.local")) {
            val queue = mutableListOf(first)
            val result = drainer(queue) {
                GlucoseIngestResult(false, ActiveEndpoint.NONE, null, error)
            }.drain(requirePrimaryAcknowledgement = true)

            assertEquals(GlucoseDrainOutcome.RETRY, result.outcome)
            assertEquals("transient_upload_failure", result.reason)
            assertEquals(listOf(first), queue)
        }
    }

    @Test
    fun recoveryDrainsMultipleReadingsInOrderExactlyOnce() = runBlocking {
        val queue = mutableListOf(first, second, third)
        val acceptedByBackend = linkedSetOf<String>()
        val deliveryOrder = mutableListOf<String>()

        val failed = drainer(queue) {
            GlucoseIngestResult(false, ActiveEndpoint.NONE, null, "dns")
        }.drain(requirePrimaryAcknowledgement = true)
        assertEquals(GlucoseDrainOutcome.RETRY, failed.outcome)
        assertEquals(listOf(first, second, third), queue)

        val recovered = drainer(queue) { reading ->
            val uid = requireNotNull(reading.readingUid)
            deliveryOrder += uid
            acceptedByBackend += uid
            GlucoseIngestResult(true, ActiveEndpoint.PRIMARY, 200, "accepted")
        }.drain(requirePrimaryAcknowledgement = true)

        assertEquals(GlucoseDrainOutcome.SUCCESS, recovered.outcome)
        assertTrue(queue.isEmpty())
        assertEquals(listOf("reading-1", "reading-2", "reading-3"), deliveryOrder)
        assertEquals(setOf("reading-1", "reading-2", "reading-3"), acceptedByBackend)
    }

    @Test
    fun terminalPayloadFailureDoesNotDropReading() = runBlocking {
        val queue = mutableListOf(first)
        val result = drainer(queue) {
            GlucoseIngestResult(false, ActiveEndpoint.NONE, 422, "invalid")
        }.drain(requirePrimaryAcknowledgement = true)

        assertEquals(GlucoseDrainOutcome.FAILURE, result.outcome)
        assertEquals(listOf(first), queue)
    }

    private fun drainer(
        queue: MutableList<GlucoseReading>,
        send: suspend (GlucoseReading) -> GlucoseIngestResult,
    ) = GlucoseQueueDrainer(
        pending = { queue.toList() },
        send = send,
        acknowledge = { acknowledged -> queue.removeAll { it.dedupeKey == acknowledged.dedupeKey } },
    )

    private fun reading(uid: String, timestamp: Long) = GlucoseReading(
        glucoseMgdl = 120,
        timestampSeconds = timestamp,
        trendArrow = "Flat",
        readingUid = uid,
    )
}

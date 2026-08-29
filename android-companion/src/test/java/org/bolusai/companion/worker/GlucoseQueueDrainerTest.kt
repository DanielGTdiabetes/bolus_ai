package org.bolusai.companion.worker

import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.delay
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
        val backupAcknowledgements = mutableSetOf<String>()
        val endpoints = mutableListOf<ActiveEndpoint>()
        val client = GlucoseIngestClient { _, _, _, endpoint ->
            endpoints += endpoint
            if (endpoint == ActiveEndpoint.PRIMARY) {
                GlucoseIngestResult(false, endpoint, 502, "bad gateway")
            } else {
                GlucoseIngestResult(true, endpoint, 200, "accepted by backup")
            }
        }

        val result = drainer(
            queue = queue,
            backupAcknowledgements = backupAcknowledgements,
            send = { reading -> client.send("https://nas", "https://render", "key", reading) },
        ).drain(requirePrimaryAcknowledgement = true)

        assertEquals(GlucoseDrainOutcome.RETRY, result.outcome)
        assertEquals("primary_ack_pending", result.reason)
        assertEquals(listOf(ActiveEndpoint.PRIMARY, ActiveEndpoint.BACKUP), endpoints)
        assertEquals(listOf(first), queue)
        assertEquals(setOf(first.dedupeKey), backupAcknowledgements)
    }

    @Test
    fun primaryOutageStillForwardsEveryQueuedReadingToBackupOnce() = runBlocking {
        val queue = mutableListOf(first, second, third)
        val backupAcknowledgements = mutableSetOf<String>()
        val delivered = mutableListOf<String>()

        val result = drainer(
            queue = queue,
            backupAcknowledgements = backupAcknowledgements,
            send = { reading ->
                delivered += requireNotNull(reading.readingUid)
                GlucoseIngestResult(true, ActiveEndpoint.BACKUP, 200, "accepted")
            },
        ).drain(requirePrimaryAcknowledgement = true)

        assertEquals(GlucoseDrainOutcome.RETRY, result.outcome)
        assertEquals("primary_ack_pending", result.reason)
        assertEquals(listOf("reading-1", "reading-2", "reading-3"), delivered)
        assertEquals(listOf(first, second, third), queue)
        assertEquals(queue.mapTo(mutableSetOf()) { it.dedupeKey }, backupAcknowledgements)
    }

    @Test
    fun backupAcknowledgedBacklogRetriesPrimaryWithoutResendingToBackup() = runBlocking {
        val queue = mutableListOf(first, second)
        val backupAcknowledgements = queue.mapTo(mutableSetOf()) { it.dedupeKey }
        var failoverSendCalls = 0
        val primaryCalls = mutableListOf<String>()

        val result = drainer(
            queue = queue,
            backupAcknowledgements = backupAcknowledgements,
            send = {
                failoverSendCalls += 1
                GlucoseIngestResult(true, ActiveEndpoint.BACKUP, 200, "duplicate")
            },
            sendPrimary = { reading ->
                primaryCalls += requireNotNull(reading.readingUid)
                GlucoseIngestResult(false, ActiveEndpoint.PRIMARY, null, "timeout")
            },
        ).drain(requirePrimaryAcknowledgement = true)

        assertEquals(GlucoseDrainOutcome.RETRY, result.outcome)
        assertEquals("primary_ack_pending", result.reason)
        assertEquals(0, failoverSendCalls)
        assertEquals(listOf("reading-1"), primaryCalls)
        assertEquals(listOf(first, second), queue)
    }

    @Test
    fun timeoutAndDnsFailureNeverAcknowledgeOrLoseReading() = runBlocking {
        for (error in listOf("Read timed out", "Unable to resolve host nas.local")) {
            val queue = mutableListOf(first)
            val result = drainer(
                queue = queue,
                send = { GlucoseIngestResult(false, ActiveEndpoint.NONE, null, error) },
            ).drain(requirePrimaryAcknowledgement = true)

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

        val failed = drainer(
            queue = queue,
            send = { GlucoseIngestResult(false, ActiveEndpoint.NONE, null, "dns") },
        ).drain(requirePrimaryAcknowledgement = true)
        assertEquals(GlucoseDrainOutcome.RETRY, failed.outcome)
        assertEquals(listOf(first, second, third), queue)

        val recovered = drainer(
            queue = queue,
            send = { reading ->
                val uid = requireNotNull(reading.readingUid)
                deliveryOrder += uid
                acceptedByBackend += uid
                GlucoseIngestResult(true, ActiveEndpoint.PRIMARY, 200, "accepted")
            },
        ).drain(requirePrimaryAcknowledgement = true)

        assertEquals(GlucoseDrainOutcome.SUCCESS, recovered.outcome)
        assertTrue(queue.isEmpty())
        assertEquals(listOf("reading-1", "reading-2", "reading-3"), deliveryOrder)
        assertEquals(setOf("reading-1", "reading-2", "reading-3"), acceptedByBackend)
    }

    @Test
    fun terminalPayloadFailureDoesNotDropReading() = runBlocking {
        val queue = mutableListOf(first)
        val result = drainer(
            queue = queue,
            send = { GlucoseIngestResult(false, ActiveEndpoint.NONE, 422, "invalid") },
        ).drain(requirePrimaryAcknowledgement = true)

        assertEquals(GlucoseDrainOutcome.FAILURE, result.outcome)
        assertEquals(listOf(first), queue)
    }

    @Test
    fun replacementAndRunningWorkerCannotConsumeConcurrently() = runBlocking {
        var activeConsumers = 0
        var maxActiveConsumers = 0

        (1..2).map {
            async {
                GlucoseSyncExecutionGate.withExclusive {
                    activeConsumers += 1
                    maxActiveConsumers = maxOf(maxActiveConsumers, activeConsumers)
                    delay(25)
                    activeConsumers -= 1
                }
            }
        }.awaitAll()

        assertEquals(1, maxActiveConsumers)
        assertEquals(0, activeConsumers)
    }

    private fun drainer(
        queue: MutableList<GlucoseReading>,
        send: suspend (GlucoseReading) -> GlucoseIngestResult,
        sendPrimary: suspend (GlucoseReading) -> GlucoseIngestResult = send,
        backupAcknowledgements: MutableSet<String> = mutableSetOf(),
    ) = GlucoseQueueDrainer(
        pending = { queue.toList() },
        send = send,
        sendPrimary = sendPrimary,
        backupAcknowledged = { it.dedupeKey in backupAcknowledgements },
        acknowledgeBackup = { backupAcknowledgements += it.dedupeKey },
        acknowledgePrimary = { acknowledged ->
            queue.removeAll { it.dedupeKey == acknowledged.dedupeKey }
            backupAcknowledgements -= acknowledged.dedupeKey
        },
    )

    private fun reading(uid: String, timestamp: Long) = GlucoseReading(
        glucoseMgdl = 120,
        timestampSeconds = timestamp,
        trendArrow = "Flat",
        readingUid = uid,
    )
}

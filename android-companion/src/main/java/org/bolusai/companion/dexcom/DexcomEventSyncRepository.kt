package org.bolusai.companion.dexcom

import android.content.Context
import java.util.Locale

internal fun rememberBoundedKeys(
    existing: Iterable<String>,
    additions: Iterable<String>,
    maxSize: Int,
): List<String> {
    require(maxSize > 0) { "maxSize must be positive" }
    val ordered = LinkedHashSet<String>()
    existing.filterTo(ordered) { it.isNotBlank() }
    additions.forEach { key ->
        if (key.isBlank()) return@forEach
        ordered.remove(key)
        ordered.add(key)
    }
    while (ordered.size > maxSize) {
        val oldest = ordered.firstOrNull() ?: break
        ordered.remove(oldest)
    }
    return ordered.toList()
}

internal fun encodeOrderedKeys(keys: Iterable<String>): String =
    keys.joinToString(separator = "\n")

internal fun decodeOrderedKeys(raw: String?): List<String> =
    raw
        ?.lineSequence()
        ?.map(String::trim)
        ?.filter(String::isNotEmpty)
        ?.distinct()
        ?.toList()
        .orEmpty()

internal fun insulinEventFingerprint(
    insulinType: String,
    insulinUnits: Double,
    timestamp: Long,
): String = "$timestamp|${insulinType.trim().uppercase(Locale.ROOT)}|${insulinUnits.toBits()}"

class DexcomEventSyncRepository(context: Context) {
    private val prefs = context.getSharedPreferences("bolus_companion_dexcom_sync", Context.MODE_PRIVATE)

    fun lastEventId(): String? = prefs.getString("last_event_id", null)
    fun lastEventTimestamp(): Long? =
        prefs.getLong("last_event_timestamp", 0L).takeIf { it > 0L }

    fun isProcessed(eventId: String): Boolean {
        if (eventId == lastEventId()) return true
        return processedEventIds().contains(eventId)
    }

    fun hasProcessedEventIds(): Boolean =
        processedEventIds().isNotEmpty()

    fun markProcessedBatch(eventIds: Collection<String>) {
        if (eventIds.isEmpty()) return
        val processedIds = rememberBoundedKeys(processedEventIds(), eventIds, MAX_PROCESSED_IDS)
        prefs.edit()
            .putString(PROCESSED_EVENT_IDS_ORDERED, encodeOrderedKeys(processedIds))
            .remove(LEGACY_PROCESSED_EVENT_IDS)
            .apply()
    }

    fun markProcessed(eventId: String, timestamp: Long) {
        val processedIds = rememberBoundedKeys(processedEventIds(), listOf(eventId), MAX_PROCESSED_IDS)
        prefs.edit()
            .putString("last_event_id", eventId)
            .putLong("last_event_timestamp", timestamp)
            .putString(PROCESSED_EVENT_IDS_ORDERED, encodeOrderedKeys(processedIds))
            .remove(LEGACY_PROCESSED_EVENT_IDS)
            .apply()
    }

    fun hasInsulinBroadcast(insulinType: String, insulinUnits: Double, timestamp: Long): Boolean =
        insulinBroadcastFingerprints().contains(
            insulinEventFingerprint(insulinType, insulinUnits, timestamp),
        )

    fun markInsulinBroadcast(insulinType: String, insulinUnits: Double, timestamp: Long) {
        val fingerprint = insulinEventFingerprint(insulinType, insulinUnits, timestamp)
        val fingerprints = rememberBoundedKeys(
            insulinBroadcastFingerprints(),
            listOf(fingerprint),
            MAX_INSULIN_FINGERPRINTS,
        )
        prefs.edit()
            .putString(INSULIN_FINGERPRINTS_ORDERED, encodeOrderedKeys(fingerprints))
            .apply()
    }

    fun hasRecentCarbsBroadcast(carbsGrams: Int, timestamp: Long): Boolean =
        recentCarbsBroadcasts().any { broadcast ->
            broadcast.carbsGrams == carbsGrams &&
                kotlin.math.abs(broadcast.timestamp - timestamp) <= CARBS_DEDUPE_WINDOW_MS
        }

    fun markCarbsBroadcast(carbsGrams: Int, timestamp: Long) {
        val cutoff = System.currentTimeMillis() - CARBS_DEDUPE_RETENTION_MS
        val broadcasts = recentCarbsBroadcasts()
            .filter { it.timestamp >= cutoff }
            .plus(CarbsBroadcast(carbsGrams, timestamp))
            .takeLast(MAX_CARBS_BROADCASTS)
            .map { "${it.timestamp}:${it.carbsGrams}" }
            .toSet()
        prefs.edit()
            .putStringSet("recent_carbs_broadcasts", broadcasts)
            .apply()
    }

    fun markInitialized(timestamp: Long = System.currentTimeMillis()) {
        prefs.edit()
            .remove("last_event_id")
            .putLong("last_event_timestamp", timestamp)
            .apply()
    }

    private fun processedEventIds(): List<String> {
        val orderedRaw = prefs.getString(PROCESSED_EVENT_IDS_ORDERED, null)
        if (orderedRaw != null) return decodeOrderedKeys(orderedRaw)

        val legacyIds = prefs.getStringSet(LEGACY_PROCESSED_EVENT_IDS, emptySet()).orEmpty()
        val migrated = rememberBoundedKeys(
            legacyIds,
            listOfNotNull(lastEventId()),
            MAX_PROCESSED_IDS,
        )
        if (migrated.isNotEmpty()) {
            prefs.edit()
                .putString(PROCESSED_EVENT_IDS_ORDERED, encodeOrderedKeys(migrated))
                .remove(LEGACY_PROCESSED_EVENT_IDS)
                .apply()
        }
        return migrated
    }

    private fun insulinBroadcastFingerprints(): List<String> =
        decodeOrderedKeys(prefs.getString(INSULIN_FINGERPRINTS_ORDERED, null))

    private fun recentCarbsBroadcasts(): List<CarbsBroadcast> =
        prefs.getStringSet("recent_carbs_broadcasts", emptySet())
            ?.mapNotNull { raw ->
                val parts = raw.split(":")
                if (parts.size != 2) return@mapNotNull null
                val timestamp = parts[0].toLongOrNull() ?: return@mapNotNull null
                val carbsGrams = parts[1].toIntOrNull() ?: return@mapNotNull null
                CarbsBroadcast(carbsGrams, timestamp)
            }
            .orEmpty()

    private data class CarbsBroadcast(
        val carbsGrams: Int,
        val timestamp: Long,
    )

    companion object {
        private const val PROCESSED_EVENT_IDS_ORDERED = "processed_event_ids_ordered_v2"
        private const val LEGACY_PROCESSED_EVENT_IDS = "processed_event_ids"
        private const val INSULIN_FINGERPRINTS_ORDERED = "insulin_fingerprints_ordered_v1"
        private const val MAX_PROCESSED_IDS = 2_000
        private const val MAX_INSULIN_FINGERPRINTS = 2_000
        private const val MAX_CARBS_BROADCASTS = 100
        private const val CARBS_DEDUPE_WINDOW_MS = 45 * 60_000L
        private const val CARBS_DEDUPE_RETENTION_MS = 24 * 60 * 60_000L
    }
}

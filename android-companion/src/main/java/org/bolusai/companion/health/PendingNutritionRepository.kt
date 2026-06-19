package org.bolusai.companion.health

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.time.Duration
import java.time.Instant

class PendingNutritionRepository(context: Context) {
    private val prefs = context.getSharedPreferences("bolus_companion_pending_nutrition", Context.MODE_PRIVATE)

    fun stableRecords(
        observedRecords: List<NutritionRecordSnapshot>,
        sentHashes: Set<String>,
        now: Instant = Instant.now(),
    ): List<NutritionRecordSnapshot> {
        val pending = load()
            .filterNot { it.record.dedupeHash in sentHashes }
            .associateBy { it.record.dedupeHash }
            .toMutableMap()

        val observed = observedRecords
            .distinctBy { it.dedupeHash }
            .filterNot { it.dedupeHash in sentHashes }

        val observedSlotKeys = observed.map { it.mealSlotKey }.toSet()
        pending.entries.removeAll { (_, pendingMeal) ->
            pendingMeal.record.mealSlotKey in observedSlotKeys &&
                observed.none { it.dedupeHash == pendingMeal.record.dedupeHash }
        }

        observed.forEach { record ->
            pending.putIfAbsent(
                record.dedupeHash,
                PendingNutritionRecord(record = record, firstSeenAt = now),
            )
        }

        val stable = pending.values
            .filter { Duration.between(it.firstSeenAt, now) >= STABILIZATION_WINDOW }
            .map { it.record }

        persist(pending.values.toList())
        return stable
    }

    fun markSent(records: List<NutritionRecordSnapshot>) {
        if (records.isEmpty()) return
        val sentHashes = records.map { it.dedupeHash }.toSet()
        persist(load().filterNot { it.record.dedupeHash in sentHashes })
    }

    private fun load(): List<PendingNutritionRecord> = runCatching {
        val raw = prefs.getString(KEY, null).orEmpty()
        if (raw.isBlank()) return@runCatching emptyList()
        val array = JSONArray(raw)
        buildList {
            for (index in 0 until array.length()) {
                val item = array.getJSONObject(index)
                add(
                    PendingNutritionRecord(
                        record = NutritionRecordSnapshot(
                            metadataId = item.optString("metadata_id"),
                            sourcePackage = item.optString("source_package"),
                            startTime = Instant.parse(item.optString("start_time")),
                            endTime = Instant.parse(item.optString("end_time")),
                            mealType = item.optString("meal_type").ifBlank { null },
                            carbohydratesGrams = item.optNullableDouble("carbohydrates_g"),
                            proteinGrams = item.optNullableDouble("protein_g"),
                            fatGrams = item.optNullableDouble("fat_g"),
                            fiberGrams = item.optNullableDouble("fiber_g"),
                            caloriesKcal = item.optNullableDouble("calories_kcal"),
                        ),
                        firstSeenAt = Instant.parse(item.optString("first_seen_at")),
                    ),
                )
            }
        }
    }.getOrDefault(emptyList())

    private fun persist(records: List<PendingNutritionRecord>) {
        val array = JSONArray()
        records.take(200).forEach { pending ->
            val record = pending.record
            array.put(
                JSONObject()
                    .put("metadata_id", record.metadataId)
                    .put("source_package", record.sourcePackage)
                    .put("start_time", record.startTime.toString())
                    .put("end_time", record.endTime.toString())
                    .put("meal_type", record.mealType.orEmpty())
                    .putNullable("carbohydrates_g", record.carbohydratesGrams)
                    .putNullable("protein_g", record.proteinGrams)
                    .putNullable("fat_g", record.fatGrams)
                    .putNullable("fiber_g", record.fiberGrams)
                    .putNullable("calories_kcal", record.caloriesKcal)
                    .put("first_seen_at", pending.firstSeenAt.toString()),
            )
        }
        prefs.edit().putString(KEY, array.toString()).apply()
    }

    private fun JSONObject.putNullable(name: String, value: Double?): JSONObject =
        put(name, value ?: JSONObject.NULL)

    private fun JSONObject.optNullableDouble(name: String): Double? =
        if (isNull(name) || !has(name)) null else optDouble(name)

    private data class PendingNutritionRecord(
        val record: NutritionRecordSnapshot,
        val firstSeenAt: Instant,
    )

    private companion object {
        const val KEY = "pending_json"
        val STABILIZATION_WINDOW: Duration = Duration.ofSeconds(60)
    }
}

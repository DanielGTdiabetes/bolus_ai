package org.bolusai.companion.bolus

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import org.json.JSONObject

class BolusProfileRepository(context: Context) {
    private val prefs = context.getSharedPreferences("bolus_companion_profile", Context.MODE_PRIVATE)
    private val state = MutableStateFlow(read())

    fun observe(): StateFlow<BolusProfile> = state.asStateFlow()
    fun current(): BolusProfile = read()

    fun save(profile: BolusProfile) {
        prefs.edit().putString("profileJson", profile.toJson().toString()).apply()
        state.value = profile
    }

    private fun read(): BolusProfile {
        val raw = prefs.getString("profileJson", null) ?: return BolusProfile()
        return runCatching { JSONObject(raw).toBolusProfile() }.getOrDefault(BolusProfile())
    }
}

fun JSONObject.toBolusProfile(): BolusProfile {
    val targets = optJSONObject("targets") ?: JSONObject()
    val cr = optJSONObject("cr") ?: JSONObject()
    val cf = optJSONObject("cf") ?: JSONObject()
    val iob = optJSONObject("iob") ?: JSONObject()
    val calculator = optJSONObject("calculator") ?: JSONObject()
    val midTarget = targets.optDoubleOrNull("mid") ?: 100.0
    val slots = listOf("breakfast", "lunch", "dinner", "snack").associateWith { slot ->
        BolusSlotProfile(
            cr = cr.optDoubleOrNull(slot) ?: 10.0,
            cf = cf.optDoubleOrNull(slot) ?: 50.0,
            target = targets.optDoubleOrNull(slot) ?: midTarget,
        )
    }

    return BolusProfile(
        schemaVersion = optInt("schema_version", 1),
        userId = optString("user_id", "default"),
        configHash = optString("config_hash", ""),
        updatedAt = optString("updated_at").takeIf { it.isNotBlank() && it != "null" },
        slots = slots,
        diaHours = iob.optDoubleOrNull("dia_hours") ?: 4.0,
        roundStepU = optDoubleOrNull("round_step_u") ?: 0.5,
        maxBolusU = optDoubleOrNull("max_bolus_u") ?: 10.0,
        maxCorrectionU = optDoubleOrNull("max_correction_u") ?: 5.0,
        subtractFiber = calculator.optBoolean("subtract_fiber", false),
        fiberFactor = calculator.optDoubleOrNull("fiber_factor") ?: 0.5,
        fiberThresholdG = calculator.optDoubleOrNull("fiber_threshold_g") ?: 5.0,
    )
}

private fun BolusProfile.toJson(): JSONObject {
    val targets = JSONObject()
    val cr = JSONObject()
    val cf = JSONObject()
    slots.forEach { (slot, profile) ->
        targets.put(slot, profile.target)
        cr.put(slot, profile.cr)
        cf.put(slot, profile.cf)
    }
    targets.put("mid", slots["snack"]?.target ?: 100.0)

    return JSONObject()
        .put("schema_version", schemaVersion)
        .put("user_id", userId)
        .put("config_hash", configHash)
        .put("updated_at", updatedAt)
        .put("targets", targets)
        .put("cr", cr)
        .put("cf", cf)
        .put("iob", JSONObject().put("dia_hours", diaHours))
        .put(
            "calculator",
            JSONObject()
                .put("subtract_fiber", subtractFiber)
                .put("fiber_factor", fiberFactor)
                .put("fiber_threshold_g", fiberThresholdG),
        )
        .put("round_step_u", roundStepU)
        .put("max_bolus_u", maxBolusU)
        .put("max_correction_u", maxCorrectionU)
}

private fun JSONObject.optDoubleOrNull(name: String): Double? =
    if (has(name) && !isNull(name)) optDouble(name) else null

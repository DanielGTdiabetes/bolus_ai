package org.bolusai.companion.usage

import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context

data class ForegroundTransition(
    val packageName: String,
)

object ForegroundEventInterpreter {
    fun currentForegroundPackage(transitions: List<ForegroundTransition>): String? =
        transitions.lastOrNull()?.packageName

    fun observedExitSince(
        packageName: String,
        transitions: List<ForegroundTransition>,
    ): Boolean {
        var sawPackageForeground = false
        transitions.forEach { transition ->
            if (transition.packageName == packageName) {
                sawPackageForeground = true
            } else if (sawPackageForeground) {
                return true
            }
        }
        return false
    }
}

class ForegroundAppWatcher(private val context: Context) {
    private val usageStatsManager = context.getSystemService(UsageStatsManager::class.java)

    fun currentForegroundPackage(): String? {
        if (!UsageAccess.hasPermission(context)) return null
        val now = System.currentTimeMillis()
        return ForegroundEventInterpreter.currentForegroundPackage(
            foregroundTransitions(now - LOOKBACK_MS, now),
        )
    }

    fun observedExitSince(packageName: String, sinceMillis: Long): Boolean {
        if (!UsageAccess.hasPermission(context)) return false
        val now = System.currentTimeMillis()
        return ForegroundEventInterpreter.observedExitSince(
            packageName = packageName,
            transitions = foregroundTransitions(sinceMillis.coerceAtMost(now), now),
        )
    }

    private fun foregroundTransitions(fromMillis: Long, toMillis: Long): List<ForegroundTransition> {
        val events = usageStatsManager.queryEvents(fromMillis, toMillis)
        val event = UsageEvents.Event()
        val transitions = mutableListOf<ForegroundTransition>()
        while (events.hasNextEvent()) {
            events.getNextEvent(event)
            if (event.eventType == UsageEvents.Event.ACTIVITY_RESUMED ||
                event.eventType == UsageEvents.Event.MOVE_TO_FOREGROUND
            ) {
                transitions += ForegroundTransition(event.packageName)
            }
        }
        return transitions
    }

    private companion object {
        const val LOOKBACK_MS = 2 * 60 * 1000L
    }
}

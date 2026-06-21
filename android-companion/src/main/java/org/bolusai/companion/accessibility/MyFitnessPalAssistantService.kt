package org.bolusai.companion.accessibility

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import org.bolusai.companion.data.AppSettingsRepository

class MyFitnessPalAssistantService : AccessibilityService() {
    override fun onServiceConnected() {
        serviceInfo = serviceInfo.apply {
            eventTypes = AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED or
                AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED or
                AccessibilityEvent.TYPE_VIEW_FOCUSED
            feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC
            flags = flags or AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS or
                AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
            packageNames = arrayOf(MYFITNESSPAL_PACKAGE)
            notificationTimeout = 250
        }
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        if (event?.packageName?.toString() != MYFITNESSPAL_PACKAGE) return
        val settings = AppSettingsRepository(applicationContext).current()
        if (!settings.myFitnessPalAssistEnabled) return
        val query = pendingQuery(applicationContext) ?: return
        val root = rootInActiveWindow ?: return
        if (fillSearchField(root, query)) clearPendingQuery(applicationContext)
    }

    override fun onInterrupt() = Unit

    private fun fillSearchField(root: AccessibilityNodeInfo, query: String): Boolean {
        val candidates = mutableListOf<AccessibilityNodeInfo>()
        collectEditableNodes(root, candidates)
        val target = candidates.firstOrNull { it.isFocused } ?: candidates.firstOrNull() ?: return false
        target.performAction(AccessibilityNodeInfo.ACTION_FOCUS)
        val args = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, query)
        }
        return target.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
    }

    private fun collectEditableNodes(node: AccessibilityNodeInfo, candidates: MutableList<AccessibilityNodeInfo>) {
        if (node.isEditable && node.isEnabled) candidates.add(node)
        for (index in 0 until node.childCount) {
            node.getChild(index)?.let { collectEditableNodes(it, candidates) }
        }
    }

    companion object {
        private const val MYFITNESSPAL_PACKAGE = "com.myfitnesspal.android"
        private const val PREFS = "bolus_companion_mfp_assist"
        private const val KEY_PENDING_QUERY = "pending_query"

        fun startSearch(context: Context, query: String): Boolean {
            val normalized = query.trim()
            if (normalized.isBlank()) return false
            val opened = openDiary(context) || launchMyFitnessPalPackage(context)
            if (!opened) return false
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .edit()
                .putString(KEY_PENDING_QUERY, normalized)
                .apply()
            return true
        }

        fun openDiary(context: Context): Boolean =
            launchMyFitnessPalDeepLink(context, "mfp://mfp/diary")

        fun openBarcodeScanner(context: Context): Boolean =
            launchMyFitnessPalDeepLink(context, "mfp://mfp/barcode_scanner") ||
                launchMyFitnessPalDeepLink(context, "mfp://mfp/diary/add/barcode")

        fun settingsIntent(): Intent =
            Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

        private fun pendingQuery(context: Context): String? =
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .getString(KEY_PENDING_QUERY, null)
                ?.takeIf { it.isNotBlank() }

        private fun clearPendingQuery(context: Context) {
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                .edit()
                .remove(KEY_PENDING_QUERY)
                .apply()
        }

        private fun launchMyFitnessPalDeepLink(context: Context, uri: String): Boolean {
            val intent = Intent(Intent.ACTION_VIEW, Uri.parse(uri))
                    .setPackage(MYFITNESSPAL_PACKAGE)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            return if (intent.resolveActivity(context.packageManager) == null) {
                false
            } else {
                context.startActivity(intent)
                true
            }
        }

        private fun launchMyFitnessPalPackage(context: Context): Boolean {
            val intent = context.packageManager.getLaunchIntentForPackage(MYFITNESSPAL_PACKAGE)
                ?.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                ?: return false
            context.startActivity(intent)
            return true
        }
    }
}

package org.bolusai.companion.portal

import android.content.Context
import android.content.Intent
import android.net.Uri

class PortalLauncher(private val context: Context) {
    fun open(url: String) {
        val normalizedUrl = normalizeHttps(url)
        // Phase 1 portal priority: TWA-capable browser/default browser first, then Custom Tabs-capable
        // browser behavior via ACTION_VIEW, with any future hardened WebView kept as a last resort only.
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(normalizedUrl)).apply {
            addCategory(Intent.CATEGORY_BROWSABLE)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
    }

    private fun normalizeHttps(url: String): String {
        val trimmed = url.trim()
        return if (trimmed.startsWith("https://")) trimmed else "https://$trimmed"
    }
}

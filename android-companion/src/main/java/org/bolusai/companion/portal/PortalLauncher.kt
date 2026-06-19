package org.bolusai.companion.portal

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.browser.customtabs.CustomTabsClient
import androidx.browser.customtabs.CustomTabsIntent

class PortalLauncher(private val context: Context) {
    fun open(url: String) {
        val normalizedUrl = normalizeHttps(url)
        val uri = Uri.parse(normalizedUrl)
        if (openInChrome(uri)) return

        val customTabsPackage = customTabsPackage()
        if (customTabsPackage != null) {
            CustomTabsIntent.Builder()
                .setShowTitle(true)
                .setUrlBarHidingEnabled(false)
                .build()
                .also { customTabs ->
                    customTabs.intent.setPackage(customTabsPackage)
                    customTabs.intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    customTabs.launchUrl(context, uri)
                }
            return
        }

        val intent = Intent(Intent.ACTION_VIEW, uri).apply {
            addCategory(Intent.CATEGORY_BROWSABLE)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
    }

    private fun openInChrome(uri: Uri): Boolean = runCatching {
        val intent = Intent(Intent.ACTION_VIEW, uri).apply {
            setPackage(CHROME_PACKAGE)
            addCategory(Intent.CATEGORY_BROWSABLE)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
        true
    }.getOrDefault(false)

    private fun customTabsPackage(): String? {
        val preferredPackages = listOf(
            CHROME_PACKAGE,
            "com.chrome.beta",
            "com.chrome.dev",
            "com.microsoft.emmx",
        )
        val availablePackages = CustomTabsClient.getPackageName(context, preferredPackages)
        return availablePackages ?: CustomTabsClient.getPackageName(context, null)
    }

    private fun normalizeHttps(url: String): String {
        val trimmed = url.trim()
        return if (trimmed.startsWith("https://")) trimmed else "https://$trimmed"
    }

    private companion object {
        const val CHROME_PACKAGE = "com.android.chrome"
    }
}

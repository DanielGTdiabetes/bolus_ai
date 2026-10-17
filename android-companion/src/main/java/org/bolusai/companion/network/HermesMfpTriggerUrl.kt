package org.bolusai.companion.network

import java.net.URI

/** Validates a base URL; the existing client appends /mfp/sync-now when requested. */
fun normalizeHermesMfpTriggerBaseUrl(value: String): String? {
    val candidate = value.trim()
    val uri = runCatching { URI(candidate) }.getOrNull() ?: return null
    if (!uri.scheme.equals("http", ignoreCase = true) && !uri.scheme.equals("https", ignoreCase = true)) return null
    if (uri.host.isNullOrBlank() || uri.rawUserInfo != null || uri.rawQuery != null || uri.rawFragment != null) return null
    if (uri.port != -1 && uri.port !in 1..65535) return null
    if (uri.rawAuthority.endsWith(":")) return null
    if (uri.path.orEmpty().trimEnd('/').endsWith("/mfp/sync-now")) return null
    return candidate.trimEnd('/')
}

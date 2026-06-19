package org.bolusai.companion.diagnostics

object Sanitizer {
    private val sensitivePatterns = listOf(
        Regex("(?i)(authorization\\s*[:=]\\s*Bearer\\s+)[^\\s,;}\"]+"),
        Regex("(?i)Bearer\\s+[A-Za-z0-9._~+/=-]+"),
        Regex("(?i)(x-ingest-key|authorization|cookie|jwt|token|api[_-]?key|secret)\\s*[:=]\\s*[^\\s,;}\"]+"),
        Regex("(?i)sk-[A-Za-z0-9_-]{12,}"),
    )

    fun sanitize(value: String?, maxLength: Int = 1_000): String {
        if (value.isNullOrBlank()) return ""
        return sensitivePatterns
            .fold(value.take(maxLength)) { current, pattern -> pattern.replace(current) { match ->
                val separator = when {
                    ":" in match.value -> ": "
                    "=" in match.value -> "="
                    else -> " "
                }
                match.value.substringBefore(separator.trim()).trim() + separator + "[redacted]"
            } }
            .replace(Regex("[\\r\\n\\t]+"), " ")
            .trim()
    }
}

package org.bolusai.companion.diagnostics

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SanitizerTest {
    @Test
    fun removesSensitiveValuesFromLogs() {
        val sanitized = Sanitizer.sanitize(
            "Authorization: Bearer abc.def.ghi X-Ingest-Key: secret-token jwt=raw-token token=abc123",
        )

        assertTrue(sanitized.contains("[redacted]"))
        assertFalse(sanitized.contains("secret-token"))
        assertFalse(sanitized.contains("raw-token"))
        assertFalse(sanitized.contains("abc.def.ghi"))
    }
}

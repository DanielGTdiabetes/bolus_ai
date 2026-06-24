package org.bolusai.companion.usage

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ForegroundEventInterpreterTest {
    @Test
    fun internalMyFitnessPalTransitionsDoNotCountAsExit() {
        val transitions = listOf(
            ForegroundTransition(MYFITNESSPAL),
            ForegroundTransition(MYFITNESSPAL),
            ForegroundTransition(MYFITNESSPAL),
        )

        assertEquals(MYFITNESSPAL, ForegroundEventInterpreter.currentForegroundPackage(transitions))
        assertFalse(ForegroundEventInterpreter.observedExitSince(MYFITNESSPAL, transitions, EXIT_PACKAGES))
    }

    @Test
    fun anotherForegroundAppAfterMyFitnessPalCountsAsExit() {
        val transitions = listOf(
            ForegroundTransition(MYFITNESSPAL),
            ForegroundTransition(SAMSUNG_LAUNCHER),
        )

        assertEquals(SAMSUNG_LAUNCHER, ForegroundEventInterpreter.currentForegroundPackage(transitions))
        assertTrue(ForegroundEventInterpreter.observedExitSince(MYFITNESSPAL, transitions, EXIT_PACKAGES))
    }

    @Test
    fun foregroundBeforeMyFitnessPalDoesNotCountAsExit() {
        val transitions = listOf(
            ForegroundTransition(SAMSUNG_LAUNCHER),
            ForegroundTransition(MYFITNESSPAL),
        )

        assertEquals(MYFITNESSPAL, ForegroundEventInterpreter.currentForegroundPackage(transitions))
        assertFalse(ForegroundEventInterpreter.observedExitSince(MYFITNESSPAL, transitions, EXIT_PACKAGES))
    }

    @Test
    fun nonExitAppAfterMyFitnessPalDoesNotCountAsExit() {
        val transitions = listOf(
            ForegroundTransition(MYFITNESSPAL),
            ForegroundTransition("com.android.chrome"),
        )

        assertEquals("com.android.chrome", ForegroundEventInterpreter.currentForegroundPackage(transitions))
        assertFalse(ForegroundEventInterpreter.observedExitSince(MYFITNESSPAL, transitions, EXIT_PACKAGES))
    }

    private companion object {
        const val MYFITNESSPAL = "com.myfitnesspal.android"
        const val SAMSUNG_LAUNCHER = "com.sec.android.app.launcher"
        val EXIT_PACKAGES = setOf(SAMSUNG_LAUNCHER, "org.bolusai.companion")
    }
}

package org.bolusai.companion.portal

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PortalDestinationTest {
    @Test
    fun buildsHashRouteWithoutLosingServerPath() {
        assertEquals(
            "https://bolus-ai.example/#/scan",
            buildPortalUrl("https://bolus-ai.example/", "#/scan"),
        )
    }

    @Test
    fun exposesEveryPrimaryFrontendArea() {
        val routes = portalDestinations.map { it.route }.toSet()
        assertTrue(
            routes.containsAll(
                setOf(
                    "#/",
                    "#/scan",
                    "#/bolus",
                    "#/basal",
                    "#/history",
                    "#/restaurant",
                    "#/scale",
                    "#/learning",
                    "#/suggestions",
                    "#/profile",
                    "#/settings",
                ),
            ),
        )
    }
}

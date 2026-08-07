package org.bolusai.companion.security

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.runBlocking
import org.bolusai.companion.data.AppSettingsRepository
import org.bolusai.companion.dexcom.GlucoseQueueRepository
import org.bolusai.companion.network.GlucoseIngestClient
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class DeviceConfigurationTest {
    @Test
    fun storesIngestKeyFromInstrumentationArgument() {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val ingestKey = InstrumentationRegistry.getArguments().getString("ingestKey").orEmpty()
        assertTrue("Missing ingestKey instrumentation argument", ingestKey.isNotBlank())

        SecretStore(instrumentation.targetContext).writeIngestKey(ingestKey)

        assertTrue(SecretStore(instrumentation.targetContext).readIngestKey().isNotBlank())
    }

    @Test
    fun reportsQueuedGlucoseDeliveryResult() = runBlocking {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val settings = AppSettingsRepository(context).current()
        val reading = GlucoseQueueRepository(context).pending().first()
        val result = GlucoseIngestClient().send(
            settings.primaryUrl,
            settings.backupUrl,
            settings.ingestKey,
            reading,
        )
        println(
            "GLUCOSE_DELIVERY ok=${result.ok} endpoint=${result.endpoint} " +
                "status=${result.statusCode} body=${result.body}",
        )
        assertTrue("Glucose delivery failed: ${result.body}", result.ok)
    }

    @Test
    fun enablesMyFitnessPalAutomation() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val repository = AppSettingsRepository(context)
        repository.setNutritionSyncEnabled(true)
        Thread.sleep(500)
        assertTrue(AppSettingsRepository(context).current().nutritionSyncEnabled)
    }
}

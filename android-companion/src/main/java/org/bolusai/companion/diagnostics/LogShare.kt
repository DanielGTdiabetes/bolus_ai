package org.bolusai.companion.diagnostics

import android.content.Context
import android.content.Intent

class LogShare(private val context: Context) {
    fun shareText(content: String, mimeType: String) {
        val intent = Intent(Intent.ACTION_SEND).apply {
            type = mimeType
            putExtra(Intent.EXTRA_TEXT, content)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(Intent.createChooser(intent, "Exportar logs Health Connect").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }
}

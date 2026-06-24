package org.bolusai.companion.portal

import android.annotation.SuppressLint
import android.content.Intent
import android.net.Uri
import android.webkit.CookieManager
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.viewinterop.AndroidView
import org.bolusai.companion.data.AppSettings
import org.bolusai.companion.network.ActiveEndpoint
import org.bolusai.companion.network.ServerStatusClient

@SuppressLint("SetJavaScriptEnabled")
@Composable
fun InAppPortal(
    settings: AppSettings,
    route: String,
    modifier: Modifier = Modifier,
) {
    var resolvedUrl by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var webView by remember { mutableStateOf<WebView?>(null) }
    var canGoBack by remember { mutableStateOf(false) }
    var fileCallback by remember { mutableStateOf<ValueCallback<Array<Uri>>?>(null) }
    val allowedHosts = remember(settings.primaryUrl, settings.backupUrl) {
        setOfNotNull(
            Uri.parse(settings.primaryUrl).host,
            Uri.parse(settings.backupUrl).host,
        )
    }
    val filePicker = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        val callback = fileCallback
        fileCallback = null
        callback?.onReceiveValue(
            WebChromeClient.FileChooserParams.parseResult(result.resultCode, result.data),
        )
    }

    LaunchedEffect(settings.primaryUrl, settings.backupUrl, route) {
        error = null
        val status = ServerStatusClient().resolve(settings.primaryUrl, settings.backupUrl)
        val baseUrl = when (status.activeEndpoint) {
            ActiveEndpoint.PRIMARY -> settings.primaryUrl
            ActiveEndpoint.BACKUP -> settings.backupUrl
            ActiveEndpoint.NONE -> null
        }
        if (baseUrl == null) {
            resolvedUrl = null
            error = "NAS y Render no responden."
        } else {
            resolvedUrl = buildPortalUrl(baseUrl, route)
        }
    }

    BackHandler(enabled = canGoBack) {
        webView?.goBack()
    }

    Box(modifier = modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        when {
            error != null -> Text(error.orEmpty(), color = MaterialTheme.colorScheme.error)
            resolvedUrl == null -> CircularProgressIndicator()
            else -> AndroidView(
                modifier = Modifier.fillMaxSize(),
                factory = { context ->
                    WebView(context).apply {
                        CookieManager.getInstance().setAcceptCookie(true)
                        CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)
                        this.settings.javaScriptEnabled = true
                        this.settings.domStorageEnabled = true
                        this.settings.databaseEnabled = true
                        this.settings.mediaPlaybackRequiresUserGesture = false
                        this.settings.allowFileAccess = false
                        this.settings.allowContentAccess = true
                        webViewClient = object : WebViewClient() {
                            override fun shouldOverrideUrlLoading(
                                view: WebView,
                                request: WebResourceRequest,
                            ): Boolean = request.url.host !in allowedHosts

                            override fun onPageFinished(view: WebView, url: String) {
                                canGoBack = view.canGoBack()
                            }
                        }
                        webChromeClient = object : WebChromeClient() {
                            override fun onShowFileChooser(
                                webView: WebView,
                                callback: ValueCallback<Array<Uri>>,
                                params: FileChooserParams,
                            ): Boolean {
                                fileCallback?.onReceiveValue(null)
                                fileCallback = callback
                                val intent = runCatching { params.createIntent() }.getOrElse {
                                    Intent(Intent.ACTION_GET_CONTENT).apply {
                                        addCategory(Intent.CATEGORY_OPENABLE)
                                        type = "image/*"
                                    }
                                }
                                filePicker.launch(intent)
                                return true
                            }
                        }
                        loadUrl(resolvedUrl!!)
                        webView = this
                    }
                },
                update = { view ->
                    if (view.url != resolvedUrl) view.loadUrl(resolvedUrl!!)
                },
            )
        }
    }

    DisposableEffect(Unit) {
        onDispose {
            fileCallback?.onReceiveValue(null)
            fileCallback = null
            webView?.stopLoading()
            webView?.destroy()
            webView = null
        }
    }
}

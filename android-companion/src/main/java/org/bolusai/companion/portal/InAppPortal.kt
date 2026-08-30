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
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
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
import androidx.compose.ui.unit.dp
import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import android.os.Handler
import android.os.Looper
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.bolusai.companion.data.AppSettings
import org.bolusai.companion.network.ActiveEndpoint
import org.bolusai.companion.network.ServerStatusClient
import org.bolusai.companion.scale.ProzisScaleManager
import java.io.File

class AndroidScaleInterface(
    private val scaleManager: ProzisScaleManager,
    private val onConnect: () -> Unit,
) {
    @android.webkit.JavascriptInterface
    fun connectScale() {
        onConnect()
    }

    @android.webkit.JavascriptInterface
    fun disconnectScale() {
        scaleManager.disconnect()
    }

    @android.webkit.JavascriptInterface
    fun tare() {
        scaleManager.tare()
    }
}

class AndroidCompanionInterface(
    private val onOpenMobileHome: () -> Unit,
    private val onOpenDiagnostics: () -> Unit,
    private val onOpenMobileSettings: () -> Unit,
    private val onOpenNativeScale: () -> Unit,
) {
    private val mainHandler = Handler(Looper.getMainLooper())

    private fun dispatch(action: () -> Unit) {
        mainHandler.post(action)
    }

    @android.webkit.JavascriptInterface
    fun openMobileHome() = dispatch(onOpenMobileHome)

    @android.webkit.JavascriptInterface
    fun openDiagnostics() = dispatch(onOpenDiagnostics)

    @android.webkit.JavascriptInterface
    fun openMobileSettings() = dispatch(onOpenMobileSettings)

    @android.webkit.JavascriptInterface
    fun openNativeScale() = dispatch(onOpenNativeScale)
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
fun InAppPortal(
    settings: AppSettings,
    scaleManager: ProzisScaleManager,
    route: String,
    onOpenNativeScale: () -> Unit,
    onOpenMobileHome: () -> Unit,
    onOpenDiagnostics: () -> Unit,
    onOpenMobileSettings: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var resolvedUrl by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var webView by remember { mutableStateOf<WebView?>(null) }
    var canGoBack by remember { mutableStateOf(false) }
    var fileCallback by remember { mutableStateOf<ValueCallback<Array<Uri>>?>(null) }
    var pendingCameraUri by remember { mutableStateOf<Uri?>(null) }
    var resolveAttempt by remember { mutableStateOf(0) }
    var resolving by remember { mutableStateOf(false) }

    val scaleState by scaleManager.state.collectAsState()

    val bluetoothPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { grants ->
        if (grants.values.all { it }) {
            scaleManager.connect()
        }
    }

    fun connectScaleWithPermission() {
        scope.launch {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                val permissions = arrayOf(
                    Manifest.permission.BLUETOOTH_SCAN,
                    Manifest.permission.BLUETOOTH_CONNECT,
                )
                val missing = permissions.filter {
                    ContextCompat.checkSelfPermission(context, it) != PackageManager.PERMISSION_GRANTED
                }
                if (missing.isNotEmpty()) {
                    bluetoothPermissionLauncher.launch(missing.toTypedArray())
                    return@launch
                }
            }
            scaleManager.connect()
        }
    }

    val androidScaleInterface = remember(scaleManager) {
        AndroidScaleInterface(scaleManager) {
            connectScaleWithPermission()
        }
    }
    val androidCompanionInterface = remember(
        onOpenMobileHome,
        onOpenDiagnostics,
        onOpenMobileSettings,
        onOpenNativeScale,
    ) {
        AndroidCompanionInterface(
            onOpenMobileHome = onOpenMobileHome,
            onOpenDiagnostics = onOpenDiagnostics,
            onOpenMobileSettings = onOpenMobileSettings,
            onOpenNativeScale = onOpenNativeScale,
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

    val cameraCapture = rememberLauncherForActivityResult(
        ActivityResultContracts.TakePicture(),
    ) { captured ->
        val callback = fileCallback
        val uri = pendingCameraUri
        fileCallback = null
        pendingCameraUri = null
        callback?.onReceiveValue(if (captured && uri != null) arrayOf(uri) else null)
    }

    val cameraPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { isGranted ->
        val callback = fileCallback
        val uri = pendingCameraUri
        if (isGranted && uri != null) {
            cameraCapture.launch(uri)
        } else {
            fileCallback = null
            pendingCameraUri = null
            callback?.onReceiveValue(null)
        }
    }

    LaunchedEffect(scaleState) {
        webView?.let { view ->
            val json = org.json.JSONObject().apply {
                put("connected", scaleState.connected)
                put("scanning", scaleState.scanning)
                put("connecting", scaleState.connecting)
                put("grams", scaleState.grams)
                put("stable", scaleState.stable)
                put("battery", scaleState.batteryPercent ?: org.json.JSONObject.NULL)
                put("message", scaleState.message)
            }
            val js = "if (window.scaleHandler) { window.scaleHandler($json); }"
            view.evaluateJavascript(js, null)
        }
    }
    val allowedHosts = remember(settings.primaryUrl, settings.backupUrl) {
        setOfNotNull(
            Uri.parse(settings.primaryUrl).host,
            Uri.parse(settings.backupUrl).host,
        )
    }

    LaunchedEffect(settings.primaryUrl, settings.backupUrl, route, resolveAttempt) {
        error = null
        resolving = true
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
        resolving = false
    }

    LaunchedEffect(error) {
        if (error == null) return@LaunchedEffect
        delay(12_000)
        resolveAttempt += 1
    }

    BackHandler(enabled = canGoBack) {
        webView?.goBack()
    }

    Box(modifier = modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        when {
            resolving -> Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                modifier = Modifier.padding(24.dp),
            ) {
                CircularProgressIndicator()
                Spacer(Modifier.height(12.dp))
                Text("Conectando con Bolus AI", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(4.dp))
                Text(
                    "Buscando NAS o Render...",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
            error != null -> Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                modifier = Modifier.padding(28.dp),
            ) {
                Text("Bolus AI no responde", style = MaterialTheme.typography.titleMedium)
                Spacer(Modifier.height(6.dp))
                Text(
                    "La app volverá a comprobar la conexión automáticamente.",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
                Spacer(Modifier.height(16.dp))
                Button(onClick = { resolveAttempt += 1 }, modifier = Modifier.width(220.dp)) {
                    Text("Comprobar ahora")
                }
            }
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
                        this.settings.useWideViewPort = true
                        this.settings.loadWithOverviewMode = true
                        this.settings.textZoom = 100
                        this.settings.setSupportZoom(false)
                        this.settings.builtInZoomControls = false
                        this.settings.displayZoomControls = false
                        this.settings.mediaPlaybackRequiresUserGesture = false
                        this.settings.allowFileAccess = false
                        this.settings.allowContentAccess = true
                        addJavascriptInterface(androidScaleInterface, "AndroidScaleInterface")
                        addJavascriptInterface(androidCompanionInterface, "AndroidCompanionInterface")
                        webViewClient = object : WebViewClient() {
                            override fun shouldOverrideUrlLoading(
                                view: WebView,
                                request: WebResourceRequest,
                            ): Boolean {
                                val url = request.url
                                if (url.host in allowedHosts) return false
                                return openExternalUrl(context, url)
                            }

                            override fun onPageFinished(view: WebView, url: String) {
                                canGoBack = view.canGoBack()
                                view.setInitialScale(0)
                                view.evaluateJavascript(
                                    """
                                    (() => {
                                      let viewport = document.querySelector('meta[name="viewport"]');
                                      if (!viewport) {
                                        viewport = document.createElement('meta');
                                        viewport.name = 'viewport';
                                        document.head.appendChild(viewport);
                                      }
                                      viewport.content = 'width=device-width, initial-scale=1';
                                      document.documentElement.style.maxWidth = '100%';
                                      document.documentElement.style.overflowX = 'hidden';
                                      document.body.style.maxWidth = '100%';
                                      document.body.style.overflowX = 'hidden';
                                    })();
                                    """.trimIndent(),
                                    null,
                                )
                                val json = org.json.JSONObject().apply {
                                    put("connected", scaleState.connected)
                                    put("scanning", scaleState.scanning)
                                    put("connecting", scaleState.connecting)
                                    put("grams", scaleState.grams)
                                    put("stable", scaleState.stable)
                                    put("battery", scaleState.batteryPercent ?: org.json.JSONObject.NULL)
                                    put("message", scaleState.message)
                                }
                                view.evaluateJavascript("if (window.scaleHandler) { window.scaleHandler($json); }", null)
                            }

                            override fun doUpdateVisitedHistory(
                                view: WebView,
                                url: String,
                                isReload: Boolean,
                            ) {
                                if (Uri.parse(url).fragment == "/scale") {
                                    onOpenNativeScale()
                                    return
                                }
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
                                val requestsImageCapture = params.isCaptureEnabled &&
                                    params.acceptTypes.any { type ->
                                        type.isBlank() || type.startsWith("image/", ignoreCase = true)
                                    }

                                if (requestsImageCapture) {
                                    val uri = createCameraOutputUri(context)
                                    pendingCameraUri = uri
                                    val hasCameraPermission = ContextCompat.checkSelfPermission(
                                        context,
                                        Manifest.permission.CAMERA,
                                    ) == PackageManager.PERMISSION_GRANTED
                                    if (hasCameraPermission) {
                                        cameraCapture.launch(uri)
                                    } else {
                                        cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
                                    }
                                    return true
                                }

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
                        tag = resolvedUrl
                        loadUrl(resolvedUrl!!)
                        webView = this
                    }
                },
                update = { view ->
                    if (view.tag != resolvedUrl) {
                        view.tag = resolvedUrl
                        view.loadUrl(resolvedUrl!!)
                    }
                },
            )
        }
    }

    DisposableEffect(Unit) {
        onDispose {
            fileCallback?.onReceiveValue(null)
            fileCallback = null
            pendingCameraUri = null
            webView?.stopLoading()
            webView?.destroy()
            webView = null
        }
    }
}

private fun createCameraOutputUri(context: android.content.Context): Uri {
    val directory = File(context.cacheDir, "camera").apply { mkdirs() }
    val image = File.createTempFile("bolus_ai_", ".jpg", directory)
    return FileProvider.getUriForFile(
        context,
        "${context.packageName}.fileprovider",
        image,
    )
}

private fun openExternalUrl(context: android.content.Context, uri: Uri): Boolean {
    val scheme = uri.scheme?.lowercase()
    if (scheme != "http" && scheme != "https" && scheme != "mailto" && scheme != "tel") {
        return true
    }
    return runCatching {
        val intent = Intent(Intent.ACTION_VIEW, uri).apply {
            addCategory(Intent.CATEGORY_BROWSABLE)
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
        true
    }.getOrDefault(true)
}

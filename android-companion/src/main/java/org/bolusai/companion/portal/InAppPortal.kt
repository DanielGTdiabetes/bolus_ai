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
import android.Manifest
import android.content.pm.PackageManager
import android.os.Build
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import kotlinx.coroutines.launch
import org.bolusai.companion.data.AppSettings
import org.bolusai.companion.network.ActiveEndpoint
import org.bolusai.companion.network.ServerStatusClient
import org.bolusai.companion.scale.ProzisScaleManager

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

@SuppressLint("SetJavaScriptEnabled")
@Composable
fun InAppPortal(
    settings: AppSettings,
    scaleManager: ProzisScaleManager,
    route: String,
    onOpenNativeScale: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var resolvedUrl by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var webView by remember { mutableStateOf<WebView?>(null) }
    var canGoBack by remember { mutableStateOf(false) }
    var fileCallback by remember { mutableStateOf<ValueCallback<Array<Uri>>?>(null) }
    var pendingIntent by remember { mutableStateOf<Intent?>(null) }

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

    val filePicker = rememberLauncherForActivityResult(
        ActivityResultContracts.StartActivityForResult(),
    ) { result ->
        val callback = fileCallback
        fileCallback = null
        callback?.onReceiveValue(
            WebChromeClient.FileChooserParams.parseResult(result.resultCode, result.data),
        )
    }

    val cameraPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { isGranted ->
        val callback = fileCallback
        val intent = pendingIntent
        fileCallback = null
        pendingIntent = null
        if (isGranted && intent != null) {
            fileCallback = callback
            filePicker.launch(intent)
        } else {
            callback?.onReceiveValue(null)
        }
    }

    LaunchedEffect(scaleState) {
        webView?.let { view ->
            val json = org.json.JSONObject().apply {
                put("connected", scaleState.connected)
                put("grams", scaleState.grams)
                put("stable", scaleState.stable)
                put("battery", scaleState.batteryPercent ?: org.json.JSONObject.NULL)
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
                        addJavascriptInterface(androidScaleInterface, "AndroidScaleInterface")
                        webViewClient = object : WebViewClient() {
                            override fun shouldOverrideUrlLoading(
                                view: WebView,
                                request: WebResourceRequest,
                            ): Boolean = request.url.host !in allowedHosts

                            override fun onPageFinished(view: WebView, url: String) {
                                canGoBack = view.canGoBack()
                                val json = org.json.JSONObject().apply {
                                    put("connected", scaleState.connected)
                                    put("grams", scaleState.grams)
                                    put("stable", scaleState.stable)
                                    put("battery", scaleState.batteryPercent ?: org.json.JSONObject.NULL)
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
                                val intent = runCatching { params.createIntent() }.getOrElse {
                                    Intent(Intent.ACTION_GET_CONTENT).apply {
                                        addCategory(Intent.CATEGORY_OPENABLE)
                                        type = "image/*"
                                    }
                                }
                                val isCamera = intent.action == android.provider.MediaStore.ACTION_IMAGE_CAPTURE ||
                                        (intent.action == Intent.ACTION_CHOOSER &&
                                                intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)?.action == android.provider.MediaStore.ACTION_IMAGE_CAPTURE)
                                                
                                val hasCameraPermission = ContextCompat.checkSelfPermission(
                                    context,
                                    Manifest.permission.CAMERA
                                ) == PackageManager.PERMISSION_GRANTED
                                
                                if (isCamera && !hasCameraPermission) {
                                    pendingIntent = intent
                                    cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
                                } else {
                                    filePicker.launch(intent)
                                }
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

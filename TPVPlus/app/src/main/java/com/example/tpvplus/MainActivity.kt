package com.example.tpvplus

import android.annotation.SuppressLint
import android.app.PendingIntent
import android.content.Intent
import android.content.IntentFilter
import android.graphics.Color
import android.nfc.NfcAdapter
import android.nfc.Tag
import android.nfc.NdefRecord
import android.nfc.tech.Ndef
import android.os.Bundle
import android.view.ViewGroup
import android.webkit.JsResult
import android.webkit.SslErrorHandler
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import android.webkit.CookieManager
import android.widget.FrameLayout
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.text.InputType
import android.os.SystemClock
import android.view.Gravity
import android.view.View
import android.view.WindowManager
import android.widget.Toast
import android.widget.EditText
import android.app.AlertDialog
import android.net.Uri
import android.webkit.JavascriptInterface
import android.content.Context
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
class MainActivity : ComponentActivity() {

    private var webView: WebView? = null
    private var nfcAdapter: NfcAdapter? = null

    // Dirección del servidor de la caja (se configura en el propio dispositivo)
    private var serverUrl: String? = null
    private var rootView: FrameLayout? = null
    private var setupPanel: View? = null
    private var cornerTaps = 0
    private var lastCornerTap = 0L

    // Interfaz para depuración desde JS
    class WebAppInterface(private val mContext: Context) {
        @JavascriptInterface
        fun showToast(toast: String) {
            // Toast oculto visualmente, pero se ejecuta la función
            android.util.Log.d("NFC_Toast", "Toast invisible: $toast")
        }
        @JavascriptInterface
        fun log(msg: String) {
            android.util.Log.d("WebViewJS", msg)
        }
    }

    private companion object {
        private const val BACK_SCRIPT =
            "(function(){try{return !!(window.tpvHandleBack && window.tpvHandleBack());}catch(e){return false;}})()"

        private val NFC_POLYFILL = """
            (function(){
                // El botón atrás nativo consulta primero al POS (window.tpvHandleBack)
                window.__tpvNativeBack = true;

                // Deshabilitar Service Workers si hay problemas de SSL para que Odoo use el modo normal
                if ('serviceWorker' in navigator) {
                    Object.defineProperty(navigator, 'serviceWorker', {
                        get: function () { return undefined; },
                        configurable: false
                    });
                }

                if(window.__nfc_installed) return;
                
                // Polyfill para AbortController (evita fallos en PDAs antiguas)
                if(typeof AbortController === 'undefined') {
                    window.AbortController = function() {
                        this.signal = { 
                            aborted: false,
                            addEventListener: function(t, c) { if(!this._l) this._l={}; this._l[t]=c; },
                            removeEventListener: function(t) { if(this._l) delete this._l[t]; }
                        };
                        this.abort = function() { 
                            this.signal.aborted = true; 
                            if(this.signal._l && this.signal._l.abort) this.signal._l.abort();
                        };
                    };
                }

                var _log = function(m) {
                    console.log("[NFC-App] " + m);
                    if(window.Android && window.Android.log) window.Android.log(m);
                };

                var _setup = function(w) {
                    try {
                        if(!w || w.NDEFReader) return;
                        
                        _log("Instalando Web NFC");
                        
                        var Reader = function() {
                            this._listeners = {};
                        };
                        
                        Reader.prototype.addEventListener = function(t, c) {
                            this._listeners[t] = c;
                        };
                        
                        Reader.prototype.removeEventListener = function(t) {
                            delete this._listeners[t];
                        };
                        
                        Reader.prototype.scan = function() {
                            _log("Scan solicitado");
                            w.__activeReader = this;
                            if(window.Android && window.Android.showToast) window.Android.showToast("NFC: Sensor activado");
                            return Promise.resolve();
                        };
                        
                        Reader.prototype.makeReadOnly = function() { return Promise.reject(); };
                        Reader.prototype.write = function() { return Promise.reject(); };
                        
                        w.NDEFReader = Reader;
                        
                        w.__nfcTriggerRead = function(id) {
                            var r = w.__activeReader;
                            if(r && r._listeners && r._listeners.reading) {
                                r._listeners.reading({
                                    serialNumber: id.toUpperCase(),
                                    message: { records: [] }
                                });
                                return true;
                            }
                            return false;
                        };
                    } catch(e) {
                        _log("Error setup: " + e.message);
                    }
                };

                var _check = function() {
                    _setup(window);
                    try {
                        var iframes = document.getElementsByTagName('iframe');
                        for(var i=0; i<iframes.length; i++) {
                            try { _setup(iframes[i].contentWindow); } catch(err){}
                        }
                    } catch(err){}
                };

                _check();
                setInterval(_check, 3000);
                window.__nfc_installed = true;
            })();
        """.trimIndent()
    }

    @SuppressLint("SetJavaScriptEnabled", "JavascriptInterface")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        serverUrl = ServerConfig.load(this)

        // Depuración remota de WebView solo en builds de depuración
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG)

        nfcAdapter = NfcAdapter.getDefaultAdapter(this)

        val wv = WebView(this).apply {
            // Solo en depuración: forzar descarga de JS frescos en cada arranque
            if (BuildConfig.DEBUG) clearCache(true)

            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
            // Forzar User Agent de Chrome moderno para evitar bloqueos de Odoo
            val chromeUA = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
            settings.userAgentString = chromeUA

            settings.javaScriptEnabled = true
            settings.domStorageEnabled = true
            settings.javaScriptCanOpenWindowsAutomatically = true
            settings.loadWithOverviewMode = true
            settings.useWideViewPort = true
            settings.setSupportZoom(true)
            settings.builtInZoomControls = true
            settings.displayZoomControls = false
            settings.allowFileAccess = false
            settings.allowContentAccess = false
            settings.mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW
            settings.databaseEnabled = true
            settings.setGeolocationEnabled(true)
            settings.mediaPlaybackRequiresUserGesture = false
            settings.cacheMode = android.webkit.WebSettings.LOAD_DEFAULT

            // Asegurar que las cookies estén habilitadas para Odoo
            val cookieManager = CookieManager.getInstance()
            cookieManager.setAcceptCookie(true)
            cookieManager.setAcceptThirdPartyCookies(this, true)

            addJavascriptInterface(WebAppInterface(this@MainActivity), "Android")

            webViewClient = object : WebViewClient() {
                // Solo se navega dentro del dominio del TPV; el resto se abre fuera de la app
                override fun shouldOverrideUrlLoading(
                    view: WebView?,
                    request: android.webkit.WebResourceRequest?
                ): Boolean {
                    val uri = request?.url ?: return false
                    if (isTpvHost(uri.host)) return false
                    try {
                        startActivity(Intent(Intent.ACTION_VIEW, uri))
                    } catch (e: Exception) {
                        android.util.Log.w("WebViewNav", "No se pudo abrir $uri", e)
                    }
                    return true
                }

                override fun onPageStarted(view: WebView?, url: String?, favicon: android.graphics.Bitmap?) {
                    super.onPageStarted(view, url, favicon)
                    view?.evaluateJavascript(NFC_POLYFILL, null)
                }

                override fun onPageFinished(view: WebView?, url: String?) {
                    super.onPageFinished(view, url)
                    view?.evaluateJavascript(NFC_POLYFILL, null)

                    val isTpv = isTpvHost(url?.let { Uri.parse(it).host })
                    if (isTpv) {
                        android.util.Log.d("NFC_App", "TPVPlus cargado - NFC activado")
                    }
                }

                override fun onReceivedSslError(
                    view: WebView?,
                    handler: SslErrorHandler?,
                    error: android.net.http.SslError?
                ) {
                    android.util.Log.w("WebViewSSL", "Error SSL detectado: $error")
                    if (BuildConfig.DEBUG) {
                        // Solo en depuración se tolera un certificado no válido
                        handler?.proceed()
                    } else {
                        handler?.cancel()
                        Toast.makeText(
                            this@MainActivity,
                            "Conexión no segura bloqueada (certificado SSL no válido)",
                            Toast.LENGTH_LONG
                        ).show()
                    }
                }

                override fun onReceivedError(
                    view: WebView?,
                    request: android.webkit.WebResourceRequest?,
                    error: android.webkit.WebResourceError?
                ) {
                    val url = request?.url?.toString() ?: "desconocida"
                    val desc = error?.description ?: "sin descripción"
                    android.util.Log.e("WebViewError", "Error cargando recurso: $url - Error: $desc")
                    if (request?.isForMainFrame == true) {
                        showSetup("No se pudo conectar con ${serverUrl ?: url}.\nRevisa la dirección y que estés en la misma Wi-Fi que el servidor.")
                    }
                }

                override fun onReceivedHttpError(
                    view: WebView?,
                    request: android.webkit.WebResourceRequest?,
                    errorResponse: android.webkit.WebResourceResponse?
                ) {
                    val url = request?.url?.toString() ?: "desconocida"
                    val status = errorResponse?.statusCode ?: 0
                    android.util.Log.e("WebViewError", "Error HTTP: $url - Código: $status")
                }
            }

            webChromeClient = object : WebChromeClient() {
                override fun onConsoleMessage(consoleMessage: android.webkit.ConsoleMessage?): Boolean {
                    val msg = consoleMessage?.message() ?: return false
                    val source = consoleMessage.sourceId() ?: "unknown"
                    val line = consoleMessage.lineNumber()
                    android.util.Log.d("WebViewJS", "[$source:$line] $msg")
                    return true
                }

                override fun onJsAlert(
                    view: WebView?,
                    url: String?,
                    message: String?,
                    result: JsResult?
                ): Boolean {
                    AlertDialog.Builder(this@MainActivity)
                        .setMessage(message)
                        .setPositiveButton(android.R.string.ok) { _, _ -> result?.confirm() }
                        .setOnCancelListener { result?.cancel() }
                        .show()
                    return true
                }

                override fun onJsConfirm(
                    view: WebView?,
                    url: String?,
                    message: String?,
                    result: JsResult?
                ): Boolean {
                    AlertDialog.Builder(this@MainActivity)
                        .setMessage(message)
                        .setPositiveButton(android.R.string.ok) { _, _ -> result?.confirm() }
                        .setNegativeButton(android.R.string.cancel) { _, _ -> result?.cancel() }
                        .setOnCancelListener { result?.cancel() }
                        .show()
                    return true
                }

                override fun onJsPrompt(
                    view: WebView?,
                    url: String?,
                    message: String?,
                    defaultValue: String?,
                    result: android.webkit.JsPromptResult?
                ): Boolean {
                    val input = EditText(this@MainActivity).apply { setText(defaultValue ?: "") }
                    AlertDialog.Builder(this@MainActivity)
                        .setMessage(message)
                        .setView(input)
                        .setPositiveButton(android.R.string.ok) { _, _ -> result?.confirm(input.text.toString()) }
                        .setNegativeButton(android.R.string.cancel) { _, _ -> result?.cancel() }
                        .setOnCancelListener { result?.cancel() }
                        .show()
                    return true
                }
            }
        }

        val root = FrameLayout(this).apply {
            setBackgroundColor(Color.WHITE)
            addView(wv)
        }
        rootView = root

        // Esquina superior derecha invisible: 5 toques seguidos abren la configuración del servidor
        val density = resources.displayMetrics.density
        val corner = View(this).apply {
            layoutParams = FrameLayout.LayoutParams(
                (72 * density).toInt(), (72 * density).toInt(), Gravity.TOP or Gravity.END
            )
            setOnClickListener {
                val now = SystemClock.elapsedRealtime()
                cornerTaps = if (now - lastCornerTap < 1500) cornerTaps + 1 else 1
                lastCornerTap = now
                if (cornerTaps >= 5) {
                    cornerTaps = 0
                    showSetup()
                }
            }
        }
        root.addView(corner)

        ViewCompat.setOnApplyWindowInsetsListener(root) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }

        setContentView(root)

        webView = wv
        val saved = serverUrl
        if (saved == null) showSetup() else wv.loadUrl(saved)

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (setupPanel != null) {
                    if (serverUrl != null) hideSetup()
                    return
                }
                val wv = webView
                if (wv == null) {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                    return
                }
                // Primero el POS: si hay un modal o wizard abierto lo cierra y consume el atrás
                wv.evaluateJavascript(BACK_SCRIPT) { result ->
                    if (result == "true") return@evaluateJavascript
                    if (wv.canGoBack()) {
                        wv.goBack()
                    } else {
                        isEnabled = false
                        onBackPressedDispatcher.onBackPressed()
                    }
                }
            }
        })
    }

    override fun onResume() {
        super.onResume()
        nfcAdapter?.let { adapter ->
            if (!adapter.isEnabled) {
                android.util.Log.w("NFC_App", "NFC desactivado en el dispositivo")
            }
            val pendingIntent = PendingIntent.getActivity(
                this, 0,
                Intent(this, javaClass).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
                PendingIntent.FLAG_MUTABLE
            )

            val ndefFilter = IntentFilter(NfcAdapter.ACTION_NDEF_DISCOVERED).apply {
                try {
                    addDataType("text/plain")
                } catch (e: Exception) { }
            }
            val filters = arrayOf(ndefFilter, IntentFilter(NfcAdapter.ACTION_TAG_DISCOVERED))
            val techList = arrayOf(arrayOf(Ndef::class.java.name))

            adapter.enableForegroundDispatch(this, pendingIntent, filters, techList)
        }
    }

    override fun onPause() {
        super.onPause()
        nfcAdapter?.disableForegroundDispatch(this)
    }

    /** Solo se navega y se entregan tarjetas NFC a páginas del servidor configurado. */
    private fun isTpvHost(host: String?): Boolean =
        host != null && host.equals(ServerConfig.hostOf(serverUrl), ignoreCase = true)

    private fun hideSetup() {
        setupPanel?.let { rootView?.removeView(it) }
        setupPanel = null
    }

    /** Pantalla para escribir la IP del servidor; también sirve de "Reintentar" si falla la conexión. */
    private fun showSetup(message: String? = null) {
        val root = rootView ?: return
        hideSetup()
        val d = resources.displayMetrics.density
        fun px(v: Int) = (v * d).toInt()

        val title = TextView(this).apply {
            text = "Servidor de la caja"
            textSize = 28f
            setTextColor(Color.BLACK)
        }
        val help = TextView(this).apply {
            text = "Escribe la IP del servidor Odoo y su puerto si lo tiene, por ejemplo 192.168.0.113:8080. " +
                "La caja se abrirá dentro de esta app."
            textSize = 16f
            setTextColor(Color.DKGRAY)
            setPadding(0, px(8), 0, px(16))
        }
        val input = EditText(this).apply {
            setText(serverUrl ?: "")
            hint = "192.168.0.113:8080"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setSingleLine(true)
            textSize = 22f
        }
        val error = TextView(this).apply {
            text = message ?: ""
            textSize = 16f
            setTextColor(Color.rgb(179, 38, 30))
            setPadding(0, px(12), 0, 0)
            visibility = if (message.isNullOrEmpty()) View.GONE else View.VISIBLE
        }
        val connect = Button(this).apply {
            text = "Conectar"
            textSize = 20f
            setOnClickListener {
                val url = ServerConfig.normalize(input.text.toString())
                if (url == null) {
                    error.text = "Dirección no válida. Ejemplo: 192.168.0.113:8080"
                    error.visibility = View.VISIBLE
                    return@setOnClickListener
                }
                ServerConfig.save(this@MainActivity, url)
                serverUrl = url
                hideSetup()
                webView?.apply {
                    clearHistory()
                    loadUrl(url)
                }
            }
        }
        val retry = Button(this).apply {
            text = "Reintentar"
            textSize = 18f
            visibility = if (serverUrl != null && !message.isNullOrEmpty()) View.VISIBLE else View.GONE
            setOnClickListener {
                hideSetup()
                serverUrl?.let { webView?.loadUrl(it) }
            }
        }
        val cancel = Button(this).apply {
            text = "Cancelar"
            textSize = 18f
            visibility = if (serverUrl != null && message.isNullOrEmpty()) View.VISIBLE else View.GONE
            setOnClickListener { hideSetup() }
        }

        val panel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_VERTICAL
            setBackgroundColor(Color.WHITE)
            setPadding(px(24), px(24), px(24), px(24))
            isClickable = true // que los toques no lleguen a la página de detrás
            addView(title)
            addView(help)
            addView(input)
            addView(error)
            addView(connect)
            addView(retry)
            addView(cancel)
        }
        root.addView(panel, FrameLayout.LayoutParams(
            FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT
        ))
        setupPanel = panel
        input.requestFocus()
    }

    private fun decodeTextRecord(payload: ByteArray): String? {
        if (payload.isEmpty()) return null
        val status = payload[0].toInt()
        val languageCodeLength = status and 0x3F
        val isUtf16 = (status and 0x80) != 0
        val textEncoding = if (isUtf16) Charsets.UTF_16 else Charsets.UTF_8
        if (payload.size <= languageCodeLength + 1) return null
        return payload.copyOfRange(languageCodeLength + 1, payload.size).toString(textEncoding)
    }

    @Suppress("DEPRECATION")
    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        when (intent.action) {
            NfcAdapter.ACTION_TAG_DISCOVERED,
            NfcAdapter.ACTION_TECH_DISCOVERED,
            NfcAdapter.ACTION_NDEF_DISCOVERED -> {
                val tag = intent.getParcelableExtra<Tag>(NfcAdapter.EXTRA_TAG)
                tag?.let {
                    var tagContent = ""
                    val ndef = Ndef.get(it)
                    
                    try {
                        ndef?.let { n ->
                            n.connect()
                            val msg = n.ndefMessage
                            msg?.records?.forEach { record ->
                                if (record.tnf == NdefRecord.TNF_WELL_KNOWN &&
                                    record.type.contentEquals(NdefRecord.RTD_TEXT)
                                ) {
                                    decodeTextRecord(record.payload)?.let { text ->
                                        tagContent = text
                                    }
                                }
                            }
                            n.close()
                        }
                    } catch (e: Exception) {
                        android.util.Log.e("NFC", "Error leyendo NDEF", e)
                    }

                    // Si no hay contenido NDEF (texto), volvemos al ID como fallback
                    if (tagContent.isEmpty()) {
                        tagContent = it.id.joinToString("") { byte -> "%02x".format(byte) }
                    }
                    
                    // Toast invisible: quitamos el .show() y usamos Log
                    android.util.Log.i("NFC_Scan", "Tag capturado (invisible): $tagContent")
                    
                    val script = """
                        (function(){
                            var scannedValue = ${org.json.JSONObject.quote(tagContent)};
                            var _t = function(w) {
                                try { 
                                    if(w.__nfcTriggerRead && w.__nfcTriggerRead(scannedValue)) return true;
                                } catch(e){}
                                return false;
                            };
                            var found = _t(window);
                            try {
                                var iframes = document.getElementsByTagName('iframe');
                                for(var i=0; i<iframes.length; i++) {
                                    if(_t(iframes[i].contentWindow)) found = true;
                                }
                            } catch(e){}
                            if(!found && typeof handleNfcScan === 'function') handleNfcScan(scannedValue);
                        })();
                    """.trimIndent()
                    
                    // Solo se entrega el tag si la página cargada es el TPV
                    if (isTpvHost(webView?.url?.let { Uri.parse(it).host })) {
                        webView?.evaluateJavascript(script, null)
                    } else {
                        android.util.Log.w("NFC_Scan", "Tag ignorado: la página actual no es el TPV")
                    }
                }
            }
        }
    }

}

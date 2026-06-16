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
import android.widget.Toast
import android.webkit.JavascriptInterface
import android.content.Context
import androidx.activity.ComponentActivity
import androidx.activity.OnBackPressedCallback
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
class MainActivity : ComponentActivity() {

    private var webView: WebView? = null
    private var nfcAdapter: NfcAdapter? = null

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
        private val NFC_POLYFILL = """
            (function(){
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

        // Habilitar depuración remota de WebView si el dispositivo está en modo depuración
        WebView.setWebContentsDebuggingEnabled(true)

        nfcAdapter = NfcAdapter.getDefaultAdapter(this)

        val wv = WebView(this).apply {
            // Limpiar caché al inicio para asegurar que se descarguen todos los JS frescos
            clearCache(true)

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
            settings.allowFileAccess = true
            settings.allowContentAccess = true
            settings.mixedContentMode = android.webkit.WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
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
                override fun onPageStarted(view: WebView?, url: String?, favicon: android.graphics.Bitmap?) {
                    super.onPageStarted(view, url, favicon)
                    view?.evaluateJavascript(NFC_POLYFILL, null)
                }

                override fun onPageFinished(view: WebView?, url: String?) {
                    super.onPageFinished(view, url)
                    view?.evaluateJavascript(NFC_POLYFILL, null)

                    val isTpv = url?.contains("tpvplus.xtd.es") == true
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
                    // Intentar forzar la confianza en el certificado para esta sesión
                    handler?.proceed()
                }

                override fun onReceivedError(
                    view: WebView?,
                    request: android.webkit.WebResourceRequest?,
                    error: android.webkit.WebResourceError?
                ) {
                    val url = request?.url?.toString() ?: "desconocida"
                    val desc = error?.description ?: "sin descripción"
                    android.util.Log.e("WebViewError", "Error cargando recurso: $url - Error: $desc")
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
                    result?.confirm()
                    return true
                }

                override fun onJsConfirm(
                    view: WebView?,
                    url: String?,
                    message: String?,
                    result: JsResult?
                ): Boolean {
                    result?.confirm()
                    return true
                }

                override fun onJsPrompt(
                    view: WebView?,
                    url: String?,
                    message: String?,
                    defaultValue: String?,
                    result: android.webkit.JsPromptResult?
                ): Boolean {
                    result?.confirm()
                    return true
                }
            }
        }

        val root = FrameLayout(this).apply {
            setBackgroundColor(Color.WHITE)
            addView(wv)
        }

        ViewCompat.setOnApplyWindowInsetsListener(root) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }

        setContentView(root)

        wv.loadUrl("https://tpvplus.xtd.es/")
        webView = wv

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (webView?.canGoBack() == true) {
                    webView?.goBack()
                } else {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
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
                            var scannedValue = '${tagContent.replace("'", "\\'")}';
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
                    
                    webView?.evaluateJavascript(script, null)
                }
            }
        }
    }

}

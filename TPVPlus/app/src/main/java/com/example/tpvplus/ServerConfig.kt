package com.example.tpvplus

import android.content.Context
import java.net.URI

/**
 * Dirección del servidor de la caja de feria, configurada en el propio dispositivo.
 * `normalize` no usa clases de Android para poder probarse con JUnit en el PC.
 */
object ServerConfig {
    private const val PREFS = "tpvplus_server"
    private const val KEY_URL = "url"

    /** Ruta de la pantalla de caja en el servidor Odoo (módulo feria_saldo). */
    const val DEFAULT_PATH = "/feria"

    /**
     * Convierte lo que escribe la persona en una URL completa, o null si no es válida.
     *  - "192.168.0.113:8080"            -> "http://192.168.0.113:8080/feria"
     *  - "https://caja.local"            -> "https://caja.local/feria"
     *  - "http://10.0.0.5:8069/otra/ruta" -> se respeta la ruta indicada
     */
    fun normalize(input: String?): String? {
        val text = input?.trim().orEmpty()
        if (text.isEmpty() || text.any { it.isWhitespace() }) return null
        val withScheme = if (text.contains("://")) text else "http://$text"
        val uri = try {
            URI(withScheme)
        } catch (e: Exception) {
            return null
        }
        val scheme = uri.scheme?.lowercase()
        if (scheme != "http" && scheme != "https") return null
        val host = uri.host
        if (host.isNullOrBlank()) return null
        if (uri.port != -1 && uri.port !in 1..65535) return null
        val port = if (uri.port == -1) "" else ":${uri.port}"
        val path = uri.rawPath.orEmpty().trimEnd('/').ifEmpty { DEFAULT_PATH }
        return "$scheme://$host$port$path"
    }

    /** Host de una URL ya normalizada (para decidir a qué páginas se entrega una tarjeta). */
    fun hostOf(url: String?): String? = try {
        url?.let { URI(it).host }
    } catch (e: Exception) {
        null
    }

    fun load(context: Context): String? =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY_URL, null)

    fun save(context: Context, url: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY_URL, url).apply()
    }
}

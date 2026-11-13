package com.example.tpvplus

/**
 * Identificador que la app entrega a la página al leer una tarjeta o pulsera.
 * Sin clases de Android para poder probarse con JUnit en el PC.
 */
object NfcCodes {
    /** UID del chip en hexadecimal minúsculas y sin separadores: 29 A2 4D 3E -> "29a24d3e". */
    fun uidHex(id: ByteArray): String = id.joinToString("") { byte -> "%02x".format(byte.toInt() and 0xFF) }
}

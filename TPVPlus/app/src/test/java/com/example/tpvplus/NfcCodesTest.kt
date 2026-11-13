package com.example.tpvplus

import org.junit.Assert.assertEquals
import org.junit.Test

class NfcCodesTest {

    @Test
    fun uidIsLowercaseHexWithoutSeparators() {
        val uid = byteArrayOf(0x29, 0xA2.toByte(), 0x4D, 0x3E)
        assertEquals("29a24d3e", NfcCodes.uidHex(uid))
    }

    @Test
    fun negativeBytesAndLeadingZerosKeepTwoDigits() {
        assertEquals("00ff0a80", NfcCodes.uidHex(byteArrayOf(0x00, 0xFF.toByte(), 0x0A, 0x80.toByte())))
    }

    @Test
    fun sevenByteUid() {
        val uid = byteArrayOf(0x04, 0xA3.toByte(), 0x1F, 0x22, 0x5B, 0x6C, 0x80.toByte())
        assertEquals("04a31f225b6c80", NfcCodes.uidHex(uid))
    }

    @Test
    fun emptyUid() {
        assertEquals("", NfcCodes.uidHex(byteArrayOf()))
    }
}

package com.example.tpvplus

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ServerConfigTest {

    @Test
    fun addsSchemeAndKioskPath() {
        assertEquals("http://192.168.0.113:8080/feria", ServerConfig.normalize("192.168.0.113:8080"))
        assertEquals("http://192.168.0.113/feria", ServerConfig.normalize("192.168.0.113"))
        assertEquals("https://caja.local/feria", ServerConfig.normalize("https://caja.local"))
    }

    @Test
    fun trimsSpacesAndTrailingSlash() {
        assertEquals("http://10.0.0.5:20069/feria", ServerConfig.normalize("  10.0.0.5:20069/  "))
        assertEquals("http://10.0.0.5:8069/feria", ServerConfig.normalize("http://10.0.0.5:8069/feria/"))
    }

    @Test
    fun keepsAnExplicitPath() {
        assertEquals("http://10.0.0.5:8069/otra/ruta", ServerConfig.normalize("http://10.0.0.5:8069/otra/ruta"))
    }

    @Test
    fun dropsQueryAndFragment() {
        assertEquals("http://10.0.0.5:8080/feria", ServerConfig.normalize("10.0.0.5:8080/?a=1#x"))
    }

    @Test
    fun rejectsInvalidInput() {
        assertNull(ServerConfig.normalize(null))
        assertNull(ServerConfig.normalize(""))
        assertNull(ServerConfig.normalize("   "))
        assertNull(ServerConfig.normalize("192.168.0. 113"))
        assertNull(ServerConfig.normalize("ftp://10.0.0.5"))
        assertNull(ServerConfig.normalize("http://"))
        assertNull(ServerConfig.normalize("http://10.0.0.5:99999"))
        assertNull(ServerConfig.normalize(":8080"))
    }

    @Test
    fun hostOfReadsTheHost() {
        assertEquals("192.168.0.113", ServerConfig.hostOf("http://192.168.0.113:8080/feria"))
        assertNull(ServerConfig.hostOf(null))
    }
}

package com.synthwomb.kida01

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

class MjpegParserTest {
    private fun jpegs(bytes: List<Int>): List<ByteArray> {
        val parser = MjpegParser()
        return bytes.mapNotNull { parser.feed(it) }
    }

    @Test fun findsAJpegInsideTheHeaders() {
        val out = jpegs(listOf(0x2D, 0x2D, 0xFF, 0xD8, 1, 2, 0xFF, 0xD9, 0x0D, 0x0A))
        assertEquals(1, out.size)
        assertArrayEquals(byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 1, 2, 0xFF.toByte(), 0xD9.toByte()), out[0])
    }

    @Test fun findsOneAfterAnother() {
        assertEquals(2, jpegs(listOf(0xFF, 0xD8, 9, 0xFF, 0xD9, 0xFF, 0xD8, 8, 0xFF, 0xD9)).size)
    }

    @Test fun ignoresAnEndWithNoStart() {
        assertEquals(0, jpegs(listOf(1, 0xFF, 0xD9, 2)).size)
    }
}

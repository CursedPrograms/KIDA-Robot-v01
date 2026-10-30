package com.synthwomb.kida01

import android.content.Context
import android.graphics.BitmapFactory
import android.os.Handler
import android.os.Looper
import android.widget.ImageView
import java.io.ByteArrayOutputStream
import java.net.HttpURLConnection
import java.net.URL

/** Finds whole JPEGs in an MJPEG stream, however its bytes are split up. */
class MjpegParser {
    private val frame = ByteArrayOutputStream()
    private var inFrame = false
    private var last = 0

    /** Feeds one byte; returns a finished JPEG when this was its last byte. */
    fun feed(b: Int): ByteArray? {
        var done: ByteArray? = null
        if (!inFrame && last == 0xFF && b == 0xD8) {
            inFrame = true
            frame.reset()
            frame.write(0xFF)
        }
        if (inFrame) {
            frame.write(b)
            if (last == 0xFF && b == 0xD9) {
                inFrame = false
                done = frame.toByteArray()
            }
        }
        last = b
        return done
    }
}

/** The robot's camera. It keeps trying while it's on: a robot can come and go. */
class CameraView(context: Context, private val onState: (String) -> Unit) : ImageView(context) {
    private val ui = Handler(Looper.getMainLooper())
    @Volatile private var url = ""
    @Volatile private var run = 0

    init { scaleType = ScaleType.FIT_CENTER }

    fun show(address: String) {
        url = address
        start()
    }

    fun start() {
        if (url.isEmpty()) return
        val mine = ++run
        Thread { watch(mine) }.start()
    }

    fun stop() { run++ }

    private fun watch(mine: Int) {
        while (mine == run) {
            var c: HttpURLConnection? = null
            try {
                c = URL(url).openConnection() as HttpURLConnection
                c.connectTimeout = 2000
                c.readTimeout = 4000
                val input = c.inputStream.buffered()
                val parser = MjpegParser()
                while (mine == run) {
                    val b = input.read()
                    if (b < 0) break
                    val jpeg = parser.feed(b) ?: continue
                    BitmapFactory.decodeByteArray(jpeg, 0, jpeg.size)?.let { ui.post { if (mine == run) setImageBitmap(it) } }
                }
            } catch (_: Exception) {
                onState("no camera picture yet")
            } finally {
                c?.disconnect()
            }
            if (mine == run) Thread.sleep(2000)
        }
    }
}

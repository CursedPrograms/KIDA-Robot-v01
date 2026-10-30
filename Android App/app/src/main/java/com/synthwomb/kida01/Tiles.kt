package com.synthwomb.kida01

import org.json.JSONObject
import java.util.Locale
import kotlin.math.pow

/**
 * The little windows: (title, value) pairs. Distance comes from radio strength, which walls, bodies
 * and antennas all change, so it's a rough guess: hence the ~. The robots' sonars measure real distance.
 */
object Tiles {
    /** Rough metres from RSSI: about 1 m at -50 dBm, a typical indoor fall-off. */
    fun metres(rssi: Double): Double = 10.0.pow((-50.0 - rssi) / 25.0)

    fun roughDistance(rssi: Double): String {
        val m = metres(rssi)
        return if (m < 10) String.format(Locale.ROOT, "~%.1f m", m) else String.format(Locale.ROOT, "~%.0f m", m)
    }

    /** A robot's /near: every robot it can hear, nearest first. */
    fun near(json: String?): List<Pair<String, String>> {
        val robots = try {
            JSONObject(json ?: return emptyList()).optJSONArray("robots") ?: return emptyList()
        } catch (_: Exception) {
            return emptyList()
        }
        return (0 until robots.length()).map { i ->
            val r = robots.getJSONObject(i)
            r.optString("name") to roughDistance(r.optDouble("rssi", -100.0))
        }
    }

    fun cm(v: Any?): String = when (v) {
        null, JSONObject.NULL -> "--"
        is Number -> if (v.toDouble() <= 0 || v.toDouble() >= 400) "--" else "${v.toInt()} cm"
        else -> v.toString().toDoubleOrNull()?.let { cm(it) } ?: "--"
    }
}

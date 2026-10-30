package com.synthwomb.kida01

import org.json.JSONObject
import java.util.Locale

// What KIDA-01 takes: the same calls as RITA and her PC controller.
class Robot(private val http: Http) : RobotApi {
    private fun n(v: Float) = String.format(Locale.ROOT, "%.2f", v)

    private fun send(command: String, more: String = "") =
        http.post("/action", "{\"command\":\"$command\"$more}")

    override fun connect(pin: String) {
        http.get("/unlock?pw=$pin")
        send("mode_1")
        send("scheme_wasd")
    }
    override fun drive(forward: Float, side: Float, turn: Float) {
        val left = (forward - turn).coerceIn(-1f, 1f)
        val right = (forward + turn).coerceIn(-1f, 1f)
        send("joy_drive", ",\"left\":${n(left)},\"right\":${n(right)}")
    }
    override fun stop() { send("move_stop") }
    override fun tiles(s: JSONObject): List<Pair<String, String>> {
        val sensors = s.optJSONObject("sensors")
        return listOf(
            "Front" to Tiles.cm(sensors?.opt("US0")),
            "Rear" to Tiles.cm(sensors?.opt("US1")),
            "Battery" to "${s.optInt("bat_pct")}%",
            "Volts" to s.optString("bus_v", "--"),
            "Mode" to s.optString("mode", "--"),
            "CPU" to "${s.optString("cpu_temp", "--")}\u00b0C",
        )
    }

    override val buttons = listOf(
        "DRIVE" to { send("mode_1"); Unit },
        "HELLO" to { send("hello"); Unit },
        "DANCE" to { send("dance"); Unit },
        "PHOTO" to { send("photo"); Unit },
        "MUSIC" to { send("music_play"); Unit },
        "STOP MUSIC" to { send("music_stop"); Unit },
        "LOCK" to { send("motor_lock_on"); Unit },
    )
}

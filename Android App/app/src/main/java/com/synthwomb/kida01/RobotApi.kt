package com.synthwomb.kida01

import org.json.JSONObject

/** How the app reaches the robot: swapped for a recorder in the tests. */
interface Http {
    fun get(path: String): String?
    fun post(path: String, json: String): String?
}

/** One robot's commands. forward, side (+ left) and turn (+ anticlockwise) are -1..1. */
interface RobotApi {
    fun connect(pin: String)
    fun drive(forward: Float, side: Float, turn: Float)
    fun stop()
    val buttons: List<Pair<String, () -> Unit>>
    /** Its sensors, from its /status: (title, value) */
    fun tiles(s: JSONObject): List<Pair<String, String>>
}

/**
 * Holding the stick drives; letting go stops, once, straight away. Driving is sent again every tick,
 * because the robots stop by themselves when it goes quiet: that's what stops them if this phone
 * walks out of range.
 */
class Driver(private val robot: RobotApi) {
    private var driving = false

    fun tick(forward: Float, side: Float, turn: Float) {
        val moving = forward != 0f || side != 0f || turn != 0f
        if (moving) {
            driving = true
            robot.drive(forward, side, turn)
        } else if (driving) {
            driving = false
            robot.stop()
        }
    }

    fun stopNow() {
        driving = false
        robot.stop()
    }
}

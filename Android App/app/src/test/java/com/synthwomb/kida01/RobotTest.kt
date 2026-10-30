package com.synthwomb.kida01

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class RobotTest {
    private class Recorder : Http {
        val calls = ArrayList<String>()
        override fun get(path: String): String? { calls.add(path); return "{}" }
        override fun post(path: String, json: String): String? { calls.add("$path $json"); return "{}" }
    }

    @Test fun lettingGoStopsOnceAndOnlyOnce() {
        val http = Recorder()
        val driver = Driver(Robot(http))
        driver.tick(0f, 0f, 0f)
        assertTrue("nothing to stop yet", http.calls.isEmpty())
        driver.tick(1f, 0f, 0f)
        val driving = http.calls.size
        assertTrue(driving >= 1)
        driver.tick(0f, 0f, 0f)
        val stopped = http.calls.size
        assertEquals(driving + 1, stopped)
        driver.tick(0f, 0f, 0f)
        assertEquals(stopped, http.calls.size)
    }

    @Test fun callsAreWhatTheRobotTakes() {
        val http = Recorder()
        val r = Robot(http)
        r.connect("1234")
        r.drive(1f, 0f, 0f)
        r.stop()
        assertEquals(listOf("/unlock?pw=1234", "/action {\"command\":\"mode_1\"}", "/action {\"command\":\"scheme_wasd\"}", "/action {\"command\":\"joy_drive\",\"left\":1.00,\"right\":1.00}", "/action {\"command\":\"move_stop\"}"), http.calls)
    }

    @Test fun tilesReadItsStatus() {
        val tiles = Robot(Recorder()).tiles(org.json.JSONObject("""{"sensors":{"US0":31,"US1":"\u2014"},"bat_pct":80,"bus_v":7.4,"mode":"KEYBOARD","cpu_temp":48}"""))
        assertTrue(tiles.toString(), tiles.contains("Front" to "31 cm"))
    }

    @Test fun nearbyRobotsGetARoughDistance() {
        val near = Tiles.near("""{"robots":[{"name":"WHIP","rssi":-50},{"name":"NORA","rssi":-75}]}""")
        assertEquals(listOf("WHIP" to "~1.0 m", "NORA" to "~10 m"), near)
        assertTrue(Tiles.near(null).isEmpty())
        assertTrue(Tiles.near("not json").isEmpty())
    }

    @Test fun everyButtonSendsSomething() {
        val http = Recorder()
        Robot(http).buttons.forEach { (_, act) -> act() }
        assertEquals(Robot(http).buttons.size, http.calls.size)
    }
}

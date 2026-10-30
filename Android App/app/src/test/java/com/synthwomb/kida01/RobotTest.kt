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

    @Test fun everyButtonSendsSomething() {
        val http = Recorder()
        Robot(http).buttons.forEach { (_, act) -> act() }
        assertEquals(Robot(http).buttons.size, http.calls.size)
    }
}

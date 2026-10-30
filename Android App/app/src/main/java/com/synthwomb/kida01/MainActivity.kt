package com.synthwomb.kida01

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.content.pm.ActivityInfo
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.net.wifi.WifiManager
import android.os.Bundle
import android.text.InputType
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.EditText
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.TextView
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors
import kotlin.concurrent.thread

private const val NAME = "KIDA-01"
private const val PORT = 5004
private const val SLIDE = false          // a second stick that slides KIDA-01 sideways
private val BG = Color.parseColor("#080A12")
private val PANEL = Color.parseColor("#0E1220")
private val ACCENT = Color.parseColor("#DF5BA3")
private val EDGE = Color.parseColor("#1C2440")
private val TEXT = Color.parseColor("#F2E9ED")

/** Plain http on the fleet's network. */
class WebLink : Http {
    @Volatile var base = ""

    private fun open(path: String) = (URL(base + path).openConnection() as HttpURLConnection).apply {
        connectTimeout = 800
        readTimeout = 1500
    }

    override fun get(path: String): String? = try {
        val c = open(path)
        try { c.inputStream.bufferedReader().readText() } finally { c.disconnect() }
    } catch (_: Exception) {
        null
    }

    override fun post(path: String, json: String): String? = try {
        val c = open(path)
        c.requestMethod = "POST"
        c.doOutput = true
        c.setRequestProperty("Content-Type", "application/json")
        c.outputStream.use { it.write(json.toByteArray()) }
        try { c.inputStream.bufferedReader().readText() } finally { c.disconnect() }
    } catch (_: Exception) {
        null
    }
}

/** KIDA-01's controller: find, connect, hold the stick to drive, let go to stop. */
private const val CAMERA_FEED = "/video_feed/0"

class MainActivity : Activity() {
    private lateinit var camera: CameraView
    private val link = WebLink()
    private val robot = Robot(link)
    private val driver = Driver(robot)
    private val work = Executors.newSingleThreadExecutor()
    private lateinit var sticks: SticksView
    private lateinit var state: TextView
    private lateinit var address: EditText
    private lateinit var pin: EditText
    private lateinit var tiles: LinearLayout
    @Volatile private var running = false
    private var wifi: ConnectivityManager.NetworkCallback? = null

    private fun button(text: String, action: () -> Unit) = Button(this).apply {
        this.text = text
        setTextColor(TEXT)
        setBackgroundColor(PANEL)
        setOnClickListener { work.execute { action() } }
    }

    private fun field(hint: String, value: String) = EditText(this).apply {
        this.hint = hint
        setText(value)
        setTextColor(TEXT)
        setHintTextColor(EDGE)
        setSingleLine()
    }

    override fun onCreate(saved: Bundle?) {
        super.onCreate(saved)
        requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        val prefs = getPreferences(Context.MODE_PRIVATE)
        sticks = SticksView(this)
        state = TextView(this).apply { text = "Find or type her address"; setTextColor(TEXT); setPadding(16, 0, 16, 0) }
        address = field("address", prefs.getString("ip", "") ?: "")
        pin = field("PIN", prefs.getString("pin", "1234") ?: "").apply {
            inputType = InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_VARIATION_PASSWORD
        }

        val top = LinearLayout(this).apply {
            gravity = Gravity.CENTER_VERTICAL
            addView(TextView(context).apply { text = NAME; textSize = 20f; setTextColor(ACCENT); setPadding(16, 0, 16, 0) })
            addView(address, LinearLayout.LayoutParams(300, -2))
            addView(pin, LinearLayout.LayoutParams(130, -2))
            addView(button("FIND") { find() })
            addView(button("CONNECT") { connect() })
            addView(state, LinearLayout.LayoutParams(0, -2, 1f))
            addView(Button(context).apply {
                text = "STOP"
                setTextColor(Color.WHITE)
                setBackgroundColor(Color.parseColor("#B91C1C"))
                setOnClickListener { sticks.release(); work.execute { driver.stopNow() } }
            })
        }
        camera = CameraView(this) { say(it) }
        val row = LinearLayout(this)
        tiles = LinearLayout(this)
        robot.buttons.forEach { (name, act) -> row.addView(button(name, act)) }
        setContentView(LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(BG)
            addView(top)
            addView(HorizontalScrollView(context).apply { addView(row) })
            addView(HorizontalScrollView(context).apply { addView(tiles) })
            addView(camera, LinearLayout.LayoutParams(-1, 0, 1f))
            addView(sticks, LinearLayout.LayoutParams(-1, 0, 1f))
        })
        showSplash()
    }

    private fun say(text: String) = runOnUiThread { state.text = text }

    // Its sensors from /status, then whoever it can hear from /near. A robot with no /near just has no
    // nearby tiles; a robot whose old firmware has no /status uses /sensors.
    private fun refresh() {
        val body = link.get("/status") ?: link.get("/sensors") ?: return
        val sensors = try { robot.tiles(JSONObject(body)) } catch (_: Exception) { emptyList() }
        val near = Tiles.near(link.get("/near"))
        runOnUiThread { showTiles(sensors + near) }
    }

    private fun showTiles(list: List<Pair<String, String>>) {
        tiles.removeAllViews()
        for ((title, value) in list) {
            tiles.addView(TextView(this).apply {
                text = "$title\n$value"
                gravity = Gravity.CENTER
                setTextColor(TEXT)
                setBackgroundColor(PANEL)
                setPadding(22, 6, 22, 6)
            }, LinearLayout.LayoutParams(-2, -2).apply { setMargins(4, 4, 4, 4) })
        }
    }

    private fun useAddress(ip: String) {
        link.base = "http://$ip:$PORT"
        camera.show(link.base + CAMERA_FEED)
        getPreferences(Context.MODE_PRIVATE).edit().putString("ip", ip).putString("pin", pin.text.toString()).apply()
    }

    private fun connect() {
        val ip = address.text.toString().trim()
        if (ip.isEmpty()) return say("No address")
        useAddress(ip)
        robot.connect(pin.text.toString())
        say(if (link.get("/status") != null || link.get("/sensors") != null) "connected" else "no answer from $ip")
    }

    // The fleet list on whoever hosts this network: RIFT, or the highest robot on the ladder
    private fun find() {
        val wm = applicationContext.getSystemService(WifiManager::class.java)
        @Suppress("DEPRECATION") val g = wm.dhcpInfo.gateway
        val gateway = "${g and 255}.${g shr 8 and 255}.${g shr 16 and 255}.${g shr 24 and 255}"
        val list = WebLink().apply { base = "http://$gateway:5000" }
        val body = list.get("/fleet") ?: list.get("/robots") ?: return say("No fleet list at $gateway")
        val robots: JSONArray = try { JSONObject(body).getJSONArray("robots") } catch (_: Exception) { return say("Odd fleet list") }
        for (i in 0 until robots.length()) {
            val r = robots.getJSONObject(i)
            if (r.optString("name").replace("-", "").equals(NAME.replace("-", ""), ignoreCase = true)) {
                val ip = r.optString("ip")
                runOnUiThread { address.setText(ip) }
                useAddress(ip)
                return say("found at $ip")
            }
        }
        say("$NAME isn't on this network")
    }

    override fun onResume() {
        super.onResume()
        camera.start()
        val cm = getSystemService(ConnectivityManager::class.java)
        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) { cm.bindProcessToNetwork(network) }
        }
        wifi = cb
        cm.requestNetwork(NetworkRequest.Builder().addTransportType(NetworkCapabilities.TRANSPORT_WIFI).build(), cb)
        running = true
        thread(name = "drive", isDaemon = true) {
            var beats = 0
            while (running) {
                if (link.base.isNotEmpty()) {
                    val s = sticks
                    work.execute { driver.tick(s.forward, s.side, s.turn) }
                    if (++beats % 2 == 0) work.execute { refresh() }   // MILA's bridge stops her if /status goes quiet
                }
                Thread.sleep(200)
            }
        }
    }

    override fun onPause() {                  // a call, the home button, the screen going off: she stops
        running = false
        camera.stop()
        sticks.release()
        work.execute { if (link.base.isNotEmpty()) driver.stopNow() }
        val cm = getSystemService(ConnectivityManager::class.java)
        wifi?.let { cm.unregisterNetworkCallback(it) }
        wifi = null
        super.onPause()
    }
}

/** Hold to drive, let go to stop: the left stick, and on a robot that can slide, a right one for that. */
@SuppressLint("ViewConstructor", "ClickableViewAccessibility")
class SticksView(context: Context) : View(context) {
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG)
    private val line = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeWidth = 4f }
    private val fingers = HashMap<Int, Int>()
    @Volatile private var left: Pair<Float, Float>? = null
    @Volatile private var right: Pair<Float, Float>? = null

    val forward: Float get() = dead(-(left?.second ?: 0f))
    val turn: Float get() = dead(-(left?.first ?: 0f))
    val side: Float get() = dead(-(right?.first ?: 0f))

    private fun dead(v: Float) = if (kotlin.math.abs(v) < 0.12f) 0f else v

    fun release() {
        fingers.clear()
        left = null
        right = null
        postInvalidate()
    }

    private fun radius() = minOf(width / 2f, height.toFloat()) * 0.44f

    private fun centreX(stick: Int) = if (!SLIDE) width / 2f else if (stick == 0) width * 0.22f else width * 0.78f

    private fun place(stick: Int, x: Float, y: Float) {
        val r = radius()
        val at = ((x - centreX(stick)) / r).coerceIn(-1f, 1f) to ((y - height / 2f) / r).coerceIn(-1f, 1f)
        if (stick == 0) left = at else right = at
    }

    override fun onTouchEvent(e: MotionEvent): Boolean {
        when (e.actionMasked) {
            MotionEvent.ACTION_DOWN, MotionEvent.ACTION_POINTER_DOWN -> {
                val i = e.actionIndex
                val stick = if (!SLIDE || e.getX(i) < width / 2f) 0 else 1
                fingers[e.getPointerId(i)] = stick
                place(stick, e.getX(i), e.getY(i))
            }
            MotionEvent.ACTION_MOVE -> for (i in 0 until e.pointerCount) {
                fingers[e.getPointerId(i)]?.let { place(it, e.getX(i), e.getY(i)) }
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_POINTER_UP -> {
                val stick = fingers.remove(e.getPointerId(e.actionIndex))
                if (stick == 0) left = null else if (stick == 1) right = null
            }
            MotionEvent.ACTION_CANCEL -> release()
        }
        invalidate()
        return true
    }

    override fun onDraw(c: Canvas) {
        val r = radius()
        val y = height / 2f
        for (i in 0 until if (SLIDE) 2 else 1) {
            val at = if (i == 0) left else right
            val x = centreX(i)
            fill.color = PANEL
            c.drawRoundRect(RectF(x - r, y - r, x + r, y + r), 28f, 28f, fill)
            line.color = EDGE
            c.drawRoundRect(RectF(x - r, y - r, x + r, y + r), 28f, 28f, line)
            c.drawLine(x - r, y, x + r, y, line)
            c.drawLine(x, y - r, x, y + r, line)
            fill.color = if (at == null) EDGE else ACCENT
            c.drawCircle(x + (at?.first ?: 0f) * r, y + (at?.second ?: 0f) * r, r * 0.2f, fill)
        }
    }
}

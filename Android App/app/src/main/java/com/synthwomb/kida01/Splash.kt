package com.synthwomb.kida01

import android.app.Activity
import android.graphics.Color
import android.os.Handler
import android.os.Looper
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.ImageView

private const val SPLASH_MS = 2500L

/** The avatar over the whole screen for a moment as the app opens. Goes after setContentView. */
fun Activity.showSplash() {
    val cover = FrameLayout(this).apply {
        setBackgroundColor(Color.BLACK)
        isClickable = true       // nothing behind it can be pressed yet
        addView(ImageView(context).apply {
            setImageResource(R.drawable.splash_avatar)
            scaleType = ImageView.ScaleType.FIT_CENTER
        }, FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
    }
    addContentView(cover, ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
    Handler(Looper.getMainLooper()).postDelayed({ (cover.parent as? ViewGroup)?.removeView(cover as View) }, SPLASH_MS)
}

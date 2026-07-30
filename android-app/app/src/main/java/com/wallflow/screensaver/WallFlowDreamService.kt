package com.wallflow.screensaver

import android.animation.ObjectAnimator
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.os.Handler
import android.os.Looper
import android.service.dreams.DreamService
import android.util.Log
import android.view.KeyEvent
import android.widget.ImageView
import android.widget.Toast
import androidx.preference.PreferenceManager
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

/**
 * Screensaver die willekeurige wallpapers toont vanaf de WallFlow HTTP-server
 * (zie app/httpserver.py in het WallFlow-project).
 *
 * - Elke 30 seconden automatisch een nieuwe, willekeurige afbeelding.
 * - D-pad links/rechts: handmatig terug/verder bladeren door de al geziene
 *   afbeeldingen (geschiedenis), of een nieuwe ophalen voorbij het einde.
 * - D-pad centrum/OK: de huidige afbeelding verwijderen (roept DELETE aan op
 *   de server) en doorgaan naar de volgende.
 * - Terug-knop: screensaver sluiten (normaal gedrag).
 */
class WallFlowDreamService : DreamService() {

    private val executor = Executors.newSingleThreadExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())

    private lateinit var imageA: ImageView
    private lateinit var imageB: ImageView
    private var showingA = true

    /** Volledige pool aan bestandsnamen zoals opgehaald van de server. */
    private var wallpapers: MutableList<String> = mutableListOf()

    /** Geschiedenis van getoonde afbeeldingen, voor handmatig terug/verder bladeren. */
    private val history: MutableList<String> = mutableListOf()
    private var historyIndex: Int = -1

    private var serverAddress: String = ""

    private val tickRunnable = Runnable { advanceToNewRandom() }

    override fun onAttachedToWindow() {
        super.onAttachedToWindow()

        isInteractive = true
        isFullscreen = true
        setContentView(R.layout.dream_layout)

        imageA = findViewById(R.id.image_a)
        imageB = findViewById(R.id.image_b)

        val prefs = PreferenceManager.getDefaultSharedPreferences(this)
        serverAddress = prefs.getString(PREF_SERVER_URL, "") ?: ""

        if (serverAddress.isBlank()) {
            Log.w(TAG, "Geen server ingesteld in de instellingen, screensaver stopt.")
            finish()
            return
        }

        refreshWallpaperList {
            advanceToNewRandom()
        }
    }

    override fun onDetachedFromWindow() {
        super.onDetachedFromWindow()
        mainHandler.removeCallbacks(tickRunnable)
        executor.shutdownNow()
    }

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        if (event.action == KeyEvent.ACTION_DOWN) {
            when (event.keyCode) {
                KeyEvent.KEYCODE_DPAD_LEFT -> {
                    goPrevious()
                    return true
                }
                KeyEvent.KEYCODE_DPAD_RIGHT -> {
                    goNext()
                    return true
                }
                KeyEvent.KEYCODE_DPAD_CENTER, KeyEvent.KEYCODE_ENTER -> {
                    deleteCurrentImage()
                    return true
                }
                KeyEvent.KEYCODE_BACK -> {
                    finish()
                    return true
                }
            }
        }
        return super.dispatchKeyEvent(event)
    }

    private fun baseUrl(): String {
        val trimmed = serverAddress.trim().trimEnd('/')
        return if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
            trimmed
        } else {
            "http://$trimmed"
        }
    }

    private fun resetTickTimer() {
        mainHandler.removeCallbacks(tickRunnable)
        mainHandler.postDelayed(tickRunnable, INTERVAL_MS)
    }

    /** Haalt de lijst met beschikbare wallpapers op via GET /wallpapers. */
    private fun refreshWallpaperList(onDone: () -> Unit) {
        executor.execute {
            try {
                val connection = URL("${baseUrl()}/wallpapers").openConnection() as HttpURLConnection
                connection.connectTimeout = 10_000
                connection.readTimeout = 10_000

                val body = connection.inputStream.bufferedReader().use { it.readText() }
                val json = JSONObject(body)
                val array = json.getJSONArray("wallpapers")

                val list = mutableListOf<String>()
                for (i in 0 until array.length()) {
                    list.add(array.getString(i))
                }

                wallpapers = list
                Log.i(TAG, "Wallpaperlijst opgehaald: ${list.size} stuks")
            } catch (e: Exception) {
                Log.e(TAG, "Ophalen wallpaperlijst mislukt: ${e.message}")
            } finally {
                mainHandler.post(onDone)
            }
        }
    }

    /** Kiest een nieuwe, nog niet als laatste getoonde afbeelding en toont die. */
    private fun advanceToNewRandom() {
        if (wallpapers.isEmpty()) {
            refreshWallpaperList { resetTickTimer() }
            return
        }

        val previous = history.getOrNull(historyIndex)
        val candidate = if (wallpapers.size == 1) {
            wallpapers[0]
        } else {
            var pick: String
            do {
                pick = wallpapers.random()
            } while (pick == previous)
            pick
        }

        // Alles na de huidige positie in de geschiedenis vervalt zodra we een
        // nieuwe afbeelding kiezen (net als "voorwaarts" browsen na terug te
        // hebben gebladerd in een normale galerij).
        while (history.size > historyIndex + 1) {
            history.removeAt(history.size - 1)
        }

        history.add(candidate)
        historyIndex = history.lastIndex

        showAtIndex(historyIndex)
        resetTickTimer()
    }

    private fun goNext() {
        if (historyIndex < history.lastIndex) {
            historyIndex++
            showAtIndex(historyIndex)
            resetTickTimer()
        } else {
            advanceToNewRandom()
        }
    }

    private fun goPrevious() {
        if (historyIndex > 0) {
            historyIndex--
            showAtIndex(historyIndex)
            resetTickTimer()
        }
        // Al bij de oudste afbeelding in de geschiedenis: niets doen.
    }

    private fun showAtIndex(index: Int) {
        val filename = history.getOrNull(index) ?: return

        executor.execute {
            try {
                val connection = URL("${baseUrl()}/wallpapers/$filename").openConnection() as HttpURLConnection
                connection.connectTimeout = 10_000
                connection.readTimeout = 15_000

                val bitmap = connection.inputStream.use { BitmapFactory.decodeStream(it) }

                if (bitmap != null) {
                    mainHandler.post { crossfadeTo(bitmap) }
                } else {
                    Log.w(TAG, "Kon '$filename' niet decoderen als afbeelding.")
                }
            } catch (e: Exception) {
                Log.e(TAG, "Ophalen afbeelding '$filename' mislukt: ${e.message}")
            }
        }
    }

    /** Verwijdert de huidig getoonde afbeelding, zowel op de server als lokaal, en gaat door. */
    private fun deleteCurrentImage() {
        val filename = history.getOrNull(historyIndex) ?: return

        executor.execute {
            try {
                val connection = URL("${baseUrl()}/wallpapers/$filename").openConnection() as HttpURLConnection
                connection.requestMethod = "DELETE"
                connection.connectTimeout = 10_000
                connection.readTimeout = 10_000
                val code = connection.responseCode
                Log.i(TAG, "Verwijderd op server: $filename (status $code)")
            } catch (e: Exception) {
                Log.e(TAG, "Verwijderen van '$filename' mislukt: ${e.message}")
            }
        }

        wallpapers.remove(filename)
        history.removeAt(historyIndex)

        if (historyIndex > history.lastIndex) {
            historyIndex = history.lastIndex
        }

        mainHandler.post {
            Toast.makeText(
                applicationContext,
                applicationContext.getString(R.string.msg_wallpaper_deleted, filename),
                Toast.LENGTH_SHORT
            ).show()
        }

        if (historyIndex >= 0) {
            showAtIndex(historyIndex)
            resetTickTimer()
        } else {
            advanceToNewRandom()
        }
    }

    private fun crossfadeTo(bitmap: Bitmap) {
        val incoming = if (showingA) imageB else imageA
        val outgoing = if (showingA) imageA else imageB

        incoming.setImageBitmap(bitmap)
        incoming.alpha = 0f
        incoming.visibility = ImageView.VISIBLE

        ObjectAnimator.ofFloat(incoming, "alpha", 0f, 1f).apply {
            duration = FADE_DURATION_MS
            start()
        }

        ObjectAnimator.ofFloat(outgoing, "alpha", 1f, 0f).apply {
            duration = FADE_DURATION_MS
            start()
        }

        showingA = !showingA
    }

    companion object {
        private const val TAG = "WallFlowDream"
        private const val PREF_SERVER_URL = "server_url"
        private const val INTERVAL_MS = 30_000L
        private const val FADE_DURATION_MS = 1500L
    }
}

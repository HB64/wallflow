package com.wallflow.screensaver

import android.graphics.BitmapFactory
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.ImageView
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.preference.PreferenceManager
import androidx.recyclerview.widget.GridLayoutManager
import androidx.recyclerview.widget.RecyclerView
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors

/**
 * Galerij van gedownloade wallpapers, opgehaald via GET /wallpapers en
 * getoond met GET /wallpapers/<naam>. Verwijderen roept DELETE aan op de
 * server - WallFlow's eigen rotatiecyclus merkt vanzelf dat het bestand
 * weg is (zie main.py: check_rotation).
 */
class GalleryActivity : AppCompatActivity() {

    // Aparte pool voor thumbnail-downloads, los van de enkele-taak executor
    // die voor lijst/verwijder-acties wordt gebruikt.
    private val thumbExecutor: ExecutorService = Executors.newFixedThreadPool(3)
    private val actionExecutor: ExecutorService = Executors.newSingleThreadExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())
    private var serverAddress: String = ""

    private lateinit var adapter: GalleryAdapter
    private val wallpapers = mutableListOf<String>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_gallery)

        val recyclerView = findViewById<RecyclerView>(R.id.gallery_recycler)
        recyclerView.layoutManager = GridLayoutManager(this, 4)

        val prefs = PreferenceManager.getDefaultSharedPreferences(this)
        serverAddress = prefs.getString(PREF_SERVER_URL, "") ?: ""

        if (serverAddress.isBlank()) {
            Toast.makeText(this, R.string.msg_set_server_first, Toast.LENGTH_LONG).show()
            finish()
            return
        }

        adapter = GalleryAdapter(wallpapers, ::baseUrl, thumbExecutor, mainHandler, ::confirmDelete)
        recyclerView.adapter = adapter

        loadWallpapers()
    }

    override fun onDestroy() {
        super.onDestroy()
        thumbExecutor.shutdownNow()
        actionExecutor.shutdownNow()
    }

    private fun baseUrl(): String {
        val trimmed = serverAddress.trim().trimEnd('/')
        return if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
            trimmed
        } else {
            "http://$trimmed"
        }
    }

    private fun loadWallpapers() {
        actionExecutor.execute {
            try {
                val connection = URL("${baseUrl()}/wallpapers").openConnection() as HttpURLConnection
                connection.connectTimeout = 10_000
                connection.readTimeout = 10_000

                val body = connection.inputStream.bufferedReader().use { it.readText() }
                val json = JSONObject(body)
                val array = json.getJSONArray("wallpapers")

                val names = mutableListOf<String>()
                for (i in 0 until array.length()) {
                    names.add(array.getString(i))
                }

                mainHandler.post {
                    wallpapers.clear()
                    wallpapers.addAll(names)
                    adapter.notifyDataSetChanged()
                }
            } catch (e: Exception) {
                mainHandler.post {
                    Toast.makeText(this, getString(R.string.msg_wallpapers_load_failed, e.message), Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    private fun confirmDelete(name: String) {
        android.app.AlertDialog.Builder(this)
            .setTitle(R.string.dialog_delete_title)
            .setMessage(getString(R.string.dialog_delete_message, name))
            .setPositiveButton(R.string.action_remove) { _, _ -> deleteWallpaper(name) }
            .setNegativeButton(R.string.action_cancel, null)
            .show()
    }

    private fun deleteWallpaper(name: String) {
        actionExecutor.execute {
            try {
                val connection = URL("${baseUrl()}/wallpapers/${URLEncoder.encode(name, "UTF-8")}")
                    .openConnection() as HttpURLConnection
                connection.requestMethod = "DELETE"
                connection.connectTimeout = 10_000
                connection.readTimeout = 10_000

                val code = connection.responseCode
                if (code != 204 && code != 200) {
                    throw RuntimeException("status $code")
                }

                mainHandler.post {
                    val index = wallpapers.indexOf(name)
                    if (index >= 0) {
                        wallpapers.removeAt(index)
                        adapter.notifyItemRemoved(index)
                    }
                    Toast.makeText(this, getString(R.string.msg_wallpaper_deleted, name), Toast.LENGTH_SHORT).show()
                }
            } catch (e: Exception) {
                mainHandler.post {
                    Toast.makeText(this, getString(R.string.msg_wallpaper_delete_failed, e.message), Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    companion object {
        private const val PREF_SERVER_URL = "server_url"
    }
}

class GalleryAdapter(
    private val items: MutableList<String>,
    private val baseUrlProvider: () -> String,
    private val thumbExecutor: ExecutorService,
    private val mainHandler: Handler,
    private val onDeleteRequested: (String) -> Unit
) : RecyclerView.Adapter<GalleryAdapter.ViewHolder>() {

    class ViewHolder(view: View) : RecyclerView.ViewHolder(view) {
        val image: ImageView = view.findViewById(R.id.tile_image)
        val label: TextView = view.findViewById(R.id.tile_label)
        val deleteButton: Button = view.findViewById(R.id.tile_delete_button)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): ViewHolder {
        val view = LayoutInflater.from(parent.context)
            .inflate(R.layout.item_wallpaper, parent, false)
        return ViewHolder(view)
    }

    override fun onBindViewHolder(holder: ViewHolder, position: Int) {
        val name = items[position]
        holder.label.text = name
        holder.image.setImageDrawable(null)
        holder.image.tag = name

        holder.deleteButton.setOnClickListener { onDeleteRequested(name) }

        val url = "${baseUrlProvider()}/wallpapers/${java.net.URLEncoder.encode(name, "UTF-8")}"
        thumbExecutor.execute {
            try {
                val connection = URL(url).openConnection() as HttpURLConnection
                connection.connectTimeout = 10_000
                connection.readTimeout = 15_000

                // Verkleind decoderen: dit is alleen een miniatuur in een
                // rasterweergave, het volledige 4K-beeld hoeft niet in het
                // geheugen te staan.
                val options = BitmapFactory.Options()
                options.inSampleSize = 6
                val bitmap = connection.inputStream.use {
                    BitmapFactory.decodeStream(it, null, options)
                }

                if (bitmap != null) {
                    mainHandler.post {
                        if (holder.image.tag == name) {
                            holder.image.setImageBitmap(bitmap)
                        }
                    }
                }
            } catch (e: Exception) {
                // Stil falen voor 1 thumbnail is prima, de rest blijft werken.
            }
        }
    }

    override fun getItemCount(): Int = items.size
}

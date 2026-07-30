package com.wallflow.screensaver

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.preference.PreferenceManager
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.util.concurrent.Executors

/**
 * Tags beheren (include/exclude), rechtstreeks tegen de WallFlow-server
 * (dezelfde /tags-endpoints als de webpagina op /ui). Wijzigingen zijn
 * direct actief op de server, geen rebuild of herstart nodig.
 */
class TagsActivity : AppCompatActivity() {

    private val executor = Executors.newSingleThreadExecutor()
    private val mainHandler = Handler(Looper.getMainLooper())
    private var serverAddress: String = ""

    private lateinit var includeList: LinearLayout
    private lateinit var excludeList: LinearLayout
    private lateinit var includeInput: EditText
    private lateinit var excludeInput: EditText

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_tags)

        includeList = findViewById(R.id.include_list)
        excludeList = findViewById(R.id.exclude_list)
        includeInput = findViewById(R.id.include_input)
        excludeInput = findViewById(R.id.exclude_input)

        val prefs = PreferenceManager.getDefaultSharedPreferences(this)
        serverAddress = prefs.getString(PREF_SERVER_URL, "") ?: ""

        if (serverAddress.isBlank()) {
            Toast.makeText(this, R.string.msg_set_server_first, Toast.LENGTH_LONG).show()
            finish()
            return
        }

        findViewById<Button>(R.id.include_add_button).setOnClickListener {
            addTag("include", includeInput)
        }
        findViewById<Button>(R.id.exclude_add_button).setOnClickListener {
            addTag("exclude", excludeInput)
        }

        loadTags()
    }

    override fun onDestroy() {
        super.onDestroy()
        executor.shutdownNow()
    }

    private fun baseUrl(): String {
        val trimmed = serverAddress.trim().trimEnd('/')
        return if (trimmed.startsWith("http://") || trimmed.startsWith("https://")) {
            trimmed
        } else {
            "http://$trimmed"
        }
    }

    /**
     * Codeert een tag voor gebruik als los pad-segment (bijv. in een
     * DELETE-URL). URLEncoder.encode codeert een spatie als '+' (bedoeld
     * voor formuliervelden), maar de server verwacht %20 in het pad -
     * daarom wordt '+' achteraf vervangen.
     */
    private fun encodePathSegment(value: String): String {
        return URLEncoder.encode(value, "UTF-8").replace("+", "%20")
    }

    private fun jsonArrayToList(array: JSONArray): List<String> {
        val list = mutableListOf<String>()
        for (i in 0 until array.length()) {
            list.add(array.getString(i))
        }
        return list
    }

    private fun loadTags() {
        executor.execute {
            try {
                val connection = URL("${baseUrl()}/tags").openConnection() as HttpURLConnection
                connection.connectTimeout = 10_000
                connection.readTimeout = 10_000

                val body = connection.inputStream.bufferedReader().use { it.readText() }
                val json = JSONObject(body)
                val include = jsonArrayToList(json.getJSONArray("include"))
                val exclude = jsonArrayToList(json.getJSONArray("exclude"))

                mainHandler.post {
                    renderTags(includeList, "include", include)
                    renderTags(excludeList, "exclude", exclude)
                }
            } catch (e: Exception) {
                mainHandler.post {
                    Toast.makeText(this, getString(R.string.msg_tags_load_failed, e.message), Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    private fun renderTags(container: LinearLayout, kind: String, tags: List<String>) {
        container.removeAllViews()
        tags.forEach { tag ->
            val row = LinearLayout(this)
            row.orientation = LinearLayout.HORIZONTAL
            row.gravity = Gravity.CENTER_VERTICAL
            row.setPadding(0, 8, 0, 8)

            val label = TextView(this)
            label.text = tag
            label.setTextColor(0xFFFFFFFF.toInt())
            label.layoutParams = LinearLayout.LayoutParams(
                0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f
            )

            val removeButton = Button(this)
            removeButton.text = getString(R.string.action_remove)
            removeButton.setOnClickListener { removeTag(kind, tag) }

            row.addView(label)
            row.addView(removeButton)
            container.addView(row)
        }
    }

    private fun addTag(kind: String, input: EditText) {
        val tag = input.text.toString().trim()
        if (tag.isEmpty()) {
            return
        }

        executor.execute {
            try {
                val connection = URL("${baseUrl()}/tags/$kind").openConnection() as HttpURLConnection
                connection.requestMethod = "POST"
                connection.doOutput = true
                connection.setRequestProperty("Content-Type", "application/json")
                connection.connectTimeout = 10_000
                connection.readTimeout = 10_000

                val payload = JSONObject().put("tag", tag).toString().toByteArray(Charsets.UTF_8)
                connection.outputStream.use { it.write(payload) }

                val code = connection.responseCode
                if (code != 200) {
                    throw RuntimeException("status $code")
                }

                val body = connection.inputStream.bufferedReader().use { it.readText() }
                val json = JSONObject(body)
                val include = jsonArrayToList(json.getJSONArray("include"))
                val exclude = jsonArrayToList(json.getJSONArray("exclude"))

                mainHandler.post {
                    renderTags(includeList, "include", include)
                    renderTags(excludeList, "exclude", exclude)
                    input.setText("")
                    Toast.makeText(this, getString(R.string.msg_tag_added, tag), Toast.LENGTH_SHORT).show()
                }
            } catch (e: Exception) {
                mainHandler.post {
                    Toast.makeText(this, getString(R.string.msg_tag_add_failed, e.message), Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    private fun removeTag(kind: String, tag: String) {
        executor.execute {
            try {
                val connection = URL("${baseUrl()}/tags/$kind/${encodePathSegment(tag)}")
                    .openConnection() as HttpURLConnection
                connection.requestMethod = "DELETE"
                connection.connectTimeout = 10_000
                connection.readTimeout = 10_000

                val code = connection.responseCode
                if (code != 200) {
                    throw RuntimeException("status $code")
                }

                val body = connection.inputStream.bufferedReader().use { it.readText() }
                val json = JSONObject(body)
                val include = jsonArrayToList(json.getJSONArray("include"))
                val exclude = jsonArrayToList(json.getJSONArray("exclude"))

                mainHandler.post {
                    renderTags(includeList, "include", include)
                    renderTags(excludeList, "exclude", exclude)
                    Toast.makeText(this, getString(R.string.msg_tag_removed, tag), Toast.LENGTH_SHORT).show()
                }
            } catch (e: Exception) {
                mainHandler.post {
                    Toast.makeText(this, getString(R.string.msg_tag_remove_failed, e.message), Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    companion object {
        private const val PREF_SERVER_URL = "server_url"
    }
}

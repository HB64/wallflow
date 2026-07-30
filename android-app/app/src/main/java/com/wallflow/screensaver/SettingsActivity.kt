package com.wallflow.screensaver

import android.content.Intent
import android.os.Bundle
import android.provider.Settings
import android.util.Log
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.preference.Preference
import androidx.preference.PreferenceFragmentCompat

/**
 * Instellingenscherm van de screensaver: hier stel je het adres (host:poort)
 * van de WallFlow-server in, en kun je naar tag-/wallpaperbeheer en de
 * systeem-screensaverinstellingen gaan. Android roept deze activity ook aan
 * vanuit het systeeminstellingenscherm "Screensaver" (via
 * android:settingsActivity in dream_info.xml).
 */
class SettingsActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_settings)

        if (savedInstanceState == null) {
            supportFragmentManager.beginTransaction()
                .replace(R.id.settings_container, SettingsFragment())
                .commit()
        }
    }
}

class SettingsFragment : PreferenceFragmentCompat() {
    override fun onCreatePreferences(savedInstanceState: Bundle?, rootKey: String?) {
        setPreferencesFromResource(R.xml.dream_prefs, rootKey)

        findPreference<Preference>("open_tags")?.setOnPreferenceClickListener {
            startActivity(Intent(requireContext(), TagsActivity::class.java))
            true
        }

        findPreference<Preference>("open_gallery")?.setOnPreferenceClickListener {
            startActivity(Intent(requireContext(), GalleryActivity::class.java))
            true
        }

        findPreference<Preference>("open_screensaver_settings")?.setOnPreferenceClickListener {
            openScreensaverSettings()
            true
        }
    }

    /**
     * Probeert direct naar het Android screensaver-instellingenscherm te
     * gaan. ACTION_DREAM_SETTINGS blijkt op de Shield TV nergens door een
     * activity afgehandeld te worden (bevestigd via dumpsys/logcat) - de TV
     * Settings-app opent zijn Daydream-scherm daar via een expliciet
     * component (com.android.tv.settings/.device.display.daydream.DaydreamActivity),
     * dat we hier als eerste proberen. Als dat op een ander toestel niet
     * bestaat, valt dit terug op het standaard ACTION_DREAM_SETTINGS-intent,
     * en als laatste redmiddel op het algemene instellingenscherm.
     */
    private fun openScreensaverSettings() {
        try {
            val explicitIntent = Intent(Intent.ACTION_MAIN).apply {
                setClassName(
                    "com.android.tv.settings",
                    "com.android.tv.settings.device.display.daydream.DaydreamActivity"
                )
            }
            startActivity(explicitIntent)
            return
        } catch (e: Exception) {
            Log.w(TAG, "TV Settings DaydreamActivity niet beschikbaar: ${e.message}", e)
        }

        try {
            startActivity(Intent(Settings.ACTION_DREAM_SETTINGS))
            return
        } catch (e: Exception) {
            Log.w(TAG, "ACTION_DREAM_SETTINGS niet beschikbaar: ${e.message}", e)
        }

        try {
            startActivity(Intent(Settings.ACTION_SETTINGS))
            Toast.makeText(
                requireContext(),
                R.string.error_screensaver_settings_unavailable,
                Toast.LENGTH_LONG
            ).show()
        } catch (e: Exception) {
            Log.e(TAG, "Kon geen enkel instellingenscherm openen: ${e.message}", e)
            Toast.makeText(
                requireContext(),
                R.string.error_screensaver_settings_unavailable,
                Toast.LENGTH_LONG
            ).show()
        }
    }

    companion object {
        private const val TAG = "WallFlowSettings"
    }
}

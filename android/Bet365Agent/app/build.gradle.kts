plugins {
    id("com.android.application")
}

android {
    namespace = "com.bet365agent"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.bet365agent"
        minSdk = 26
        targetSdk = 34
        versionCode = 96
        versionName = "0.9.13-session"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
        debug {
            isDebuggable = true
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.constraintlayout:constraintlayout:2.1.4")

    // Tesseract OCR for visual control (legacy engine, default, rollback)
    implementation("com.rmtheis:tess-two:9.1.0")
    // Fast on-device OCR (Milestone C2): ML Kit text recognition with the Latin model BUNDLED in the APK
    // (no network, no model download); word-level bounding boxes.
    implementation("com.google.mlkit:text-recognition:16.0.1")
    // Bet365 credentials in EncryptedSharedPreferences (Android Keystore master key)
    implementation("androidx.security:security-crypto:1.1.0-alpha06")

    // Plain JVM unit tests for pure classifiers (no device needed)
    testImplementation("junit:junit:4.13.2")
}


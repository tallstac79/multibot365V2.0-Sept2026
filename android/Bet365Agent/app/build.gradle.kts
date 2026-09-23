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
        versionCode = 38
        versionName = "0.6.26-ocr"
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

    // Tesseract OCR for visual control
    implementation("com.rmtheis:tess-two:9.1.0")
}


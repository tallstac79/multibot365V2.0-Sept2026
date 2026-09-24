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
        versionCode = 56
        versionName = "0.6.44-prepare"
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

    // Plain JVM unit tests for pure classifiers (no device needed)
    testImplementation("junit:junit:4.13.2")
}


# MON Mobile & Web Application

This folder contains the **MON Control Center** client application. It functions as a responsive single-page web app and is fully configured to be used as a Progressive Web App (PWA) on mobile devices or packaged into a native Android app.

## Options for Mobile Execution

### Option 1: Install as a Progressive Web App (PWA) - Recommended
Because the app includes a service worker and standard web manifest, you can install it directly onto your Android or iOS device without compiling any native code:
1. Open Chrome (on Android) or Safari (on iOS).
2. Navigate to your deployed Render server URL (e.g. `https://your-mon-server.onrender.com/app/`).
3. Click the menu button (three dots in Chrome, or the "Share" button in Safari) and select **"Add to Home Screen"** or **"Install App"**.
4. The app icon will appear on your app list and will launch in full-screen standalone mode, behaving exactly like a native app.

---

### Option 2: Package as a Native Android App (using Capacitor)
If you want to compile this HTML/JS client into a `.apk` package to distribute or side-load on your Android device:

1. **Pre-requisites**:
   - Ensure [Node.js](https://nodejs.org) is installed on your computer.
   - Install **Android Studio** and the **Android SDK**.

2. **Initialize Capacitor**:
   In your terminal, navigate to the `mobile_app` folder and run:
   ```bash
   npm init -y
   npm install @capacitor/core @capacitor/cli
   npx cap init "MON Control" "com.mon.control" --web-dir=.
   ```

3. **Add Android Platform**:
   Install the Android platform library and add it to Capacitor:
   ```bash
   npm install @capacitor/android
   npx cap add android
   ```

4. **Sync the Web Assets**:
   Sync your HTML/JS code into the Android native template project:
   ```bash
   npx cap sync
   ```

5. **Open and Compile in Android Studio**:
   Open the native Android project in Android Studio:
   ```bash
   npx cap open android
   ```
   In Android Studio, let Gradle sync finish, and click **Build > Build Bundle(s) / APK(s) > Build APK(s)** to compile your installable `.apk` file!

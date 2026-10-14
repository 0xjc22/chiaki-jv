# V2.1 launch crash fix — verified on connected Fold

Cause from actual AndroidRuntime crash log: activity_main.xml used relative CoordinatorLayout behavior names (.main.FloatingActionButtonBackgroundBehavior and .main.FloatingActionButtonSpeedDialBehavior). CoordinatorLayout resolves those against Context.getPackageName(), which is com.gameblabla.chiaki.hevcfix in the separate test app. The compiled classes remain under com.gameblabla.chiaki.main. This caused ClassNotFoundException/InflateException at MainActivity.onCreate before the decoder was created. The side-by-side packaging change introduced the regression; it is not evidence that low-latency mode itself crashes the phone.

Correction: fully qualified the two actual behavior class names. No decoder changes bundled with this correction.

Regression: test/android-layout-package-test.py reproduces class resolution for production and suffixed app IDs. It failed for both relative behavior attributes, then passed after qualification. Existing input, sizing and low-latency configuration tests also pass.

Rebuilt versionCode 19, versionName 2.1.1-hevc-lowlatency-v2.1. adb install -r succeeded on the connected SM-F971U without clearing app data. am start -W launched MainActivity, PID 26564 remained alive over subsequent calls, resumed activity was verified, and native Chiaki initialization logged success. User navigated settings/registration afterward without the startup crash.

APK: /home/jc/dl/chiaki-up-hevc-lowlatency-v2.1-arm64.apk
SHA256: 42007812edcfcd6a00bad4a149ed752cb2ed97fc4e706dbfac6d3abd37d096b9
APK signature and ZIP16KiB alignment verified before staging. The prior V2 APK is retained only as a broken historical artifact, not a recommended build.

Playback remains unverified: the current registration attempt reached the PS5 at 192.168.1.238 but was rejected with HTTP403. User must complete console pairing on-device before a HEVC stream can be captured. Do not request pairing codes in chat; let the user enter them on-device. No DeepSeek package was installed when adb queried packages, so its registration could not be imported from that app.

Important verification gap: host callback/native tests and APK signature/alignment cannot establish actual Android UI startup. am start Status: ok also returned for the crashed build; verify persistent PID and UI/crash log as well.

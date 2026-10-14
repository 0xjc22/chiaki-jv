# Chiaki-Up controller latency investigation and verified build

## Deliverable

Installed package: `com.gameblabla.chiaki.hevcfix`
Version: `2.1.1-hevc-input-lowlatency-v5.5`, versionCode 28
Label: Chiaki-Up HEVC Test 5
APK: `/home/jc/dl/chiaki-up-hevc-input-lowlatency-v5.5-arm64.apk`
SHA256: `eb47497391215c698a3a3ad6e134b0787afffaaf97c48b4da8d73595e1e03157`

Updated through `adb install -r`. Registered-console reconnect and live HEVC streaming were exercised on the connected Fold. Existing HEVC access-unit, low-latency configure/fallback, UDP receive-capacity and malformed-frame rejection fixes remain.

## Measured improvement

The connected input device is GameSir-G8+, exposing GAMEPAD and JOYSTICK sources over Bluetooth. Android's input consumer batches MOVE events; Chiaki already signals its controller-feedback sender immediately when the app receives a changed state. The sender's nominal 8 ms minimum constant is not enforced in this checkout: the changed-state branch contains a TODO, not a sleep. Lowering that constant would not remove the measured delivery delay.

The functional change requests `window.decorView.requestUnbufferedDispatch(InputDevice.SOURCE_CLASS_JOYSTICK)` in `StreamActivity.onAttachedToWindow`, after the superclass callback. This uses the public API available at the app's minimum SDK 30. It applies only to joystick-class input and leaves touchscreen batching/resampling unchanged.

Physical continuous-stick tests, with weighted averages by delivered-event count:

| Build | Input events | Android timestamp-to-app average | Maximum |
|---|---:|---:|---:|
| Buffered baseline, v5.3 | 493 | 9.7079 ms | 15 ms |
| Unbuffered, v5.4 | 393 | 1.0229 ms | 6 ms |
| Final unbuffered, v5.5, refresh request removed | 531 | 1.1073 ms | 6 ms |

Final measured stage reduction: 8.6006 ms, approximately 88.6%. The baseline and first candidate retained identical display and codec settings; the final capture confirms the improvement persists without the forced 120 Hz preference. Captures have different event counts and durations, are not randomized laboratory trials, and cannot prove an exact end-to-end reduction. Millisecond event timestamps limit precision.

This is Android event timestamp to app handling. It does not include controller hardware/radio delay, feedback-network transit, PS5 input/game rendering/encoding, downstream video-network transit, or final display scanout. It is NOT a claim of 1.1 ms input-to-photon latency.

## Experiments rejected

- Explicit codec frame-rate/operating-rate 60 and priority 0 did not improve measured decode latency (roughly 3.8 ms baseline versus 4.4 ms candidate). These overrides and their JNI/state changes were removed.
- Requesting the panel's highest supported refresh produced a verified 120 Hz mode but did not demonstrate lower average video-presentation delay. The preference was removed rather than shipping a power-costly, unproven optimization.
- CCodec's default frame-rate metadata of 1 is not the actual stream decode rate. The final timing windows contain approximately 120 frames per two seconds, consistent with 60 FPS.

## Final verification

- All 11 targeted Android/receiver regression scripts passed, including actual Kotlin timing-accounting and Activity attach-callback execution on the host JVM.
- Native ctest unit target passed.
- Gradle arm64 debug APK built successfully; installed package/version were read back from the phone.
- APK v2 signature verification passed.
- APK ZIP alignment and embedded native ELF LOAD-segment 16 KiB alignment passed.
- Final 20-second scoped stream capture: 722 measured decoded frames, weighted decoder-path average 3.6680 ms, maximum 9.37 ms; zero input queue failures/timeouts and zero FEC failures within that capture.
- Live attach log confirmed joystick unbuffering; scoped fatal-exception count was zero.
- Final SurfaceFlinger snapshot: 127 valid rows, reported refresh interval 16,666,664 ns; input-PTS-to-presentation average 15.3854 ms and ready-to-presentation average 11.5596 ms. These presentation timestamps are not a camera-based input-to-photon measurement.

At 60 FPS a frame period is 16.6667 ms. Console game/encoder/network/display stages still prevent literal zero end-to-end delay. Further claims require testing the whole path, ideally with high-speed video of a physical button/stick action and the phone's visible response.

## Evidence

- `build-controller-baseline.txt` / `.json`
- `build-controller-lowlatency.txt` / `.json`
- `build-controller-final.json`
- `build-latency-final-v5.5.txt` / `.json`
- `build-latency-final-live.txt`
- `build-surface-latency-final.txt` / `.json`
- `build-apk-v5.5.log`
- `test/android-controller-timing-test.py`
- `test/android-controller-unbuffered-test.py`

## References

- Android public API: https://developer.android.com/reference/android/view/View#requestUnbufferedDispatch(int)
- AOSP View implementation: https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/core/java/android/view/View.java
- AOSP batching implementation: https://android.googlesource.com/platform/frameworks/native/+/refs/heads/main/libs/input/InputConsumer.cpp

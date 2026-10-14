# Chiaki-Up HEVC input framing investigation

Source checkout: /home/jc/chiaki-up-hevc-fix
Base: gameblabla/chiaki-up, 86e38bf (separate clone; DeepSeek checkout untouched).
APK: /home/jc/dl/chiaki-up-hevc-test-arm64.apk
Package: com.gameblabla.chiaki.hevcfix
Label: Chiaki-Up HEVC Test
Version: 2.1.1-hevc-test (upstream CMake version is 2.1.1).
ABI: arm64-v8a, minimum Android API 30.
SHA256: fa476876a5f5dcdf0430fbcfd58cc3fe3d993b50492940910f74bc69e3220f57

## Confirmed source defects versus unconfirmed playback cause

Original Android input callback cuts access units to fit codec buffers, queues every fragment with flags=0, and increments PTS per fragment. Android requires access-unit boundaries unless BUFFER_FLAG_PARTIAL_FRAME is used. Equal PTS by itself is NOT the documented batching mechanism. Documentation: https://developer.android.com/reference/android/media/MediaCodec#BUFFER_FLAG_PARTIAL_FRAME

This is a reproducible submission defect. No connected Android device or PS5 HEVC capture was available, so whether the reported stream actually crosses input capacity remains unconfirmed. The every-few-seconds cadence does not establish that overflowing keyframes are responsible. HEVC keyframes need not be larger than AVC keyframes in general; actual sample sizes and codec capacities matter.

Original code also shadows the boolean result with media_status_t, logs queue errors but returns success, dereferences null input buffers, and loops without progress if capacity is zero.

## Candidate correction

- Request max-input-size = max(2 MiB, width*height*3/2), capped at INT32_MAX. At 1080p the request is 3,110,400 bytes. This is a sizing hint, not a guaranteed capacity or universal encoded-frame upper bound.
- Queue whole samples only, with one timestamp per queued sample. No unmarked arbitrary fragmentation.
- If actual capacity is insufficient, queue an empty non-EOS buffer to return ownership, then return false without submitting any frame bytes. The receiver can recognize the unsuccessful frame and report its missing/corrupt range on subsequent frame processing. This fallback can still drop frames; it does not make an undersized decoder work.
- Return false for initialization, dequeue, input-pointer/capacity, and queue failures.
- Log requested size, first actual input capacity, and failed sample size/capacity.
- Do not bundle realtime-priority, low-latency, network, or rendering changes: keep the candidate attributable to framing/capacity.

Separate debug package allows coexistence with the installed Chiaki-Up. FileProvider manifest authority and runtime authority use the actual application ID. The test app has separate settings/registration storage. Export/import the existing hosts or register again; do not uninstall the original app.

## Verified

- Regression harness compiles the actual C input callback against fake MediaCodec API functions. Original code: 3/8 scenarios passed; candidate: 8/8 passed. Covers complete frames, oversize rejection, queue failure, input timeout, uninitialized codec, zero capacity, null input pointer, empty sample, timestamp advancement and mutex balance. These are submission tests, NOT hardware decoding tests.
- Actual MediaFormat setup block compiled/exercised at 720p, 1080p and 2160p; requested capacities matched expectations.
- NDK r29 arm64 API30 syntax check succeeded with -Wall -Wextra -Werror.
- Existing host unit binary: 94/94 tests passed; CTest aggregate 1/1 passed.
- Gradle assembleDebug completed successfully.
- APK Signature Scheme v2 verified with apksigner.
- zipalign -c -P 16 4 succeeded; all native ELF LOAD segments have 0x4000 alignment. Packaged FileProvider and AndroidX startup authorities use the separate test package ID.
- Packaged APK has the distinct ID/label, arm64 ABI, and no testOnly flag. Actual native library contains the new diagnostic strings.
- Copied APK byte-for-byte to /home/jc/dl and hashed.

## Build environment / reproducibility

Portable JDK: /home/jc/.local/opt/jdk17
SDK: /home/jc/.local/opt/android-sdk
SDK components: platform 35, build-tools 35.0.0, CMake 3.22.1, NDK 29.0.14206865.
Required submodules: oboe, gf-complete, jerasure, nanopb; munit for host tests.

Pinned Oboe uses -Ofast with -Werror; recent Clang rejects that combination. The only Oboe edit replaces -Ofast with equivalent -O3 -ffast-math. Patch saved as oboe-ndk29.patch; this is a modified submodule file, not a changed submodule revision.

Nanopb 0.4.6 requires legacy protobuf reflection and pkg_resources. Build-only Python packages installed in .build-python: protobuf==3.20.3 and setuptools<81. System protoc 36.1 generated incompatible nanopb_pb2.py. Portable protoc 3.20.3 is under .build-python/protoc. Regenerate only the generator's Python definitions with the matching compiler before building:

    .build-python/protoc/bin/protoc --python_out=third-party/nanopb/generator/proto -Ithird-party/nanopb/generator/proto -I.build-python/protoc/include third-party/nanopb/generator/proto/nanopb.proto

No protocol schema is changed. The generated Python definitions are ignored build files. Host CMake additionally pins PROTOC to the portable binary and CMAKE_C_STANDARD=11 because the old munit uses ATOMIC_VAR_INIT removed from C23.

APK build from checkout root:

    PYTHONPATH=/home/jc/chiaki-up-hevc-fix/.build-python JAVA_HOME=/home/jc/.local/opt/jdk17 ANDROID_HOME=/home/jc/.local/opt/android-sdk android/gradlew -p android :app:assembleDebug --max-workers=4 --console=plain

Use the standard debug build ABI filter, not -Pandroid.injected.build.abi: the injected IDE property produced an intermediate APK marked testOnly, which cannot be installed normally from Android's file manager. The delivered APK was rebuilt without that property.

## Phone acceptance test (not yet performed)

1. Install the separate HEVC Test APK. Keep original Chiaki-Up installed for A/B.
2. Import/register the PS5, enable session logging, and match the original settings: H.265, 1080p, 60fps, same bitrate and network.
3. Play the same moving scene for several minutes, then compare original HEVC and candidate HEVC. Also check candidate H.264 for regressions.
4. If corruption persists, export the session log from the candidate. Look for:
   - Requesting video input buffer size
   - Video decoder input capacity
   - Cannot submit complete video sample
   - Failed to get input buffer
   - AMediaCodec_queueInputBuffer() failed
   - Missing unit / missing or corrupt frame(s) / FEC failure

If sample-capacity errors persist, the larger hint was ignored or still insufficient: rejecting frames is safe but cannot eliminate stutter. If there are no capacity errors, do not continue claiming the framing defect caused this phone's issue. Investigate packet loss/FEC and hardware codec behavior. The current receiver explicitly permits FEC-failed frames to reach the decoder (FLUSH_CORRUPT_FRAMES); missing units are concatenated out by frameprocessor.c. That is a separate credible corruption path, deliberately left unchanged without stream evidence.

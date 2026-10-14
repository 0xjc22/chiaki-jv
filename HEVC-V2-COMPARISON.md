# HEVC candidate v2: comparison with DeepSeek's finished build

APK: /home/jc/dl/chiaki-up-hevc-lowlatency-v2-arm64.apk
SHA256: b87645181b0dbb075e1a223cc7deda9c5d2830a770e487faa98f5bb5d7437d38
Package: com.gameblabla.chiaki.hevcfix
Label: Chiaki-Up HEVC Test 2
Version: 2.1.1-hevc-lowlatency-v2, versionCode 18

The original v1 APK remains at /home/jc/dl/chiaki-up-hevc-test-arm64.apk.
V2 updates v1's separate package without deleting its data. It coexists with DeepSeek's com.gameblabla.chiaki package.

## Comparison based on actual source/artifacts

DeepSeek source was moved to /home/jc/.local/opt/chiaki-android-build/chiakiup.
Its delivered APK is /home/jc/chiaki-up-fix-debug.apk, SHA256 ce441aec0f3f9eebcd3daad4b158eb6c6f4760f3d29c55f47b66c3a06e9c6c6f.

DeepSeek's diff requests realtime priority and 4MiB input buffers, moves PTS advancement outside the split loop, but still queues arbitrary fragments with flags=0. It still returns success after a queue error due to shadowed status handling, and retains null/zero-capacity hazards. It adds no actual codec-name/capacity logging. Its larger requested buffer may prevent fragmentation; there is no phone evidence that a split is occurring. The user reports remaining stutter with that APK.

This checkout uses whole access units only, checked real capacity, truthful failure returns, and a max-input-size hint with a 2MiB floor and width*height*3/2 scaling (3,110,400 bytes at 1080p). It is not correct to say it requests a larger buffer than DeepSeek at 1080p: DeepSeek requests 4MiB. Neither hint guarantees actual capacity.

The host callback test reports 2/8 passed for DeepSeek source, versus 8/8 here. Some scenarios encode this checkout's intentional conservative design (reject oversize / leave PTS unchanged for an empty sample); the count is NOT a hardware-decoding comparison or a measurement of actual playback quality. Queue failure and invalid buffers are genuine safety/correctness checks.

## New v2 experiment

Only the new functional decoder mode relative to v1 is Android's official low-latency request, enabled for HEVC and not AVC:

    AMediaFormat_setInt32(format, AMEDIAFORMAT_KEY_LOW_LATENCY, 1);

Google's documentation says a supporting driver must return decoded frames as soon as the coding standard allows, without waiting for later input, and stay awake. This is distinct from realtime priority. See https://source.android.com/docs/core/media/low-latency-media . Moonlight Android's MediaCodecHelper also tries the official low-latency setting first; no proprietary vendor keys or undocumented SoC assumptions are added here.

If configure rejects the option, v2 recreates the decoder and retries with low-latency=0. If normal configure also fails, the real error is retained. A successful configure does not prove the driver honors the option. The APK logs implementation name and input format, in addition to requested/actual input capacity and sample failure sizes.

No network/FEC, rendering, target SDK, buffer sizing, or bitrate changes are bundled into this v2 experiment relative to v1. DeepSeek's checkout/artifact is untouched.

## Verified execution

- Low-latency configuration test was red before the change, then passed four cases: HEVC request, unchanged AVC mode, rejected optional mode fallback, and true configuration failure.
- All eight actual-input-callback host scenarios pass.
- Input-size configuration test passes at 720p/1080p/2160p.
- Full decoder compiles under the real NDK29 arm64/API30 headers with -Wall -Wextra -Werror.
- Existing CTest/native suite passes (the unit binary contains 94 cases, verified during v1 work).
- Gradle assembleDebug succeeds; build-apk-v2.log retains output.
- APK v2 signature verifies, ZIP16KiB alignment verifies, native ELF LOAD segments are at least 0x4000 aligned, and no testOnly flag is present.
- Packaged library contains the actual low-latency request and codec-name diagnostic strings; version/label/ABI verified.
- Copied APK to /home/jc/dl and verified bytes/hash.

No Android device is connected. The user opted to self-test rather than provide USB diagnostics. This is a tested candidate, not a confirmed solution for the Fold's remaining stutter.

## Phone acceptance

Install the separate test APK without uninstalling DeepSeek's version. Import/register the PS5. Use the same H.265, 1080p/60 and bitrate as the prior test. Compare the same moving scene for several minutes. Report horizontal distortion separately from isolated frame hitches and input latency. Also test H.264 for regressions.

If it still fails, export Settings -> session logs if willing. The implementation/name, input capacity, configure fallback and queue/FEC errors can prevent another blind experiment. AVC working does not eliminate codec-specific network/FEC effects. Previous reports that Axixi was smooth are useful A/B evidence, but do not prove which source/build delta caused the difference.

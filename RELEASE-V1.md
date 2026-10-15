# chiaki-jv — Version 1 (v1.1.2)

Fork of [gameblabla/chiaki-up](https://github.com/gameblabla/chiaki-up) at upstream commit 86e38bf, hardened for HEVC streaming and cellular remote play. Developed and verified on a Samsung Z Fold 8 streaming from a PS5 over LAN and over a WireGuard cellular VPN (FreshTomato 2026.3 router).

Repository: https://github.com/0xjc22/chiaki-jv
Release branch: chiaki-jv (default)
Tags: v1.0.0 (first cut), v1.0.1 (review hardening), v1.1.0 (SELECT remap), v1.1.1 (decoder/recovery hardening), v1.1.2 (current release)

## v1.1.2 changes

- Audio safety: balance decoder locking on input failure; validate codec setup, callbacks, input capacity and PCM output ranges/offsets; reject oversized compressed packets instead of splitting them; do not start an Oboe stream after opening fails. Teardown uses bounded dequeue waits and an atomic shutdown request rather than depending on EOS delivery; a failed input queue quarantines that codec until explicit replacement.
- Frame assembly: validate slot bounds and per-frame metadata; propagate allocation/insertion failures; reject malformed padding, missing/short source units and empty access units; preserve real FEC repair and separately count late network receipts.
- Loss accounting: synchronize sequence updates, use wrap-safe distances, suppress duplicates and allow bounded same-interval reordering. Reports finalize gaps on reset; packets arriving after that interval cannot retroactively repair it.
- Surface switching: only replace the owned window after a successful codec switch, releasing rejected candidate references without changing the active decoder.
- Add four host regression scripts, including real Jerasure/gf-complete frame-repair fixtures; make existing Kotlin host tests honor JAVA_HOME rather than the old machine's absolute path.
- No controller mappings, profiles, rumble, touchpad features, bitrate adaptation, watchdog or reordering-buffer feature was added.

See RELEASE-V1.1.2-VERIFICATION.md for current build/test/review evidence and remaining limits.

## v1.1.1 changes

- Release native-window references during decoder teardown and surface removal.
- Dispatch key-only L2/R2 press and release immediately; SELECT remains mapped to the touchpad button.
- Handle MediaCodec output-format/buffer notifications without false error logs.
- Retry pending IDR recovery after two seconds of continued frame rejection; rate-limit all attempts, including failed sends, to 500 ms. Decoder callback rejection now uses the same recovery policy. Callback acceptance still closes the episode as an approximation, not confirmation that an IDR was decoded or displayed.
- Verify APKs in place without overwriting prior artifacts, with explicit identity, signing, architecture, ELF range and alignment checks.
- Strengthen host regressions and correct the MTU/backlog documentation. See [REVIEW-FOLLOWUP.md](REVIEW-FOLLOWUP.md) for the review findings and remaining limits.

## v1.1.0 changes

- The controller SELECT button now maps to the PS5 touchpad press (BUTTON_TOUCHPAD) instead of Share, for games that open menus via the touchpad. Momentary like any other button: held = pressed, released = up, composes with face buttons. Share is no longer bound to a controller button.

## Artifacts

v1.1.2 debug APK (separate package, installs next to the upstream app and updates earlier HEVC builds; original debug signing certificate preserved):
- Path: /home/darkin/herm/releases/chiaki-up-hevc-v1.1.2-arm64.apk
- SHA256: 3ee90523e3c5c578842888abf8c2d62ba1382e88fc9510c3fceac24b30c06abc
- Package: com.gameblabla.chiaki.hevcfix
- versionCode 34, versionName 1.1.2-hevcfix
- Label: Chiaki-Up HEVC 1.1.2
- arm64-v8a, minSdk 30, debug-signed, v2 signature, ZIP/ELF 16 KiB aligned

## What is fixed or added

Video pipeline
- Complete access units are queued to MediaCodec instead of arbitrary fragments, with real input-capacity validation and honest queue-failure reporting. Oversized access units are rejected rather than fed as corrupt prefixes.
- HEVC requests Android's explicit low-latency mode. Any configure rejection (low-latency key, max-input-size hint, or anything else) recreates the codec and retries with a minimal mime/width/height format, so an optional hint can never make the session fatal.
- Input dequeue retries up to three attempts so a transient buffer shortage does not cost a whole access unit (usually the keyframe recovery depends on).
- Incomplete or FEC-failed frames are dropped before decoding instead of poisoning decoder reference pictures. Recovery requests are rate-limited to one attempt per 500 ms. A pending successful request suppresses further requests for two seconds while rejection continues; callback acceptance clears the episode without proving keyframe decoding.
- Frames arriving while no decoder exists are discarded silently-by-design instead of being reported corrupt, so a surface detach does not spam the console with per-frame corrupt reports.
- The stream MTU advertised to the PS5 is capped at 1280. With IPv4, 1280 bytes plus 28 bytes of UDP/IP headers fits the tested router's 1420-byte WireGuard interface MTU; that interface MTU already measures inner packets, so WireGuard encapsulation must not be subtracted again. This reduces fragmentation on the tested path, not every possible tunnel or smaller path MTU. Before this change the investigation observed fragmented video traffic and widespread cellular HEVC frame damage.
- Android encrypted-stream receive buffer requests 4 MiB (the test phone accepted 8 MiB; Linux doubles the request for sk_rcvbuf accounting). A kernel clamp below the request now logs a warning instead of silently under-provisioning, a failed setsockopt falls back to the default buffer instead of aborting the connect, and the log line identifies which socket it describes.

Decoder teardown
- kill_decoder no longer deletes the codec while the receiver thread may be inside a codec call, and always joins the output thread before deletion.
- set_surface(NULL) no longer deadlocks on the codec mutex and no longer leaks the lock when no codec exists.
- The output thread logs a persistent codec error once and backs off instead of spinning at 100%.

Input latency
- Joystick-class input is dispatched unbuffered so remote-game stick input is not held for UI vsync batching. The request is re-applied on window refocus and whenever batched delivery is observed, so a view-focus change cannot silently revert the feature.
- Android input delivery age is instrumented (event timestamp to app handling) with an idle-gap reset so reconnects do not emit misleading one-sample reports.

Android build and packaging
- Debug builds use a separate applicationIdSuffix so test builds install next to the original package.
- CoordinatorLayout behavior classes are fully qualified so the suffixed package inflates instead of crashing on startup.
- Oboe submodule builds with -O3 -ffast-math instead of -Ofast for NDK 29 compatibility, pinned to the companion fork github.com/0xjc22/oboe (branch chiaki-jv, immutable tag chiaki-jv-n1), and .gitmodules points at that fork so the repo builds standalone.
- Gradle wrapper pins the distribution checksum.

## Verified measurements

- Decoder path (assembled frame to output): about 3.7 ms average at 60 FPS on the test device.
- Android controller-event delivery: about 1.1 ms average after unbuffered joystick dispatch (buffered baseline 9.7 ms).
- Cellular H.265 before the MTU cap: 984 frames dropped (984 FEC failures) during a 36.4 s capture whose frame indices reached 1710 — a large share of frames damaged, effectively unwatchable. After the cap, playback was confirmed clean by the user.
- H.264 over the same tunnel worked before the cap (user-reported), consistent with its smaller frames tolerating the fragmentation.
- The IDR request path is verified by host tests encoding the real message; it has not been observed firing on a live stream yet, so live behavior claims remain user-level only.

## Known notes

- Cellular quality still depends on carrier loss and jitter; on a weak link, lower resolution/bitrate in the app.
- The PS5 must be reachable at the manual-host IP through the VPN; discovery broadcasts do not cross tunnels.
- The enlarged OS receive queue can accumulate playback latency during a long consumer stall. Linux's doubled buffer accounting is not usable video-payload capacity; queue duration depends on bitrate and packet overhead. The receiver rejects damaged frames but does not discard complete queued frames by age.
- chiaki-ng's IDR recovery was the reference for IDRREQUEST handling; its connect-info enable toggle is not exposed in this fork yet.

## Tests

Host regression scripts (20/20 pass at v1.1.2; extracted-source/API-fake tests are not Android hardware acceptance):
- android-audio-safety-test.py (26 cases, including real pthread shutdown checks)
- frame-assembly-validation-test.py (real Jerasure/gf-complete repair, malformed data, allocation failure and receiver fixtures; also passed ASan/UBSan)
- packet-stats-accounting-test.py (startup, duplicates, reorder, interval reset and wrap)
- android-video-surface-switch-test.py (transactional switch and window ownership)
- android-video-input-test.py (8/8 submission scenarios)
- android-video-format-test.py (format sizing + low-latency keys)
- android-video-low-latency-test.py (configure fallback semantics)
- android-video-scheduling-test.py (scheduling left automatic)
- android-video-clock-test.py (monotonic clock)
- android-video-output-timing-test.py (latency aggregation)
- android-video-teardown-test.py (kill_decoder/set_surface locking and ordering)
- android-udp-buffer-test.py (receive-buffer setup, clamp warning, desktop unchanged)
- video-receiver-corruption-test.py (rejection bookkeeping, IDR throttle/latch/episode)
- stream-idr-request-test.py (real nanopb IDRREQUEST encoding)
- session-mtu-cap-test.py (MTU cap)
- android-layout-package-test.py (behavior-class resolution)
- android-controller-timing-test.py (timing accounting incl. idle reset)
- android-controller-unbuffered-test.py (attach/refocus re-request)
- android-controller-select-touchpad-test.py (added in v1.1.0; SELECT down/up and composed buttons)
- apk-artifact-verifier-test.py (8 isolated verifier cases, including malformed ELF rejection)
- android-phone-stream-smoke.py (device-only; skips without adb)
- verify-apk-artifact.py (APK signature/alignment/native tokens)

Native suite: build-host ctest 1/1 (94/94 unit tests).

The v1.1.2 offline Android build and APK signature/identity/alignment checks pass, with the same signing certificate as v1.1.1. CTest covers the native unit suite only; the Python regression scripts are a separate gate. No phone acceptance was performed for this release, so live playback acceptance is still unperformed. Build success does not establish bit-for-bit reproducibility.

Build prerequisites: JDK17, SDK35/build-tools 35.0.0, CMake 3.22.1, NDK 29.0.14206865, plus a Python protobuf-3.20.3 toolchain for the old nanopb generator (see HEVC-INVESTIGATION.md and the test scripts).

## Upstream

- gameblabla/chiaki-up, base commit 86e38bf.
- WireGuard remote access validated against FreshTomato 2026.3 (Netgear R6700v3), wg0 MTU 1420, phone tunnel MTU 1280.

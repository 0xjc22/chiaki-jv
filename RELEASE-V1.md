# chiaki-jv — Version 1

Fork of [gameblabla/chiaki-up](https://github.com/gameblabla/chiaki-up) at upstream commit 86e38bf, with a series of HEVC robustness, input-latency and remote-play fixes developed and verified on a Samsung Z Fold 8 streaming from a PS5 over LAN and over a WireGuard cellular VPN.

Repository: https://github.com/0xjc22/chiaki-jv
Release branch: chiaki-jv
Tag: v1.0.0

## What is fixed or added

Video pipeline
- Complete access units are queued to MediaCodec instead of arbitrary fragments, with real input-capacity validation and honest queue-failure reporting. Oversized access units are rejected rather than fed as corrupt prefixes.
- HEVC requests Android's explicit low-latency mode with codec recreation and normal-mode fallback when configuration is rejected.
- Incomplete or FEC-failed frames are dropped before decoding instead of poisoning decoder reference pictures, with IDR requests sent to the console (throttled to one per 500 ms) so the decoder recovers instead of stalling black after damage.
- The stream MTU advertised to the PS5 is capped at 1280. PS5 video packets then fit inside a 1420-MTU WireGuard tunnel without fragmentation. Before this change every video packet fragmented on the tunnel and cellular jitter destroyed virtually every HEVC frame; H.264 was affected less because its frames are smaller.
- Android encrypted-stream receive buffer enlarged to 4 MiB, with the protocol advertised window unchanged.

Input latency
- Joystick-class input is dispatched unbuffered so remote-game stick input is not held for UI vsync batching. Measured Android event delivery delay dropped from about 9.7 ms to about 1.1 ms on the test device.
- Android input delivery age is instrumented and logged (event timestamp to app handling).

Android build and packaging
- Debug builds use a separate applicationIdSuffix so test builds install next to the original package.
- CoordinatorLayout behavior classes are fully qualified so the suffixed package inflates instead of crashing on startup.
- Oboe submodule builds with -O3 -ffast-math instead of -Ofast for NDK 29 compatibility. The submodule is pinned to a commit on the 0xjc22/oboe fork (branch chiaki-jv); the original patch is kept as oboe-ndk29.patch.
- Host regression tests cover decoder submission, format configuration, low-latency fallback, UDP buffer setup, receiver corruption handling, clock/timing accounting, controller dispatch, IDR encoding and the MTU cap.

## Verified measurements

- Decoder path (assembled frame to output): about 3.7 ms average at 60 FPS on the test device.
- Android controller-event delivery: about 1.1 ms average after unbuffered joystick dispatch (baseline 9.7 ms).
- Cellular H.265: every frame was damaged before the MTU cap (984/984 frames dropped in one 30 s capture); after the cap the user reported clean playback.
- H.264 over the same tunnel worked before the cap, consistent with smaller frames tolerating the fragmentation.

## Known notes

- Cellular quality still depends on carrier loss and jitter; if a cell link is poor, lower resolution/bitrate in the app.
- The PS5 must be reachable at the manual-host IP through the VPN; discovery broadcasts do not cross tunnels.
- chiaki-ng's IDR recovery was used as the reference for IDRREQUEST handling; the equivalent connect-info toggle is not exposed in this fork yet.
- Build prerequisites: JDK17, SDK35, CMake 3.22.1, NDK 29.0.14206865, plus the local Python toolchain for the old nanopb generator (see the test scripts and build notes in docs).

## Upstream

- gameblabla/chiaki-up, base commit 86e38bf.
- WireGuard remote access was validated against FreshTomato 2026.3 (Netgear R6700v3) with a 1420-MTU wg0 and a phone tunnel MTU of 1280.

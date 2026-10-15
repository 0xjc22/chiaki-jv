# v1.1.2 verification and review

Baseline: v1.1.1, `07e7f84c04dcc2a77d2f34cee872ed61e9f329dd`. Actual fork parent: gameblabla/chiaki-up `86e38bfba0c942da2a05b2e1e175f53dbfad0cc4`.

## Scope

Audio safety/lifecycle, frame assembly validation, packet-loss accounting and transactional video surface switching. No controller mappings/profiles/rumble/touchpad features, adaptive bitrate, watchdog or AV reorder-buffer feature. The packet-statistics reorder history only changes measurement, not delivery order.

## Independent review and follow-up

Three GPT-6 Luna reviewers independently covered audio, frame assembly and packet statistics/surface ownership. Parent inspected the implementation and all reports, reran the supplied probes/tests, and applied a further correction through a fresh implementation worker.

- Audio review identified uncertain input-buffer ownership after a queue failure and an inherited EOS-dependent shutdown hang. Fixed with per-codec input quarantine, atomic shutdown request, bounded input/output dequeue waits, unlocked join-before-delete and serialized callback access. Lifecycle tests include real pthread/no-output cases and PCM consumption before codec buffer release.
- Frame review flagged the inherited 256-slot limit against wider wire fields. Parent checked the actual engine: `CHIAKI_FEC_WORDSIZE=8`; bundled `cauchy_original_coding_matrix(255,1,8)` succeeds while `(256,1,8)` returns NULL. Retained the engine-supported bound rather than assuming a larger wire field guarantees compatible FEC.
- Statistics/surface reviewer found no release-blocking defect. Parent checked sequence interval boundaries, duplicate/wrap arithmetic and candidate-window ownership.
- A fresh fourth GPT-6 Luna reviewer reviewed the complete implementation including the audio follow-up. Final machine-readable verdict: passed=true, security_concerns=[], logic_errors=[]. It independently reran all 20 host scripts and 26 audio cases. Device acceptance remains unperformed.

## Executed verification

- Every standalone `test/*-test.py` script: **20/20 exit 0**. Run individually; unittest discovery does not execute this suite.
- Audio safety suite: **26 tests**, including mutex balance, failed setup/open, capacity/range checks, synchronous borrowed PCM consumption, input quarantine/reset, recursive-lock join ordering and real threaded bounded shutdown.
- Frame assembly suite: actual bundled Jerasure/gf-complete with valid complete/repaired frames, parity-first arrival, malformed padding, duplicates/late receipts, allocation failures and receiver bookkeeping. Passed normally and with **ASan/UBSan + leak detection**.
- Native CMake build succeeded. CTest **1/1**; native unit executable **94/94**, zero skipped.
- Real offline Gradle `:app:assembleDebug` succeeded after the final audio changes, including NDK compilation and APK repackaging. Existing Android/Gradle/OpenSSL deprecation warnings remain.
- APK verifier passed v2 signature, identity/label, no testOnly, ARM64, ZIP/ELF 16 KiB alignment, ELF ranges and expected native tokens.
- Signer certificate SHA256 equals v1.1.1: `63da3efd84adca78bc4e18ee96a19eac92a7123420431ecc81fb4b2543a11611`.
- Refreshed `hevc-decoder.patch` applies to actual upstream files and reconstructs current decoder C/header byte-for-byte.
- Added-lines targeted scan found no secret assignments, shell injection patterns, eval/exec, unsafe pickle loading or conflict markers. Not a whole-program security audit.
- Source whitespace check excludes generated `.patch` context lines; patch application is checked separately.

## Artifact

- File: `chiaki-up-hevc-v1.1.2-arm64.apk`
- Local path: `/home/darkin/herm/releases/chiaki-up-hevc-v1.1.2-arm64.apk`
- SHA256: `3ee90523e3c5c578842888abf8c2d62ba1382e88fc9510c3fceac24b30c06abc`
- Size: 23411388 bytes
- Package: `com.gameblabla.chiaki.hevcfix`
- Version code/name: `34` / `1.1.2-hevcfix`
- Label: `Chiaki-Up HEVC 1.1.2`
- ABI: `arm64-v8a`; minSdk 30; original debug signing key preserved for in-place updates.

## Deliberate limits

No device installation, PS4/PS5 playback, surface recreation on hardware, audio-route switching or performance improvement is claimed. No build bit-for-bit reproducibility claim. The old drive was mounted read-only to restore the original signing key and cached toolchains.

Shutdown discards pending audio instead of guaranteeing a full EOS drain. A failed input queue stops further submissions until explicit codec replacement/new session; this is safe quarantine, not automatic recovery. Codec lifecycle owners must not overlap, session callbacks finish before fini, and callbacks must not initiate teardown. Device APIs that ignore their documented dequeue timeout or block in another driver call remain outside the host liveness guarantee.

The fixed 256-slot FEC capacity remains inherited. Sequence repair is limited to the current reporting interval and at most 255 positions behind its high-water mark; reset finalizes gaps. These measurement policies do not adapt stream quality or retransmit packets.

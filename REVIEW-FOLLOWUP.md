# chiaki-jv follow-up review

Reviewed release HEAD: `31662accbdc0f8424ade5d615b341fcffb78be4a` (`v1.1.0`).
Primary revision range: `v1.0.0` (`d8b2ca0`) → `v1.0.1` (`3d10d62`) → `v1.1.0` (`31662ac`), with original fork changes traced to upstream `86e38bf`.

Eight read-only GPT-6 Luna reviewers covered decoder lifecycle, MediaCodec submission/output, receiver/IDR protocol, networking, controller input, regression harnesses, Android packaging, and cross-component code quality. The parent rechecked findings, reproduced actionable defects, and made local changes. One Luna worker implemented the isolated verifier fix; a tenth fresh Luna reviewer checked the complete follow-up diff. The follow-up source and tests are committed on `chiaki-jv` after v1.1.0. This update does not create a new tag or APK release; installation and live playback acceptance remain unperformed.

## Verdict on the existing revisions

The v1.0.1 hardening is substantially valid, rather than just cleanup:
- Whole-access-unit submission, actual input-capacity checks, and honest submission failure reporting remain intact.
- Optional codec-format rejection recreates the codec and retries a minimal format, including AVC rejection. New tests check recreation order and recreation failure, not merely configuration-call counts.
- Input dequeue retries remain bounded. No-codec callbacks deliberately succeed rather than emit corruption reports.
- Teardown joins the output thread on both EOS-dequeue paths and does not hold the codec mutex across the join. Detaching the pointer under the mutex before deletion protects input callbacks; the previous comment incorrectly claimed deletion itself occurred under the mutex.
- Android stream receive-buffer enlargement is optional; bootstrap/desktop failure semantics and the protocol window remain unchanged. New tests exercise failed setsockopt/getsockopt behavior.
- Empty frame flushes do not request IDR; incomplete/FEC-failed access units are rejected. The IDRREQUEST message is correctly encoded as type 25, flags 1, channel 2.
- Unbuffered joystick requests are issued on attachment, refocus, and evidence of batched delivery. Timing's idle reset remains intact.
- Debug-package authorities, fully qualified CoordinatorLayout behaviors, Gradle wrapper checksum, and the immutable Oboe fork pin remain valid.

The v1.1.0 SELECT change is correct and remains unchanged: Kotlin bit 14 reaches native controller state and touchpad feedback transitions (`0xb1` press / `0x91` release), rather than Share (`0xad` / `0x8d`). It is a physical touchpad-button press, not a synthesized touch position or swipe. Down/up and composition with face buttons are tested. End-to-end controller hardware behavior still requires phone/console acceptance.

## Confirmed findings and adjustments

1. Native-window ownership leak (medium, inherited): decoder teardown/surface removal did not release the reference acquired by ANativeWindow_fromSurface, and a new surface could overwrite the retained pointer. Initialize window ownership explicitly, detach references under the mutex, and release once after codec teardown, including no-codec cleanup and direct fini. Tests verify window release and actual join-before-delete order; they do not claim to simulate real Android concurrency.

2. Key-only L2/R2 transitions lost or delayed (medium, inherited): key dispatch updated trigger values and returned without publishing controller state. Add immediate state publication to both trigger branches. A regression first failed on press/release without any intervening motion event and now passes. SELECT mapping is unchanged.

3. Informational codec statuses misreported (low, introduced by hardening): output-format/buffer notifications were logged as errors and slept unnecessarily. Handle -2/-3 as notifications; treat -1 as no-output with backoff and only log unexpected errors. Tests cover each status, repeated real errors, and existing output timing/EOS behavior.

4. Recovery-latch liveness and send-failure churn (medium, policy edge): a pending request could suppress all later requests during continuous rejection, while failed sends were retried per damaged frame. Preserve the episode latch but permit a retry after two seconds of continued rejection. Separate attempt time from successful-send time and bound failed attempts to 500 ms. Apply the same policy to a false video callback. Tests first failed on pending timeout, failed-send backoff (including monotonic uptime zero), and callback rejection, and now pass. This is bounded recovery policy, not proof of better live playback.

5. Destructive artifact verifier (medium tooling risk): verification deleted/replaced the named published APK before checking it. Verify explicit APKs in place instead; resolve SDK/JDK from arguments/environment, and validate package/version/label, absence of testOnly, explicit v2 signature, ARM64 ELF identity, nonempty load segments, 16 KiB alignment, and native diagnostic tokens. Isolated fixtures do not represent real signing/decoding results. Parent real-APK execution also caught and fixed incorrect default label resolution: the debug resource override must take precedence over main resources.

6. Misleading documentation/patch export: update the current README tag, distinguish separate Python/native test gates, and remove universal fragmentation and stale-backlog draining guarantees. A WireGuard interface MTU describes inner packets; overhead must not be subtracted twice. Complete queued frames are not discarded by age. Regenerate the decoder-only reference patch with both C and required header changes; applying it to actual upstream files reconstructs the current decoder byte-for-byte.

## Verification

Baseline before changes:
- 15/15 standalone host regression scripts passed.
- Native suite: 94/94 tests; CTest 1/1.
- Offline Android debug build passed.
- Build output matched the published v1.1.0 APK hash, identity, v2 signature, and ZIP alignment.

Follow-up execution:
- 16/16 standalone host regression scripts passed, including eight isolated verifier test cases.
- Native rebuild passed; native executable reports 94/94 tests, zero skipped; CTest 1/1 passed.
- Actual offline Gradle assembleDebug passed after native/Kotlin changes, not just extracted-host compilation.
- Real candidate verifier passed signature, identity, testOnly, ZIP/ELF alignment, architecture, and token checks.
- Added-line secret/shell-injection/conflict-marker scan found no matches. This is a targeted scan, not proof that the entire inherited app has no vulnerabilities.
- `git diff --check` passes for source/tests/docs. Generated .patch context lines are excluded from whitespace lint; those files are validated by application instead.
- Decoder patch applies to upstream `86e38bf` and reconstructs current C/header files exactly.

Candidate APK (unreleased; still uses v1.1.0 debug identity, not a version bump):
`/home/jc/chiaki-up-hevc-fix/android/app/build/outputs/apk/debug/app-debug.apk`
SHA256: `0621bce484ee2dccbedd4739844966c4d95183d85ae4bac41a88bfede3bffdc8`

Published artifact remains untouched:
`/home/jc/dl/chiaki-up-hevc-v1.1.0-arm64.apk`
SHA256: `c6548f22333a52860c9f51e57ed720c364220c31dd301a978bcf44dc9c8bb11a`

Execution logs/manifest: `/home/jc/.hermes/cache/scratch/chiaki-jv-review/final-verification.json` (scratch, not durable).

## Remaining limits and deliberate non-changes

- No adb device is connected. Phone smoke is explicitly skipped, not counted as a passing test. Surface destroy/recreate, key-only triggers, SELECT menus, HEVC/AVC, LAN/cellular playback, and real recovery behavior remain acceptance work.
- The callback says whether an access unit was accepted, not whether an IDR was decoded/displayed. It can also deliberately discard frames without a codec. This fork has no receiver-level keyframe confirmation; clearing the latch on callback acceptance is retained and documented as an approximation. No speculative bitstream parser or chiaki-ng decoder architecture was backported.
- Persistent loss is not repaired by an IDR request alone, and a larger queue does not bound playback age. The two-second pending retry is a conservative guardrail requiring live validation, not a measured optimum.
- Concurrent arbitrary surface setters are outside the traced main-thread lifecycle contract. No unsupported concurrency framework was added.
- Existing OpenSSL API, Android lifecycle annotation, and Gradle deprecation warnings remain. They are inherited modernization work, not failures introduced by these fixes.
- CTest runs the native unit suite only; Python scripts are a separate explicit gate. Full Gradle transitive dependency locking/checksum metadata and bit-for-bit reproducible binaries are not established.
- These follow-up changes are source updates, not a new APK release. A release must get a new versionCode/versionName and fresh artifact metadata; never replace or retag v1.1.0.

## Final independent review

The tenth reviewer found no security concerns or further streaming/input logic errors, but correctly rejected the verifier's malformed-ELF handling: non-power-of-two p_align values and PT_LOAD ranges beyond the file could pass. The parent reproduced both false acceptances with failing synthetic-fixture tests, added explicit power-of-two/range checks, then reran all 16 host scripts and actual APK verification successfully. All eight verifier cases pass. The reviewer did not separately re-review that final small verifier-only correction; its previously reported defect is now regression-tested and resolved.

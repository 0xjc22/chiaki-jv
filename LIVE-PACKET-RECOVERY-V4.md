# Live HEVC investigation: packet reception and recovery (v3/v4)

## Captured evidence

Connected Fold uses c2.qti.hevc.decoder. At 1080p the actual decoder input capacity is 8,388,608 bytes. Captures show no oversize submissions, dequeue failures or queue failures. The frame-splitting theory is not supported for these live samples.

Baseline v2.1 receiver logs show failed FEC with missing data units. An initial capture counted 12 FEC failures / 72 Missing unit logs; the later full baseline snapshot counted 36 FEC failures / 141 Missing unit logs. Those are different-duration snapshots, not rates. The app's UDP socket showed 8 kernel drops in /proc/net/udp. Phone ICMP probe: 15/15 replies, average 4.527ms, max17.583ms; this short probe does not rule out streaming packet loss.

The source requests SO_RCVBUF from a_rwnd (102,400 bytes), and packet handling invokes the video callback synchronously. The sender/receiver window advertised on the Takion protocol is a separate concern.

## V3: Android receive-queue capacity

Changed only Android encrypted-stream SO_RCVBUF request to4MiB; bootstrap and advertised window unchanged. Added getsockopt logging. Real phone accepted8MiB for the stream and retained204,800 bytes for bootstrap.

Live30-second V3 capture: five FEC failures, seven FEC successes, twelve Missing unit logs, zero app input-capacity/dequeue/queue errors, zero old-frame packet warnings, zero fatal exceptions. Stream socket's kernel drops were0. User still observed a horizontal distorted line during an overworld transition. Thus eliminating sampled local kernel drops did not eliminate the whole problem. Large scene changes are a plausible burst trigger, not proven causality.

APK saved at /home/jc/dl/chiaki-up-hevc-network-v3-arm64.apk for comparison.

## V4: Do not decode incomplete frames

Baseline receiver defines FLUSH_CORRUPT_FRAMES. frameprocessor.c concatenates received source units while omitting missing units after failed FEC. The resulting truncated access unit still reaches the decoder before the frame is reported corrupt.

Correction: reject failed assembly and FEC-failed samples before callback; set frame_index_prev=current to avoid repeatedly flushing that frame; keep prev_complete unchanged so the existing next-frame corrupt-range report remains intact. Complete and successfully repaired frames continue to decode. No Wi-Fi settings, bitrate, rendering changes, vendor codec keys or new IDR protocol messages were bundled.

This is a correctness/recovery guard, not restoration of lost packets. It may replace distorted output with a brief held frame. Later predictive frames may still depend on a missing reference.

Note for v1.0.1 readers: the IDR-request/recovery backport landed after this v4-era snapshot (see RELEASE-V1.md): stream_connection_send_idr_request plus a throttled, episode-latched call on FEC failure. It is verified by host tests (test/video-receiver-corruption-test.py, test/stream-idr-request-test.py) but has not yet been observed firing on a live stream, so keep it host-verified-only in any claims.

## Verification

- Receive-buffer regression was red for102,400 versus requested4MiB, then green for Android stream, unchanged bootstrap and unchanged desktop behavior.
- Actual receiver flush regression was red because the incomplete frame was delivered, then green in six scenarios: incomplete rejection/bookkeeping, complete delivery, repaired delivery, failed assembly, callback rejection and frame-number wrap.
- Existing input/format/low-latency/layout tests pass; rebuilt host CTest passes.
- Android build succeeds, installed via adb -r without clearing registration/settings. Startup/process survival and native library initialization verified.
- V4 reconnected to the registered PS5 and liveHEVC input began with8MiB codec capacity and8MiB socket buffer.
- Live trace at23:55:09.241: FEC failed for frame282, then 'Dropping incomplete video frame282 before decoding', then existing corrupt report282..282 on the next frame. The guard was exercised on the actual phone; process remained alive and no fatal/queue/capacity failures were captured. This does not yet establish absence of visible artifacts.
- V4 /proc/net/udp socket sample reports0 kernel drops.
- APK signature and ZIP16KiB alignment verify; no testOnly flag; package/version/native guard string checked.

Current phone: Chiaki-Up HEVC Test4, package com.gameblabla.chiaki.hevcfix, versionCode21, version2.1.1-hevc-recovery-v4.
APK: /home/jc/dl/chiaki-up-hevc-recovery-v4-arm64.apk
SHA256:6a0b17e88afec221581783546e939b83c766b708bd184fa007727d4eb25a83c1

Evidence files in this checkout:
- build-live-hevc-logcat.txt (initial)
- build-live-hevc-baseline-final.txt (later baseline)
- build-live-hevc-v3-start.txt (accepted buffer sizes)
- build-live-hevc-v3-30s.txt (bounded candidate capture)
- build-live-hevc-v4-recovery.txt (actual rejection/reporting)

The user is testing visible corruption in the liveV4 stream. Do not claim the stutter or distortion is solved without that acceptance result.

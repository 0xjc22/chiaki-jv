// SPDX-License-Identifier: LicenseRef-AGPL-3.0-only-OpenSSL

#ifndef CHIAKI_PACKETSTATS_H
#define CHIAKI_PACKETSTATS_H

#include "thread.h"
#include "seqnum.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct chiaki_packet_stats_t
{
	ChiakiMutex mutex;

	// For generations of packets, i.e. where we know the number of expected packets per generation
	uint64_t gen_received;
	uint64_t gen_lost;

	/* Sequence accounting: first observation establishes the stream baseline
	 * and counts as one received/expected packet (no assumed startup loss).
	 * Forward distances must be < 32768; exactly half-range is ambiguous
	 * and ignored. Unique reordered packets repair only the current interval
	 * and only within 256 sequence positions of the high-water mark.
	 * Reset/get(reset=true) finalizes all gaps through seq_max: late packets
	 * from that interval cannot change later reports. get(false) is a snapshot.
	 * History and per-push work are bounded, even over multiple wraps. */
	ChiakiSeqNum16 seq_max;
	bool seq_initialized;
	uint64_t seq_expected;
	uint64_t seq_received;
	uint8_t seq_seen[256];
} ChiakiPacketStats;

CHIAKI_EXPORT ChiakiErrorCode chiaki_packet_stats_init(ChiakiPacketStats *stats);
CHIAKI_EXPORT void chiaki_packet_stats_fini(ChiakiPacketStats *stats);
CHIAKI_EXPORT void chiaki_packet_stats_reset(ChiakiPacketStats *stats);
CHIAKI_EXPORT void chiaki_packet_stats_push_generation(ChiakiPacketStats *stats, uint64_t received, uint64_t lost);
CHIAKI_EXPORT void chiaki_packet_stats_push_seq(ChiakiPacketStats *stats, ChiakiSeqNum16 seq_num);
CHIAKI_EXPORT void chiaki_packet_stats_get(ChiakiPacketStats *stats, bool reset, uint64_t *received, uint64_t *lost);

#ifdef __cplusplus
}
#endif

#endif // CHIAKI_PACKETSTATS_H

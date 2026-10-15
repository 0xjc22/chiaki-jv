// SPDX-License-Identifier: LicenseRef-AGPL-3.0-only-OpenSSL

#include <chiaki/packetstats.h>
#include <chiaki/log.h>
#include <string.h>

CHIAKI_EXPORT ChiakiErrorCode chiaki_packet_stats_init(ChiakiPacketStats *stats)
{
	stats->gen_received = 0;
	stats->gen_lost = 0;
	stats->seq_max = 0;
	stats->seq_initialized = false;
	stats->seq_expected = 0;
	stats->seq_received = 0;
	memset(stats->seq_seen, 0, sizeof(stats->seq_seen));
	return chiaki_mutex_init(&stats->mutex, false);
}

CHIAKI_EXPORT void chiaki_packet_stats_fini(ChiakiPacketStats *stats)
{
	chiaki_mutex_fini(&stats->mutex);
}

static void reset_stats(ChiakiPacketStats *stats)
{
	stats->gen_received = 0;
	stats->gen_lost = 0;
	stats->seq_expected = 0;
	stats->seq_received = 0;
	memset(stats->seq_seen, 0, sizeof(stats->seq_seen));
}

CHIAKI_EXPORT void chiaki_packet_stats_reset(ChiakiPacketStats *stats)
{
	chiaki_mutex_lock(&stats->mutex);
	reset_stats(stats);
	chiaki_mutex_unlock(&stats->mutex);
}

CHIAKI_EXPORT void chiaki_packet_stats_push_generation(ChiakiPacketStats *stats, uint64_t received, uint64_t lost)
{
	chiaki_mutex_lock(&stats->mutex);
	stats->gen_received += received;
	stats->gen_lost += lost;
	chiaki_mutex_unlock(&stats->mutex);
}

CHIAKI_EXPORT void chiaki_packet_stats_push_seq(ChiakiPacketStats *stats, ChiakiSeqNum16 seq_num)
{
	chiaki_mutex_lock(&stats->mutex);
	uint16_t forward = (uint16_t)(seq_num - stats->seq_max);
	if(!stats->seq_initialized)
	{
		stats->seq_initialized = true;
		stats->seq_max = seq_num;
		stats->seq_expected = 1;
		stats->seq_received = 1;
		stats->seq_seen[seq_num % sizeof(stats->seq_seen)] = 1;
	}
	else if(forward > 0 && forward < 0x8000)
	{
		/* Retire reused ring slots before recording the new high-water mark. */
		if(forward >= sizeof(stats->seq_seen))
			memset(stats->seq_seen, 0, sizeof(stats->seq_seen));
		else
			for(uint16_t i = 1; i <= forward; i++)
				stats->seq_seen[(uint16_t)(stats->seq_max + i) % sizeof(stats->seq_seen)] = 0;
		stats->seq_max = seq_num;
		stats->seq_expected += forward;
		stats->seq_received++;
		stats->seq_seen[seq_num % sizeof(stats->seq_seen)] = 1;
	}
	else
	{
		uint16_t behind = (uint16_t)(stats->seq_max - seq_num);
		if(behind < sizeof(stats->seq_seen) && behind < stats->seq_expected
				&& !stats->seq_seen[seq_num % sizeof(stats->seq_seen)])
		{
			stats->seq_seen[seq_num % sizeof(stats->seq_seen)] = 1;
			stats->seq_received++;
		}
	}
	chiaki_mutex_unlock(&stats->mutex);
}

CHIAKI_EXPORT void chiaki_packet_stats_get(ChiakiPacketStats *stats, bool reset, uint64_t *received, uint64_t *lost)
{
	chiaki_mutex_lock(&stats->mutex);

	// gen
	*received = stats->gen_received;
	*lost = stats->gen_lost;

	//CHIAKI_LOGD(NULL, "gen received: %llu, lost: %llu",
	//		(unsigned long long)stats->gen_received,
	//		(unsigned long long)stats->gen_lost);

	// seq
	uint64_t seq_lost = stats->seq_expected - stats->seq_received;
	*received += stats->seq_received;
	*lost += seq_lost;

	//CHIAKI_LOGD(NULL, "seq received: %llu, lost: %llu",
	//		(unsigned long long)stats->seq_received,
	//		(unsigned long long)seq_lost);

	if(reset)
		reset_stats(stats);
	chiaki_mutex_unlock(&stats->mutex);
}

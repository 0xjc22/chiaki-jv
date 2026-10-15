// SPDX-License-Identifier: LicenseRef-AGPL-3.0-only-OpenSSL

#include <chiaki/frameprocessor.h>
#include <chiaki/fec.h>
#include <chiaki/video.h>

#include <jerasure.h>

#include <string.h>
#include <assert.h>

#ifndef _WIN32
#include <arpa/inet.h>
#endif

CHIAKI_EXPORT void chiaki_stream_stats_reset(ChiakiStreamStats *stats)
{
	stats->frames = 0;
	stats->bytes = 0;
}

CHIAKI_EXPORT void chiaki_stream_stats_frame(ChiakiStreamStats *stats, uint64_t size)
{
	stats->frames++;
	stats->bytes += size;
	//float br = (float)chiaki_stream_stats_bitrate(stats, 60) / 1000000.0f;
	//CHIAKI_LOGD(NULL, "bitrate: %f", br);
}

CHIAKI_EXPORT uint64_t chiaki_stream_stats_bitrate(ChiakiStreamStats *stats, uint64_t framerate)
{
	return (stats->bytes * 8 * framerate) / stats->frames;
}

#define UNIT_SLOTS_MAX 256

struct chiaki_frame_unit_t
{
	size_t data_size;
	bool received; // FEC reconstruction is not a received network packet.
};

CHIAKI_EXPORT void chiaki_frame_processor_init(ChiakiFrameProcessor *frame_processor, ChiakiLog *log)
{
	frame_processor->log = log;
	frame_processor->frame_buf = NULL;
	frame_processor->frame_buf_size = 0;
	frame_processor->buf_size_per_unit = 0;
	frame_processor->buf_stride_per_unit = 0;
	frame_processor->units_source_expected = 0;
	frame_processor->units_fec_expected = 0;
	frame_processor->units_source_received = 0;
	frame_processor->units_fec_received = 0;
	frame_processor->unit_slots = NULL;
	frame_processor->unit_slots_size = 0;
	frame_processor->flushed = true;
	chiaki_stream_stats_reset(&frame_processor->stream_stats);
}

CHIAKI_EXPORT void chiaki_frame_processor_fini(ChiakiFrameProcessor *frame_processor)
{
	free(frame_processor->frame_buf);
	free(frame_processor->unit_slots);
}

CHIAKI_EXPORT ChiakiErrorCode chiaki_frame_processor_alloc_frame(ChiakiFrameProcessor *frame_processor, ChiakiTakionAVPacket *packet)
{
	/* Invalidate the previous generation before any fallible operation. Buffers
	 * may be reused, but a failed allocation must never expose stale units. */
	frame_processor->flushed = true;
	frame_processor->units_source_expected = 0;
	frame_processor->units_fec_expected = 0;
	frame_processor->units_source_received = 0;
	frame_processor->units_fec_received = 0;

	if(!packet->is_video || !packet->data || packet->data_size < 2
		|| packet->units_in_frame_total <= packet->units_in_frame_fec
		|| packet->units_in_frame_total > UNIT_SLOTS_MAX
		|| packet->unit_index >= packet->units_in_frame_total)
		return CHIAKI_ERR_INVALID_DATA;

	unsigned int source_expected = packet->units_in_frame_total - packet->units_in_frame_fec;
	size_t unit_size = packet->data_size;
	if(packet->unit_index < source_expected)
	{
		uint16_t padding = ntohs(((chiaki_unaligned_uint16_t *)packet->data)[0]);
		if(unit_size > SIZE_MAX - padding)
			return CHIAKI_ERR_OVERFLOW;
		unit_size += padding;
	}
	if(unit_size > SIZE_MAX - 0xf)
		return CHIAKI_ERR_OVERFLOW;
	size_t stride = (unit_size + 0xf) & ~(size_t)0xf;
	size_t slots = packet->units_in_frame_total;
	if(stride > (SIZE_MAX - CHIAKI_VIDEO_BUFFER_PADDING_SIZE) / slots)
		return CHIAKI_ERR_OVERFLOW;
	size_t frame_size = slots * stride;

	if(slots != frame_processor->unit_slots_size)
	{
		void *new_ptr = realloc(frame_processor->unit_slots, slots * sizeof(ChiakiFrameUnit));
		if(!new_ptr)
			return CHIAKI_ERR_MEMORY;
		frame_processor->unit_slots = new_ptr;
		frame_processor->unit_slots_size = slots;
	}
	if(frame_processor->frame_buf_size < frame_size)
	{
		void *new_ptr = realloc(frame_processor->frame_buf, frame_size + CHIAKI_VIDEO_BUFFER_PADDING_SIZE);
		if(!new_ptr)
			return CHIAKI_ERR_MEMORY;
		frame_processor->frame_buf = new_ptr;
		frame_processor->frame_buf_size = frame_size;
	}
	memset(frame_processor->unit_slots, 0, slots * sizeof(ChiakiFrameUnit));
	memset(frame_processor->frame_buf, 0, frame_size + CHIAKI_VIDEO_BUFFER_PADDING_SIZE);

	frame_processor->buf_size_per_unit = unit_size;
	frame_processor->buf_stride_per_unit = stride;
	frame_processor->units_source_expected = source_expected;
	frame_processor->units_fec_expected = packet->units_in_frame_fec;
	frame_processor->frame_index = packet->frame_index;
	frame_processor->codec = packet->codec;
	frame_processor->adaptive_stream_index = packet->adaptive_stream_index;
	frame_processor->flushed = false;
	return CHIAKI_ERR_SUCCESS;
}

CHIAKI_EXPORT ChiakiErrorCode chiaki_frame_processor_put_unit(ChiakiFrameProcessor *frame_processor, ChiakiTakionAVPacket *packet)
{
	if(!frame_processor->units_source_expected
		|| packet->unit_index >= frame_processor->unit_slots_size)
	{
		CHIAKI_LOGE(frame_processor->log, "Packet's unit index is too high");
		return CHIAKI_ERR_INVALID_DATA;
	}

	if(!packet->is_video || !packet->data || packet->data_size < 2
		|| packet->frame_index != frame_processor->frame_index
		|| packet->codec != frame_processor->codec
		|| packet->adaptive_stream_index != frame_processor->adaptive_stream_index
		|| packet->units_in_frame_total != frame_processor->units_source_expected + frame_processor->units_fec_expected
		|| packet->units_in_frame_fec != frame_processor->units_fec_expected)
	{
		CHIAKI_LOGW(frame_processor->log, "Invalid unit payload or frame metadata");
		return CHIAKI_ERR_INVALID_DATA;
	}

	if(packet->data_size > frame_processor->buf_size_per_unit)
	{
		CHIAKI_LOGW(frame_processor->log, "Unit is bigger than pre-calculated size!");
		return CHIAKI_ERR_INVALID_DATA;
	}

	/* Source units omit zero padding on the wire; parity units include the
	 * entire FEC symbol. Never silently zero-extend truncated parity. */
	if(packet->unit_index < frame_processor->units_source_expected)
	{
		uint16_t padding = ntohs(((chiaki_unaligned_uint16_t *)packet->data)[0]);
		if(padding != frame_processor->buf_size_per_unit - packet->data_size)
			return CHIAKI_ERR_INVALID_DATA;
	}
	else if(packet->data_size != frame_processor->buf_size_per_unit)
		return CHIAKI_ERR_INVALID_DATA;

	ChiakiFrameUnit *unit = frame_processor->unit_slots + packet->unit_index;
	if(unit->received)
	{
		CHIAKI_LOGW(frame_processor->log, "Received duplicate unit");
		return CHIAKI_ERR_INVALID_DATA;
	}

	unit->data_size = packet->data_size;
	unit->received = true;
	if(!frame_processor->flushed)
	{
		memcpy(frame_processor->frame_buf + packet->unit_index * frame_processor->buf_stride_per_unit,
				packet->data,
				packet->data_size);
	}

	if(packet->unit_index < frame_processor->units_source_expected)
		frame_processor->units_source_received++;
	else
		frame_processor->units_fec_received++;

	return CHIAKI_ERR_SUCCESS;
}

CHIAKI_EXPORT void chiaki_frame_processor_report_packet_stats(ChiakiFrameProcessor *frame_processor, ChiakiPacketStats *packet_stats)
{
	uint64_t received = frame_processor->units_source_received + frame_processor->units_fec_received;
	uint64_t expected = frame_processor->units_source_expected + frame_processor->units_fec_expected;
	chiaki_packet_stats_push_generation(packet_stats, received, expected - received);
}

static ChiakiErrorCode chiaki_frame_processor_fec(ChiakiFrameProcessor *frame_processor)
{
	CHIAKI_LOGI(frame_processor->log, "Frame Processor received %u+%u / %u+%u units, attempting FEC",
				frame_processor->units_source_received, frame_processor->units_fec_received,
				frame_processor->units_source_expected, frame_processor->units_fec_expected);


	size_t erasures_count = (frame_processor->units_source_expected + frame_processor->units_fec_expected)
			- (frame_processor->units_source_received + frame_processor->units_fec_received);
	unsigned int *erasures = calloc(erasures_count, sizeof(unsigned int));
	if(!erasures)
		return CHIAKI_ERR_MEMORY;

	size_t erasure_index = 0;
	for(size_t i=0; i<frame_processor->units_source_expected + frame_processor->units_fec_expected; i++)
	{
		ChiakiFrameUnit *slot = frame_processor->unit_slots + i;
		if(!slot->data_size)
		{
			if(erasure_index >= erasures_count)
			{
				// should never happen by design, but too scary not to check
				assert(false);
				free(erasures);
				return CHIAKI_ERR_UNKNOWN;
			}
			erasures[erasure_index++] = (unsigned int)i;
		}
	}
	assert(erasure_index == erasures_count);

	ChiakiErrorCode err = chiaki_fec_decode(frame_processor->frame_buf,
			frame_processor->buf_size_per_unit, frame_processor->buf_stride_per_unit,
			frame_processor->units_source_expected, frame_processor->units_fec_expected,
			erasures, erasures_count);

	if(err != CHIAKI_ERR_SUCCESS)
	{
		err = CHIAKI_ERR_FEC_FAILED;
		CHIAKI_LOGE(frame_processor->log, "FEC failed");
	}
	else
	{
		err = CHIAKI_ERR_SUCCESS;
		CHIAKI_LOGI(frame_processor->log, "FEC successful");

		// restore unit sizes
		for(size_t i=0; i<frame_processor->units_source_expected; i++)
		{
			ChiakiFrameUnit *slot = frame_processor->unit_slots + i;
			uint8_t *buf_ptr = frame_processor->frame_buf + frame_processor->buf_stride_per_unit * i;
			uint16_t padding = ntohs(*((chiaki_unaligned_uint16_t *)buf_ptr));
			if(padding > frame_processor->buf_size_per_unit - 2)
			{
				CHIAKI_LOGE(frame_processor->log, "Invalid source padding (%#x) for unit size (%zu)",
							(unsigned int)padding, frame_processor->buf_size_per_unit);
				err = CHIAKI_ERR_INVALID_DATA;
				break;
			}
			slot->data_size = frame_processor->buf_size_per_unit - padding;
		}
	}

	free(erasures);
	return err;
}

CHIAKI_EXPORT ChiakiFrameProcessorFlushResult chiaki_frame_processor_flush(ChiakiFrameProcessor *frame_processor, uint8_t **frame, size_t *frame_size)
{
	*frame = NULL;
	*frame_size = 0;
	if(frame_processor->units_source_expected == 0 || frame_processor->flushed)
		return CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_FAILED;
	frame_processor->flushed = true;

	ChiakiFrameProcessorFlushResult result = CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_SUCCESS;
	if(frame_processor->units_source_received < frame_processor->units_source_expected)
	{
		if(!frame_processor->units_fec_expected
			|| frame_processor->units_source_received + frame_processor->units_fec_received < frame_processor->units_source_expected
			|| chiaki_frame_processor_fec(frame_processor) != CHIAKI_ERR_SUCCESS)
			return CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_FEC_FAILED;
		result = CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_FEC_SUCCESS;
	}

	/* Validate every source before compacting any bytes. A successful FEC
	 * operation alone does not establish that its output is a valid AU. */
	size_t total = 0;
	for(size_t i=0; i<frame_processor->units_source_expected; i++)
	{
		ChiakiFrameUnit *unit = frame_processor->unit_slots + i;
		if(unit->data_size < 2 || unit->data_size > frame_processor->buf_size_per_unit)
			return CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_FEC_FAILED;
		uint8_t *buf = frame_processor->frame_buf + i * frame_processor->buf_stride_per_unit;
		uint16_t padding = ntohs(((chiaki_unaligned_uint16_t *)buf)[0]);
		if(padding != frame_processor->buf_size_per_unit - unit->data_size)
			return CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_FEC_FAILED;
		total += unit->data_size - 2;
	}
	if(!total)
		return CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_FEC_FAILED;

	size_t cur = 0;
	for(size_t i=0; i<frame_processor->units_source_expected; i++)
	{
		size_t part_size = frame_processor->unit_slots[i].data_size - 2;
		uint8_t *buf = frame_processor->frame_buf + i * frame_processor->buf_stride_per_unit;
		memmove(frame_processor->frame_buf + cur, buf + 2, part_size);
		cur += part_size;
	}
	chiaki_stream_stats_frame(&frame_processor->stream_stats, (uint64_t)cur);
	*frame = frame_processor->frame_buf;
	*frame_size = cur;
	return result;
}

// SPDX-License-Identifier: LicenseRef-AGPL-3.0-only-OpenSSL

#include <chiaki/videoreceiver.h>
#include <chiaki/session.h>
#include <chiaki/streamconnection.h>
#include <chiaki/time.h>

#include <string.h>

static ChiakiErrorCode chiaki_video_receiver_flush_frame(ChiakiVideoReceiver *video_receiver);

CHIAKI_EXPORT void chiaki_video_receiver_init(ChiakiVideoReceiver *video_receiver, struct chiaki_session_t *session, ChiakiPacketStats *packet_stats)
{
	video_receiver->session = session;
	video_receiver->log = session->log;
	memset(video_receiver->profiles, 0, sizeof(video_receiver->profiles));
	video_receiver->profiles_count = 0;
	video_receiver->profile_cur = -1;

	video_receiver->frame_index_cur = -1;
	video_receiver->frame_index_prev = -1;
	video_receiver->frame_index_prev_complete = 0;

	chiaki_frame_processor_init(&video_receiver->frame_processor, video_receiver->log);
	video_receiver->packet_stats = packet_stats;
	video_receiver->idr_request_prev_ms = 0;
	video_receiver->idr_request_attempt_prev_ms = 0;
	video_receiver->idr_request_attempted = false;
	video_receiver->idr_pending = false;
}

CHIAKI_EXPORT void chiaki_video_receiver_fini(ChiakiVideoReceiver *video_receiver)
{
	for(size_t i=0; i<video_receiver->profiles_count; i++)
		free(video_receiver->profiles[i].header);
	chiaki_frame_processor_fini(&video_receiver->frame_processor);
}

CHIAKI_EXPORT void chiaki_video_receiver_stream_info(ChiakiVideoReceiver *video_receiver, ChiakiVideoProfile *profiles, size_t profiles_count)
{
	if(video_receiver->profiles_count > 0)
	{
		CHIAKI_LOGE(video_receiver->log, "Video Receiver profiles already set");
		return;
	}

	memcpy(video_receiver->profiles, profiles, profiles_count * sizeof(ChiakiVideoProfile));
	video_receiver->profiles_count = profiles_count;

	CHIAKI_LOGI(video_receiver->log, "Video Profiles:");
	for(size_t i=0; i<video_receiver->profiles_count; i++)
	{
		ChiakiVideoProfile *profile = &video_receiver->profiles[i];
		CHIAKI_LOGI(video_receiver->log, "  %zu: %ux%u", i, profile->width, profile->height);
		//chiaki_log_hexdump(video_receiver->log, CHIAKI_LOG_DEBUG, profile->header, profile->header_sz);
	}
}

CHIAKI_EXPORT void chiaki_video_receiver_av_packet(ChiakiVideoReceiver *video_receiver, ChiakiTakionAVPacket *packet)
{
	// old frame?
	ChiakiSeqNum16 frame_index = packet->frame_index;
	if(video_receiver->frame_index_cur >= 0
		&& chiaki_seq_num_16_lt(frame_index, (ChiakiSeqNum16)video_receiver->frame_index_cur))
	{
		CHIAKI_LOGW(video_receiver->log, "Video Receiver received old frame packet");
		return;
	}

	// check adaptive stream index
	if(video_receiver->profile_cur < 0 || video_receiver->profile_cur != packet->adaptive_stream_index)
	{
		if(packet->adaptive_stream_index >= video_receiver->profiles_count)
		{
			CHIAKI_LOGE(video_receiver->log, "Packet has invalid adaptive stream index %lu >= %lu",
					(unsigned int)packet->adaptive_stream_index,
					(unsigned int)video_receiver->profiles_count);
			return;
		}
		video_receiver->profile_cur = packet->adaptive_stream_index;

		ChiakiVideoProfile *profile = video_receiver->profiles + video_receiver->profile_cur;
		CHIAKI_LOGI(video_receiver->log, "Switched to profile %d, resolution: %ux%u", video_receiver->profile_cur, profile->width, profile->height);
		if(video_receiver->session->video_sample_cb)
			video_receiver->session->video_sample_cb(profile->header, profile->header_sz, video_receiver->session->video_sample_cb_user);
	}

	// next frame?
	if(video_receiver->frame_index_cur < 0 ||
		chiaki_seq_num_16_gt(frame_index, (ChiakiSeqNum16)video_receiver->frame_index_cur))
	{
		if(video_receiver->packet_stats)
			chiaki_frame_processor_report_packet_stats(&video_receiver->frame_processor, video_receiver->packet_stats);

		// last frame not flushed yet?
		if(video_receiver->frame_index_cur >= 0 && video_receiver->frame_index_prev != video_receiver->frame_index_cur)
			chiaki_video_receiver_flush_frame(video_receiver);

		ChiakiSeqNum16 next_frame_expected = (ChiakiSeqNum16)(video_receiver->frame_index_prev_complete + 1);
		if(chiaki_seq_num_16_gt(frame_index, next_frame_expected)
			&& !(frame_index == 1 && video_receiver->frame_index_cur < 0)) // ok for frame 1
		{
			CHIAKI_LOGW(video_receiver->log, "Detected missing or corrupt frame(s) from %d to %d", next_frame_expected, (int)frame_index);
			stream_connection_send_corrupt_frame(&video_receiver->session->stream_connection, next_frame_expected, frame_index - 1);
		}

		video_receiver->frame_index_cur = frame_index;
		chiaki_frame_processor_alloc_frame(&video_receiver->frame_processor, packet);
	}

	chiaki_frame_processor_put_unit(&video_receiver->frame_processor, packet);

	// if we are currently building up a frame
	if(video_receiver->frame_index_cur != video_receiver->frame_index_prev)
	{
		// if we already have enough for the whole frame, flush it already
		if(chiaki_frame_processor_flush_possible(&video_receiver->frame_processor))
			chiaki_video_receiver_flush_frame(video_receiver);
	}
}

#define IDR_REQUEST_COOLDOWN_MS 500
#define IDR_REQUEST_PENDING_TIMEOUT_MS 2000

static void chiaki_video_receiver_request_idr(ChiakiVideoReceiver *video_receiver)
{
	uint64_t now_ms = chiaki_time_now_monotonic_ms();
	if(video_receiver->idr_request_attempted
		&& now_ms - video_receiver->idr_request_attempt_prev_ms < IDR_REQUEST_COOLDOWN_MS)
		return;
	if(video_receiver->idr_pending
		&& now_ms - video_receiver->idr_request_prev_ms < IDR_REQUEST_PENDING_TIMEOUT_MS)
		return;

	/* Failed sends need backoff too, but must not record successful recovery.
	 * A pending request may be lost along with its keyframe: retry only after
	 * two seconds of continued frame rejection, not on every cooldown tick. */
	video_receiver->idr_request_attempted = true;
	video_receiver->idr_request_attempt_prev_ms = now_ms;
	ChiakiErrorCode err = stream_connection_send_idr_request(&video_receiver->session->stream_connection);
	if(err == CHIAKI_ERR_SUCCESS)
	{
		video_receiver->idr_pending = true;
		video_receiver->idr_request_prev_ms = now_ms;
	}
	else
		CHIAKI_LOGW(video_receiver->log, "Failed to send IDR request after rejecting video frame");
}

static ChiakiErrorCode chiaki_video_receiver_flush_frame(ChiakiVideoReceiver *video_receiver)
{
	uint8_t *frame;
	size_t frame_size;
	ChiakiFrameProcessorFlushResult flush_result = chiaki_frame_processor_flush(&video_receiver->frame_processor, &frame, &frame_size);

	if(flush_result == CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_FAILED
		|| flush_result == CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_FEC_FAILED)
	{
		video_receiver->frame_index_prev = video_receiver->frame_index_cur;
		/* Plain FAILED is an empty flush; only damaged access units need IDR. */
		if(flush_result == CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_FEC_FAILED)
		{
			CHIAKI_LOGW(video_receiver->log, "Dropping incomplete video frame %d before decoding", (int)video_receiver->frame_index_cur);
			chiaki_video_receiver_request_idr(video_receiver);
		}
		return CHIAKI_ERR_UNKNOWN;
	}

	bool succ = true;

	if(video_receiver->session->video_sample_cb)
	{
		bool cb_succ = video_receiver->session->video_sample_cb(frame, frame_size, video_receiver->session->video_sample_cb_user);
		if(!cb_succ)
		{
			succ = false;
			CHIAKI_LOGW(video_receiver->log, "Video callback did not process frame successfully.");
			chiaki_video_receiver_request_idr(video_receiver);
		}
	}

	video_receiver->frame_index_prev = video_receiver->frame_index_cur;

	if(succ)
	{
		video_receiver->frame_index_prev_complete = video_receiver->frame_index_cur;
		/* Callback acceptance is not confirmation of an IDR or displayed
		 * frame. Keep this existing approximation; timeout bounds retries
		 * while rejection continues without adding a bitstream parser. */
		video_receiver->idr_pending = false;
	}

	return CHIAKI_ERR_SUCCESS;
}

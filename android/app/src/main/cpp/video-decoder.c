// SPDX-License-Identifier: LicenseRef-AGPL-3.0-only-OpenSSL

#include "video-decoder.h"

#include <jni.h>

#include <media/NdkMediaCodec.h>
#include <media/NdkMediaFormat.h>
#include <android/native_window_jni.h>

#include <string.h>
#include <time.h>

#define INPUT_BUFFER_TIMEOUT_MS 10

static uint64_t android_chiaki_video_decoder_time_us(void)
{
	struct timespec now;
	if(clock_gettime(CLOCK_MONOTONIC, &now) != 0)
		return 0;
	return (uint64_t)now.tv_sec * 1000000 + (uint64_t)now.tv_nsec / 1000;
}

static void *android_chiaki_video_decoder_output_thread_func(void *user);

ChiakiErrorCode android_chiaki_video_decoder_init(AndroidChiakiVideoDecoder *decoder, ChiakiLog *log, int32_t target_width, int32_t target_height, ChiakiCodec codec)
{
	decoder->log = log;
	decoder->codec = NULL;
	decoder->timestamp_cur = 0;
	decoder->target_width = target_width;
	decoder->target_height = target_height;
	decoder->target_codec = codec;
	decoder->shutdown_output = false;
	return chiaki_mutex_init(&decoder->codec_mutex, false);
}

static void kill_decoder(AndroidChiakiVideoDecoder *decoder)
{
	chiaki_mutex_lock(&decoder->codec_mutex);
	decoder->shutdown_output = true;
	ssize_t codec_buf_index = AMediaCodec_dequeueInputBuffer(decoder->codec, 1000);
	if(codec_buf_index >= 0)
	{
		CHIAKI_LOGI(decoder->log, "Video Decoder sending EOS buffer");
		AMediaCodec_queueInputBuffer(decoder->codec, (size_t)codec_buf_index, 0, 0, decoder->timestamp_cur++, AMEDIACODEC_BUFFER_FLAG_END_OF_STREAM);
		AMediaCodec_stop(decoder->codec);
		chiaki_mutex_unlock(&decoder->codec_mutex);
		chiaki_thread_join(&decoder->output_thread, NULL);
	}
	else
	{
		CHIAKI_LOGE(decoder->log, "Failed to get input buffer for shutting down Video Decoder!");
		AMediaCodec_stop(decoder->codec);
		chiaki_mutex_unlock(&decoder->codec_mutex);
	}
	AMediaCodec_delete(decoder->codec);
	decoder->codec = NULL;
	decoder->shutdown_output = false;
}

void android_chiaki_video_decoder_fini(AndroidChiakiVideoDecoder *decoder)
{
	if(decoder->codec)
		kill_decoder(decoder);
	chiaki_mutex_fini(&decoder->codec_mutex);
}

void android_chiaki_video_decoder_set_surface(AndroidChiakiVideoDecoder *decoder, JNIEnv *env, jobject surface)
{
	chiaki_mutex_lock(&decoder->codec_mutex);

	if(!surface)
	{
		if(decoder->codec)
		{
			kill_decoder(decoder);
			CHIAKI_LOGI(decoder->log, "Decoder shut down after surface was removed");
		}
		return;
	}

	if(decoder->codec)
	{
#if __ANDROID_API__ >= 23
		CHIAKI_LOGI(decoder->log, "Video decoder already initialized, swapping surface");
		ANativeWindow *new_window = surface ? ANativeWindow_fromSurface(env, surface) : NULL;
		AMediaCodec_setOutputSurface(decoder->codec, new_window);
		ANativeWindow_release(decoder->window);
		decoder->window = new_window;
#else
		CHIAKI_LOGE(decoder->log, "Video Decoder already initialized");
#endif
		goto beach;
	}

	decoder->window = ANativeWindow_fromSurface(env, surface);

	const char *mime = chiaki_codec_is_h265(decoder->target_codec) ? "video/hevc" : "video/avc";
	CHIAKI_LOGI(decoder->log, "Initializing decoder with mime %s", mime);

	decoder->codec = AMediaCodec_createDecoderByType(mime);
	if(!decoder->codec)
	{
		CHIAKI_LOGE(decoder->log, "Failed to create AMediaCodec for mime type %s", mime);
		goto error_surface;
	}

	AMediaFormat *format = AMediaFormat_new();
	AMediaFormat_setString(format, AMEDIAFORMAT_KEY_MIME, mime);
	AMediaFormat_setInt32(format, AMEDIAFORMAT_KEY_WIDTH, decoder->target_width);
	AMediaFormat_setInt32(format, AMEDIAFORMAT_KEY_HEIGHT, decoder->target_height);
	/* Reserve room for bursty keyframes, not just average bitrate per frame.
	 * The codec may ignore this hint; the input callback checks real capacity.
	 */
	int64_t max_input_size = (int64_t)decoder->target_width * decoder->target_height * 3 / 2;
	if(max_input_size < 2 * 1024 * 1024)
		max_input_size = 2 * 1024 * 1024;
	if(max_input_size > INT32_MAX)
		max_input_size = INT32_MAX;
	AMediaFormat_setInt32(format, AMEDIAFORMAT_KEY_MAX_INPUT_SIZE, (int32_t)max_input_size);
	CHIAKI_LOGI(decoder->log, "Requesting video input buffer size %d bytes", (int)max_input_size);

	bool request_low_latency = chiaki_codec_is_h265(decoder->target_codec);
	if(request_low_latency)
	{
		/* Android 11+ low-latency decoding is distinct from realtime priority.
		 * It asks the driver to avoid holding decoded frames/powering down.
		 */
		AMediaFormat_setInt32(format, AMEDIAFORMAT_KEY_LOW_LATENCY, 1);
		CHIAKI_LOGI(decoder->log, "Requesting Android HEVC low-latency decoding");
	}

	media_status_t r = AMediaCodec_configure(decoder->codec, format, decoder->window, NULL, 0);
	if(r != AMEDIA_OK && request_low_latency)
	{
		CHIAKI_LOGW(decoder->log, "HEVC low-latency configure failed (%d), retrying normal mode", (int)r);
		/* Recreate rather than assume the failed configure left a usable codec. */
		AMediaCodec_delete(decoder->codec);
		decoder->codec = AMediaCodec_createDecoderByType(mime);
		if(decoder->codec)
		{
			AMediaFormat_setInt32(format, AMEDIAFORMAT_KEY_LOW_LATENCY, 0);
			r = AMediaCodec_configure(decoder->codec, format, decoder->window, NULL, 0);
		}
	}
	if(r != AMEDIA_OK)
	{
		CHIAKI_LOGE(decoder->log, "AMediaCodec_configure() failed: %d", (int)r);
		AMediaFormat_delete(format);
		goto error_codec;
	}

	r = AMediaCodec_start(decoder->codec);
	AMediaFormat_delete(format);
	if(r != AMEDIA_OK)
	{
		CHIAKI_LOGE(decoder->log, "AMediaCodec_start() failed: %d", (int)r);
		goto error_codec;
	}

	char *codec_name = NULL;
	if(AMediaCodec_getName(decoder->codec, &codec_name) == AMEDIA_OK && codec_name)
	{
		CHIAKI_LOGI(decoder->log, "Video decoder implementation: %s", codec_name);
		AMediaCodec_releaseName(decoder->codec, codec_name);
	}
	AMediaFormat *input_format = AMediaCodec_getInputFormat(decoder->codec);
	if(input_format)
	{
		CHIAKI_LOGI(decoder->log, "Video decoder input format: %s", AMediaFormat_toString(input_format));
		AMediaFormat_delete(input_format);
	}

	ChiakiErrorCode err = chiaki_thread_create(&decoder->output_thread, android_chiaki_video_decoder_output_thread_func, decoder);
	if(err != CHIAKI_ERR_SUCCESS)
	{
		CHIAKI_LOGE(decoder->log, "Failed to create output thread for AMediaCodec");
		goto error_codec;
	}

	goto beach;

error_codec:
	if(decoder->codec)
		AMediaCodec_delete(decoder->codec);
	decoder->codec = NULL;

error_surface:
	ANativeWindow_release(decoder->window);
	decoder->window = NULL;

beach:
	chiaki_mutex_unlock(&decoder->codec_mutex);
}

bool android_chiaki_video_decoder_video_sample(uint8_t *buf, size_t buf_size, void *user)
{
	bool success = false;
	AndroidChiakiVideoDecoder *decoder = user;
	chiaki_mutex_lock(&decoder->codec_mutex);

	if(!decoder->codec)
	{
		CHIAKI_LOGE(decoder->log, "Received video data, but decoder is not initialized!");
		goto beach;
	}

	if(buf_size == 0)
	{
		success = true;
		goto beach;
	}

	uint64_t sample_time_us = android_chiaki_video_decoder_time_us();
	ssize_t codec_buf_index = AMediaCodec_dequeueInputBuffer(decoder->codec, INPUT_BUFFER_TIMEOUT_MS * 1000);
	if(codec_buf_index < 0)
	{
		CHIAKI_LOGE(decoder->log, "Failed to get input buffer for sample of %zu bytes", buf_size);
		goto beach;
	}

	size_t codec_buf_size = 0;
	uint8_t *codec_buf = AMediaCodec_getInputBuffer(decoder->codec, (size_t)codec_buf_index, &codec_buf_size);
	if(decoder->timestamp_cur == 0)
		CHIAKI_LOGI(decoder->log, "Video decoder input capacity: %zu bytes", codec_buf_size);
	if(!codec_buf || buf_size > codec_buf_size)
	{
		/* Never split an access unit into unmarked, arbitrary byte fragments.
		 * Return the unused input buffer without submitting any frame bytes.
		 * Returning false lets the receiver report the failed frame to the PS5.
		 */
		CHIAKI_LOGE(decoder->log, "Cannot submit complete video sample: size=%zu, capacity=%zu, buffer=%p",
				buf_size, codec_buf_size, (void *)codec_buf);
		media_status_t status = AMediaCodec_queueInputBuffer(decoder->codec, (size_t)codec_buf_index,
				0, 0, decoder->timestamp_cur, 0);
		if(status != AMEDIA_OK)
			CHIAKI_LOGE(decoder->log, "Failed to return unused input buffer: %d", (int)status);
		goto beach;
	}

	memcpy(codec_buf, buf, buf_size);
	/* Use monotonic input-arrival time to measure client processing delay.
	 * Output is still released immediately, not paced from these timestamps.
	 */
	if(sample_time_us <= decoder->timestamp_cur)
		sample_time_us = decoder->timestamp_cur + 1;
	decoder->timestamp_cur = sample_time_us;
	media_status_t status = AMediaCodec_queueInputBuffer(decoder->codec, (size_t)codec_buf_index,
			0, buf_size, sample_time_us, 0);
	if(status != AMEDIA_OK)
		CHIAKI_LOGE(decoder->log, "AMediaCodec_queueInputBuffer() failed: %d", (int)status);
	else
		success = true;

beach:
	chiaki_mutex_unlock(&decoder->codec_mutex);
	return success;
}

static void *android_chiaki_video_decoder_output_thread_func(void *user)
{
	AndroidChiakiVideoDecoder *decoder = user;
	uint64_t stats_start_us = 0, stats_total_us = 0, stats_max_us = 0, stats_frames = 0;

	while(1)
	{
		AMediaCodecBufferInfo info;
		ssize_t status = AMediaCodec_dequeueOutputBuffer(decoder->codec, &info, -1);
		if(status >= 0)
		{
			uint64_t now_us = 0, delay_us = 0;
			bool timed_frame = info.size > 0
				&& !(info.flags & (AMEDIACODEC_BUFFER_FLAG_END_OF_STREAM | AMEDIACODEC_BUFFER_FLAG_CODEC_CONFIG));
			if(timed_frame)
			{
				now_us = android_chiaki_video_decoder_time_us();
				timed_frame = info.presentationTimeUs > 0 && (uint64_t)info.presentationTimeUs <= now_us;
				if(timed_frame)
					delay_us = now_us - (uint64_t)info.presentationTimeUs;
			}
			/* Keep the render path immediate; log only after returning the buffer. */
			AMediaCodec_releaseOutputBuffer(decoder->codec, (size_t)status, info.size != 0);
			if(timed_frame)
			{
				if(!stats_start_us)
					stats_start_us = now_us;
				stats_total_us += delay_us;
				if(delay_us > stats_max_us)
					stats_max_us = delay_us;
				stats_frames++;
				if(now_us - stats_start_us >= 2000000)
				{
					CHIAKI_LOGI(decoder->log, "Video client decode latency: avg=%.2f ms, max=%.2f ms, frames=%llu",
						(double)stats_total_us / stats_frames / 1000.0,
						(double)stats_max_us / 1000.0, (unsigned long long)stats_frames);
					stats_start_us = now_us;
					stats_total_us = stats_max_us = stats_frames = 0;
				}
			}
			if(info.flags & AMEDIACODEC_BUFFER_FLAG_END_OF_STREAM)
			{
				CHIAKI_LOGI(decoder->log, "AMediaCodec reported EOS");
				break;
			}
		}
		else
		{
			chiaki_mutex_lock(&decoder->codec_mutex);
			bool shutdown = decoder->shutdown_output;
			chiaki_mutex_unlock(&decoder->codec_mutex);
			if(shutdown)
			{
				CHIAKI_LOGI(decoder->log, "Video Decoder Output Thread detected shutdown after reported error");
				break;
			}
		}
	}

	CHIAKI_LOGI(decoder->log, "Video Decoder Output Thread exiting");

	return NULL;
}
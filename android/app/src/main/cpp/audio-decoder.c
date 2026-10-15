// SPDX-License-Identifier: LicenseRef-AGPL-3.0-only-OpenSSL

#include "audio-decoder.h"

#include <jni.h>

#include <media/NdkMediaCodec.h>
#include <media/NdkMediaFormat.h>

#include <string.h>

#define INPUT_BUFFER_TIMEOUT_MS 10
#define OUTPUT_BUFFER_TIMEOUT_MS 10

static void *android_chiaki_audio_decoder_output_thread_func(void *user);
static void android_chiaki_audio_decoder_header(ChiakiAudioHeader *header, void *user);
static void android_chiaki_audio_decoder_frame(uint8_t *buf, size_t buf_size, void *user);

ChiakiErrorCode android_chiaki_audio_decoder_init(AndroidChiakiAudioDecoder *decoder, ChiakiLog *log)
{
	decoder->log = log;
	memset(&decoder->audio_header, 0, sizeof(decoder->audio_header));
	decoder->codec = NULL;
	decoder->input_failed = false;
	decoder->timestamp_cur = 0;
	atomic_init(&decoder->shutdown_requested, false);

	decoder->cb_user = NULL;
	decoder->settings_cb = NULL;
	decoder->frame_cb = NULL;

	return chiaki_mutex_init(&decoder->codec_mutex, true);
}

// Called with exactly one codec_mutex acquisition; returns with it held.
// Lifecycle owners (header callback / fini after session join) must not overlap.
static void android_chiaki_audio_decoder_shutdown_codec_locked(AndroidChiakiAudioDecoder *decoder)
{
	if(!decoder->codec)
		return;
	ssize_t codec_buf_index = decoder->input_failed ? -1 :
		AMediaCodec_dequeueInputBuffer(decoder->codec, INPUT_BUFFER_TIMEOUT_MS * 1000);
	if(codec_buf_index >= 0)
	{
		CHIAKI_LOGI(decoder->log, "Audio Decoder sending EOS buffer");
		if(AMediaCodec_queueInputBuffer(decoder->codec, (size_t)codec_buf_index, 0, 0, decoder->timestamp_cur, AMEDIACODEC_BUFFER_FLAG_END_OF_STREAM) != AMEDIA_OK)
			CHIAKI_LOGE(decoder->log, "Failed to queue Audio Decoder EOS");
	}
	else
		CHIAKI_LOGE(decoder->log, "Failed to get input buffer for shutting down Audio Decoder!");
	// EOS is best effort, not a liveness requirement. Discard pending audio on teardown.
	atomic_store(&decoder->shutdown_requested, true);
	chiaki_mutex_unlock(&decoder->codec_mutex);
	chiaki_thread_join(&decoder->output_thread, NULL);
	chiaki_mutex_lock(&decoder->codec_mutex);
	AMediaCodec_delete(decoder->codec);
	decoder->codec = NULL;
}

void android_chiaki_audio_decoder_shutdown_codec(AndroidChiakiAudioDecoder *decoder)
{
	chiaki_mutex_lock(&decoder->codec_mutex);
	android_chiaki_audio_decoder_shutdown_codec_locked(decoder);
	chiaki_mutex_unlock(&decoder->codec_mutex);
}

void android_chiaki_audio_decoder_fini(AndroidChiakiAudioDecoder *decoder)
{
	android_chiaki_audio_decoder_shutdown_codec(decoder);
	chiaki_mutex_fini(&decoder->codec_mutex);
}

void android_chiaki_audio_decoder_get_sink(AndroidChiakiAudioDecoder *decoder, ChiakiAudioSink *sink)
{
	sink->user = decoder;
	sink->header_cb = android_chiaki_audio_decoder_header;
	sink->frame_cb = android_chiaki_audio_decoder_frame;
}

static void *android_chiaki_audio_decoder_output_thread_func(void *user)
{
	AndroidChiakiAudioDecoder *decoder = user;

	while(!atomic_load(&decoder->shutdown_requested))
	{
		AMediaCodecBufferInfo info;
		ssize_t codec_buf_index = AMediaCodec_dequeueOutputBuffer(decoder->codec, &info, OUTPUT_BUFFER_TIMEOUT_MS * 1000);
		if(codec_buf_index >= 0)
		{
			chiaki_mutex_lock(&decoder->codec_mutex);
			if(!atomic_load(&decoder->shutdown_requested) && decoder->frame_cb)
			{
				size_t codec_buf_size = 0;
				uint8_t *codec_buf = AMediaCodec_getOutputBuffer(decoder->codec, (size_t)codec_buf_index, &codec_buf_size);
				if(!codec_buf || info.offset < 0 || info.size < 0
						|| (size_t)info.offset > codec_buf_size
						|| (size_t)info.size > codec_buf_size - (size_t)info.offset
						|| (size_t)info.size % sizeof(int16_t) != 0
						|| (uintptr_t)(codec_buf + info.offset) % _Alignof(int16_t) != 0)
					CHIAKI_LOGE(decoder->log, "Invalid audio output buffer range");
				else
					decoder->frame_cb((int16_t *)(codec_buf + info.offset), (size_t)info.size / sizeof(int16_t), decoder->cb_user);
			}
			AMediaCodec_releaseOutputBuffer(decoder->codec, (size_t)codec_buf_index, false);
			chiaki_mutex_unlock(&decoder->codec_mutex);
			if(info.flags & AMEDIACODEC_BUFFER_FLAG_END_OF_STREAM)
			{
				CHIAKI_LOGI(decoder->log, "AMediaCodec for Audio Decoder reported EOS");
				break;
			}
		}
	}

	CHIAKI_LOGI(decoder->log, "Audio Decoder Output Thread exiting");

	return NULL;
}

static void android_chiaki_audio_decoder_header(ChiakiAudioHeader *header, void *user)
{
	AndroidChiakiAudioDecoder *decoder = user;
	chiaki_mutex_lock(&decoder->codec_mutex);
	if(atomic_load(&decoder->shutdown_requested) && decoder->codec)
		goto beach;
	memcpy(&decoder->audio_header, header, sizeof(decoder->audio_header));

	if(decoder->codec)
	{
		CHIAKI_LOGI(decoder->log, "Audio decoder already initialized, shutting down the old one");
		android_chiaki_audio_decoder_shutdown_codec_locked(decoder);
	}

	const char *mime = "audio/opus";
	decoder->codec = AMediaCodec_createDecoderByType(mime);
	if(!decoder->codec)
	{
		CHIAKI_LOGE(decoder->log, "Failed to create AMediaCodec for mime type %s", mime);
		goto beach;
	}

	AMediaFormat *format = AMediaFormat_new();
	if(!format)
	{
		CHIAKI_LOGE(decoder->log, "Failed to allocate audio decoder format");
		AMediaCodec_delete(decoder->codec);
		decoder->codec = NULL;
		goto beach;
	}
	AMediaFormat_setString(format, AMEDIAFORMAT_KEY_MIME, mime);
	AMediaFormat_setInt32(format, AMEDIAFORMAT_KEY_CHANNEL_COUNT, header->channels);
	AMediaFormat_setInt32(format, AMEDIAFORMAT_KEY_SAMPLE_RATE, header->rate);
	// AMediaFormat_setInt32(format, AMEDIAFORMAT_KEY_PCM_ENCODING)

	if(AMediaCodec_configure(decoder->codec, format, NULL, NULL, 0) != AMEDIA_OK)
	{
		CHIAKI_LOGE(decoder->log, "Failed to configure audio decoder");
		AMediaFormat_delete(format);
		AMediaCodec_delete(decoder->codec);
		decoder->codec = NULL;
		goto beach;
	}
	if(AMediaCodec_start(decoder->codec) != AMEDIA_OK)
	{
		CHIAKI_LOGE(decoder->log, "Failed to start audio decoder");
		AMediaFormat_delete(format);
		AMediaCodec_delete(decoder->codec);
		decoder->codec = NULL;
		goto beach;
	}

	AMediaFormat_delete(format);
	decoder->input_failed = false;
	atomic_store(&decoder->shutdown_requested, false);

	ChiakiErrorCode err = chiaki_thread_create(&decoder->output_thread, android_chiaki_audio_decoder_output_thread_func, decoder);
	if(err != CHIAKI_ERR_SUCCESS)
	{
		CHIAKI_LOGE(decoder->log, "Failed to create output thread for AMediaCodec");
		AMediaCodec_delete(decoder->codec);
		decoder->codec = NULL;
		goto beach;
	}

	uint8_t opus_id_head[0x13];
	memcpy(opus_id_head, "OpusHead", 8);
	opus_id_head[0x8] = 1; // version
	opus_id_head[0x9] = header->channels;
	uint16_t pre_skip = 3840;
	opus_id_head[0xa] = (uint8_t)(pre_skip & 0xff);
	opus_id_head[0xb] = (uint8_t)(pre_skip >> 8);
	opus_id_head[0xc] = (uint8_t)(header->rate & 0xff);
	opus_id_head[0xd] = (uint8_t)((header->rate >> 0x8) & 0xff);
	opus_id_head[0xe] = (uint8_t)((header->rate >> 0x10) & 0xff);
	opus_id_head[0xf] = (uint8_t)(header->rate >> 0x18);
	uint16_t output_gain = 0;
	opus_id_head[0x10] = (uint8_t)(output_gain & 0xff);
	opus_id_head[0x11] = (uint8_t)(output_gain >> 8);
	opus_id_head[0x12] = 0; // channel map
	//AMediaFormat_setBuffer(format, AMEDIAFORMAT_KEY_CSD_0, opus_id_head, sizeof(opus_id_head));
	android_chiaki_audio_decoder_frame(opus_id_head, sizeof(opus_id_head), decoder);

	uint64_t pre_skip_ns = 0;
	uint8_t csd1[8] = { (uint8_t)(pre_skip_ns & 0xff), (uint8_t)((pre_skip_ns >> 0x8) & 0xff), (uint8_t)((pre_skip_ns >> 0x10) & 0xff), (uint8_t)((pre_skip_ns >> 0x18) & 0xff),
						(uint8_t)((pre_skip_ns >> 0x20) & 0xff), (uint8_t)((pre_skip_ns >> 0x28) & 0xff), (uint8_t)((pre_skip_ns >> 0x30) & 0xff), (uint8_t)(pre_skip_ns >> 0x38)};
	android_chiaki_audio_decoder_frame(csd1, sizeof(csd1), decoder);

	uint64_t pre_roll_ns = 0;
	uint8_t csd2[8] = { (uint8_t)(pre_roll_ns & 0xff), (uint8_t)((pre_roll_ns >> 0x8) & 0xff), (uint8_t)((pre_roll_ns >> 0x10) & 0xff), (uint8_t)((pre_roll_ns >> 0x18) & 0xff),
						(uint8_t)((pre_roll_ns >> 0x20) & 0xff), (uint8_t)((pre_roll_ns >> 0x28) & 0xff), (uint8_t)((pre_roll_ns >> 0x30) & 0xff), (uint8_t)(pre_roll_ns >> 0x38)};
	android_chiaki_audio_decoder_frame(csd2, sizeof(csd2), decoder);

	if(decoder->settings_cb)
		decoder->settings_cb(header->channels, header->rate, decoder->cb_user);

beach:
	chiaki_mutex_unlock(&decoder->codec_mutex);
}

static void android_chiaki_audio_decoder_frame(uint8_t *buf, size_t buf_size, void *user)
{
	AndroidChiakiAudioDecoder *decoder = user;
	chiaki_mutex_lock(&decoder->codec_mutex);

	if(!decoder->codec)
	{
		CHIAKI_LOGE(decoder->log, "Received audio data, but decoder is not initialized!");
		goto beach;
	}
	if(decoder->input_failed || atomic_load(&decoder->shutdown_requested))
		goto beach;

	if(!buf && buf_size > 0)
	{
		CHIAKI_LOGE(decoder->log, "Received NULL audio input");
		goto beach;
	}

	while(buf_size > 0)
	{
		ssize_t codec_buf_index = AMediaCodec_dequeueInputBuffer(decoder->codec, INPUT_BUFFER_TIMEOUT_MS * 1000);
		if(codec_buf_index < 0)
		{
			CHIAKI_LOGE(decoder->log, "Failed to get input audio buffer");
			goto beach;
		}

		size_t codec_buf_size = 0;
		uint8_t *codec_buf = AMediaCodec_getInputBuffer(decoder->codec, (size_t)codec_buf_index, &codec_buf_size);
		size_t codec_sample_size = buf_size;
		if(!codec_buf || codec_sample_size > codec_buf_size)
		{
			// A compressed Opus packet must be submitted whole, not as independent fragments.
			CHIAKI_LOGE(decoder->log, "Invalid audio input buffer or insufficient capacity");
			if(AMediaCodec_queueInputBuffer(decoder->codec, (size_t)codec_buf_index, 0, 0, decoder->timestamp_cur, 0) != AMEDIA_OK)
			{
				decoder->input_failed = true;
				CHIAKI_LOGE(decoder->log, "Failed to return unused audio input buffer");
			}
			goto beach;
		}
		memcpy(codec_buf, buf, codec_sample_size);
		if(AMediaCodec_queueInputBuffer(decoder->codec, (size_t)codec_buf_index, 0, codec_sample_size, decoder->timestamp_cur, 0) != AMEDIA_OK)
		{
			// Never retry an index with unknown ownership or consume more indices.
			// Stay quarantined until explicit codec replacement by a new header.
			decoder->input_failed = true;
			CHIAKI_LOGE(decoder->log, "Failed to queue audio input buffer");
			goto beach;
		}
		decoder->timestamp_cur++; // timestamp just raised by 1 for maximum realtime
		buf += codec_sample_size;
		buf_size -= codec_sample_size;
	}

beach:
	chiaki_mutex_unlock(&decoder->codec_mutex);
}
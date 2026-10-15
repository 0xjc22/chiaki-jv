// SPDX-License-Identifier: LicenseRef-AGPL-3.0-only-OpenSSL

#ifndef CHIAKI_JNI_AUDIO_DECODER_H
#define CHIAKI_JNI_AUDIO_DECODER_H

#include <jni.h>
#include <stdatomic.h>

#include <chiaki/thread.h>
#include <chiaki/log.h>
#include <chiaki/audioreceiver.h>

typedef void (*AndroidChiakiAudioDecoderSettingsCallback)(uint32_t channels, uint32_t rate, void *user);
// buf is borrowed codec storage: consume/copy synchronously, never retain it.
// Callbacks run under codec_mutex and must not initiate decoder teardown.
typedef void (*AndroidChiakiAudioDecoderFrameCallback)(int16_t *buf, size_t samples_count, void *user);

typedef struct android_chiaki_audio_decoder_t
{
	ChiakiLog *log;
	ChiakiAudioHeader audio_header;

	ChiakiMutex codec_mutex;
	struct AMediaCodec *codec;
	// Protected by codec_mutex. A failed queue leaves buffer ownership unknown.
	bool input_failed;
	atomic_bool shutdown_requested;
	uint64_t timestamp_cur;
	ChiakiThread output_thread;

	AndroidChiakiAudioDecoderSettingsCallback settings_cb;
	AndroidChiakiAudioDecoderFrameCallback frame_cb;
	void *cb_user;
} AndroidChiakiAudioDecoder;

ChiakiErrorCode android_chiaki_audio_decoder_init(AndroidChiakiAudioDecoder *decoder, ChiakiLog *log);
void android_chiaki_audio_decoder_fini(AndroidChiakiAudioDecoder *decoder);
void android_chiaki_audio_decoder_get_sink(AndroidChiakiAudioDecoder *decoder, ChiakiAudioSink *sink);

static inline void android_chiaki_audio_decoder_set_cb(AndroidChiakiAudioDecoder *decoder, AndroidChiakiAudioDecoderSettingsCallback settings_cb, AndroidChiakiAudioDecoderFrameCallback frame_cb, void *user)
{
	chiaki_mutex_lock(&decoder->codec_mutex);
	decoder->settings_cb = settings_cb;
	decoder->frame_cb = frame_cb;
	decoder->cb_user = user;
	chiaki_mutex_unlock(&decoder->codec_mutex);
}

#endif
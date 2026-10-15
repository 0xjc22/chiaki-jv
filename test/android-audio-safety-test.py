#!/usr/bin/env python3
"""Compile actual Android audio functions against deterministic host API fakes.

No Android SDK/device required. These prove error handling, not real playback.
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / 'android/app/src/main/cpp'

DECODER_FAKE = r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <sys/types.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include <stdatomic.h>
static void fake_log(void *log, const char *fmt, ...) { (void)log; (void)fmt; }
#define CHIAKI_LOGI fake_log
#define CHIAKI_LOGE fake_log
#define CHIAKI_LOGD fake_log
#define CHIAKI_LOGW fake_log
typedef int ChiakiLog;
typedef int ChiakiMutex;
typedef int ChiakiThread;
typedef int ChiakiErrorCode;
#define CHIAKI_ERR_SUCCESS 0
static int chiaki_mutex_init(int *m, bool recursive) { (void)recursive; *m=0; return 0; }
static int lock_calls;
static void chiaki_mutex_lock(int *m) { ++lock_calls; ++*m; }
static void chiaki_mutex_unlock(int *m) { assert(*m>0); --*m; }
static void chiaki_mutex_fini(int *m) { assert(*m==0); }
static int thread_result, threads, joins;
static bool active_thread, joined;
static void *(*thread_func)(void *);
static void *thread_user;
static int chiaki_thread_create(int *t, void *(*f)(void *), void *u) {
 (void)t; ++threads; thread_func=f; thread_user=u;
 active_thread=thread_result==0; joined=false; return thread_result;
}
static void chiaki_thread_join(int *t, void *u);
typedef struct { uint32_t channels, rate; } ChiakiAudioHeader;
typedef struct { void *user; void (*header_cb)(ChiakiAudioHeader *,void *); void (*frame_cb)(uint8_t *,size_t,void *); } ChiakiAudioSink;
typedef struct AMediaCodec { int value; } AMediaCodec;
typedef struct { int value; } AMediaFormat;
typedef struct { int32_t offset, size; int64_t presentationTimeUs; uint32_t flags; } AMediaCodecBufferInfo;
/* DECODER_HEADER */
#define AMEDIA_OK 0
static AndroidChiakiAudioDecoder *lifecycle_decoder;
static bool probe_join_callbacks;
#define AMEDIACODEC_BUFFER_FLAG_END_OF_STREAM 4
#define AMEDIAFORMAT_KEY_MIME "mime"
#define AMEDIAFORMAT_KEY_CHANNEL_COUNT "channels"
#define AMEDIAFORMAT_KEY_SAMPLE_RATE "rate"
static AMediaCodec codec;
static AMediaFormat format;
static int configure_result, start_result, deleted, format_deleted, started, configured;
static bool null_format, null_codec;
static ssize_t input_index;
static uint8_t storage[128];
static uint8_t *input_ptr=storage, *output_ptr=storage;
static size_t input_capacity=sizeof(storage), output_capacity=sizeof(storage);
static int queues, queue_result, dequeues, releases, frames, settings;
static size_t queued_size, received_count;
static uint64_t queued_timestamp;
static int16_t *received_ptr;
static int16_t copied_pcm[64];
static bool output_owned;
static AMediaCodecBufferInfo output_info={0,4,0,AMEDIACODEC_BUFFER_FLAG_END_OF_STREAM};
static AMediaCodec *AMediaCodec_createDecoderByType(const char *s) { (void)s; return null_codec?NULL:&codec; }
static int AMediaCodec_delete(AMediaCodec *c) {
 assert(c && lifecycle_decoder->codec_mutex>0);
 assert(!active_thread || joined); ++deleted; active_thread=false; return 0;
}
static AMediaFormat *AMediaFormat_new(void) { return null_format?NULL:&format; }
static void AMediaFormat_setString(AMediaFormat *f,const char *k,const char *v) { assert(f); (void)k; (void)v; }
static void AMediaFormat_setInt32(AMediaFormat *f,const char *k,int32_t v) { assert(f); (void)k; (void)v; }
static void AMediaFormat_delete(AMediaFormat *f) { assert(f); ++format_deleted; }
static int AMediaCodec_configure(AMediaCodec *c, AMediaFormat *f,void *s,void *d,uint32_t flags) { assert(c && f); (void)s; (void)d; (void)flags; ++configured; return configure_result; }
static int AMediaCodec_start(AMediaCodec *c) { assert(c); ++started; return start_result; }
static ssize_t AMediaCodec_dequeueInputBuffer(AMediaCodec *c,int64_t t) { assert(c); assert(t>=0 && t<=100000); assert(++dequeues<100); return input_index; }
static uint8_t *AMediaCodec_getInputBuffer(AMediaCodec *c,size_t i,size_t *n) { assert(c); (void)i; *n=input_capacity; return input_ptr; }
static int AMediaCodec_queueInputBuffer(AMediaCodec *c,size_t i,size_t o,size_t n,uint64_t ts,uint32_t f) { assert(c); (void)i; (void)o; (void)f; ++queues; queued_size=n; queued_timestamp=ts; return queue_result; }
static int output_polls;
static bool no_output;
static atomic_bool *poll_stop;
static ssize_t AMediaCodec_dequeueOutputBuffer(AMediaCodec *c,AMediaCodecBufferInfo *i,int64_t t) {
 assert(c); assert(t>0 && t<=100000); assert(++output_polls<10);
 if(poll_stop && output_polls==3) atomic_store(poll_stop,true);
 *i=output_info; return no_output?-1:0;
}
static uint8_t *AMediaCodec_getOutputBuffer(AMediaCodec *c,size_t i,size_t *n) { assert(c); (void)i; *n=output_capacity; output_owned=true; return output_ptr; }
static int AMediaCodec_releaseOutputBuffer(AMediaCodec *c,size_t i,bool render) { assert(c); (void)i; (void)render; ++releases; output_owned=false; memset(storage,0xa5,sizeof(storage)); return 0; }
static void chiaki_thread_join(int *t, void *u) {
 (void)t; (void)u;
 AndroidChiakiAudioDecoder *d=thread_user;
 assert(active_thread && !joined && d->codec_mutex==0);
 if(probe_join_callbacks) {
  int old_queues=queues, old_dequeues=dequeues, old_threads=threads, old_settings=settings;
  ChiakiAudioSink sink; android_chiaki_audio_decoder_get_sink(d,&sink);
  uint8_t packet[4]={0}; ChiakiAudioHeader header={2,48000};
  sink.frame_cb(packet,sizeof(packet),sink.user); sink.header_cb(&header,sink.user);
  assert(queues==old_queues && dequeues==old_dequeues);
  assert(threads==old_threads && settings==old_settings && d->codec_mutex==0);
 }
 ++joins; thread_func(thread_user); joined=true;
}
static void settings_cb(uint32_t c,uint32_t r,void *u) { (void)c; (void)r; (void)u; ++settings; }
static void frame_cb(int16_t *p,size_t n,void *u) {
 if(u) assert(((AndroidChiakiAudioDecoder *)u)->codec_mutex>0);
 assert(output_owned && n<=64); memcpy(copied_pcm,p,n*sizeof(*p));
 ++frames; received_ptr=p; received_count=n;
}
'''


def threaded_decoder_fake():
    """Same codec seams, real recursive mutex/thread and gated output dequeue."""
    fake = '#include <pthread.h>\n#include <time.h>\n' + DECODER_FAKE

    def replace_between(start, end, replacement):
        nonlocal fake
        assert fake.count(start) == 1 and fake.count(end) == 1
        a, b = fake.index(start), fake.index(end)
        fake = fake[:a] + replacement + fake[b:]

    replace_between('static int chiaki_mutex_init', 'static int thread_result', r'''
static pthread_mutex_t real_mutex;
static _Thread_local int held_locks;
static int chiaki_mutex_init(int *m,bool recursive) {
 assert(recursive); *m=0;
 pthread_mutexattr_t attr;
 assert(pthread_mutexattr_init(&attr)==0);
 assert(pthread_mutexattr_settype(&attr,PTHREAD_MUTEX_RECURSIVE)==0);
 assert(pthread_mutex_init(&real_mutex,&attr)==0);
 assert(pthread_mutexattr_destroy(&attr)==0); return 0;
}
static void chiaki_mutex_lock(int *m) {
 assert(pthread_mutex_lock(&real_mutex)==0); ++*m; ++held_locks;
}
static void chiaki_mutex_unlock(int *m) {
 assert(*m>0); --*m; --held_locks; assert(pthread_mutex_unlock(&real_mutex)==0);
}
static void chiaki_mutex_fini(int *m) {
 assert(*m==0); assert(pthread_mutex_destroy(&real_mutex)==0);
}
static int lock_calls;
static pthread_t worker;
static pthread_mutex_t gate=PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t wake=PTHREAD_COND_INITIALIZER;
static bool entered_output;
''')
    replace_between('static int chiaki_thread_create',
                    'static void chiaki_thread_join(int *t, void *u);', r'''
static int chiaki_thread_create(int *t,void *(*f)(void *),void *u) {
 (void)t; ++threads; thread_func=f; thread_user=u;
 active_thread=true; joined=false;
 return pthread_create(&worker,NULL,f,u);
}
''')
    replace_between('static ssize_t AMediaCodec_dequeueOutputBuffer',
                    'static uint8_t *AMediaCodec_getOutputBuffer', r'''
static ssize_t AMediaCodec_dequeueOutputBuffer(AMediaCodec *c,AMediaCodecBufferInfo *i,int64_t t) {
 assert(c && t>0 && t<=100000); (void)i;
 assert(pthread_mutex_lock(&gate)==0);
 entered_output=true; ++output_polls; assert(pthread_cond_signal(&wake)==0);
 assert(pthread_mutex_unlock(&gate)==0);
 struct timespec delay={0,t*1000}; nanosleep(&delay,NULL);
 return -1; // No output and no EOS, even if EOS input submission succeeded.
}
''')
    replace_between('static void chiaki_thread_join(int *t, void *u) {',
                    'static void settings_cb', r'''
static void chiaki_thread_join(int *t,void *u) {
 (void)t; (void)u; assert(held_locks==0 && active_thread && !joined);
 ++joins; assert(pthread_join(worker,NULL)==0); joined=true;
}
''')
    return fake


OUTPUT_FAKE = r'''
#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <memory>
#include <cstdarg>
#include <limits>
#include "circular-buf.hpp"
typedef int ChiakiLog;
static void fake_log(void *log, const char *fmt, ...) { (void)log; (void)fmt; }
#define CHIAKI_LOGI fake_log
#define CHIAKI_LOGE fake_log
#define CHIAKI_LOGW fake_log
#define CHIAKI_LOGV fake_log
namespace oboe {
enum class Result { OK, Error };
enum class AudioFormat { I16, Other };
enum class DataCallbackResult { Continue, Stop };
enum class PerformanceMode { LowLatency };
enum class SharingMode { Exclusive };
class AudioStream;
class AudioStreamCallback {
public:
 virtual ~AudioStreamCallback()=default;
 virtual DataCallbackResult onAudioReady(AudioStream *,void *,int32_t)=0;
 virtual void onErrorBeforeClose(AudioStream *,Result)=0;
 virtual void onErrorAfterClose(AudioStream *,Result)=0;
};
static Result open_result=Result::OK, start_result=Result::OK;
static int starts;
static bool null_open;
class AudioStream {
public:
 AudioFormat format=AudioFormat::I16;
 int32_t bytes_per_frame=4;
 Result start() { assert(this); ++starts; return start_result; }
 AudioFormat getFormat() { return format; }
 int32_t getBytesPerFrame() { return bytes_per_frame; }
};
using ManagedStream=std::shared_ptr<AudioStream>;
class AudioStreamBuilder {
public:
 AudioStreamBuilder *setPerformanceMode(PerformanceMode) { return this; }
 AudioStreamBuilder *setSharingMode(SharingMode) { return this; }
 AudioStreamBuilder *setFormat(AudioFormat) { return this; }
 AudioStreamBuilder *setChannelCount(uint32_t) { return this; }
 AudioStreamBuilder *setSampleRate(uint32_t) { return this; }
 AudioStreamBuilder *setCallback(AudioStreamCallback *) { return this; }
 Result openManagedStream(ManagedStream &s) {
  if(open_result==Result::OK && !null_open) s=std::make_shared<AudioStream>();
  return open_result;
 }
};
static const char *convertToText(Result) { return "fake"; }
}
'''


def source_without_includes(name):
    source = (CPP / name).read_text()
    assert len(source) > 1000 and 'android_chiaki_audio_' in source
    return '\n'.join(line for line in source.splitlines()
                     if not line.startswith('#include'))


class AudioSafetyTest(unittest.TestCase):
    def compile_run(self, fake, source, body, cpp=False):
        with tempfile.TemporaryDirectory(prefix='audio-safety-') as tmp:
            (Path(tmp) / 'android').mkdir()
            (Path(tmp) / 'android/log.h').write_text('')
            path = Path(tmp) / ('test.cpp' if cpp else 'test.c')
            path.write_text(fake + '\n' + source + '\nint main(void) {\n' + body + '\nreturn 0;\n}\n')
            exe = Path(tmp) / 'test'
            compile_result = subprocess.run([os.environ.get('CXX' if cpp else 'CC', 'c++' if cpp else 'cc'),
                            '-std=c++17' if cpp else '-std=c11', '-Wall', '-Wextra',
                            '-Werror', '-Wno-unused-function', '-Wno-unused-variable',
                            '-Wno-unused-parameter', '-pthread', '-D_POSIX_C_SOURCE=200809L',
                            '-I', tmp, '-I', str(CPP), str(path), '-o', str(exe)], capture_output=True, text=True)
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)

    def decoder(self, body, fake=DECODER_FAKE):
        self.compile_run(fake.replace('/* DECODER_HEADER */', source_without_includes('audio-decoder.h')), source_without_includes('audio-decoder.c'), r'''
AndroidChiakiAudioDecoder d;
assert(android_chiaki_audio_decoder_init(&d,NULL)==0);
lifecycle_decoder=&d;
d.codec=&codec;
d.settings_cb=settings_cb;
d.frame_cb=frame_cb;
uint8_t data[256]={1,2,3,4};
(void)data;
''' + body)

    def test_output_no_output_observes_shutdown_request(self):
        self.decoder('''
no_output=true; poll_stop=&d.shutdown_requested;
android_chiaki_audio_decoder_output_thread_func(&d);
assert(output_polls==3 && releases==0 && frames==0);
''')

    def test_shutdown_without_eos_delivery_joins_before_delete(self):
        for failure in ['input_index=-1;', 'queue_result=-1;', '']:
            with self.subTest(failure=failure):
                self.decoder('''
d.codec=NULL;
ChiakiAudioHeader header={2,48000};
android_chiaki_audio_decoder_header(&header,&d);
no_output=true;
''' + failure + '''
android_chiaki_audio_decoder_fini(&d);
assert(joins==1 && joined && deleted==1 && d.codec==NULL);
assert(d.codec_mutex==0);
assert(queues==(input_index<0 ? 3 : 4) && d.timestamp_cur==3);
''')

    def test_real_output_thread_exits_when_eos_is_unavailable(self):
        for failure in ['input_index=-1;', 'queue_result=-1;', '']:
            with self.subTest(failure=failure):
                self.decoder('''
d.codec=NULL;
ChiakiAudioHeader header={2,48000};
android_chiaki_audio_decoder_header(&header,&d);
assert(pthread_mutex_lock(&gate)==0);
while(!entered_output) assert(pthread_cond_wait(&wake,&gate)==0);
assert(pthread_mutex_unlock(&gate)==0);
''' + failure + '''
android_chiaki_audio_decoder_fini(&d);
assert(joins==1 && deleted==1 && joined && output_polls>=1);
assert(d.codec==NULL && d.codec_mutex==0 && frames==0);
''', fake=threaded_decoder_fake())

    def test_output_acquired_during_stop_is_released_without_callback(self):
        self.decoder('''
output_info.flags=0; poll_stop=&d.shutdown_requested;
android_chiaki_audio_decoder_output_thread_func(&d);
assert(output_polls==3 && frames==2 && releases==3 && d.codec_mutex==0);
''')

    def test_replacement_joins_without_recursive_mutex_held(self):
        self.decoder('''
d.codec=NULL;
probe_join_callbacks=true;
ChiakiAudioHeader header={2,48000};
android_chiaki_audio_decoder_header(&header,&d);
android_chiaki_audio_decoder_header(&header,&d);
assert(joins==1 && deleted==1 && threads==2 && settings==2);
assert(!atomic_load(&d.shutdown_requested));
android_chiaki_audio_decoder_fini(&d);
assert(joins==2 && deleted==2 && d.codec_mutex==0);
''')

    def test_failed_open_does_not_start(self):
        self.compile_run(OUTPUT_FAKE, source_without_includes('audio-output.cpp'), r'''
AudioOutput ao;
oboe::open_result=oboe::Result::Error;
android_chiaki_audio_output_settings(2,48000,&ao);
assert(oboe::starts==0);
assert(!ao.stream);
''', cpp=True)

    def test_configure_failure_cleans_up(self):
        self.decoder('''
d.codec=NULL;
configure_result=-1;
ChiakiAudioHeader header={2,48000};
android_chiaki_audio_decoder_header(&header,&d);
assert(d.codec==NULL && d.codec_mutex==0);
assert(configured==1 && started==0 && threads==0 && queues==0 && settings==0);
assert(deleted==1 && format_deleted==1);
''')

    def test_start_failure_cleans_up(self):
        self.decoder('''
d.codec=NULL; start_result=-1;
ChiakiAudioHeader header={2,48000};
android_chiaki_audio_decoder_header(&header,&d);
assert(d.codec==NULL && d.codec_mutex==0);
assert(started==1 && threads==0 && queues==0 && settings==0);
assert(deleted==1 && format_deleted==1);
''')

    def test_format_allocation_failure_cleans_up(self):
        self.decoder('''
d.codec=NULL; null_format=true;
ChiakiAudioHeader header={2,48000};
android_chiaki_audio_decoder_header(&header,&d);
assert(d.codec==NULL && d.codec_mutex==0);
assert(configured==0 && threads==0 && settings==0 && deleted==1);
''')

    def test_thread_failure_does_not_publish_settings(self):
        self.decoder('''
d.codec=NULL; thread_result=-1;
ChiakiAudioHeader header={2,48000};
android_chiaki_audio_decoder_header(&header,&d);
assert(d.codec==NULL && d.codec_mutex==0 && deleted==1);
assert(queues==0 && settings==0);
''')

    def test_oversized_packet_is_not_split(self):
        self.decoder('''
input_capacity=3;
android_chiaki_audio_decoder_frame(data,4,&d);
assert(dequeues==1 && queues==1 && queued_size==0);
assert(d.timestamp_cur==0 && d.codec_mutex==0);
assert(storage[0]==0);
''')

    def test_null_input_pointers_are_rejected(self):
        for setup, call, expected_dequeues in [
                ('input_ptr=NULL;', 'data,4', 1),
                ('', 'NULL,4', 0)]:
            with self.subTest(call=call, setup=setup):
                self.decoder(setup + f'''
android_chiaki_audio_decoder_frame({call},&d);
assert(d.codec_mutex==0 && d.timestamp_cur==0);
assert(dequeues=={expected_dequeues});
assert(queues=={expected_dequeues} && queued_size==0);
''')

    def test_queue_failure_quarantines_input_until_codec_replacement(self):
        for setup in ['', 'input_capacity=0;', 'input_ptr=NULL;']:
            with self.subTest(setup=setup):
                self.decoder(setup + '''
queue_result=-1;
android_chiaki_audio_decoder_frame(data,4,&d);
queue_result=0;
for(int i=0;i<20;i++) android_chiaki_audio_decoder_frame(data,4,&d);
assert(dequeues==1 && queues==1);
assert(d.timestamp_cur==0 && d.codec_mutex==0);
''')

    def test_new_codec_resets_input_quarantine(self):
        self.decoder('''
d.codec=NULL;
ChiakiAudioHeader header={2,48000};
android_chiaki_audio_decoder_header(&header,&d);
queue_result=-1;
android_chiaki_audio_decoder_frame(data,4,&d);
assert(d.input_failed);
queue_result=0; queues=0; dequeues=0;
android_chiaki_audio_decoder_header(&header,&d);
assert(joins==1 && deleted==1 && dequeues==3); // No EOS index from quarantined codec.
assert(!d.input_failed && !atomic_load(&d.shutdown_requested) && queues==3);
android_chiaki_audio_decoder_frame(data,4,&d);
assert(queues==4 && d.codec_mutex==0);
android_chiaki_audio_decoder_fini(&d);
''')

    def test_queue_failure_does_not_advance_timestamp(self):
        self.decoder('''
queue_result=-1; d.timestamp_cur=42;
android_chiaki_audio_decoder_frame(data,4,&d);
assert(queues==1 && queued_size==4 && queued_timestamp==42);
assert(d.timestamp_cur==42 && d.codec_mutex==0);
''')

    def test_output_callback_runs_under_codec_mutex(self):
        self.decoder('''
d.cb_user=&d;
android_chiaki_audio_decoder_output_thread_func(&d);
assert(frames==1 && d.codec_mutex==0);
''')

    def test_callback_setter_uses_codec_mutex(self):
        self.decoder('''
int before=lock_calls;
android_chiaki_audio_decoder_set_cb(&d,settings_cb,frame_cb,&d);
assert(lock_calls==before+1 && d.codec_mutex==0 && d.cb_user==&d);
''')

    def test_output_uses_offset(self):
        self.decoder('''
output_info.offset=4; output_info.size=6;
int16_t expected[3]={123,-456,789};
memcpy(storage+4,expected,sizeof(expected));
android_chiaki_audio_decoder_output_thread_func(&d);
assert(frames==1 && received_ptr==(int16_t *)(storage+4) && received_count==3);
assert(releases==1 && !output_owned);
assert(memcmp(copied_pcm,expected,sizeof(expected))==0);
assert(storage[4]==0xa5); // Codec storage is invalid immediately after release.
''')

    def test_invalid_output_ranges_are_released_without_callback(self):
        cases = [
            'output_ptr=NULL;',
            'output_capacity=0;',
            'output_info.offset=-1;',
            'output_info.size=-1;',
            'output_info.offset=129;',
            'output_info.offset=126; output_info.size=4;',
            'output_info.offset=1;',
            'output_info.size=3;',
            'output_ptr=storage+1;',
        ]
        for setup in cases:
            with self.subTest(setup=setup):
                self.decoder(setup + '''
android_chiaki_audio_decoder_output_thread_func(&d);
assert(frames==0 && releases==1);
''')

    def test_output_checks_frame_callback_not_settings_callback(self):
        for setup, expected in [('d.frame_cb=NULL;', 0), ('d.settings_cb=NULL;', 1)]:
            with self.subTest(setup=setup):
                self.decoder(setup + f'''
android_chiaki_audio_decoder_output_thread_func(&d);
assert(frames=={expected} && releases==1);
''')

    def test_successful_header_and_packet_preserve_callbacks(self):
        self.decoder('''
d.codec=NULL;
ChiakiAudioHeader header={2,48000};
android_chiaki_audio_decoder_header(&header,&d);
assert(d.codec==&codec && d.codec_mutex==0 && threads==1);
assert(configured==1 && started==1 && format_deleted==1 && deleted==0);
assert(queues==3 && settings==1 && d.timestamp_cur==3);
queues=0; dequeues=0; input_capacity=4;
android_chiaki_audio_decoder_frame(data,4,&d);
assert(queues==1 && queued_size==4 && queued_timestamp==3 && d.timestamp_cur==4);
assert(memcmp(data,storage,4)==0 && d.codec_mutex==0);
''')

    def test_empty_or_uninitialized_input_is_ignored(self):
        self.decoder('''
android_chiaki_audio_decoder_frame(NULL,0,&d);
d.codec=NULL;
android_chiaki_audio_decoder_frame(data,4,&d);
assert(queues==0 && dequeues==0 && d.codec_mutex==0);
''')

    def test_zero_capacity_returns_buffer_once_even_when_queue_fails(self):
        self.decoder('''
input_capacity=0; queue_result=-1;
android_chiaki_audio_decoder_frame(data,4,&d);
assert(dequeues==1 && queues==1 && queued_size==0);
assert(d.timestamp_cur==0 && d.codec_mutex==0);
''')

    def test_output_range_ending_at_capacity_is_valid(self):
        self.decoder('''
output_info.offset=124; output_info.size=4;
android_chiaki_audio_decoder_output_thread_func(&d);
assert(frames==1 && received_ptr==(int16_t *)(storage+124) && received_count==2);
assert(releases==1);
''')

    def test_output_start_and_pcm_silence_behavior_preserved(self):
        self.compile_run(OUTPUT_FAKE, source_without_includes('audio-output.cpp'), r'''
AudioOutput ao;
android_chiaki_audio_output_settings(2,48000,&ao);
assert(oboe::starts==1 && ao.stream);
int16_t pcm[512];
for(auto &sample:pcm) sample=123;
android_chiaki_audio_output_frame(pcm,512,&ao);
int16_t output[512]={};
assert(ao.stream_callback.onAudioReady(ao.stream.get(),output,256)==oboe::DataCallbackResult::Continue);
assert(memcmp(pcm,output,sizeof(pcm))==0);
assert(ao.stream_callback.onAudioReady(ao.stream.get(),output,256)==oboe::DataCallbackResult::Continue);
for(auto sample:output) assert(sample==0);
''', cpp=True)

    def test_dequeue_failure_unlocks(self):
        self.decoder('input_index=-1; android_chiaki_audio_decoder_frame(data,4,&d); assert(d.codec_mutex==0);')


if __name__ == '__main__':
    unittest.main(verbosity=2)
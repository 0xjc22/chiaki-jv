#!/usr/bin/env python3
"""Check extracted decoder teardown ordering and native-window ownership.

API fakes check mutex balance and lifecycle order, not real Android concurrency.
"""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
s = (root / 'android/app/src/main/cpp/video-decoder.c').read_text()
init_start = s.index('ChiakiErrorCode android_chiaki_video_decoder_init(')
kill_start = s.index('static void kill_decoder(AndroidChiakiVideoDecoder *decoder)\n{')
fini_start = s.index('void android_chiaki_video_decoder_fini(')
surface_start = s.index('void android_chiaki_video_decoder_set_surface(')
lifecycle = s[init_start:surface_start]
assert 'chiaki_thread_join' in lifecycle and 'AMediaCodec_delete' in lifecycle
null_start = s.index('\tif(!surface)', surface_start)
null_end = s.index('\n\tif(decoder->codec)', null_start)
null_block = s[null_start:null_end]
assert 'kill_decoder' in null_block
harness = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#define CHIAKI_LOGI(...) ((void)0)
#define CHIAKI_LOGE(...) ((void)0)
#define AMEDIACODEC_BUFFER_FLAG_END_OF_STREAM 4
typedef int ChiakiErrorCode;
typedef int ChiakiCodec;
typedef void ChiakiLog;
typedef void AMediaCodec;
typedef void ANativeWindow;
typedef struct { int depth, max_depth; } ChiakiMutex;
typedef struct { bool joined; } ChiakiThread;
typedef struct {
    ChiakiLog *log; AMediaCodec *codec; ANativeWindow *window;
    ChiakiMutex codec_mutex; ChiakiThread output_thread;
    bool shutdown_output, input_capacity_logged, codec_missing_logged;
    uint64_t timestamp_cur; int32_t target_width, target_height; ChiakiCodec target_codec;
} AndroidChiakiVideoDecoder;
static int dequeue_result, stop_count, delete_count, eos_queued, window_releases;
static AndroidChiakiVideoDecoder *tracked_decoder;
static int chiaki_mutex_init(ChiakiMutex *m, bool recursive) { (void)recursive; *m=(ChiakiMutex){0}; return 0; }
static void chiaki_mutex_fini(ChiakiMutex *m) { if(m->depth) abort(); }
static void chiaki_mutex_lock(ChiakiMutex *m) { if(++m->depth!=1) abort(); if(m->depth > m->max_depth) m->max_depth=m->depth; }
static void chiaki_mutex_unlock(ChiakiMutex *m) { if(--m->depth!=0) abort(); }
static void chiaki_thread_join(ChiakiThread *t, void *r) {
    (void)r;
    if(tracked_decoder->codec_mutex.depth || !tracked_decoder->shutdown_output || !stop_count) abort();
    t->joined=true;
}
static ssize_t AMediaCodec_dequeueInputBuffer(AMediaCodec *c, int64_t t) { (void)c; (void)t; return dequeue_result; }
static void AMediaCodec_queueInputBuffer(AMediaCodec *c, size_t i, size_t o, size_t sz, uint64_t pts, uint32_t f) {
    (void)c; (void)i; (void)o; (void)sz; (void)pts; if(f & AMEDIACODEC_BUFFER_FLAG_END_OF_STREAM) eos_queued++;
}
static void AMediaCodec_stop(AMediaCodec *c) { (void)c; stop_count++; }
static void AMediaCodec_delete(AMediaCodec *c) {
    (void)c;
    if(!tracked_decoder->output_thread.joined || tracked_decoder->codec || tracked_decoder->codec_mutex.depth) abort();
    delete_count++;
}
void ANativeWindow_release(ANativeWindow *window) {
    if(!window || tracked_decoder->window || (delete_count==0 && stop_count)) abort();
    window_releases++;
}
''' + lifecycle + r'''
static void set_surface_null_branch(AndroidChiakiVideoDecoder *decoder)
{
    bool surface = false; (void)surface;
''' + null_block + r'''
}
#define CHECK(x) do { if(!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); return 1; } } while(0)
static void reset(AndroidChiakiVideoDecoder *d, bool codec, bool window) {
    *d=(AndroidChiakiVideoDecoder){.codec=codec?(void*)1:NULL,.window=window?(void*)2:NULL};
    tracked_decoder=d; stop_count=delete_count=eos_queued=window_releases=0;
}
int main(void) {
    AndroidChiakiVideoDecoder d;
    memset(&d,0xa5,sizeof(d)); tracked_decoder=&d;
    CHECK(android_chiaki_video_decoder_init(&d,NULL,1920,1080,1)==0);
    CHECK(d.codec==NULL); CHECK(d.window==NULL);
    puts("PASS init establishes empty native-window ownership");
    for(int eos=0; eos<2; eos++) {
        reset(&d,true,true); dequeue_result=eos?0:-1;
        kill_decoder(&d);
        CHECK(d.codec==NULL); CHECK(d.window==NULL); CHECK(stop_count==1); CHECK(delete_count==1);
        CHECK(window_releases==1); CHECK(d.output_thread.joined); CHECK(eos_queued==eos);
        CHECK(d.codec_mutex.depth==0); CHECK(d.codec_mutex.max_depth==1); CHECK(!d.shutdown_output);
    }
    puts("PASS kill joins unlocked, detaches before delete, and releases window on both EOS paths");
    reset(&d,true,true); chiaki_mutex_lock(&d.codec_mutex); set_surface_null_branch(&d);
    CHECK(d.codec==NULL); CHECK(d.window==NULL); CHECK(delete_count==1); CHECK(window_releases==1);
    CHECK(d.codec_mutex.depth==0); CHECK(d.codec_mutex.max_depth==1);
    android_chiaki_video_decoder_fini(&d); CHECK(window_releases==1);
    puts("PASS surface removal releases once; subsequent fini is harmless");
    reset(&d,false,true); chiaki_mutex_lock(&d.codec_mutex); set_surface_null_branch(&d);
    CHECK(d.window==NULL); CHECK(window_releases==1); CHECK(delete_count==0); CHECK(d.codec_mutex.depth==0);
    puts("PASS surface removal cleans retained window without a codec");
    reset(&d,true,true); android_chiaki_video_decoder_fini(&d);
    CHECK(window_releases==1); CHECK(d.window==NULL); CHECK(delete_count==1);
    puts("PASS direct fini releases attached window");
    reset(&d,false,false); android_chiaki_video_decoder_fini(&d);
    CHECK(window_releases==0); CHECK(delete_count==0); CHECK(d.codec_mutex.depth==0);
    puts("PASS empty fini is a no-op");
}
'''
with tempfile.TemporaryDirectory(prefix='chiaki-teardown-', dir=os.environ.get('TMPDIR')) as tmp:
    c = Path(tmp) / 'test.c'
    exe = Path(tmp) / 'test'
    c.write_text(harness)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=2)

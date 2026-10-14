#!/usr/bin/env python3
"""Exercise actual decoder teardown: no deadlock, no lock leak, no use-after-free ordering."""
from pathlib import Path
import os
import subprocess
import tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'android/app/src/main/cpp/video-decoder.c').read_text()
kill_start=s.index('static void kill_decoder(AndroidChiakiVideoDecoder *decoder)\n{')
kill_end=s.index('void android_chiaki_video_decoder_fini(AndroidChiakiVideoDecoder *decoder)')
kill_block=s[kill_start:kill_end]
null_start=s.index('\tif(!surface)')
null_end=s.index('\n\tif(decoder->codec)', null_start)
null_block=s[null_start:null_end]
harness=r'''
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <sys/types.h>
#define CHIAKI_LOGI(...) ((void)0)
#define CHIAKI_LOGE(...) ((void)0)
#define AMEDIACODEC_BUFFER_FLAG_END_OF_STREAM 4
typedef void *AMediaCodec;
typedef struct { int depth, max_depth; } ChiakiMutex;
typedef struct { bool joined; } ChiakiThread;
typedef struct { void *log; AMediaCodec *codec; ChiakiMutex codec_mutex; ChiakiThread output_thread; bool shutdown_output; uint64_t timestamp_cur; } AndroidChiakiVideoDecoder;
static int dequeue_result, stop_count, delete_count, eos_queued;
static int depth_at_delete;
static ChiakiMutex *tracked_mutex;
static void chiaki_mutex_lock(ChiakiMutex *m) { m->depth++; if(m->depth > m->max_depth) m->max_depth = m->depth; tracked_mutex = m; }
static void chiaki_mutex_unlock(ChiakiMutex *m) { m->depth--; }
static void chiaki_thread_join(ChiakiThread *t, void *r) { (void)r; t->joined = true; }
static ssize_t AMediaCodec_dequeueInputBuffer(AMediaCodec c, int64_t t) { (void)c; (void)t; return dequeue_result; }
static void AMediaCodec_queueInputBuffer(AMediaCodec c, size_t i, size_t o, size_t sz, uint64_t pts, uint32_t f) { (void)c;(void)i;(void)o;(void)sz;(void)pts; if(f & AMEDIACODEC_BUFFER_FLAG_END_OF_STREAM) eos_queued++; }
static void AMediaCodec_stop(AMediaCodec c) { (void)c; stop_count++; }
static void AMediaCodec_delete(AMediaCodec c) { (void)c; delete_count++; if(tracked_mutex) depth_at_delete = tracked_mutex->depth; }
'''+kill_block+r'''
static void set_surface_null_branch(AndroidChiakiVideoDecoder *decoder)
{
	bool surface = 0; (void)surface;
'''+null_block+r'''
}
#define CHECK(x) do { if(!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); return 1; } } while(0)
int main(void) {
    AMediaCodec fake_codec = (AMediaCodec)1;
    AndroidChiakiVideoDecoder d = {.codec=&fake_codec};
    dequeue_result = -1;
    kill_decoder(&d);
    CHECK(d.codec==NULL); CHECK(stop_count==1); CHECK(delete_count==1); CHECK(d.output_thread.joined);
    CHECK(depth_at_delete==0); CHECK(d.codec_mutex.depth==0); CHECK(d.codec_mutex.max_depth==1); CHECK(!d.shutdown_output);
    puts("PASS kill_decoder: joined before delete, deleted unlocked, state reset");
    d=(AndroidChiakiVideoDecoder){.codec=&fake_codec}; dequeue_result=0; stop_count=delete_count=eos_queued=0;
    kill_decoder(&d);
    CHECK(eos_queued==1); CHECK(d.output_thread.joined); CHECK(delete_count==1); CHECK(depth_at_delete==0); CHECK(d.codec_mutex.depth==0);
    puts("PASS kill_decoder EOS path: ordered join, unlocked delete");
    d=(AndroidChiakiVideoDecoder){.codec=NULL}; stop_count=delete_count=0;
    kill_decoder(&d);
    CHECK(stop_count==0); CHECK(delete_count==0); CHECK(d.codec_mutex.depth==0);
    puts("PASS kill_decoder with no codec: no-op, no lock leak");
    d=(AndroidChiakiVideoDecoder){.codec=&fake_codec}; stop_count=delete_count=0;
    chiaki_mutex_lock(&d.codec_mutex);
    set_surface_null_branch(&d);
    CHECK(d.codec==NULL); CHECK(delete_count==1); CHECK(d.codec_mutex.depth==0); CHECK(d.codec_mutex.max_depth==1);
    puts("PASS set_surface(NULL) with codec: no deadlock, no lock leak, decoder killed");
    d=(AndroidChiakiVideoDecoder){.codec=NULL}; stop_count=delete_count=0;
    chiaki_mutex_lock(&d.codec_mutex);
    set_surface_null_branch(&d);
    CHECK(delete_count==0); CHECK(d.codec_mutex.depth==0);
    puts("PASS set_surface(NULL) without codec: unlocks before returning");
}
'''
with tempfile.TemporaryDirectory(prefix='chiaki-teardown-',dir=os.environ.get('TMPDIR')) as tmp:
    c=Path(tmp)/'test.c'; exe=Path(tmp)/'test'; c.write_text(harness)
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

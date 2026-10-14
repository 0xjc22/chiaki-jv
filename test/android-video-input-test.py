#!/usr/bin/env python3
"""Host regression test of the actual Android input callback, with codec API fakes.
Run: python3 test/android-video-input-test.py [optional source path]
No Android device is required; this tests submission, not hardware decoding.
"""
from pathlib import Path
import os
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
source = Path(sys.argv[1]) if len(sys.argv) > 1 else root / 'android/app/src/main/cpp/video-decoder.c'
text = source.read_text()
start = text.index('bool android_chiaki_video_decoder_video_sample(')
end = text.index('\nstatic void *android_chiaki_video_decoder_output_thread_func', start)
callback = text[start:end]
harness = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#define INPUT_BUFFER_TIMEOUT_MS 10
#define INPUT_BUFFER_DEQUEUE_ATTEMPTS 3
#define AMEDIA_OK 0
#define CHIAKI_LOGE(...) ((void)0)
#define CHIAKI_LOGI(...) ((void)0)
#define CHIAKI_LOGW(...) ((void)0)
typedef int media_status_t;
typedef struct { void *codec; int codec_mutex; void *log; uint64_t timestamp_cur; bool input_capacity_logged; bool codec_missing_logged; } AndroidChiakiVideoDecoder;
static int locks, queues, deqs, fail_queue, timeout, null_buffer;
static size_t capacity = 8, queued_sizes[8];
static uint8_t storage[32], submitted[32];
static uint64_t pts[8];
uint64_t android_chiaki_video_decoder_time_us(void) { return 1000; }
static void chiaki_mutex_lock(int *m) { (void)m; locks++; }
static void chiaki_mutex_unlock(int *m) { (void)m; locks--; }
static ssize_t AMediaCodec_dequeueInputBuffer(void *c, int64_t t) { (void)c;(void)t; deqs++; return timeout ? -1 : 0; }
static uint8_t *AMediaCodec_getInputBuffer(void *c, size_t i, size_t *n) { (void)c;(void)i; *n=capacity; return null_buffer ? NULL : storage; }
static media_status_t AMediaCodec_queueInputBuffer(void *c, size_t i, size_t o, size_t n, uint64_t t, uint32_t f) {
    (void)c;(void)i;(void)o;(void)f;
    if(queues >= 8) { fprintf(stderr,"unbounded queue loop\n"); exit(2); }
    queued_sizes[queues]=n; pts[queues]=t; queues++;
    if(n) memcpy(submitted,storage,n);
    return fail_queue ? -1 : 0;
}
'''
harness += callback
harness += r'''
#define CHECK(x) do { if(!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); return 1; } } while(0)
int main(int argc, char **argv) {
    const char *scenario=argv[1]; (void)argc;
    uint8_t frame[16]; for(int i=0;i<16;i++) frame[i]=(uint8_t)i;
    AndroidChiakiVideoDecoder d={.codec=(void*)1,.timestamp_cur=100};
    bool ok;
    if(!strcmp(scenario,"oversize")) {
        ok=android_chiaki_video_decoder_video_sample(frame,16,&d);
        CHECK(!ok); CHECK(queues==1); CHECK(queued_sizes[0]==0); CHECK(pts[0]==101); CHECK(d.timestamp_cur==100);
    } else if(!strcmp(scenario,"complete")) {
        ok=android_chiaki_video_decoder_video_sample(frame,8,&d);
        CHECK(ok); CHECK(queues==1); CHECK(queued_sizes[0]==8); CHECK(pts[0]==1000); CHECK(d.timestamp_cur==1000); CHECK(!memcmp(frame,submitted,8));
        CHECK(android_chiaki_video_decoder_video_sample(frame,4,&d)); CHECK(pts[1]==1001);
    } else if(!strcmp(scenario,"queue_failure")) {
        fail_queue=1; ok=android_chiaki_video_decoder_video_sample(frame,8,&d); CHECK(!ok); CHECK(queues==1);
    } else if(!strcmp(scenario,"timeout")) {
        timeout=1; ok=android_chiaki_video_decoder_video_sample(frame,8,&d); CHECK(!ok); CHECK(queues==0); CHECK(deqs==3);
    } else if(!strcmp(scenario,"uninitialized")) {
        d.codec=NULL; ok=android_chiaki_video_decoder_video_sample(frame,8,&d); CHECK(ok); CHECK(deqs==0);
    } else if(!strcmp(scenario,"zero_capacity")) {
        capacity=0; ok=android_chiaki_video_decoder_video_sample(frame,8,&d); CHECK(!ok); CHECK(queues==1); CHECK(queued_sizes[0]==0); CHECK(pts[0]==101);
    } else if(!strcmp(scenario,"null_buffer")) {
        null_buffer=1; ok=android_chiaki_video_decoder_video_sample(frame,8,&d); CHECK(!ok);
    } else if(!strcmp(scenario,"empty")) {
        ok=android_chiaki_video_decoder_video_sample(frame,0,&d); CHECK(ok); CHECK(deqs==0); CHECK(d.timestamp_cur==100);
    } else return 2;
    CHECK(locks==0); printf("PASS %s\n",scenario); return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='chiaki-input-', dir=os.environ.get('TMPDIR')) as tmp:
    c = Path(tmp)/'test.c'
    exe = Path(tmp)/'test'
    c.write_text(harness)
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-parameter',str(c),'-o',str(exe)],check=True)
    failures = 0
    for case in ['oversize','complete','queue_failure','timeout','uninitialized','zero_capacity','null_buffer','empty']:
        try:
            result = subprocess.run([str(exe),case],timeout=2)
            failures += result.returncode != 0
        except subprocess.TimeoutExpired:
            print('FAIL timeout:',case)
            failures += 1
    print(f'{8-failures}/8 input callback scenarios passed')
    sys.exit(bool(failures))

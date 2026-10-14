#!/usr/bin/env python3
"""Exercise the actual output loop and client decode-latency accounting."""
from pathlib import Path
import os
import subprocess
import tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'android/app/src/main/cpp/video-decoder.c').read_text()
start=s.rindex('static void *android_chiaki_video_decoder_output_thread_func(void *user)')
block=s[start:]
harness=r'''
#define _DEFAULT_SOURCE
#include <stdbool.h>
#include <stdint.h>
#include <unistd.h>
#include <stddef.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <math.h>
#include <sys/types.h>
#define AMEDIACODEC_BUFFER_FLAG_END_OF_STREAM 4
#define AMEDIACODEC_BUFFER_FLAG_CODEC_CONFIG 2
#define AMEDIACODEC_INFO_OUTPUT_FORMAT_CHANGED -2
#define AMEDIACODEC_INFO_OUTPUT_BUFFERS_CHANGED -3
#define AMEDIACODEC_INFO_TRY_AGAIN_LATER -1
#define CHIAKI_LOGI(log,...) log_info(__VA_ARGS__)
#define CHIAKI_LOGW(...) ((void)0)
#define CHIAKI_LOGE(...) do { errors++; } while(0)
typedef struct { int size; int64_t presentationTimeUs; uint32_t flags; } AMediaCodecBufferInfo;
typedef struct { void *codec,*log; int codec_mutex; bool shutdown_output; } AndroidChiakiVideoDecoder;
static int output_index,released,reports,clock_index,invalid_pts;
static int negative_index,negative_count,negative_status,errors,backoffs;
static int fake_usleep(unsigned int delay) { if(delay!=2000) return -1; backoffs++; return 0; }
#define usleep fake_usleep
static double avg_ms,max_ms; static unsigned long long frames;
uint64_t android_chiaki_video_decoder_time_us(void) { const uint64_t t[]={1001000,3001000}; return t[clock_index++]; }
static void log_info(const char *fmt,...) {
    if(strstr(fmt,"Video client decode latency:")) {
        va_list ap; va_start(ap,fmt); avg_ms=va_arg(ap,double); max_ms=va_arg(ap,double); frames=va_arg(ap,unsigned long long); va_end(ap); reports++;
    }
}
static void chiaki_mutex_lock(int *m) { (void)m; }
static void chiaki_mutex_unlock(int *m) { (void)m; }
static ssize_t AMediaCodec_dequeueOutputBuffer(void *c,AMediaCodecBufferInfo *info,int64_t timeout) {
    (void)c;(void)timeout;
    if(negative_index++ < negative_count) return negative_status;
    info->size=output_index<2 ? 5 : 0;
    info->flags=output_index==2 ? AMEDIACODEC_BUFFER_FLAG_END_OF_STREAM : 0;
    info->presentationTimeUs=output_index==0 ? 1000000 : 2997000;
    if(invalid_pts) info->presentationTimeUs=output_index==0 ? 0 : 4000000;
    return output_index++;
}
static int AMediaCodec_releaseOutputBuffer(void *c,size_t i,bool render) {
    (void)c; if(render!=(i<2)) return -1; released++; return 0;
}
'''+block+r'''
int main(int argc,char **argv) {
    (void)argc; invalid_pts=!strcmp(argv[1],"invalid");
    if(!strcmp(argv[1],"format")) { negative_count=1; negative_status=AMEDIACODEC_INFO_OUTPUT_FORMAT_CHANGED; }
    if(!strcmp(argv[1],"buffers")) { negative_count=1; negative_status=AMEDIACODEC_INFO_OUTPUT_BUFFERS_CHANGED; }
    if(!strcmp(argv[1],"retry")) { negative_count=1; negative_status=AMEDIACODEC_INFO_TRY_AGAIN_LATER; }
    if(!strcmp(argv[1],"error")) { negative_count=2; negative_status=-10000; }
    AndroidChiakiVideoDecoder d={.codec=(void*)1};
    android_chiaki_video_decoder_output_thread_func(&d);
    if(errors!=(!strcmp(argv[1],"error")?1:0)) { fprintf(stderr,"FAIL informational/error logs: %d\n",errors); return 1; }
    int expected_backoffs=!strcmp(argv[1],"error")?2:!strcmp(argv[1],"retry")?1:0;
    if(backoffs!=expected_backoffs) { fprintf(stderr,"FAIL unexpected backoff: %d\n",backoffs); return 1; }
    if(released!=3 || output_index!=3) return 1;
    if(invalid_pts) { if(reports!=0) return 1; puts("PASS invalid/future PTS ignored; EOS handled"); }
    else {
        if(reports!=1 || frames!=2 || fabs(avg_ms-(1.0+4.0)/2.0)>0.001 || fabs(max_ms-4.0)>0.001) {
            fprintf(stderr,"FAIL telemetry: reports=%d frames=%llu avg=%f max=%f\n",reports,frames,avg_ms,max_ms); return 1;
        }
        puts("PASS input-to-output latency aggregation without changing render behavior");
    }
}
'''
with tempfile.TemporaryDirectory(prefix='chiaki-output-',dir=os.environ.get('TMPDIR')) as tmp:
    c=Path(tmp)/'test.c'; exe=Path(tmp)/'test'; c.write_text(harness)
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(c),'-lm','-o',str(exe)],check=True)
    for case in ['normal','invalid','format','buffers','retry','error']:
        subprocess.run([str(exe),case],check=True,timeout=2)

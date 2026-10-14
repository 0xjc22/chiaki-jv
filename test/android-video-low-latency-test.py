#!/usr/bin/env python3
"""Exercise actual decoder configuration, including optional low-latency fallback."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
s = (root/'android/app/src/main/cpp/video-decoder.c').read_text()
block = s[s.index('\tAMediaFormat *format = AMediaFormat_new();'):s.index('\tr = AMediaCodec_start(')]
assert 'AMediaCodec_configure' in block and 'AMediaCodec_createDecoderByType' in block
harness = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define AMEDIAFORMAT_KEY_MIME "mime"
#define AMEDIAFORMAT_KEY_WIDTH "width"
#define AMEDIAFORMAT_KEY_HEIGHT "height"
#define AMEDIAFORMAT_KEY_MAX_INPUT_SIZE "max-input-size"
#define AMEDIAFORMAT_KEY_LOW_LATENCY "low-latency"
#define AMEDIAFORMAT_KEY_FRAME_RATE "frame-rate"
#define AMEDIAFORMAT_KEY_OPERATING_RATE "operating-rate"
#define AMEDIAFORMAT_KEY_PRIORITY "priority"
#define AMEDIA_OK 0
#define CHIAKI_LOGI(...) ((void)0)
#define CHIAKI_LOGW(...) ((void)0)
#define CHIAKI_LOGE(...) ((void)0)
typedef int media_status_t;
typedef struct { int low_latency; } AMediaFormat;
typedef struct { int32_t target_width,target_height,target_codec,target_fps; void *log,*codec,*window; } AndroidChiakiVideoDecoder;
static AMediaFormat fmt;
static int calls, flags[4], reject_low_latency, reject_all, deletes, creates, fail_create, reject_full;
static bool chiaki_codec_is_h265(int codec) { return codec==1; }
static AMediaFormat *AMediaFormat_new(void) { fmt.low_latency=0; return &fmt; }
static void AMediaFormat_setString(AMediaFormat *f,const char *k,const char *v) { (void)f;(void)k;(void)v; }
static void AMediaFormat_setFloat(AMediaFormat *f,const char *k,float v) { (void)f;(void)k;(void)v; }
static void AMediaFormat_setInt32(AMediaFormat *f,const char *k,int v) { if(!strcmp(k,"low-latency")) f->low_latency=v; }
static void AMediaFormat_delete(AMediaFormat *f) { (void)f; }
static void AMediaCodec_delete(void *c) { if(c!=(void*)1) abort(); deletes++; }
static void *AMediaCodec_createDecoderByType(const char *mime) { (void)mime; if(deletes!=creates+1) abort(); creates++; return fail_create?NULL:(void*)2; }
static media_status_t AMediaCodec_configure(void *c,AMediaFormat *f,void *w,void *crypto,int opts) {
    (void)c;(void)w;(void)crypto;(void)opts;
    if(c!=(calls==0?(void*)1:(void*)2)) abort();
    flags[calls++]=f->low_latency;
    return (reject_all || (reject_full && calls==1) || (reject_low_latency && f->low_latency)) ? -1 : AMEDIA_OK;
}
static int configure(int codec) {
    AndroidChiakiVideoDecoder d={.target_width=1920,.target_height=1080,.target_codec=codec,.codec=(void*)1};
    AndroidChiakiVideoDecoder *decoder=&d;
    const char *mime=codec==1 ? "video/hevc" : "video/avc";
'''+block+r'''
    AMediaFormat_delete(format); return AMEDIA_OK;
error_codec:
    return r;
}
#define CHECK(x) do { if(!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); return 1; } } while(0)
int main(void) {
    CHECK(configure(1)==AMEDIA_OK); CHECK(calls==1); CHECK(flags[0]==1);
    puts("PASS HEVC requests explicit low latency");
    calls=0; CHECK(configure(0)==AMEDIA_OK); CHECK(calls==1); CHECK(flags[0]==0);
    puts("PASS AVC configuration unchanged");
    calls=0; reject_low_latency=1; CHECK(configure(1)==AMEDIA_OK); CHECK(calls==2); CHECK(flags[0]==1); CHECK(flags[1]==0);
    puts("PASS unsupported HEVC low latency falls back");
    calls=0; reject_all=1; CHECK(configure(1)!=AMEDIA_OK); CHECK(calls==2);
    puts("PASS real configuration failure remains failure");
    CHECK(deletes==2); CHECK(creates==2);
    calls=0; reject_all=reject_low_latency=0; reject_full=1;
    CHECK(configure(0)==AMEDIA_OK); CHECK(calls==2); CHECK(deletes==3); CHECK(creates==3);
    puts("PASS AVC full-format rejection also recreates codec before minimal fallback");
    calls=0; fail_create=1;
    CHECK(configure(1)!=AMEDIA_OK); CHECK(calls==1); CHECK(deletes==4); CHECK(creates==4);
    puts("PASS codec recreation failure propagates without configuring NULL");
}
'''
with tempfile.TemporaryDirectory(prefix='chiaki-lowlatency-',dir=os.environ.get('TMPDIR')) as tmp:
    c=Path(tmp)/'test.c'; exe=Path(tmp)/'test'
    c.write_text(harness)
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-function',str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

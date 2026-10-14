#!/usr/bin/env python3
"""Compile and exercise the actual MediaFormat setup block on the host."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
s = (root/'android/app/src/main/cpp/video-decoder.c').read_text()
block = s[s.index('\tAMediaFormat *format = AMediaFormat_new();'):s.index('\tmedia_status_t r = AMediaCodec_configure(')]
assert len(block) > 400 and 'AMEDIAFORMAT_KEY_MAX_INPUT_SIZE' in block and 'AMEDIAFORMAT_KEY_LOW_LATENCY' in block, 'extracted decoder format block is empty or missing keys'
harness = r'''
#include <stdint.h>
#include <stdbool.h>
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
#define CHIAKI_LOGI(...) ((void)0)
typedef struct { int32_t max_size; } AMediaFormat;
typedef struct { int32_t target_width, target_height, target_codec, target_fps; void *log; } AndroidChiakiVideoDecoder;
static bool chiaki_codec_is_h265(int codec) { return codec == 1; }
static AMediaFormat fmt;
static AMediaFormat *AMediaFormat_new(void) { fmt.max_size=0; return &fmt; }
static void AMediaFormat_setString(AMediaFormat *f,const char *k,const char *v) {(void)f;(void)k;(void)v;}

static void AMediaFormat_setInt32(AMediaFormat *f,const char *k,int32_t v) { if(!strcmp(k,"max-input-size")) f->max_size=v; }
static int32_t configure(int32_t w,int32_t h) {
    AndroidChiakiVideoDecoder d={.target_width=w,.target_height=h};
    AndroidChiakiVideoDecoder *decoder=&d;
    const char *mime="video/hevc";
'''+block+r'''
    return fmt.max_size;
}
int main(void) {
    const int32_t cases[][3]={{1280,720,2097152},{1920,1080,3110400},{3840,2160,12441600}};
    for(size_t i=0;i<sizeof(cases)/sizeof(cases[0]);i++) {
        int32_t actual=configure(cases[i][0],cases[i][1]);
        if(actual!=cases[i][2]) { fprintf(stderr,"FAIL %dx%d: requested %d, expected %d\n",cases[i][0],cases[i][1],actual,cases[i][2]); return 1; }
    }
    puts("PASS input-size requests for 720p, 1080p and 2160p");
}
'''
with tempfile.TemporaryDirectory(prefix='chiaki-format-',dir=os.environ.get('TMPDIR')) as tmp:
    c=Path(tmp)/'test.c'
    exe=Path(tmp)/'test'
    c.write_text(harness)
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

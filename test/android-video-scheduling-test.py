#!/usr/bin/env python3
"""Guard against reintroducing scheduling overrides that regressed phone latency."""
from pathlib import Path
import os
import subprocess
import tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'android/app/src/main/cpp/video-decoder.c').read_text()
block=s[s.index('\tAMediaFormat *format = AMediaFormat_new();'):s.index('\tmedia_status_t r = AMediaCodec_configure(')]
assert len(block) > 400 and 'AMEDIAFORMAT_KEY_MAX_INPUT_SIZE' in block, 'extracted decoder format block is empty or narrowed'
harness=r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
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
typedef struct { float fps,operating_rate; int priority; } AMediaFormat;
typedef struct { int32_t target_width,target_height,target_fps,target_codec; void *log; } AndroidChiakiVideoDecoder;
static AMediaFormat f;
static bool chiaki_codec_is_h265(int c) { return c==1; }
static AMediaFormat *AMediaFormat_new(void) { f=(AMediaFormat){.fps=1,.priority=4}; return &f; }
static void AMediaFormat_setString(AMediaFormat *f,const char *k,const char *v) { (void)f;(void)k;(void)v; }
static void AMediaFormat_setInt32(AMediaFormat *f,const char *k,int v) { if(!strcmp(k,"priority")) f->priority=v; if(!strcmp(k,"frame-rate")) f->fps=v; if(!strcmp(k,"operating-rate")) f->operating_rate=v; }
void AMediaFormat_setFloat(AMediaFormat *f,const char *k,float v) { if(!strcmp(k,"frame-rate")) f->fps=v; if(!strcmp(k,"operating-rate")) f->operating_rate=v; }
static void configure(int fps) {
    AndroidChiakiVideoDecoder d={.target_width=1920,.target_height=1080,.target_fps=fps,.target_codec=1};
    AndroidChiakiVideoDecoder *decoder=&d; const char *mime="video/hevc";
'''+block+r'''
}
int main(void) {
    for(int fps=30;fps<=60;fps+=30) {
        configure(fps);
        if(f.fps!=1 || f.operating_rate!=0 || f.priority!=4) { fprintf(stderr,"FAIL automatic scheduling overridden: frame-rate=%f operating-rate=%f priority=%d\n",f.fps,f.operating_rate,f.priority); return 1; }
    }
    puts("PASS decoder scheduling left automatic after measured regression");
}
'''
with tempfile.TemporaryDirectory(prefix='chiaki-scheduling-',dir=os.environ.get('TMPDIR')) as tmp:
    c=Path(tmp)/'test.c'; exe=Path(tmp)/'test'; c.write_text(harness)
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

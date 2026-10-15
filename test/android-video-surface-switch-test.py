#!/usr/bin/env python3
"""Real decoder lifecycle against NDK/JNI fakes; no hardware/concurrency claim."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
s = (root / 'android/app/src/main/cpp/video-decoder.c').read_text()
block = s[s.index('ChiakiErrorCode android_chiaki_video_decoder_init('):s.index('bool android_chiaki_video_decoder_video_sample(')]
assert 'AMediaCodec_setOutputSurface' in block and 'error_surface:' in block
harness = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <sys/types.h>
#define CHECK(x) do { if(!(x)) { fprintf(stderr,"FAIL %d: %s\n",__LINE__,#x); exit(1); } } while(0)
#define __ANDROID_API__ 23
#define AMEDIA_OK 0
#define CHIAKI_ERR_SUCCESS 0
#define AMEDIACODEC_BUFFER_FLAG_END_OF_STREAM 4
#define AMEDIAFORMAT_KEY_MIME "mime"
#define AMEDIAFORMAT_KEY_WIDTH "width"
#define AMEDIAFORMAT_KEY_HEIGHT "height"
#define AMEDIAFORMAT_KEY_MAX_INPUT_SIZE "max-input-size"
#define AMEDIAFORMAT_KEY_LOW_LATENCY "low-latency"
typedef int ChiakiErrorCode;
typedef int ChiakiCodec;
typedef int ChiakiLog;
typedef int JNIEnv;
typedef void *jobject;
typedef int AMediaCodec;
typedef int AMediaFormat;
typedef int media_status_t;
typedef struct { int refs, releases; } ANativeWindow;
typedef struct { int depth; } ChiakiMutex;
typedef struct { bool joined; } ChiakiThread;
typedef struct {
    ChiakiLog *log; AMediaCodec *codec; ANativeWindow *window;
    ChiakiMutex codec_mutex; ChiakiThread output_thread;
    bool shutdown_output, input_capacity_logged, codec_missing_logged;
    uint64_t timestamp_cur; int32_t target_width,target_height; ChiakiCodec target_codec;
} AndroidChiakiVideoDecoder;
static AndroidChiakiVideoDecoder *tracked;
static ANativeWindow old_window, new_window, *acquired;
static AMediaCodec codec;
static AMediaFormat format;
static int switch_status, switches, errors, creates, fail_create, deletes;
static char last_error[256];
static void log_noop(void *log, const char *fmt, ...) { (void)log; (void)fmt; }
static void log_error(void *log, const char *fmt, ...) {
    (void)log; errors++; va_list args; va_start(args,fmt);
    vsnprintf(last_error,sizeof(last_error),fmt,args); va_end(args);
}
#define CHIAKI_LOGI(...) log_noop(__VA_ARGS__)
#define CHIAKI_LOGW(...) log_noop(__VA_ARGS__)
#define CHIAKI_LOGE(...) log_error(__VA_ARGS__)
static int chiaki_mutex_init(ChiakiMutex *m,bool r) { (void)r; m->depth=0; return 0; }
static void chiaki_mutex_lock(ChiakiMutex *m) { CHECK(++m->depth==1); }
static void chiaki_mutex_unlock(ChiakiMutex *m) { CHECK(--m->depth==0); }
static void chiaki_mutex_fini(ChiakiMutex *m) { CHECK(!m->depth); }
static int chiaki_thread_create(ChiakiThread *t,void *(*f)(void *),void *arg) { (void)f; (void)arg; t->joined=false; return 0; }
static void chiaki_thread_join(ChiakiThread *t,void *r) { (void)r; CHECK(!tracked->codec_mutex.depth); t->joined=true; }
static void *android_chiaki_video_decoder_output_thread_func(void *arg) { return arg; }
static bool chiaki_codec_is_h265(int c) { return c==1; }
static ANativeWindow *ANativeWindow_fromSurface(JNIEnv *env,jobject surface) {
    (void)env; CHECK(surface); CHECK(tracked->codec_mutex.depth==1);
    if(acquired) acquired->refs++;
    return acquired;
}
static void ANativeWindow_release(ANativeWindow *w) { CHECK(w && w->refs>0); w->refs--; w->releases++; }
static int AMediaCodec_setOutputSurface(AMediaCodec *c,ANativeWindow *w) {
    CHECK(c==&codec && w && w->refs>0); CHECK(tracked->window==&old_window);
    CHECK(old_window.refs>0 && tracked->codec_mutex.depth==1); switches++; return switch_status;
}
static AMediaCodec *AMediaCodec_createDecoderByType(const char *mime) { (void)mime; creates++; return fail_create?NULL:&codec; }
static void AMediaCodec_delete(AMediaCodec *c) { CHECK(c==&codec); deletes++; }
static int AMediaCodec_configure(AMediaCodec *c,AMediaFormat *f,ANativeWindow *w,void *crypto,int flags) {
    (void)f; (void)crypto; (void)flags; CHECK(c==&codec && w && w->refs>0); return 0;
}
static int AMediaCodec_start(AMediaCodec *c) { CHECK(c==&codec); return 0; }
static void AMediaCodec_stop(AMediaCodec *c) { CHECK(c==&codec); }
static ssize_t AMediaCodec_dequeueInputBuffer(AMediaCodec *c,int64_t timeout) { (void)c; (void)timeout; return -1; }
static void AMediaCodec_queueInputBuffer(AMediaCodec *c,size_t i,size_t o,size_t sz,uint64_t pts,int flags) { (void)c; (void)i; (void)o; (void)sz; (void)pts; (void)flags; }
static int AMediaCodec_getName(AMediaCodec *c,char **name) { (void)c; *name=NULL; return -1; }
static void AMediaCodec_releaseName(AMediaCodec *c,char *name) { (void)c; (void)name; }
static AMediaFormat *AMediaCodec_getInputFormat(AMediaCodec *c) { (void)c; return NULL; }
static AMediaFormat *AMediaFormat_new(void) { return &format; }
static void AMediaFormat_setString(AMediaFormat *f,const char *k,const char *v) { (void)f; (void)k; (void)v; }
static void AMediaFormat_setInt32(AMediaFormat *f,const char *k,int32_t v) { (void)f; (void)k; (void)v; }
static void AMediaFormat_delete(AMediaFormat *f) { (void)f; }
static const char *AMediaFormat_toString(AMediaFormat *f) { (void)f; return "fake"; }
''' + block + r'''
static void reset(AndroidChiakiVideoDecoder *d,bool active) {
    tracked=d; CHECK(android_chiaki_video_decoder_init(d,NULL,1920,1080,1)==0);
    old_window=(ANativeWindow){.refs=active?1:0}; new_window=(ANativeWindow){0};
    d->codec=active?&codec:NULL; d->window=active?&old_window:NULL;
    acquired=&new_window; switch_status=switches=errors=creates=fail_create=deletes=0;
}
int main(void) {
    AndroidChiakiVideoDecoder d;
    reset(&d,true); switch_status=-37;
    android_chiaki_video_decoder_set_surface(&d,NULL,(void*)1);
    CHECK(d.window==&old_window && d.codec==&codec);
    CHECK(old_window.refs==1 && old_window.releases==0);
    CHECK(new_window.refs==0 && new_window.releases==1);
    CHECK(switches==1 && errors==1 && strstr(last_error,"-37"));
    CHECK(!d.codec_mutex.depth);
    android_chiaki_video_decoder_fini(&d);
    CHECK(old_window.releases==1 && new_window.releases==1);
    puts("PASS rejected switch preserves old ownership, releases candidate once and logs status");
    reset(&d,true); acquired=NULL;
    android_chiaki_video_decoder_set_surface(&d,NULL,(void*)1);
    CHECK(d.window==&old_window && d.codec==&codec);
    CHECK(old_window.refs==1 && !old_window.releases && !new_window.releases);
    CHECK(!switches && errors==1 && !d.codec_mutex.depth);
    android_chiaki_video_decoder_fini(&d);
    CHECK(old_window.releases==1);
    puts("PASS failed replacement acquisition leaves active decoder unchanged");
    reset(&d,false); acquired=NULL;
    android_chiaki_video_decoder_set_surface(&d,NULL,(void*)1);
    CHECK(!d.codec && !d.window && creates==0 && errors==1);
    CHECK(!d.codec_mutex.depth && !new_window.releases);
    android_chiaki_video_decoder_fini(&d);
    puts("PASS failed initial acquisition never creates a codec or releases NULL");
    reset(&d,true);
    android_chiaki_video_decoder_set_surface(&d,NULL,(void*)1);
    CHECK(d.window==&new_window && d.codec==&codec && switches==1 && !errors);
    CHECK(old_window.refs==0 && old_window.releases==1 && new_window.refs==1);
    CHECK(!d.codec_mutex.depth);
    android_chiaki_video_decoder_set_surface(&d,NULL,NULL);
    CHECK(!d.window && !d.codec && new_window.releases==1 && deletes==1);
    android_chiaki_video_decoder_fini(&d);
    CHECK(new_window.releases==1 && old_window.releases==1);
    puts("PASS successful replacement commits ownership; detach/fini release each reference once");
    reset(&d,true); acquired=&old_window;
    android_chiaki_video_decoder_set_surface(&d,NULL,(void*)1);
    CHECK(d.window==&old_window && old_window.refs==1 && old_window.releases==1);
    android_chiaki_video_decoder_fini(&d);
    CHECK(old_window.refs==0 && old_window.releases==2);
    puts("PASS replacing with the same native window balances both acquired references");
    reset(&d,false); fail_create=1;
    android_chiaki_video_decoder_set_surface(&d,NULL,(void*)1);
    CHECK(!d.window && !d.codec && creates==1 && errors==1);
    CHECK(new_window.refs==0 && new_window.releases==1 && !d.codec_mutex.depth);
    android_chiaki_video_decoder_fini(&d);
    CHECK(new_window.releases==1);
    puts("PASS initial codec creation failure releases acquired window exactly once");
    reset(&d,false);
    android_chiaki_video_decoder_set_surface(&d,NULL,(void*)1);
    CHECK(d.window==&new_window && d.codec==&codec && creates==1 && !errors);
    CHECK(new_window.refs==1 && new_window.releases==0);
    android_chiaki_video_decoder_fini(&d);
    CHECK(new_window.refs==0 && new_window.releases==1);
    puts("PASS initial success retains its acquired window until fini");
}
'''
with tempfile.TemporaryDirectory(prefix='chiaki-surface-', dir=os.environ.get('TMPDIR')) as tmp:
    c = Path(tmp) / 'test.c'
    exe = Path(tmp) / 'test'
    c.write_text(harness)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', str(c), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True, timeout=5)

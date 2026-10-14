#!/usr/bin/env python3
"""Exercise actual video receiver flush; never decode FEC-failed access units."""
from pathlib import Path
import os
import subprocess
import tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'lib/src/videoreceiver.c').read_text()
start=s.index('#define IDR_REQUEST_COOLDOWN_MS') if '#define IDR_REQUEST_COOLDOWN_MS' in s else s.index('static ChiakiErrorCode chiaki_video_receiver_flush_frame(ChiakiVideoReceiver *video_receiver)\n{')
block=s[start:]
harness=r'''
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#define CHIAKI_LOGW(...) ((void)0)
#define CHIAKI_ERR_SUCCESS 0
#define CHIAKI_ERR_UNKNOWN -1
typedef int ChiakiErrorCode;
typedef enum { CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_SUCCESS, CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_FEC_SUCCESS, CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_FEC_FAILED, CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_FAILED } ChiakiFrameProcessorFlushResult;
typedef struct { bool (*video_sample_cb)(uint8_t*,size_t,void*); void *video_sample_cb_user; int stream_connection; } Session;
typedef struct { int frame_processor; void *log; Session *session; int frame_index_cur,frame_index_prev,frame_index_prev_complete; uint64_t idr_request_prev_ms, idr_request_attempt_prev_ms; bool idr_pending, idr_request_attempted; } ChiakiVideoReceiver;
static ChiakiFrameProcessorFlushResult result;
static int decoded; static bool callback_ok=true;
static uint8_t data[]={0,0,0,1,0x26};
static uint64_t fake_ms;
static int idr_sends, idr_result=CHIAKI_ERR_SUCCESS;
uint64_t chiaki_time_now_monotonic_ms(void) { return fake_ms; }
ChiakiErrorCode stream_connection_send_idr_request(int *s) { (void)s; idr_sends++; return idr_result; }
static ChiakiFrameProcessorFlushResult chiaki_frame_processor_flush(int *p,uint8_t **f,size_t *n) { (void)p; *f=data; *n=sizeof(data); return result; }
static bool decode(uint8_t *f,size_t n,void *u) { (void)u; if(f!=data || n!=sizeof(data)) return false; decoded++; return callback_ok; }
'''+block+r'''
#define CHECK(x) do { if(!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); return 1; } } while(0)
int main(void) {
    Session session={.video_sample_cb=decode};
    ChiakiVideoReceiver v={.session=&session,.frame_index_cur=42,.frame_index_prev=41,.frame_index_prev_complete=41};
    fake_ms=1000;
    result=CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_FEC_FAILED;
    CHECK(chiaki_video_receiver_flush_frame(&v)!=CHIAKI_ERR_SUCCESS); CHECK(decoded==0); CHECK(v.frame_index_prev==42); CHECK(v.frame_index_prev_complete==41);
    CHECK(idr_sends==1); CHECK(v.idr_request_prev_ms==1000); CHECK(v.idr_pending);
    puts("PASS incomplete frame rejected; recovery bookkeeping retained; IDR requested once");
    result=CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_SUCCESS; v.frame_index_cur=43;
    CHECK(chiaki_video_receiver_flush_frame(&v)==CHIAKI_ERR_SUCCESS); CHECK(decoded==1); CHECK(v.frame_index_prev_complete==43); CHECK(idr_sends==1); CHECK(!v.idr_pending);
    puts("PASS complete frame delivered; IDR episode closed on delivery");
    result=CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_FEC_SUCCESS; v.frame_index_cur=44;
    CHECK(chiaki_video_receiver_flush_frame(&v)==CHIAKI_ERR_SUCCESS); CHECK(decoded==2); CHECK(v.frame_index_prev_complete==44); CHECK(idr_sends==1);
    puts("PASS successfully repaired frame delivered without IDR request");
    result=CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_FEC_FAILED; v.frame_index_cur=45; fake_ms=1100;
    CHECK(chiaki_video_receiver_flush_frame(&v)!=CHIAKI_ERR_SUCCESS); CHECK(decoded==2); CHECK(v.frame_index_prev==45); CHECK(v.frame_index_prev_complete==44);
    CHECK(idr_sends==1);
    puts("PASS IDR request throttled within 500 ms cooldown");
    result=CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_FEC_FAILED; v.frame_index_cur=46; fake_ms=1601;
    CHECK(chiaki_video_receiver_flush_frame(&v)!=CHIAKI_ERR_SUCCESS); CHECK(idr_sends==2); CHECK(v.idr_request_prev_ms==1601); CHECK(v.idr_pending);
    puts("PASS IDR re-requested after cooldown elapses");
    result=CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_FEC_FAILED; v.frame_index_cur=47; fake_ms=2000;
    CHECK(chiaki_video_receiver_flush_frame(&v)!=CHIAKI_ERR_SUCCESS); CHECK(idr_sends==2);
    puts("PASS pending IDR episode latches; no keyframe storm during damage");
    result=CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_FAILED; v.frame_index_cur=48; fake_ms=2101;
    CHECK(chiaki_video_receiver_flush_frame(&v)!=CHIAKI_ERR_SUCCESS); CHECK(v.frame_index_prev==48); CHECK(idr_sends==2);
    puts("PASS empty flush rejected without IDR request");
    result=CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_SUCCESS; callback_ok=false; v.frame_index_cur=49;
    chiaki_video_receiver_flush_frame(&v); CHECK(v.frame_index_prev==49); CHECK(v.frame_index_prev_complete==44); CHECK(v.idr_pending);
    puts("PASS callback rejection preserves last complete index and keeps IDR latch");
    result=CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_SUCCESS; callback_ok=true; v.frame_index_cur=50;
    CHECK(chiaki_video_receiver_flush_frame(&v)==CHIAKI_ERR_SUCCESS); CHECK(v.frame_index_prev_complete==50); CHECK(!v.idr_pending);
    puts("PASS delivered frame closes pending IDR episode");
    result=CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_FEC_FAILED; v.frame_index_prev_complete=65535; v.frame_index_cur=0; fake_ms=2200;
    CHECK(chiaki_video_receiver_flush_frame(&v)!=CHIAKI_ERR_SUCCESS); CHECK(v.frame_index_prev==0); CHECK(v.frame_index_prev_complete==65535);
    puts("PASS failure bookkeeping across frame-number wrap");
    v=(ChiakiVideoReceiver){.session=&session,.frame_index_cur=60}; idr_sends=0;
    fake_ms=4000; chiaki_video_receiver_flush_frame(&v); CHECK(idr_sends==1); CHECK(v.idr_pending);
    fake_ms=5999; chiaki_video_receiver_flush_frame(&v); CHECK(idr_sends==1);
    fake_ms=6000; chiaki_video_receiver_flush_frame(&v); CHECK(idr_sends==2); CHECK(v.idr_request_prev_ms==6000);
    puts("PASS pending recovery retries only after two seconds of continued rejection");
    v=(ChiakiVideoReceiver){.session=&session,.frame_index_cur=70}; idr_sends=0; idr_result=CHIAKI_ERR_UNKNOWN;
    fake_ms=0; chiaki_video_receiver_flush_frame(&v); CHECK(idr_sends==1); CHECK(!v.idr_pending); CHECK(v.idr_request_prev_ms==0);
    fake_ms=499; chiaki_video_receiver_flush_frame(&v); CHECK(idr_sends==1);
    fake_ms=500; chiaki_video_receiver_flush_frame(&v); CHECK(idr_sends==2); CHECK(!v.idr_pending); CHECK(v.idr_request_prev_ms==0);
    idr_result=CHIAKI_ERR_SUCCESS; fake_ms=1000; chiaki_video_receiver_flush_frame(&v);
    CHECK(idr_sends==3); CHECK(v.idr_pending); CHECK(v.idr_request_prev_ms==1000);
    puts("PASS failed IDR sends are rate-limited without recording false success, including uptime zero");
    v=(ChiakiVideoReceiver){.session=&session,.frame_index_cur=80,.frame_index_prev_complete=79}; idr_sends=0;
    result=CHIAKI_FRAME_PROCESSOR_FLUSH_RESULT_SUCCESS; callback_ok=false; fake_ms=10000;
    chiaki_video_receiver_flush_frame(&v); CHECK(idr_sends==1); CHECK(v.idr_pending); CHECK(v.frame_index_prev_complete==79);
    fake_ms=11999; chiaki_video_receiver_flush_frame(&v); CHECK(idr_sends==1);
    fake_ms=12000; chiaki_video_receiver_flush_frame(&v); CHECK(idr_sends==2);
    callback_ok=true; chiaki_video_receiver_flush_frame(&v); CHECK(!v.idr_pending); CHECK(v.frame_index_prev_complete==80);
    puts("PASS callback rejection initiates bounded recovery; accepted frame clears the approximation");
}
'''
with tempfile.TemporaryDirectory(prefix='chiaki-fec-',dir=os.environ.get('TMPDIR')) as tmp:
    c=Path(tmp)/'test.c'; exe=Path(tmp)/'test'; c.write_text(harness)
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(c),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

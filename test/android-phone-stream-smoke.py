#!/usr/bin/env python3
"""Phone smoke test + scoped client latency capture; requires user's connected adb device.
Starts only this test package and the explicitly named registered console.
"""
import argparse
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET

parser=argparse.ArgumentParser()
parser.add_argument('--name',default='jps5p')
parser.add_argument('--seconds',type=float,default=20)
parser.add_argument('--output',required=True)
args=parser.parse_args()
package='com.gameblabla.chiaki.hevcfix'

devices=subprocess.check_output(['adb','devices'],text=True).strip().splitlines()[1:]
if not any('\tdevice' in line for line in devices):
    print('SKIP no adb device connected')
    raise SystemExit(0)

def adb(*a):
    return subprocess.check_output(['adb',*a],text=True,timeout=15).strip()

activities=adb('shell','dumpsys','activity','activities')
if any('topResumedActivity=' in line and package+'/com.gameblabla.chiaki.stream.StreamActivity' in line for line in activities.splitlines()):
    # Let StreamActivity.onPause close the remote session before killing the process.
    print(adb('shell','am','start','-W','-f','0x04000000','-n',package+'/com.gameblabla.chiaki.main.MainActivity'))
adb('shell','am','force-stop',package)
print(adb('shell','am','start','-W','-n',package+'/com.gameblabla.chiaki.main.MainActivity'))
pid=adb('shell','pidof',package)
assert re.fullmatch(r'\d+',pid), 'App did not survive startup'
with tempfile.TemporaryDirectory(prefix='chiaki-ui-',dir=os.environ.get('TMPDIR')) as tmp:
    remote='/sdcard/chiaki-agent-ui.xml'
    adb('shell','uiautomator','dump',remote)
    local=Path(tmp)/'ui.xml'
    adb('pull',remote,str(local))
    tree=ET.parse(local)
    nodes=[n for n in tree.iter('node') if n.get('package')==package and n.get('resource-id','').endswith(':id/nameTextView') and n.get('text')==args.name]
    assert len(nodes)==1, 'Explicit registered-console row not found uniquely'
    q=list(map(int,re.findall(r'\d+',nodes[0].get('bounds') or '')))
    assert len(q)==4, 'Invalid console row bounds'
    adb('shell','input','tap',str((q[0]+q[2])//2),str((q[1]+q[3])//2))
    adb('shell','rm',remote)

proc=subprocess.Popen(['adb','logcat','--pid='+pid,'-v','threadtime','Chiaki:V','CCodec:V','CCodecConfig:V','AndroidRuntime:E','*:S'],stdout=subprocess.PIPE)
assert proc.stdout is not None
sel=selectors.DefaultSelector()
sel.register(proc.stdout,selectors.EVENT_READ)
end=time.monotonic()+args.seconds
data=b''
try:
    while time.monotonic()<end:
        events=sel.select(max(0,end-time.monotonic()))
        if not events:
            break
        chunk=os.read(proc.stdout.fileno(),65536)
        if not chunk:
            break
        data+=chunk
finally:
    proc.terminate()
    proc.wait(timeout=3)
text=data.decode(errors='replace')
output=Path(args.output)
output.parent.mkdir(parents=True,exist_ok=True)
output.write_text(text)
windows=[{'avg_ms':float(a),'max_ms':float(m),'frames':int(n)} for a,m,n in re.findall(r'Video client decode latency: avg=([\d.]+) ms, max=([\d.]+) ms, frames=(\d+)',text)]
assert 'FATAL EXCEPTION' not in text, 'Phone crashed during test'
assert adb('shell','pidof',package)==pid, 'App process changed or stopped'
assert windows, 'No valid client-latency measurements; inspect scoped log'
count=sum(w['frames'] for w in windows)
report={'pid':pid,'windows':windows,'frames':count,'weighted_client_decode_avg_ms':sum(w['avg_ms']*w['frames'] for w in windows)/count,'max_client_decode_ms':max(w['max_ms'] for w in windows),'fec_failures':text.count('FEC failed'),'damaged_frames_rejected':text.count('Dropping incomplete video frame'),'input_queue_failures':text.count('AMediaCodec_queueInputBuffer() failed'),'input_timeouts':text.count('Failed to get input buffer'),'codec_input_formats':[l.split('Video decoder input format: ',1)[1] for l in text.splitlines() if 'Video decoder input format: ' in l],'scope':'assembled-frame arrival to decoder output; NOT input-to-photon or PS5 encode/network time'}
output.with_suffix('.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))

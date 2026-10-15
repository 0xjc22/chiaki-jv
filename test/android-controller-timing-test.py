#!/usr/bin/env python3
"""Compile/run the actual Kotlin input-age accounting on the host JVM."""
from pathlib import Path
import os,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
source=root/'android/app/src/main/java/com/metallic/chiaki/session/ControllerInputTiming.kt'
assert source.exists(), 'Missing controller input timing: Android dispatch age cannot be measured'
cache=Path.home()/'.gradle/caches/modules-2/files-2.1'
deps=list(cache.glob('org.jetbrains.kotlin/*/1.8.0/*/*.jar'))+list(cache.glob('org.jetbrains.kotlin/kotlin-reflect/1.6.10/*/*.jar'))+list(cache.glob('org.jetbrains.intellij.deps/trove4j/*/*/*.jar'))+list(cache.glob('org.jetbrains/annotations/*/*/*.jar'))
stdlib=next(cache.glob('org.jetbrains.kotlin/kotlin-stdlib/1.8.0/*/*.jar'))
code='''
import com.gameblabla.chiaki.session.ControllerInputTiming
import kotlin.math.abs
fun main() {
    val t=ControllerInputTiming()
    check(t.record(1000,992,980,2)==null)
    check(t.record(1010,1004,1002,1)==null)
    check(t.record(1100,1101,1101,0)==null) // future event ignored
    check(t.record(1200,1199,1200,0)==null) // impossible history ignored
    val s=t.record(3000,2999,2999,0)!!
    check(s.events==3L && s.batchedEvents==2L && s.samples==6L)
    check(abs(s.latestAvgMs-5.0)<0.000001)
    check(abs(s.oldestAvgMs-29.0/3.0)<0.000001 && s.oldestMaxMs==20L)
    check(t.record(4000,4000,4000,0)==null)
    val fresh=t.record(5000,5000,5000,0)!!
    check(fresh.events==2L && fresh.samples==2L && fresh.batchedEvents==0L)
    check(fresh.latestAvgMs==0.0 && fresh.oldestAvgMs==0.0 && fresh.oldestMaxMs==0L)
    check(t.record(50000,49999,49999,0)==null) // idle gap resets window, no one-sample report
    check(t.record(51000,50999,50999,0)==null)
    val resumed=t.record(53000,52999,52999,0)!!
    check(resumed.events==2L && resumed.samples==2L && resumed.batchedEvents==0L)
    check(resumed.latestAvgMs==1.0 && resumed.oldestAvgMs==1.0 && resumed.oldestMaxMs==1L)
    println("PASS actual Kotlin controller input timing: ages/history, invalid events, interval, reset and idle-gap")
}
'''
with tempfile.TemporaryDirectory(prefix='chiaki-controller-',dir=os.environ.get('TMPDIR')) as d:
    p=Path(d); test=p/'InputTimingTest.kt'; test.write_text(code); jar=p/'test.jar'
    subprocess.run([str(Path(os.environ.get('JAVA_HOME', Path.home()/'.local/opt/jdk17'))/'bin/java'),'-cp',os.pathsep.join(map(str,deps)),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-classpath',str(stdlib),'-d',str(jar),str(source),str(test)],check=True)
    subprocess.run([str(Path(os.environ.get('JAVA_HOME', Path.home()/'.local/opt/jdk17'))/'bin/java'),'-cp',str(jar)+os.pathsep+str(stdlib),'InputTimingTestKt'],check=True)

#!/usr/bin/env python3
"""Execute the actual Activity attach callback against an attached-view seam."""
from pathlib import Path
import os,re,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'android/app/src/main/java/com/metallic/chiaki/stream/StreamActivity.kt').read_text()
m=re.search(r'override fun onAttachedToWindow\(\)\s*\{',s)
assert m, 'Stream window never requests immediate joystick dispatch'
start=m.start(); pos=m.end(); depth=1
while depth:
    if s[pos]=='{': depth+=1
    elif s[pos]=='}': depth-=1
    pos+=1
method=s[start:pos]
code='''
object InputDevice { const val SOURCE_CLASS_JOYSTICK=16 }
object android { object util { object Log { fun i(tag:String,message:String) { check(tag.isNotEmpty() && message.isNotEmpty()) } } } }
class View { var attached=false; val requests=mutableListOf<Int>(); fun requestUnbufferedDispatch(source:Int) { check(attached); requests.add(source) } }
class Window { val decorView=View() }
open class Base { val window=Window(); open fun onAttachedToWindow() { window.decorView.attached=true } }
class Activity: Base() {
'''+method+'''
}
fun main() {
    val a=Activity()
    check(a.window.decorView.requests.isEmpty())
    a.onAttachedToWindow()
    check(a.window.decorView.requests==listOf(InputDevice.SOURCE_CLASS_JOYSTICK))
    a.window.decorView.attached=false
    a.onAttachedToWindow()
    check(a.window.decorView.requests==listOf(16,16))
    println("PASS actual Activity callback: joystick-only unbuffering, after attachment, reapplied on reattach")
}
'''
cache=Path.home()/'.gradle/caches/modules-2/files-2.1'
deps=list(cache.glob('org.jetbrains.kotlin/*/1.8.0/*/*.jar'))+list(cache.glob('org.jetbrains.kotlin/kotlin-reflect/1.6.10/*/*.jar'))+list(cache.glob('org.jetbrains.intellij.deps/trove4j/*/*/*.jar'))+list(cache.glob('org.jetbrains/annotations/*/*/*.jar'))
stdlib=next(cache.glob('org.jetbrains.kotlin/kotlin-stdlib/1.8.0/*/*.jar'))
with tempfile.TemporaryDirectory(prefix='chiaki-unbuffered-',dir=os.environ.get('TMPDIR')) as d:
    p=Path(d); test=p/'UnbufferedTest.kt'; test.write_text(code); jar=p/'test.jar'
    subprocess.run(['/home/jc/.local/opt/jdk17/bin/java','-cp',os.pathsep.join(map(str,deps)),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-classpath',str(stdlib),'-d',str(jar),str(test)],check=True)
    subprocess.run(['/home/jc/.local/opt/jdk17/bin/java','-cp',str(jar)+os.pathsep+str(stdlib),'UnbufferedTestKt'],check=True)

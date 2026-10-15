#!/usr/bin/env python3
"""Exercise the actual SELECT key mapping: touchpad press instead of Share."""
from pathlib import Path
import os,re,subprocess,tempfile
root=Path(__file__).resolve().parents[1]
s=(root/'android/app/src/main/java/com/metallic/chiaki/session/StreamInput.kt').read_text()
c=(root/'android/app/src/main/java/com/metallic/chiaki/lib/Chiaki.kt').read_text()
# Guard the harness's faked constants against drift in the real class.
assert 'BUTTON_TOUCHPAD\t\t= (1 shl 14).toUInt()' in c or 'BUTTON_TOUCHPAD = (1 shl 14)' in c.replace('\t',' '), 'real BUTTON_TOUCHPAD constant drifted'
assert 'BUTTON_SHARE \t\t= (1 shl 13).toUInt()' in c or 'BUTTON_SHARE = (1 shl 13)' in c.replace('\t',' '), 'real BUTTON_SHARE constant drifted'
m=re.search(r'fun dispatchKeyEvent\(event: KeyEvent\): Boolean',s)
assert m, 'dispatchKeyEvent not found'
pos=m.end(); depth=0; end=None
for i in range(pos,len(s)):
    if s[i]=='{': depth+=1
    elif s[i]=='}':
        depth-=1
        if depth==0: end=i+1; break
assert end, 'unterminated dispatchKeyEvent'
block=s[m.start():end]
assert 'KEYCODE_BUTTON_SELECT -> ControllerState.BUTTON_TOUCHPAD' in block, 'SELECT no longer maps to TOUCHPAD'
assert 'KEYCODE_BUTTON_SELECT -> ControllerState.BUTTON_SHARE' not in block, 'SELECT still maps to SHARE'
code='''
class KeyEvent(val action: Int, val keyCode: Int) {
    companion object {
        const val ACTION_DOWN = 0
        const val ACTION_UP = 1
        const val KEYCODE_BUTTON_A = 96
        const val KEYCODE_BUTTON_B = 97
        const val KEYCODE_BUTTON_C = 98
        const val KEYCODE_BUTTON_X = 99
        const val KEYCODE_BUTTON_Y = 100
        const val KEYCODE_BUTTON_L1 = 102
        const val KEYCODE_BUTTON_R1 = 103
        const val KEYCODE_BUTTON_L2 = 104
        const val KEYCODE_BUTTON_R2 = 105
        const val KEYCODE_BUTTON_THUMBL = 106
        const val KEYCODE_BUTTON_THUMBR = 107
        const val KEYCODE_BUTTON_START = 108
        const val KEYCODE_BUTTON_SELECT = 109
        const val KEYCODE_BUTTON_MODE = 110
        const val KEYCODE_DPAD_LEFT = 21
    }
}
class ControllerState {
    var buttons: UInt = 0u
    var l2State: UByte = 0u
    var r2State: UByte = 0u
    companion object {
        val BUTTON_CROSS = (1 shl 0).toUInt()
        val BUTTON_MOON = (1 shl 1).toUInt()
        val BUTTON_BOX = (1 shl 2).toUInt()
        val BUTTON_PYRAMID = (1 shl 3).toUInt()
        val BUTTON_L1 = (1 shl 8).toUInt()
        val BUTTON_R1 = (1 shl 9).toUInt()
        val BUTTON_L3 = (1 shl 10).toUInt()
        val BUTTON_R3 = (1 shl 11).toUInt()
        val BUTTON_OPTIONS = (1 shl 12).toUInt()
        val BUTTON_SHARE = (1 shl 13).toUInt()
        val BUTTON_TOUCHPAD = (1 shl 14).toUInt()
        val BUTTON_PS = (1 shl 15).toUInt()
    }
}
class Harness {
    val keyControllerState = ControllerState()
    val swapCrossMoon = false
    val deliveredTriggers = mutableListOf<Pair<UByte, UByte>>()
    private fun controllerStateUpdated() {
        deliveredTriggers.add(keyControllerState.l2State to keyControllerState.r2State)
    }
'''+block+'''
}
fun main() {
    val h = Harness()
    check(h.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_BUTTON_SELECT)))
    check(h.keyControllerState.buttons == ControllerState.BUTTON_TOUCHPAD)
    check(h.keyControllerState.buttons and ControllerState.BUTTON_SHARE == 0u)
    println("PASS SELECT down sets touchpad press, not share")
    check(h.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_UP, KeyEvent.KEYCODE_BUTTON_SELECT)))
    check(h.keyControllerState.buttons == 0u)
    println("PASS SELECT up releases touchpad press")
    check(h.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_BUTTON_SELECT)))
    check(h.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_BUTTON_A)))
    check(h.keyControllerState.buttons == (ControllerState.BUTTON_TOUCHPAD or ControllerState.BUTTON_CROSS))
    check(h.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_UP, KeyEvent.KEYCODE_BUTTON_A)))
    check(h.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_UP, KeyEvent.KEYCODE_BUTTON_SELECT)))
    check(h.keyControllerState.buttons == 0u)
    println("PASS touchpad press composes with face buttons and releases cleanly")
    h.deliveredTriggers.clear()
    check(h.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_BUTTON_L2)))
    check(h.keyControllerState.l2State == UByte.MAX_VALUE)
    check(h.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_UP, KeyEvent.KEYCODE_BUTTON_L2)))
    check(h.keyControllerState.l2State == 0u.toUByte())
    check(h.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_BUTTON_R2)))
    check(h.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_UP, KeyEvent.KEYCODE_BUTTON_R2)))
    check(h.deliveredTriggers == listOf(
        UByte.MAX_VALUE to 0u.toUByte(), 0u.toUByte() to 0u.toUByte(),
        0u.toUByte() to UByte.MAX_VALUE, 0u.toUByte() to 0u.toUByte()
    )) { "Key-only trigger transitions must reach the session immediately" }
    println("PASS key-only L2/R2 press and release dispatched without later motion")
    check(!h.dispatchKeyEvent(KeyEvent(KeyEvent.ACTION_DOWN, KeyEvent.KEYCODE_DPAD_LEFT)))
    println("PASS unmapped keys still return false")
}
'''
cache=Path.home()/'.gradle/caches/modules-2/files-2.1'
deps=list(cache.glob('org.jetbrains.kotlin/*/1.8.0/*/*.jar'))+list(cache.glob('org.jetbrains.kotlin/kotlin-reflect/1.6.10/*/*.jar'))+list(cache.glob('org.jetbrains.intellij.deps/trove4j/*/*/*.jar'))+list(cache.glob('org.jetbrains/annotations/*/*/*.jar'))
stdlib=next(cache.glob('org.jetbrains.kotlin/kotlin-stdlib/1.8.0/*/*.jar'))
with tempfile.TemporaryDirectory(prefix='chiaki-select-',dir=os.environ.get('TMPDIR')) as d:
    p=Path(d); test=p/'SelectTouchpadTest.kt'; test.write_text(code); jar=p/'test.jar'
    subprocess.run([str(Path(os.environ.get('JAVA_HOME', Path.home()/'.local/opt/jdk17'))/'bin/java'),'-cp',os.pathsep.join(map(str,deps)),'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler','-no-stdlib','-no-reflect','-classpath',str(stdlib),'-d',str(jar),str(test)],check=True)
    subprocess.run([str(Path(os.environ.get('JAVA_HOME', Path.home()/'.local/opt/jdk17'))/'bin/java'),'-cp',str(jar)+os.pathsep+str(stdlib),'SelectTouchpadTestKt'],check=True)

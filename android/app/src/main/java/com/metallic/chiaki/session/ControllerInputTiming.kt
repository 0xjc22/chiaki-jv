package com.gameblabla.chiaki.session

/** Android event timestamp to app delivery; excludes controller radio and video latency. */
class ControllerInputTiming
{
    data class Snapshot(val events: Long, val samples: Long, val batchedEvents: Long,
                        val latestAvgMs: Double, val oldestAvgMs: Double, val oldestMaxMs: Long)
    private var reportStartMs: Long? = null
    private var events = 0L
    private var samples = 0L
    private var batchedEvents = 0L
    private var latestSumMs = 0L
    private var oldestSumMs = 0L
    private var oldestMaxMs = 0L

    fun record(nowMs: Long, latestMs: Long, oldestMs: Long, historySize: Int): Snapshot?
    {
        if(latestMs < 0 || oldestMs < 0 || latestMs > nowMs || oldestMs > latestMs || historySize < 0)
            return null
        val start = reportStartMs ?: nowMs.also { reportStartMs = it }
        events++
        samples += historySize.toLong() + 1L
        if(historySize > 0) batchedEvents++
        latestSumMs += nowMs - latestMs
        oldestSumMs += nowMs - oldestMs
        oldestMaxMs = maxOf(oldestMaxMs, nowMs - oldestMs)
        if(nowMs - start < 2000L) return null
        val snapshot = Snapshot(events, samples, batchedEvents,
            latestSumMs.toDouble() / events, oldestSumMs.toDouble() / events, oldestMaxMs)
        events = 0L
        samples = 0L
        batchedEvents = 0L
        latestSumMs = 0L
        oldestSumMs = 0L
        oldestMaxMs = 0L
        reportStartMs = nowMs
        return snapshot
    }
}

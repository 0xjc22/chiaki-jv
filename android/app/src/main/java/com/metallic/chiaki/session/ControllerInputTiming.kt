package com.gameblabla.chiaki.session

/** Android event timestamp to app delivery; excludes controller radio and video latency. */
class ControllerInputTiming
{
    data class Snapshot(val events: Long, val samples: Long, val batchedEvents: Long,
                        val latestAvgMs: Double, val oldestAvgMs: Double, val oldestMaxMs: Long)

    companion object
    {
        private const val REPORT_INTERVAL_MS = 2000L
        // After an idle gap this long, restart the window instead of emitting
        // a misleading one-sample report.
        private const val IDLE_RESET_MULTIPLIER = 3L
    }

    private var reportStartMs: Long? = null
    private var events = 0L
    private var samples = 0L
    private var batchedEvents = 0L
    private var latestSumMs = 0L
    private var oldestSumMs = 0L
    private var oldestMaxMs = 0L

    /** Main-thread only. Returns a snapshot every REPORT_INTERVAL_MS of
     * accumulated events; null otherwise. */
    fun record(nowMs: Long, latestMs: Long, oldestMs: Long, historySize: Int): Snapshot?
    {
        if(latestMs < 0 || oldestMs < 0 || latestMs > nowMs || oldestMs > latestMs)
            return null
        val start = reportStartMs ?: nowMs.also { reportStartMs = it }
        if(nowMs - start > REPORT_INTERVAL_MS * IDLE_RESET_MULTIPLIER)
        {
            events = 0L
            samples = 0L
            batchedEvents = 0L
            latestSumMs = 0L
            oldestSumMs = 0L
            oldestMaxMs = 0L
            reportStartMs = nowMs
            return null
        }
        events++
        samples += historySize.toLong() + 1L
        if(historySize > 0) batchedEvents++
        latestSumMs += nowMs - latestMs
        oldestSumMs += nowMs - oldestMs
        oldestMaxMs = maxOf(oldestMaxMs, nowMs - oldestMs)
        if(nowMs - start < REPORT_INTERVAL_MS) return null
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

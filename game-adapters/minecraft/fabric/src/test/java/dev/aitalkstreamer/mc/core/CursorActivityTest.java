package dev.aitalkstreamer.mc.core;

import org.junit.jupiter.api.Test;
import java.util.concurrent.atomic.AtomicLong;
import static org.junit.jupiter.api.Assertions.*;

class CursorActivityTest {
    private final AtomicLong now = new AtomicLong(1000);
    private final CursorActivity cursor = new CursorActivity(42, now::get);
    @Test void explicitWarpExemptsOnlyOneMatchingEvent() {
        cursor.expectWarp(42, 960, 540); assertFalse(cursor.moved(42, 960, 540));
        assertTrue(cursor.moved(42, 965, 540)); assertFalse(cursor.moved(42, 965, 540));
    }
    @Test void warpDoesNotCreateABlanketIgnorePeriod() {
        cursor.expectWarp(42, 100, 100); assertTrue(cursor.moved(42, 80, 100));
        assertTrue(cursor.moved(42, 100, 100));
    }
    @Test void expiredWarpIsAnUnexplainedInput() {
        cursor.expectWarp(42, 100, 100); now.addAndGet(101); assertTrue(cursor.moved(42, 100, 100));
    }
    @Test void warpAtTheExactDeadlineIsStillMatched() {
        cursor.expectWarp(42, 100, 100); now.addAndGet(100); assertFalse(cursor.moved(42, 100, 100));
    }
    @Test void anotherWindowCannotMoveOrConsumeTheExpectedWarp() {
        cursor.expectWarp(42, 100, 100); cursor.expectWarp(99, 200, 200);
        assertFalse(cursor.moved(99, 1, 2)); assertFalse(cursor.moved(42, 100, 100)); assertTrue(cursor.moved(42, 101, 100));
    }
    @Test void smallPhysicalMovesAccumulateInsteadOfEvadingTakeover() {
        cursor.expectWarp(42, 0, 0); assertFalse(cursor.moved(42, 0, 0));
        assertFalse(cursor.moved(42, 0.2, 0)); assertFalse(cursor.moved(42, 0.4, 0)); assertTrue(cursor.moved(42, 0.6, 0));
    }
    @Test void invalidCoordinatesCannotPoisonTheKnownPosition() {
        cursor.expectWarp(42, 100, 100); assertFalse(cursor.moved(42, 100, 100));
        cursor.expectWarp(42, Double.NaN, 1); assertFalse(cursor.moved(42, Double.NaN, 1));
        assertFalse(cursor.moved(42, Double.POSITIVE_INFINITY, 1)); assertTrue(cursor.moved(42, 101, 100));
    }
    @Test void firstUnexplainedMotionIsConservativelyManual() { assertTrue(cursor.moved(42, 10, 20)); }
    @Test void aNewWarpReplacesThePreviousOne() {
        cursor.expectWarp(42, 10, 10); cursor.expectWarp(42, 20, 20);
        assertTrue(cursor.moved(42, 10, 10)); assertTrue(cursor.moved(42, 20, 20));
    }
}

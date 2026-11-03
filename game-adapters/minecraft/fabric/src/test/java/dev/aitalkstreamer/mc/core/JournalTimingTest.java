package dev.aitalkstreamer.mc.core;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import java.nio.file.Path;
import java.util.concurrent.*;
import static org.junit.jupiter.api.Assertions.*;

class JournalTimingTest {
    @TempDir Path temporary;
    @Test void timingDiagnosticsRemainReadableWhileAnotherThreadOwnsTheJournalMonitor() throws Exception {
        try (LocalJournal journal = new LocalJournal(temporary.resolve("ledger"))) {
            var worker = Executors.newSingleThreadExecutor();
            try {
                synchronized (journal) {
                    var read = worker.submit(journal::timings).get(2, TimeUnit.SECONDS);
                    assertTrue(read.get("transactions").getAsLong() > 0);
                    assertTrue(read.get("max_transaction_ms").getAsDouble() >= 0);
                    assertEquals(3, read.size());
                }
            } finally { worker.shutdownNow(); assertTrue(worker.awaitTermination(2, TimeUnit.SECONDS)); }
        }
    }
}

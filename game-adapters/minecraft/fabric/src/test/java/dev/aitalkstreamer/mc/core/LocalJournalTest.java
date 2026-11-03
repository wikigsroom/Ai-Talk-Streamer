package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.sql.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static dev.aitalkstreamer.mc.core.Json.*;

class LocalJournalTest {
    @TempDir Path root;
    private JsonObject task(String world, String request, String state, long version) {
        return obj("task_id", "task-" + world + "-" + request, "game_instance_id", "mc-fixture", "bridge_boot_id", "boot",
                "world_id", "world-stable", "world_session_id", world, "request_id", request, "state", state, "version", version,
                "created_at", "2026-10-30T00:00:00Z", "updated_at", "2026-10-30T00:00:00Z", "control_epoch", 7, "goal", obj("skill", "gather"));
    }
    private Connection sql() throws SQLException { return DriverManager.getConnection("jdbc:sqlite:" + root.resolve("mc-control.sqlite3")); }
    private String scalar(Connection c, String query) throws SQLException {
        try (Statement statement = c.createStatement(); ResultSet rows = statement.executeQuery(query)) { assertTrue(rows.next()); return rows.getString(1); }
    }
    private void seedWindow(int size) throws Exception {
        try (Connection c = sql()) {
            c.setAutoCommit(false);
            try (PreparedStatement row = c.prepareStatement("INSERT INTO reliable(boot,world,stream,delivery_seq,type,payload,created_at) VALUES('boot','world','events',?,'game_event',?,0)")) {
                for (int i = 2; i <= size; i++) { row.setInt(1, i); row.setString(2, GSON.toJson(obj("event_id", "event-" + i, "delivery_seq", i))); row.addBatch(); } row.executeBatch();
            }
            try (Statement s = c.createStatement()) { s.executeUpdate("UPDATE streams SET issued=" + size + " WHERE boot='boot' AND world='world' AND stream='events'"); }
            c.commit();
        }
    }
    private JsonObject legacy() {
        JsonObject request = obj("request_id", "request-one", "goal", obj("skill", "gather"));
        JsonObject tasks = obj("world:request-one", obj("hash", hash(canonical(request)), "task", task("world", "request-one", "succeeded", 3)));
        return obj("schema_version", 1, "instance_id", "mc-original-install", "tasks", tasks, "worlds", obj(hash("private-world"), "world-stable"),
                "counters", obj("boot:world:events", 5), "outbox", List.of(obj("type", "game_event", "boot", "boot", "world", "world", "stream", "events", "payload", obj("delivery_seq", 5, "event_id", "event-5"))));
    }
    @Test void simultaneousOwnerIsRejectedAndLockIsReleased() throws Exception {
        String instance;
        try (LocalJournal first = new LocalJournal(root)) { instance = first.instance(); assertThrows(IOException.class, () -> new LocalJournal(root)); }
        try (LocalJournal second = new LocalJournal(root)) { assertEquals(instance, second.instance()); }
    }
    @Test void nativeEngineAndDurabilitySettingsMatchLockedContract() throws Exception {
        try (LocalJournal j = new LocalJournal(root); Connection c = sql()) {
            assertEquals("3.53.4", scalar(c, "SELECT sqlite_version()")); assertEquals("wal", scalar(c, "PRAGMA journal_mode"));
            assertEquals("3", scalar(c, "PRAGMA user_version"));
            assertEquals(3, LocalJournal.SCHEMA_VERSION);
        }
    }
    @Test void unfinishedTaskBecomesUnknownWithoutReplayOnRestart() throws Exception {
        try (LocalJournal journal = new LocalJournal(root)) { journal.accept("world", obj("request_id", "one"), task("world", "one", "running", 2), "boot"); }
        try (LocalJournal journal = new LocalJournal(root)) {
            JsonObject recovered = journal.find("world", "one").getAsJsonObject("task");
            assertEquals("failed", str(recovered, "state")); assertEquals("unknown", str(recovered, "effect_status"));
            assertEquals("INTERRUPTED_RESTART", str(recovered, "reason")); assertEquals(3, num(recovered, "version"));
            assertEquals("boot", str(recovered, "bridge_boot_id"));
            journal.activateContext("new-boot", "new-world"); assertTrue(journal.pending("boot", "world").isEmpty());
            assertEquals(2, journal.archivePage("boot", "world", "task_transitions", 0, 10).size());
        }
        try (LocalJournal again = new LocalJournal(root)) { assertEquals(3, num(again.find("world", "one").getAsJsonObject("task"), "version")); }
    }
    @Test void separateWorldsAndCanonicalRequestHashPersist() throws Exception {
        JsonObject request = obj("request_id", "same", "goal", obj("skill", "gather", "count", 4));
        try (LocalJournal journal = new LocalJournal(root)) {
            journal.accept("a", request, task("a", "same", "succeeded", 3)); journal.accept("b", request, task("b", "same", "succeeded", 3));
            assertEquals(hash(canonical(request)), str(journal.find("a", "same"), "hash"));
            assertThrows(Json.Rejected.class, () -> journal.accept("a", request, task("a", "same", "running", 2)));
        }
    }
    @Test void reliableStreamsHaveIndependentSequencesAndAckScope() throws Exception {
        try (LocalJournal journal = new LocalJournal(root)) {
            assertEquals(1, num(journal.reliable("game_event", "boot", "world", obj()), "delivery_seq"));
            assertEquals(1, num(journal.reliable("task_update", "boot", "world", obj()), "delivery_seq"));
            assertEquals(2, num(journal.reliable("game_event", "boot", "world", obj()), "delivery_seq"));
            journal.ack("boot", "world", "events", 1); assertEquals(2, journal.pending("boot", "world").size());
            journal.ack("boot", "world", "events", 0); assertEquals(2, journal.pending("boot", "world").size());
            assertThrows(Json.Rejected.class, () -> journal.ack("boot", "world", "events", 999));
            assertThrows(Json.Rejected.class, () -> journal.ack("other", "world", "events", 0));
            assertTrue(journal.pending("other-boot", "world").isEmpty());
        }
        try (Connection c = sql()) { assertEquals("1", scalar(c, "SELECT acked FROM streams WHERE stream='events'")); }
    }
    @Test void fullReliableWindowStopsInsteadOfLosingResults() throws Exception {
        try (LocalJournal journal = new LocalJournal(root)) { journal.reliable("game_event", "boot", "world", obj("event_id", "event-1")); }
        seedWindow(255);
        try (LocalJournal journal = new LocalJournal(root)) {
            assertEquals(256, num(journal.reliable("game_event", "boot", "world", obj("event_id", "event-256")), "delivery_seq"));
            assertThrows(Json.Rejected.class, () -> journal.reliable("game_event", "boot", "world", obj()));
            assertEquals(256, journal.pending("boot", "world").size());
        }
        try (LocalJournal reopened = new LocalJournal(root)) { assertEquals(256, reopened.pending("boot", "world").size()); }
    }
    @Test void rawWorldAddressIsNotWrittenAndRegisteredWorldIsStable() throws Exception {
        String world;
        try (LocalJournal journal = new LocalJournal(root)) { world = journal.worldId("private-address-never-export"); }
        assertFalse(new String(Files.readAllBytes(root.resolve("mc-control.sqlite3")), StandardCharsets.ISO_8859_1).contains("private-address-never-export"));
        try (LocalJournal journal = new LocalJournal(root)) { assertEquals(world, journal.worldId("private-address-never-export")); }
    }
    @Test void ledgerLookupCrossesWorldAndBootWithoutRepeatingAnEffect() throws Exception {
        try (LocalJournal journal = new LocalJournal(root)) {
            journal.accept("old", obj("request_id", "request"), task("old", "request", "succeeded", 3));
            JsonArray ids = new JsonArray(); ids.add("task-old-request"); JsonObject entry = journal.lookup(ids).get(0).getAsJsonObject();
            assertEquals("found", str(entry, "status")); entry.getAsJsonObject("task").addProperty("state", "failed");
            assertEquals("succeeded", str(journal.lookup(ids).get(0).getAsJsonObject().getAsJsonObject("task"), "state"));
            ids.set(0, new JsonPrimitive("missing")); assertTrue(journal.lookup(ids).get(0).getAsJsonObject().get("task").isJsonNull());
        }
    }
    @Test void ledgerLookupRejectsAnUnboundedBatch() throws Exception {
        try (LocalJournal journal = new LocalJournal(root)) {
            JsonArray ids = new JsonArray(); ids.add("one"); ids.add("two"); assertThrows(Json.Rejected.class, () -> journal.lookup(ids));
        }
    }
    @Test void legacyMigrationPreservesIdentityHashCursorAndExactBackup() throws Exception {
        byte[] original = GSON.toJson(legacy()).getBytes(StandardCharsets.UTF_8); Files.write(root.resolve("journal.json"), original);
        try (LocalJournal journal = new LocalJournal(root)) {
            assertEquals("mc-original-install", journal.instance()); assertEquals("world-stable", journal.worldId("private-world"));
            assertEquals("succeeded", str(journal.find("world", "request-one").getAsJsonObject("task"), "state"));
            assertEquals(6, num(journal.reliable("game_event", "boot", "world", obj("event_id", "event-6")), "delivery_seq"));
        }
        assertArrayEquals(original, Files.readAllBytes(root.resolve("journal.json")));
        try (var files = Files.list(root.resolve("backups"))) { List<Path> all = files.toList(); assertEquals(1, all.size()); assertArrayEquals(original, Files.readAllBytes(all.getFirst())); }
        // SQLite remains authoritative after migration, even if the historical JSON is replaced.
        Files.writeString(root.resolve("journal.json"), "invalid historical backup");
        try (LocalJournal journal = new LocalJournal(root)) { assertEquals("mc-original-install", journal.instance()); }
    }
    @Test void malformedMigrationRollsBackTablesAndReleasesOwner() throws Exception {
        JsonObject source = legacy(); source.getAsJsonObject("counters").addProperty("boot:world:events", 1); Files.writeString(root.resolve("journal.json"), GSON.toJson(source));
        assertThrows(Json.Rejected.class, () -> new LocalJournal(root));
        try (Connection c = sql()) { assertEquals("0", scalar(c, "PRAGMA user_version")); assertEquals("0", scalar(c, "SELECT count(*) FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")); }
        Files.writeString(root.resolve("journal.json"), GSON.toJson(legacy()));
        try (LocalJournal journal = new LocalJournal(root)) { assertEquals("mc-original-install", journal.instance()); }
    }
    @Test void newerSQLiteVersionIsRejectedBeforeJournalModeOrDataMutation() throws Exception {
        try (LocalJournal ignored = new LocalJournal(root)) {}
        try (Connection c = sql(); Statement s = c.createStatement()) { s.execute("PRAGMA journal_mode=DELETE"); s.execute("PRAGMA user_version=99"); }
        byte[] before = Files.readAllBytes(root.resolve("mc-control.sqlite3"));
        assertThrows(Json.Rejected.class, () -> new LocalJournal(root));
        assertArrayEquals(before, Files.readAllBytes(root.resolve("mc-control.sqlite3")));
        try (Connection c = sql()) { assertEquals("delete", scalar(c, "PRAGMA journal_mode")); assertEquals("99", scalar(c, "PRAGMA user_version")); }
        assertThrows(Json.Rejected.class, () -> new LocalJournal(root));
    }
    @Test void unknownLegacyVersionRefusesWithoutImport() throws Exception {
        JsonObject source = legacy(); source.addProperty("schema_version", 99); String original = GSON.toJson(source); Files.writeString(root.resolve("journal.json"), original);
        assertThrows(Json.Rejected.class, () -> new LocalJournal(root)); assertEquals(original, Files.readString(root.resolve("journal.json")));
    }
    @Test void admissionAndFirstTransitionRollBackWhenDeliveryWindowIsFull() throws Exception {
        try (LocalJournal j = new LocalJournal(root)) { j.reliable("game_event", "boot", "world", obj()); }
        seedWindow(256);
        try (LocalJournal j = new LocalJournal(root)) {
            assertThrows(Json.Rejected.class, () -> j.accept("world", obj("request_id", "one"), task("world", "one", "accepted", 1), "boot"));
            assertNull(j.find("world", "one")); assertEquals(256, j.pending("boot", "world").size());
        }
        try (Connection c = sql()) { assertEquals("0", scalar(c, "SELECT count(*) FROM task_transitions")); }
    }
    @Test void runningTransitionRollsBackWhenItsReliableRecordCannotCommit() throws Exception {
        try (LocalJournal j = new LocalJournal(root)) {
            j.accept("world", obj("request_id", "one"), task("world", "one", "accepted", 1));
            // Exercise actual commits for this boundary, rather than a second writer on an active store.
            for (int i = 0; i < 256; i++) j.reliable("game_event", "boot", "world", obj());
            assertThrows(Json.Rejected.class, () -> j.update(task("world", "one", "running", 2), "boot"));
            assertEquals("accepted", str(j.find("world", "one").getAsJsonObject("task"), "state"));
        }
        try (Connection c = sql()) { assertEquals("1", scalar(c, "SELECT count(*) FROM task_transitions")); assertEquals("256", scalar(c, "SELECT issued FROM streams WHERE stream='events'")); }
    }
    @Test void unresolvedHistoryBudgetStopsWithoutDeletingOldEvidenceOrIssuingASequence() throws Exception {
        try (LocalJournal j = new LocalJournal(root)) { j.reliable("game_event", "boot", "world", obj()); }
        // Closed near-capacity fixture; retain every unacknowledged row in SQLite.
        try (Connection c = sql(); Statement s = c.createStatement()) {
            c.setAutoCommit(false);
            s.executeUpdate("WITH RECURSIVE n(x) AS (VALUES(2) UNION ALL SELECT x+1 FROM n WHERE x<50000) INSERT INTO reliable(boot,world,stream,delivery_seq,type,payload,created_at,archived_at,archive_reason) SELECT 'boot','world','events',x,'game_event',json_object('delivery_seq',x),0,1,'bridge_restart' FROM n");
            s.executeUpdate("UPDATE streams SET issued=50000"); c.commit();
        }
        try (LocalJournal j = new LocalJournal(root)) {
            j.activateContext("new-boot", "new-world"); assertTrue(j.status().get("retention_blocked").getAsBoolean());
            assertThrows(Json.Rejected.class, () -> j.reliable("game_event", "new-boot", "new-world", obj()));
            assertEquals(50000, num(j.status(), "archived_unacked")); assertEquals(100, j.archivePage("boot", "world", "events", 49900, 100).size());
        }
        try (Connection c = sql()) { assertEquals("0", scalar(c, "SELECT count(*) FROM streams WHERE boot='new-boot'")); }
    }
    @Test void duplicateTaskIdRollsBackInsteadOfCreatingAmbiguousProof() throws Exception {
        try (LocalJournal j = new LocalJournal(root)) {
            JsonObject a = task("a", "one", "succeeded", 3), b = task("b", "two", "succeeded", 3); b.addProperty("task_id", str(a, "task_id"));
            j.accept("a", obj("request_id", "one"), a); assertThrows(IOException.class, () -> j.accept("b", obj("request_id", "two"), b));
            assertNull(j.find("b", "two")); assertEquals(1, num(j.status(), "tasks"));
        }
    }
    @Test void taskVersionAndContextCannotBeRewrittenOrResurrected() throws Exception {
        try (LocalJournal j = new LocalJournal(root)) {
            JsonObject value = task("world", "one", "accepted", 1); j.accept("world", obj("request_id", "one"), value, "boot");
            value.addProperty("version", 2); value.addProperty("state", "running"); value.addProperty("control_epoch", 8);
            assertThrows(Json.Rejected.class, () -> j.update(value, "boot")); value.addProperty("control_epoch", 7); j.update(value, "boot");
            value.addProperty("version", 3); value.addProperty("state", "succeeded"); j.update(value, "boot");
            value.addProperty("version", 4); value.addProperty("state", "running"); assertThrows(Json.Rejected.class, () -> j.update(value, "boot"));
            assertEquals("succeeded", str(j.find("world", "one").getAsJsonObject("task"), "state")); assertEquals(3, j.pending("boot", "world").size());
        }
        try (Connection c = sql()) { assertEquals("3", scalar(c, "SELECT count(*) FROM task_transitions")); }
    }
    @Test void oldBootArchiveFreesActiveCapacityAndKeepsOriginalPayload() throws Exception {
        try (LocalJournal j = new LocalJournal(root)) { j.reliable("game_event", "boot", "world", obj("event_id", "event-one")); }
        seedWindow(256);
        try (LocalJournal j = new LocalJournal(root)) {
            j.activateContext("new-boot", "new-world"); assertTrue(j.pending("boot", "world").isEmpty());
            assertEquals(256, num(j.status(), "archived_unacked")); assertEquals(1, num(j.reliable("game_event", "new-boot", "new-world", obj()), "delivery_seq"));
            JsonArray page = j.archivePage("boot", "world", "events", 100, 100); assertEquals(100, page.size());
            assertEquals(101, num(page.get(0).getAsJsonObject(), "delivery_seq")); assertEquals("bridge_restart", str(page.get(0).getAsJsonObject(), "archive_reason"));
            assertThrows(Json.Rejected.class, () -> j.archivePage("boot", "world", "events", 0, 101));
        }
    }
    @Test void worldChangeAndLateOldResultStayInHistoricalContext() throws Exception {
        try (LocalJournal j = new LocalJournal(root)) {
            j.activateContext("boot", "world"); j.reliable("game_event", "boot", "world", obj("event_id", "original"));
            j.activateContext("boot", "next-world"); j.reliable("game_event", "boot", "world", obj("event_id", "late"));
            assertTrue(j.pending("boot", "world").isEmpty()); assertTrue(j.pending("boot", "next-world").isEmpty());
            JsonArray page = j.archivePage("boot", "world", "events", 0, 10);
            assertEquals("world_changed", str(page.get(0).getAsJsonObject(), "archive_reason")); assertEquals("late_historical_result", str(page.get(1).getAsJsonObject(), "archive_reason"));
        }
    }
    @Test void consistentBackupIncludesCommittedWalAndOfflineRestoreKeepsSafetyCopy() throws Exception {
        Path snapshot;
        try (LocalJournal j = new LocalJournal(root)) {
            j.activateContext("boot", "world"); j.accept("world", obj("request_id", "one"), task("world", "one", "running", 2), "boot");
            assertTrue(Files.size(root.resolve("mc-control.sqlite3-wal")) > 0); snapshot = j.backup();
            assertThrows(IOException.class, () -> LocalJournal.restore(root, snapshot.getFileName().toString()));
            j.accept("world", obj("request_id", "two"), task("world", "two", "succeeded", 3), "boot");
        }
        try (Connection c = DriverManager.getConnection("jdbc:sqlite:" + snapshot)) { assertEquals("1", scalar(c, "SELECT count(*) FROM tasks")); assertEquals("running", scalar(c, "SELECT state FROM tasks")); }
        Path safety = LocalJournal.restore(root, snapshot.getFileName().toString()); assertTrue(Files.exists(safety));
        try (LocalJournal j = new LocalJournal(root)) {
            assertNull(j.find("world", "two")); assertEquals("unknown", str(j.find("world", "one").getAsJsonObject("task"), "effect_status"));
        }
        try (Connection c = DriverManager.getConnection("jdbc:sqlite:" + safety)) { assertEquals("2", scalar(c, "SELECT count(*) FROM tasks")); }
    }
    @Test void tamperedBackupAndExternalPathsAreRefusedWithoutRestore() throws Exception {
        Path snapshot;
        try (LocalJournal j = new LocalJournal(root)) { snapshot = j.backup(); }
        Files.write(snapshot, new byte[] {1}, StandardOpenOption.APPEND);
        assertThrows(Json.Rejected.class, () -> LocalJournal.restore(root, snapshot.getFileName().toString()));
        assertThrows(Json.Rejected.class, () -> LocalJournal.restore(root, "../other.sqlite3"));
        try (LocalJournal j = new LocalJournal(root)) { assertEquals(0, num(j.status(), "tasks")); }
    }
    @Test void snapshotFromAnotherInstallationIsRefused() throws Exception {
        Path other = root.resolve("other"); Files.createDirectories(other); Path snapshot;
        try (LocalJournal j = new LocalJournal(other)) { snapshot = j.backup(); }
        try (LocalJournal j = new LocalJournal(root)) { j.backup(); }
        Path copied = root.resolve("backups").resolve(snapshot.getFileName()); Files.copy(snapshot, copied); Files.copy(snapshot.resolveSibling(snapshot.getFileName() + ".json"), copied.resolveSibling(copied.getFileName() + ".json"));
        assertThrows(Json.Rejected.class, () -> LocalJournal.restore(root, copied.getFileName().toString()));
    }
}

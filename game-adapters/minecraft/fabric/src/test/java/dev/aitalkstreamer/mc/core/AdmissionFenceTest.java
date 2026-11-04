package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import java.nio.file.*;
import java.sql.*;
import static org.junit.jupiter.api.Assertions.*;
import static dev.aitalkstreamer.mc.core.Json.*;

class AdmissionFenceTest {
    @TempDir Path root;
    private JsonArray ids(String id) { JsonArray a = new JsonArray(); a.add(id); return a; }
    private JsonObject lookup(LocalJournal j, String id, String boot, String world) throws Exception {
        return j.lookupForRecovery(ids(id), boot, world).get(0).getAsJsonObject();
    }
    private void rejected(String expected, org.junit.jupiter.api.function.Executable action) {
        assertEquals(expected, assertThrows(Json.Rejected.class, action).code);
    }
    @Test void aCommittedAbsenceFenceBlocksLateAdmissionWithoutCreatingATask() throws Exception {
        try (LocalJournal j = new LocalJournal(root)) {
            j.activateContext("boot-one", "world-one");
            JsonObject entry = lookup(j, "task-one", "boot-one", "world-one"), proof = entry.getAsJsonObject("admission_fence");
            assertEquals("missing", str(entry,"status")); assertTrue(entry.get("task").isJsonNull());
            assertEquals(j.instance(), str(proof,"game_instance_id")); assertEquals("boot-one", str(proof,"checked_bridge_boot_id"));
            rejected("GAME_TASK_HISTORY_EXPIRED", () -> j.accept("world-one", obj("request_id","late"), obj("task_id","task-one"), "boot-one"));
            assertNull(j.find("world-one","late")); assertTrue(j.pending("boot-one","world-one").isEmpty());
        }
    }
    @Test void repeatsAndRestartPreserveTheFenceWhileBindingEachFreshQuery() throws Exception {
        String fence;
        try (LocalJournal j = new LocalJournal(root)) {
            j.activateContext("boot-one","world-one"); fence = str(lookup(j,"task-one","boot-one","world-one").getAsJsonObject("admission_fence"),"fence_id");
            assertEquals(fence, str(lookup(j,"task-one","boot-one","world-one").getAsJsonObject("admission_fence"),"fence_id"));
        }
        try (LocalJournal j = new LocalJournal(root)) {
            j.activateContext("boot-two","world-two"); JsonObject proof = lookup(j,"task-one","boot-two","world-two").getAsJsonObject("admission_fence");
            assertEquals(fence,str(proof,"fence_id")); assertEquals("world-two",str(proof,"checked_world_session_id"));
            rejected("GAME_TASK_HISTORY_EXPIRED", () -> j.accept("world-two", obj("request_id","new"), obj("task_id","task-one")));
        }
    }
    @Test void wrongContextCannotCreateAnAbsenceFence() throws Exception {
        try (LocalJournal j = new LocalJournal(root)) {
            j.activateContext("boot-one","world-one");
            rejected("GAME_LEDGER_CONTEXT", () -> lookup(j,"task-one","old-boot","world-one"));
            assertFalse(j.lookup(ids("task-one")).get(0).getAsJsonObject().has("admission_fence"));
        }
        try (Connection c=DriverManager.getConnection("jdbc:sqlite:"+root.resolve("mc-control.sqlite3")); Statement s=c.createStatement(); ResultSet r=s.executeQuery("SELECT count(*) FROM journal_retired_tasks")) { assertTrue(r.next()); assertEquals(0,r.getInt(1)); }
    }
    @Test void actualAndPreviouslyRetiredTasksNeverProduceAbsenceProof() throws Exception {
        try (LocalJournal j = new LocalJournal(root)) {
            j.activateContext("boot-one","world-one");
            j.accept("world-one",obj("request_id","known"),obj("task_id","task-known","world_session_id","world-one","request_id","known","version",1,"state","accepted"));
            JsonObject found = lookup(j,"task-known","boot-one","world-one"); assertEquals("found",str(found,"status")); assertFalse(found.has("admission_fence"));
            try (Connection c=DriverManager.getConnection("jdbc:sqlite:"+root.resolve("mc-control.sqlite3")); PreparedStatement q=c.prepareStatement("INSERT INTO journal_retired_tasks VALUES('old-world','old-request','task-retired',?,0,'{}')")) { q.setString(1,"0".repeat(64)); q.executeUpdate(); }
            assertFalse(lookup(j,"task-retired","boot-one","world-one").has("admission_fence"));
        }
    }
    @Test void restoringAnOlderBackupCannotRemoveTheLaterAbsenceFence() throws Exception {
        Path backup; String fence;
        try (LocalJournal j = new LocalJournal(root)) {
            j.activateContext("boot-one","world-one"); backup=j.backup();
            fence=str(lookup(j,"task-one","boot-one","world-one").getAsJsonObject("admission_fence"),"fence_id");
        }
        LocalJournal.restore(root,backup.getFileName().toString());
        try (LocalJournal j = new LocalJournal(root)) {
            j.activateContext("boot-two","world-two"); assertEquals(fence,str(lookup(j,"task-one","boot-two","world-two").getAsJsonObject("admission_fence"),"fence_id"));
            rejected("GAME_TASK_HISTORY_EXPIRED", () -> j.accept("world-two",obj("request_id","late"),obj("task_id","task-one")));
        }
    }
    @Test void aTamperedFenceFailsClosedInsteadOfBeingReissued() throws Exception {
        try (LocalJournal j = new LocalJournal(root)) {
            j.activateContext("boot-one","world-one"); lookup(j,"task-one","boot-one","world-one");
            try (Connection c=DriverManager.getConnection("jdbc:sqlite:"+root.resolve("mc-control.sqlite3")); Statement s=c.createStatement()) { s.executeUpdate("UPDATE journal_retired_tasks SET body_hash='tampered'"); }
            rejected("GAME_JOURNAL_ADMISSION_FENCE_INVALID", () -> lookup(j,"task-one","boot-one","world-one"));
        }
    }
    @Test void anAbsenceGuardIsNeverPresentedAsARetiredExecutedTask() throws Exception {
        try (LocalJournal j = new LocalJournal(root)) {
            j.activateContext("boot-one","world-one"); lookup(j,"task-one","boot-one","world-one");
            JsonObject page=j.historyPage(obj("source","retired_tasks","after",0,"offset",0,"through",null,"limit",20));
            assertEquals(0,num(page,"through")); assertTrue(page.get("complete").getAsBoolean()); assertTrue(page.getAsJsonArray("chunks").isEmpty());
            assertTrue(lookup(j,"task-one","boot-one","world-one").has("admission_fence"));
        }
    }
}

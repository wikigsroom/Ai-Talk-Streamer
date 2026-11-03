package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.sql.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static dev.aitalkstreamer.mc.core.Json.*;

class JournalHistoryTest {
    @TempDir Path root;
    private boolean bool(JsonObject value, String key) { return value.get(key).getAsBoolean(); }
    private JsonObject request(String source, long after, int offset, Long through, int limit) {
        return obj("source", source, "after", after, "offset", offset, "through", through, "limit", limit);
    }
    private JsonObject task(LocalJournal journal, long version) {
        return obj("task_id", "history-task", "request_id", "history-request", "game_instance_id", journal.instance(),
            "bridge_boot_id", "old-boot", "world_session_id", "old-world", "state", version == 3 ? "succeeded" : "running", "version", version);
    }
    private JsonObject payload(JsonObject chunk) {
        return JsonParser.parseString(new String(Base64.getDecoder().decode(str(chunk,"data_base64")), StandardCharsets.UTF_8)).getAsJsonObject();
    }
    private Connection sql() throws SQLException { return DriverManager.getConnection("jdbc:sqlite:" + root.resolve("mc-control.sqlite3")); }
    private String dump(Connection db, String table) throws SQLException {
        List<String> rows = new ArrayList<>();
        try (Statement query = db.createStatement(); ResultSet result = query.executeQuery("SELECT * FROM " + table + " ORDER BY rowid")) {
            while (result.next()) { List<String> row = new ArrayList<>(); for(int i=1;i<=result.getMetaData().getColumnCount();i++) row.add(result.getString(i)); rows.add(row.toString()); }
        }
        return rows.toString();
    }
    @Test void allDispositionsKeepTheirOriginalContextWithoutChangingJournalAuthority() throws Exception {
        try (LocalJournal journal = new LocalJournal(root); Connection db = sql()) {
            journal.reliable("game_event", "old-boot", "old-world", obj("event_id", "acked"));
            journal.ack("old-boot", "old-world", "events", 1);
            journal.reliable("game_event", "old-boot", "old-world", obj("event_id", "archived"));
            journal.activateContext("current-boot", "current-world");
            journal.reliable("game_event", "current-boot", "current-world", obj("event_id", "pending"));
            Map<String,String> before = new LinkedHashMap<>();
            for(String table:List.of("reliable","streams","tasks","task_transitions")) before.put(table,dump(db,table));
            JsonObject result = journal.historyPage(request("reliable",0,0,null,20));
            assertTrue(bool(result,"complete")); JsonArray chunks = result.getAsJsonArray("chunks"); assertEquals(3,chunks.size());
            JsonObject acked=chunks.get(0).getAsJsonObject(), archived=chunks.get(1).getAsJsonObject(), pending=chunks.get(2).getAsJsonObject();
            assertFalse(acked.get("acked_at").isJsonNull()); assertEquals("old-world",str(acked,"world_session_id"));
            assertEquals("old-boot",str(archived,"source_boot_id")); assertEquals("bridge_restart",str(archived,"archive_reason"));
            assertEquals("current-world",str(pending,"world_session_id")); assertTrue(pending.get("archived_at").isJsonNull());
            assertEquals("pending",str(payload(pending),"event_id"));
            for(var entry:before.entrySet()) assertEquals(entry.getValue(),dump(db,entry.getKey()));
        }
    }
    @Test void everyTaskVersionRemainsQueryableEvenWhenItsDeliveryRowIsAbsent() throws Exception {
        try (LocalJournal journal = new LocalJournal(root); Connection db = sql()) {
            journal.accept("old-world",obj("request_id","history-request"),task(journal,1),"old-boot");
            journal.update(task(journal,2),"old-boot"); journal.update(task(journal,3),"old-boot");
            db.createStatement().executeUpdate("DELETE FROM reliable WHERE type='task_update'");
            JsonObject result=journal.historyPage(request("task_versions",0,0,null,20));
            assertEquals(3,result.getAsJsonArray("chunks").size()); assertTrue(bool(result,"complete"));
            for(JsonElement element:result.getAsJsonArray("chunks")) {
                JsonObject chunk=element.getAsJsonObject(); assertEquals(num(payload(chunk),"version"),num(chunk,"sequence"));
                assertEquals("old-boot",str(chunk,"source_boot_id")); assertEquals("task_version",str(chunk,"type"));
                assertTrue(chunk.get("acked_at").isJsonNull());
            }
        }
    }
    @Test void initialWatermarkExcludesLaterRowsUntilAnExplicitNewScan() throws Exception {
        try(LocalJournal journal=new LocalJournal(root)) {
            for(int i=1;i<=21;i++)journal.reliable("game_event","boot","world",obj("event_id","e"+i));
            JsonObject first=journal.historyPage(request("reliable",0,0,null,20)); assertFalse(bool(first,"complete")); assertEquals(21,num(first,"through"));
            journal.reliable("game_event","boot","world",obj("event_id","later"));
            JsonObject rest=journal.historyPage(request("reliable",num(first,"next_after"),0,num(first,"through"),20));
            assertTrue(bool(rest,"complete")); assertEquals(1,rest.getAsJsonArray("chunks").size()); assertEquals(21,num(rest,"next_after"));
            assertEquals(22,num(journal.historyPage(request("reliable",0,0,null,20)),"through"));
        }
    }
    @Test void multibytePayloadCrossesChunkBoundariesWithoutIncreasingWireLimit() throws Exception {
        try(LocalJournal journal=new LocalJournal(root)) {
            JsonObject original=journal.reliable("game_event","boot","world",obj("event_id","large","text","界".repeat(40000)));
            ByteArrayOutputStream assembled=new ByteArrayOutputStream(); long after=0; int offset=0,pages=0; Long through=null;
            do {
                JsonObject page=journal.historyPage(request("reliable",after,offset,through,20)); int bytes=0;
                for(JsonElement value:page.getAsJsonArray("chunks")) {JsonObject chunk=value.getAsJsonObject();byte[] part=Base64.getDecoder().decode(str(chunk,"data_base64"));
                    assertTrue(part.length<=JournalHistory.CHUNK_BYTES); bytes+=part.length;assembled.write(part);assertEquals(hash(GSON.toJson(original)),str(chunk,"payload_sha256"));}
                assertTrue(bytes<=JournalHistory.PAGE_BYTES);assertTrue(GSON.toJson(page).getBytes(StandardCharsets.UTF_8).length<Wire.MAX_BYTES);
                after=num(page,"next_after");offset=(int)num(page,"next_offset");through=num(page,"through");pages++;
                if(bool(page,"complete"))break;assertTrue(pages<8);
            }while(true);
            assertTrue(pages>=4);assertEquals(original,JsonParser.parseString(assembled.toString(StandardCharsets.UTF_8)));
        }
    }
    @Test void pageByteBudgetBoundsManyMediumSizedRows() throws Exception {
        try(LocalJournal journal=new LocalJournal(root)) {
            for(int i=0;i<20;i++)journal.reliable("game_event","boot","world",obj("text","x".repeat(6000)));
            JsonObject result=journal.historyPage(request("reliable",0,0,null,20));int total=0;
            for(JsonElement element:result.getAsJsonArray("chunks"))total+=Base64.getDecoder().decode(str(element.getAsJsonObject(),"data_base64")).length;
            assertEquals(JournalHistory.PAGE_BYTES,total);assertFalse(bool(result,"complete"));assertTrue(num(result,"next_offset")>0);
        }
    }
    @Test void invalidAndStaleCursorsCannotReadAnotherTableOrSkipBeyondTheWindow() throws Exception {
        try(LocalJournal journal=new LocalJournal(root)) {
            journal.reliable("game_event","boot","world",obj("event_id","one"));
            for(JsonObject params:List.of(request("reliable;DROP TABLE tasks",0,0,null,1),request("reliable",-1,0,null,1),
                request("reliable",0,0,2L,1),request("reliable",1,1,1L,1),request("reliable",0,131072,null,1),request("reliable",0,0,null,21)))
                assertThrows(Json.Rejected.class,()->journal.historyPage(params));
        }
    }
    @Test void oversizedHistoricalRowsFailExplicitlyWithoutAcknowledgingThem() throws Exception {
        try(LocalJournal journal=new LocalJournal(root);Connection db=sql()) {
            journal.reliable("game_event","boot","world",obj("event_id","one"));
            try(PreparedStatement row=db.prepareStatement("UPDATE reliable SET payload=?")){row.setString(1,"{\"large\":\""+"x".repeat(131072)+"\"}");row.executeUpdate();}
            String before=dump(db,"reliable");assertThrows(Json.Rejected.class,()->journal.historyPage(request("reliable",0,0,null,20)));
            assertEquals(before,dump(db,"reliable"));
        }
    }
    @Test void emptyJournalCompletesBothSourcesWithAZeroWatermark() throws Exception {
        try(LocalJournal journal=new LocalJournal(root)) {
            for(String source:List.of("reliable","task_versions")) {
                JsonObject page=journal.historyPage(request(source,0,0,null,20));assertTrue(bool(page,"complete"));
                assertEquals(0,num(page,"through"));assertEquals(0,page.getAsJsonArray("chunks").size());
            }
        }
    }
}

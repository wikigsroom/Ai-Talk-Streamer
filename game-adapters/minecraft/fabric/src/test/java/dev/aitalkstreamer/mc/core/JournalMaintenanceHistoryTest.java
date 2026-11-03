package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.sql.*;
import java.time.Instant;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static dev.aitalkstreamer.mc.core.Json.*;

class JournalMaintenanceHistoryTest {
    @TempDir Path root;
    private final long now=System.currentTimeMillis(), old=now-45*JournalRetention.DAY;
    private static final List<String> SOURCES=List.of("retention_summaries","retired_tasks","retention_runs");
    private Connection sql()throws SQLException{return DriverManager.getConnection("jdbc:sqlite:"+root.resolve("mc-control.sqlite3"));}
    private void write(String statement,Object...args)throws SQLException {
        try(Connection db=sql();PreparedStatement q=db.prepareStatement(statement)){for(int i=0;i<args.length;i++)q.setObject(i+1,args[i]);q.executeUpdate();}
    }
    private JsonObject page(LocalJournal journal,String source,long after,Long through,int limit) {
        return journal.historyPage(obj("source",source,"after",after,"offset",0,"through",through,"limit",limit));
    }
    private JsonObject payload(JsonObject chunk) {
        return JsonParser.parseString(new String(Base64.getDecoder().decode(str(chunk,"data_base64")),StandardCharsets.UTF_8)).getAsJsonObject();
    }
    private JsonObject first(LocalJournal journal,String source){return page(journal,source,0,null,20).getAsJsonArray("chunks").get(0).getAsJsonObject();}
    private String summaryKey(JsonObject value){return hash(canonical(obj("world_session_id",value.get("world_session_id"),"source",value.get("source"),"kind",value.get("kind"),"utc_day",value.get("utc_day"))));}
    private String dump()throws Exception {
        JsonObject all=new JsonObject();try(Connection db=sql()) {
            for(String table:List.of("metadata","tasks","task_transitions","streams","reliable","contexts","worlds","journal_summaries","journal_retired_tasks","journal_retention_runs")) {
                JsonArray data=new JsonArray();try(Statement q=db.createStatement();ResultSet rows=q.executeQuery("SELECT rowid,* FROM "+table+" ORDER BY rowid")) {
                    while(rows.next()){JsonArray row=new JsonArray();for(int i=1;i<=rows.getMetaData().getColumnCount();i++)row.add(rows.getString(i));data.add(row);}
                }all.add(table,data);
            }
        }return canonical(all);
    }
    private JsonObject seedAndRetire()throws Exception {
        try(LocalJournal journal=new LocalJournal(root)) {
            journal.activateContext("old-boot","old-world");String time=Instant.ofEpochMilli(old).toString();
            JsonObject task=obj("task_id","retired-one","request_id","req-retired-one","game_instance_id",journal.instance(),
                "bridge_boot_id","old-boot","world_session_id","old-world","world_id","stable-world","state","succeeded","version",1,
                "effect_status","verified","created_at",time,"updated_at",time,"control_epoch",4,"goal",obj("skill","gather","item_id","minecraft:oak_log","count",1));
            journal.accept("old-world",obj("request_id","req-retired-one"),task,"old-boot");
            journal.reliable("game_event","old-boot","old-world",obj("event_id","private-event","kind","inventory_changed","occurred_at",time,"data",obj("text","PRIVATE ORIGINAL")));
            journal.ack("old-boot","old-world","events",1);journal.ack("old-boot","old-world","task_transitions",1);
            journal.activateContext("current-boot","current-world");
        }
        write("UPDATE reliable SET created_at=?,acked_at=?",old,old);write("UPDATE task_transitions SET recorded_at=?",old);
        write("UPDATE contexts SET closed_at=? WHERE boot='old-boot'",old);
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)) {
            JsonObject plan=journal.retentionPlan(now,Set.of());return journal.applyRetention(plan,hash(canonical(plan)));
        }
    }
    @Test void actualMaintenanceRecordsAreFullyQueryableAndNeverChangeJournalAuthority()throws Exception {
        seedAndRetire();try(LocalJournal journal=new LocalJournal(root)) {
            String before=dump();Wire wire=new Wire();int total=0;
            for(String source:SOURCES) {
                JsonObject result=page(journal,source,0,null,20);assertTrue(result.get("complete").getAsBoolean());
                for(JsonElement item:result.getAsJsonArray("chunks")) {
                    JsonObject chunk=item.getAsJsonObject(),raw=payload(chunk);total++;
                    wire.validate("JournalMaintenanceChunk",chunk);wire.validate("JournalMaintenancePayload",raw);
                    assertEquals(source,str(raw,"source"));assertEquals(journal.instance(),str(raw,"game_instance_id"));
                    assertEquals(hash(canonical(raw)),str(chunk,"payload_sha256"));assertEquals(0,num(chunk,"sequence"));
                    JsonArray key=GSON.toJsonTree(List.of(source,str(raw,"source_key"),str(chunk,"payload_sha256"))).getAsJsonArray();
                    assertEquals(hash(canonical(key)),str(chunk,"record_key"));assertFalse(canonical(raw).contains("PRIVATE ORIGINAL"));
                }
            }
            assertEquals(4,total);assertEquals(before,dump());
        }
    }
    @Test void allFiveEmptySourcesCompleteWithoutInventingRecords()throws Exception {
        try(LocalJournal journal=new LocalJournal(root)) {
            for(String source:List.of("reliable","task_versions","retention_summaries","retired_tasks","retention_runs")) {
                JsonObject result=page(journal,source,0,null,20);assertTrue(result.get("complete").getAsBoolean());
                assertEquals(0,num(result,"through"));assertEquals(0,result.getAsJsonArray("chunks").size());
            }
        }
    }
    @Test void summaryPagingReadsBeyondTheCliPreviewAndKeepsItsInitialUpperBound()throws Exception {
        seedAndRetire();try(LocalJournal journal=new LocalJournal(root)) {
            JsonObject template=payload(first(journal,"retention_summaries")).getAsJsonObject("value");
            for(int i=0;i<55;i++){JsonObject value=template.deepCopy();value.addProperty("kind","fixture-"+i);write("INSERT INTO journal_summaries VALUES(?,?)",summaryKey(value),canonical(value));}
            JsonObject first=page(journal,"retention_summaries",0,null,20);assertEquals(57,num(first,"through"));
            JsonObject later=template.deepCopy();later.addProperty("kind","later");write("INSERT INTO journal_summaries VALUES(?,?)",summaryKey(later),canonical(later));
            Set<String> keys=new HashSet<>();JsonObject current=first;
            while(true){for(JsonElement item:current.getAsJsonArray("chunks"))assertTrue(keys.add(str(item.getAsJsonObject(),"record_key")));
                if(current.get("complete").getAsBoolean())break;
                current=page(journal,"retention_summaries",num(current,"next_after"),num(first,"through"),20);}
            assertEquals(57,keys.size());assertEquals(58,num(page(journal,"retention_summaries",0,null,20),"through"));
        }
    }
    @Test void changedSummaryCreatesANewContentVersionWhileStableObjectsKeepTheirKeys()throws Exception {
        seedAndRetire();try(LocalJournal journal=new LocalJournal(root)) {
            JsonObject before=first(journal,"retention_summaries"),raw=payload(before);String retired=str(first(journal,"retired_tasks"),"record_key");
            write("UPDATE metadata SET value='2' WHERE key='retention_generation'");
            assertEquals(str(before,"record_key"),str(first(journal,"retention_summaries"),"record_key"));
            assertEquals(retired,str(first(journal,"retired_tasks"),"record_key"));
            write("UPDATE journal_summaries SET value=json_set(value,'$.count',4) WHERE summary_key=?",str(raw,"source_key"));
            JsonObject after=first(journal,"retention_summaries");assertNotEquals(str(before,"record_key"),str(after,"record_key"));
            assertEquals(4,num(payload(after).getAsJsonObject("value"),"count"));
        }
    }
    @Test void retiredProofNeverMasqueradesAsACompleteTaskOrChangesRecoveryLookup()throws Exception {
        seedAndRetire();try(LocalJournal journal=new LocalJournal(root)) {
            JsonObject chunk=first(journal,"retired_tasks"),raw=payload(chunk);
            assertEquals("old-boot",str(chunk,"source_boot_id"));assertEquals("old-world",str(chunk,"world_session_id"));
            assertThrows(Json.Rejected.class,()->new Wire().validate("Task",raw));
            JsonArray ids=new JsonArray();ids.add("retired-one");assertEquals("missing",str(journal.lookup(ids).get(0).getAsJsonObject(),"status"));
            assertEquals("GAME_TASK_HISTORY_EXPIRED",assertThrows(Json.Rejected.class,()->journal.find("old-world","req-retired-one")).code);
        }
    }
    @Test void summaryAndGlobalRunKeepTheirActualContextWithoutFabricatedDeliveryAcknowledgements()throws Exception {
        seedAndRetire();try(LocalJournal journal=new LocalJournal(root)) {
            JsonObject summary=first(journal,"retention_summaries"),run=first(journal,"retention_runs");
            assertTrue(summary.get("source_boot_id").isJsonNull());assertEquals("old-world",str(summary,"world_session_id"));
            assertTrue(run.get("source_boot_id").isJsonNull());assertTrue(run.get("world_session_id").isJsonNull());
            for(JsonObject chunk:List.of(summary,run))for(String key:List.of("acked_at","archived_at","archive_reason"))assertTrue(chunk.get(key).isJsonNull());
            assertEquals(str(payload(run),"source_key"),str(payload(run).getAsJsonObject("value"),"run_id"));
        }
    }
    @Test void oldBackupRestoreStillExposesPreservedRetiredProofEvenWhenSummaryAndRunAreAbsent()throws Exception {
        JsonObject result=seedAndRetire();LocalJournal.restore(root,str(result,"backup_file"));
        try(LocalJournal journal=new LocalJournal(root)) {
            assertEquals(1,page(journal,"retired_tasks",0,null,20).getAsJsonArray("chunks").size());
            assertEquals(0,page(journal,"retention_summaries",0,null,20).getAsJsonArray("chunks").size());
            assertEquals(0,page(journal,"retention_runs",0,null,20).getAsJsonArray("chunks").size());
            new Wire().validate("JournalMaintenancePayload",payload(first(journal,"retired_tasks")));
        }
    }
    @Test void nativeHistoryRejectsUnknownMaintenanceTablesAndOversizedRawRecords()throws Exception {
        seedAndRetire();try(LocalJournal journal=new LocalJournal(root)) {
            assertThrows(Json.Rejected.class,()->page(journal,"journal_summaries",0,null,20));
            write("UPDATE journal_summaries SET value=json_set(value,'$.kind',?)","x".repeat(Wire.MAX_BYTES));
            String before=dump();assertThrows(Json.Rejected.class,()->page(journal,"retention_summaries",0,null,20));assertEquals(before,dump());
        }
    }
}

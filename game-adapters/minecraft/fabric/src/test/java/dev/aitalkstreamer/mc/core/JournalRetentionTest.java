package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import org.junit.jupiter.api.function.Executable;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.sql.*;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.TimeUnit;
import static org.junit.jupiter.api.Assertions.*;
import static dev.aitalkstreamer.mc.core.Json.*;

class JournalRetentionTest {
    @TempDir Path root;
    private final long now=System.currentTimeMillis(),old=now-45*JournalRetention.DAY;
    private Connection sql()throws SQLException{return DriverManager.getConnection("jdbc:sqlite:"+root.resolve("mc-control.sqlite3"));}
    private void write(String query,Object...args)throws SQLException{try(Connection db=sql();PreparedStatement q=db.prepareStatement(query)){for(int i=0;i<args.length;i++)q.setObject(i+1,args[i]);q.executeUpdate();}}
    private long count(String query)throws SQLException{try(Connection db=sql();Statement q=db.createStatement();ResultSet rows=q.executeQuery(query)){assertTrue(rows.next());return rows.getLong(1);}}
    private JsonObject task(LocalJournal journal,String id,String state,long version,String effect) {
        String time=Instant.ofEpochMilli(old).toString();
        return obj("task_id",id,"request_id","req-"+id,"game_instance_id",journal.instance(),"bridge_boot_id","old-boot","world_id","stable-world","world_session_id","old-world",
            "state",state,"version",version,"effect_status",effect,"created_at",time,"updated_at",time,"control_epoch",4,"goal",obj("skill","gather","item_id","minecraft:oak_log","count",2));
    }
    private void seed()throws Exception {
        try(LocalJournal journal=new LocalJournal(root)) {
            journal.activateContext("old-boot","old-world");
            JsonObject request=obj("request_id","req-task-one","goal",obj("skill","gather","count",2));
            journal.accept("old-world",request,task(journal,"task-one","accepted",1,"none"),"old-boot");
            journal.update(task(journal,"task-one","running",2,"unknown"),"old-boot");
            journal.update(task(journal,"task-one","succeeded",3,"verified"),"old-boot");
            journal.reliable("game_event","old-boot","old-world",obj("event_id","old-event","kind","inventory_changed","occurred_at",Instant.ofEpochMilli(old).toString(),"data",obj("text","PRIVATE ORIGINAL EVENT")));
            journal.ack("old-boot","old-world","events",1);journal.ack("old-boot","old-world","task_transitions",3);
            journal.activateContext("current-boot","current-world");
        }
        write("UPDATE reliable SET created_at=?,acked_at=CASE WHEN acked_at IS NULL THEN NULL ELSE ? END",old,old);
        write("UPDATE task_transitions SET recorded_at=?",old);write("UPDATE contexts SET closed_at=? WHERE boot='old-boot'",old);
    }
    private JsonObject plan(LocalJournal journal)throws Exception{return journal.retentionPlan(now,Set.of());}
    private JsonObject apply(LocalJournal journal,JsonObject plan)throws Exception{return journal.applyRetention(plan,hash(canonical(plan)));}
    private void code(String code,Executable executable){assertEquals(code,assertThrows(Json.Rejected.class,executable).code);}
    private long backups()throws IOException{Path directory=root.resolve("backups");if(!Files.exists(directory))return 0;try(var paths=Files.list(directory)){return paths.filter(p->p.toString().endsWith(".sqlite3")).count();}}
    private String data()throws SQLException {
        JsonObject result=new JsonObject();try(Connection db=sql()) {
            for(String table:List.of("metadata","tasks","task_transitions","contexts","streams","reliable","journal_retired_tasks","journal_summaries","journal_retention_runs")) {
                JsonArray values=new JsonArray();try(Statement q=db.createStatement();ResultSet rows=q.executeQuery("SELECT rowid,* FROM "+table+" ORDER BY rowid")) {
                    while(rows.next()){JsonArray row=new JsonArray();for(int i=1;i<=rows.getMetaData().getColumnCount();i++)row.add(rows.getString(i));values.add(row);}
                }result.add(table,values);
            }
        }return canonical(result);
    }
    private void schema2Fixture()throws Exception {
        write("DROP TABLE journal_retired_tasks");write("DROP TABLE journal_summaries");write("DROP TABLE journal_retention_runs");
        write("DELETE FROM metadata WHERE key IN ('history_reliable_highwater','history_tasks_highwater','retention_generation')");write("PRAGMA user_version=2");
    }
    private String fileHash(Path file)throws Exception{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(file)));}
    @Test void previewPreservesEveryBusinessRowAndDoesNotCreateBackup()throws Exception {
        seed();String before=data();try(LocalJournal journal=LocalJournal.openForMaintenance(root)) {
            JsonObject plan=plan(journal);assertEquals(1,num(plan.getAsJsonObject("counts"),"events"));assertEquals(1,num(plan.getAsJsonObject("counts"),"tasks"));
            assertEquals(3,num(plan.getAsJsonObject("counts"),"task_versions"));assertEquals(3,num(plan.getAsJsonObject("counts"),"task_deliveries"));
            assertEquals(before,data());assertEquals(0,backups());
        }
    }
    @Test void maintenanceOpenDoesNotConvertAnUnfinishedTaskIntoRestartFailure()throws Exception {
        seed();write("UPDATE tasks SET state='running',task=json_set(task,'$.state','running','$.effect_status','unknown')");String before=data();
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)){assertEquals(0,num(plan(journal).getAsJsonObject("counts"),"tasks"));assertEquals(before,data());}
    }
    @Test void existingBridgeOwnerExcludesBothPreviewAndApply()throws Exception {
        seed();try(LocalJournal journal=new LocalJournal(root)){assertEquals("GAME_LOCAL_STORE_BUSY",assertThrows(IOException.class,()->LocalJournal.openForMaintenance(root)).getMessage());assertEquals("GAME_LOCAL_STORE_BUSY",assertThrows(IOException.class,()->JournalMaintenanceCli.run("--directory",root.toString(),"--action","preview")).getMessage());}
    }
    @Test void missingAndUnversionedLedgersCannotBeInitializedByMaintenance()throws Exception {
        Path missing=root.resolve("missing");code("GAME_JOURNAL_MISSING",()->LocalJournal.openForMaintenance(missing));assertFalse(Files.exists(missing));
        Files.createFile(root.resolve("mc-control.sqlite3"));code("GAME_JOURNAL_UNVERSIONED",()->LocalJournal.openForMaintenance(root));assertEquals(0,count("SELECT count(*) FROM sqlite_master"));
    }
    @Test void ordinaryBridgeHandleCannotRunMaintenance()throws Exception {
        seed();try(LocalJournal journal=new LocalJournal(root)){code("GAME_JOURNAL_OFFLINE_REQUIRED",()->plan(journal));code("GAME_JOURNAL_OFFLINE_REQUIRED",journal::retentionStatus);}
    }
    @Test void eligibleDataIsBackedUpSummarizedAndRetiredInOneCommit()throws Exception {
        seed();try(LocalJournal journal=LocalJournal.openForMaintenance(root)) {
            JsonObject result=apply(journal,plan(journal));assertEquals(1,num(result,"generation"));assertTrue(result.get("originals_in_backup").getAsBoolean());
            assertEquals(0,count("SELECT count(*) FROM tasks"));assertEquals(0,count("SELECT count(*) FROM reliable"));assertEquals(0,count("SELECT count(*) FROM task_transitions"));
            assertEquals(1,count("SELECT count(*) FROM journal_retired_tasks"));assertEquals(2,count("SELECT sum(json_extract(value,'$.count')) FROM journal_summaries"));
            assertFalse(data().contains("PRIVATE ORIGINAL EVENT"));
            try(Connection backup=DriverManager.getConnection("jdbc:sqlite:"+root.resolve("backups").resolve(str(result,"backup_file")));Statement q=backup.createStatement();ResultSet rows=q.executeQuery("SELECT count(*) FROM reliable")){assertTrue(rows.next());assertEquals(4,rows.getInt(1));}
        }
    }
    @Test void retiredRequestAndTaskIdCannotBeReacceptedAfterRestart()throws Exception {
        seed();try(LocalJournal journal=LocalJournal.openForMaintenance(root)){apply(journal,plan(journal));}
        try(LocalJournal journal=new LocalJournal(root)) {
            code("GAME_TASK_HISTORY_EXPIRED",()->journal.find("old-world","req-task-one"));
            code("GAME_TASK_HISTORY_EXPIRED",()->journal.accept("old-world",obj("request_id","req-task-one"),task(journal,"another-id","accepted",1,"none")));
            JsonObject replacement=task(journal,"task-one","accepted",1,"none");replacement.addProperty("request_id","new-request");
            code("GAME_TASK_HISTORY_EXPIRED",()->journal.accept("old-world",obj("request_id","new-request"),replacement));
            assertEquals("missing",str(journal.lookup(GSON.toJsonTree(List.of("task-one")).getAsJsonArray()).get(0).getAsJsonObject(),"status"));
            assertEquals(0,count("SELECT count(*) FROM tasks"));
        }
    }
    @Test void unknownEffectsKeepAllTaskVersionsAndDependentEvents()throws Exception {
        seed();write("UPDATE tasks SET task=json_set(task,'$.effect_status','unknown')");
        write("UPDATE reliable SET payload=json_set(payload,'$.data.task_id','task-one') WHERE type='game_event'");
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)){JsonObject plan=plan(journal);assertEquals(0,num(plan.getAsJsonObject("counts"),"tasks"));assertEquals(0,num(plan.getAsJsonObject("counts"),"events"));assertEquals(3,count("SELECT count(*) FROM task_transitions"));}
    }
    @Test void explicitDependenciesProtectTaskAndItsRelatedEvent()throws Exception {
        seed();write("UPDATE reliable SET payload=json_set(payload,'$.data.task_id','task-one') WHERE type='game_event'");
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)){JsonObject plan=journal.retentionPlan(now,Set.of("task-one"));assertEquals(0,num(plan.getAsJsonObject("counts"),"tasks"));assertEquals(0,num(plan.getAsJsonObject("counts"),"events"));}
    }
    @Test void recentEventReferenceProtectsAnOldTerminalTask()throws Exception {
        seed();write("UPDATE reliable SET created_at=?,payload=json_set(payload,'$.data.task_id','task-one') WHERE type='game_event'",now);
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)){assertEquals(0,num(plan(journal).getAsJsonObject("counts"),"tasks"));}
    }
    @Test void unacknowledgedIncludingArchivedDeliveryNeverExpires()throws Exception {
        seed();write("UPDATE reliable SET acked_at=NULL,archived_at=?",old);
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)){JsonObject plan=plan(journal);assertEquals(0,num(plan.getAsJsonObject("counts"),"tasks"));assertEquals(0,num(plan.getAsJsonObject("counts"),"events"));}
    }
    @Test void currentAndUnclosedContextsAreProtected()throws Exception {
        seed();write("UPDATE metadata SET value='old-boot' WHERE key='active_boot'");write("UPDATE metadata SET value='old-world' WHERE key='active_world'");
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)){assertEquals(0,num(plan(journal).getAsJsonObject("counts"),"tasks"));assertEquals(0,num(plan(journal).getAsJsonObject("counts"),"events"));}
        write("UPDATE metadata SET value='' WHERE key IN ('active_boot','active_world')");write("UPDATE contexts SET closed_at=NULL WHERE boot='old-boot'");
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)){assertEquals(0,num(plan(journal).getAsJsonObject("counts"),"tasks"));assertEquals(0,num(plan(journal).getAsJsonObject("counts"),"events"));}
    }
    @Test void recentVersionOrDeliveryAcknowledgementProtectsTheWholeTask()throws Exception {
        seed();write("UPDATE task_transitions SET recorded_at=? WHERE version=2",now);
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)){assertEquals(0,num(plan(journal).getAsJsonObject("counts"),"tasks"));}
        write("UPDATE task_transitions SET recorded_at=?",old);write("UPDATE reliable SET acked_at=? WHERE type='task_update' AND delivery_seq=1",now);
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)){assertEquals(0,num(plan(journal).getAsJsonObject("counts"),"tasks"));}
    }
    @Test void malformedLegacyDatesAndUnboundPayloadsArePreserved()throws Exception {
        seed();write("UPDATE tasks SET task=json_remove(task,'$.updated_at')");write("UPDATE reliable SET payload=json_remove(payload,'$.occurred_at') WHERE type='game_event'");
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)){assertEquals(0,num(plan(journal).getAsJsonObject("counts"),"tasks"));assertEquals(0,num(plan(journal).getAsJsonObject("counts"),"events"));}
        write("UPDATE reliable SET payload='{}' WHERE type='task_update'");
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)){assertTrue(num(plan(journal).getAsJsonObject("protected"),"unreadable_dependency_payload")>0);}
    }
    @Test void exactCutoffAndZeroTimestampsAreKept()throws Exception {
        seed();write("UPDATE reliable SET created_at=? WHERE type='game_event'",now-7*JournalRetention.DAY);
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)){assertEquals(0,num(plan(journal).getAsJsonObject("counts"),"events"));}
        write("UPDATE reliable SET created_at=0 WHERE type='game_event'");
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)){assertEquals(0,num(plan(journal).getAsJsonObject("counts"),"events"));}
    }
    @Test void sourceChangesInvalidateReviewEvenWhenRowCountsAreUnchanged()throws Exception {
        seed();try(LocalJournal journal=LocalJournal.openForMaintenance(root)){JsonObject plan=plan(journal);write("UPDATE reliable SET payload=json_set(payload,'$.data.text','changed') WHERE type='game_event'");String before=data();code("GAME_RETENTION_PLAN_CHANGED",()->apply(journal,plan));assertEquals(before,data());assertEquals(0,backups());}
    }
    @Test void tamperedSelectionAndWrongReviewHashCannotAuthorizeDeletion()throws Exception {
        seed();try(LocalJournal journal=LocalJournal.openForMaintenance(root)){JsonObject plan=plan(journal);code("GAME_RETENTION_PLAN_HASH",()->journal.applyRetention(plan,"0".repeat(64)));plan.getAsJsonArray("events").add(900);code("GAME_RETENTION_PLAN_CHANGED",()->apply(journal,plan));assertEquals(4,count("SELECT count(*) FROM reliable"));assertEquals(0,backups());}
    }
    @Test void expiredPlansAndFutureClocksAreRejected()throws Exception {
        seed();try(LocalJournal journal=LocalJournal.openForMaintenance(root)){JsonObject expired=journal.retentionPlan(now-JournalRetention.PLAN_TTL-1000,Set.of());code("GAME_RETENTION_PLAN_EXPIRED",()->apply(journal,expired));code("GAME_RETENTION_CLOCK",()->journal.retentionPlan(System.currentTimeMillis()+60000,Set.of()));}
    }
    @Test void backupLimitRefusesApplyWithoutChangingAnyRow()throws Exception {
        seed();Files.createDirectories(root.resolve("backups"));for(int i=0;i<8;i++)Files.write(root.resolve("backups/retained-"+i+".sqlite3"),new byte[]{1});
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)){JsonObject plan=plan(journal);String before=data();code("GAME_LOCAL_BACKUP_LIMIT",()->apply(journal,plan));assertEquals(before,data());}
    }
    @Test void sqlFailureRollsBackSummariesTombstonesAndAllDeletions()throws Exception {
        seed();write("CREATE TRIGGER retention_fixture_failure BEFORE DELETE ON tasks BEGIN SELECT RAISE(ABORT,'fixture injected failure'); END");
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)){JsonObject plan=plan(journal);String before=data();assertThrows(IOException.class,()->apply(journal,plan));assertEquals(before,data());assertEquals(1,backups());}
    }
    @Test void retryAfterProcessReopenReturnsTheOriginalReceiptWithoutAnotherBackup()throws Exception {
        seed();JsonObject plan,result;try(LocalJournal journal=LocalJournal.openForMaintenance(root)){plan=plan(journal);result=apply(journal,plan);}
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)){assertEquals(result,apply(journal,plan));assertEquals(1,backups());assertEquals(1,count("SELECT count(*) FROM journal_retention_runs"));}
    }
    @Test void futureHistoryIdsRemainMonotonicAfterDeletingEveryRow()throws Exception {
        seed();try(LocalJournal journal=LocalJournal.openForMaintenance(root)){apply(journal,plan(journal));}
        try(LocalJournal journal=new LocalJournal(root)) {
            journal.reliable("game_event","current-boot","current-world",obj("event_id","new"));
            JsonObject next=task(journal,"new-task","succeeded",1,"verified");journal.accept("old-world",obj("request_id","req-new-task"),next);
            assertTrue(count("SELECT rowid FROM reliable")>4);assertTrue(count("SELECT rowid FROM task_transitions")>3);
        }
    }
    @Test void schemaTwoMigrationCreatesVerifiableOriginalBackupAndKeepsIdentity()throws Exception {
        seed();String instance;try(LocalJournal journal=LocalJournal.openForMaintenance(root)){instance=journal.instance();}schema2Fixture();
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)){assertEquals(instance,journal.instance());assertEquals(3,count("PRAGMA user_version"));assertEquals(4,count("SELECT count(*) FROM reliable"));assertEquals(1,backups());}
        Path backup;try(var paths=Files.list(root.resolve("backups"))){backup=paths.filter(p->p.getFileName().toString().startsWith("schema-v2-")&&p.toString().endsWith(".sqlite3")).findFirst().orElseThrow();}
        JsonObject receipt=JsonParser.parseString(Files.readString(backup.resolveSibling(backup.getFileName()+".json"))).getAsJsonObject();assertEquals(2,num(receipt,"schema_version"));assertEquals(fileHash(backup),str(receipt,"sha256"));
        try(Connection db=DriverManager.getConnection("jdbc:sqlite:"+backup);Statement q=db.createStatement();ResultSet rows=q.executeQuery("PRAGMA user_version")){assertTrue(rows.next());assertEquals(2,rows.getInt(1));}
    }
    @Test void backupBeforeTaskCreationCannotEraseRetiredRequestProtection()throws Exception {
        Path empty;try(LocalJournal journal=new LocalJournal(root)){empty=journal.backup();}seed();
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)){apply(journal,plan(journal));}
        LocalJournal.restore(root,empty.getFileName().toString());
        try(LocalJournal journal=new LocalJournal(root)){code("GAME_TASK_HISTORY_EXPIRED",()->journal.find("old-world","req-task-one"));assertEquals(1,count("SELECT count(*) FROM journal_retired_tasks"));}
    }
    @Test void preRetirementBackupDoesNotResurrectItsFullTaskOrDelivery()throws Exception {
        seed();Path snapshot;try(LocalJournal journal=LocalJournal.openForMaintenance(root)){snapshot=journal.backup();apply(journal,plan(journal));}
        LocalJournal.restore(root,snapshot.getFileName().toString());
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)){assertEquals(0,count("SELECT count(*) FROM tasks"));assertEquals(0,count("SELECT count(*) FROM task_transitions"));assertEquals(0,count("SELECT count(*) FROM reliable WHERE type='task_update'"));assertEquals(1,count("SELECT count(*) FROM journal_retired_tasks"));assertEquals(1,count("SELECT count(*) FROM reliable WHERE type='game_event'"));}
    }
    @Test void conflictingRestoreRollsBackToThePreRestoreDatabase()throws Exception {
        seed();Path snapshot;try(LocalJournal journal=LocalJournal.openForMaintenance(root)){snapshot=journal.backup();apply(journal,plan(journal));}
        try(Connection db=DriverManager.getConnection("jdbc:sqlite:"+snapshot);Statement q=db.createStatement()){q.executeUpdate("UPDATE tasks SET body_hash='different'");}
        Path receiptFile=snapshot.resolveSibling(snapshot.getFileName()+".json");JsonObject receipt=JsonParser.parseString(Files.readString(receiptFile)).getAsJsonObject();receipt.addProperty("sha256",fileHash(snapshot));receipt.addProperty("bytes",Files.size(snapshot));Files.writeString(receiptFile,GSON.toJson(receipt));
        String before=data();code("GAME_RETENTION_RESTORE_CONFLICT",()->LocalJournal.restore(root,snapshot.getFileName().toString()));assertEquals(before,data());
    }
    @Test void dependencyAndRunLimitsRefuseInsteadOfDiscardingProof()throws Exception {
        seed();try(LocalJournal journal=LocalJournal.openForMaintenance(root)) {
            Set<String> tooMany=new HashSet<>();for(int i=0;i<=JournalRetention.PROTECTED_LIMIT;i++)tooMany.add("task-"+i);code("GAME_RETENTION_DEPENDENCY_LIMIT",()->journal.retentionPlan(now,tooMany));
            try(Connection db=sql();PreparedStatement q=db.prepareStatement("INSERT INTO journal_retention_runs VALUES(?,?,'{}')")){db.setAutoCommit(false);for(int i=0;i<JournalRetention.RUN_LIMIT;i++){q.setString(1,"run-"+i);q.setString(2,"hash-"+i);q.addBatch();}q.executeBatch();db.commit();}
            code("GAME_RETENTION_RUN_LIMIT",()->plan(journal));assertEquals(1,count("SELECT count(*) FROM tasks"));
        }
    }
    @Test void cliPreviewApplyStatusAndSourceFileHashUseTheRealLedger()throws Exception {
        seed();JsonObject preview=JournalMaintenanceCli.run("--directory",root.toString(),"--action","preview");assertFalse(preview.get("applied").getAsBoolean());
        code("GAME_RETENTION_PLAN_HASH",()->JournalMaintenanceCli.run("--directory",root.toString(),"--action","apply","--plan",str(preview,"plan_file"),"--sha256","0".repeat(64)));
        JsonObject result=JournalMaintenanceCli.run("--directory",root.toString(),"--action","apply","--plan",str(preview,"plan_file"),"--sha256",str(preview,"plan_sha256"));assertEquals(1,num(result,"generation"));
        JsonObject status=JournalMaintenanceCli.run("--directory",root.toString(),"--action","status");assertEquals(1,num(status,"retired_tasks"));assertEquals(2,num(status,"summary_groups"));
        code("GAME_RETENTION_ARGUMENTS",()->JournalMaintenanceCli.run("--directory",root.toString(),"--action","apply","--plan","../outside.json","--sha256","0".repeat(64)));
    }
    @Test void cliProtectionFileMustMatchThisInstallationAndKeepsItsTask()throws Exception {
        seed();Path file=root.resolve("dependencies.json");String instance;try(LocalJournal journal=LocalJournal.openForMaintenance(root)){instance=journal.instance();}
        Files.writeString(file,GSON.toJson(obj("game_instance_id",instance,"task_ids",List.of("task-one"))));
        JsonObject preview=JournalMaintenanceCli.run("--directory",root.toString(),"--action","preview","--protect",file.toString());assertEquals(0,num(preview.getAsJsonObject("counts"),"tasks"));
        Files.writeString(file,GSON.toJson(obj("game_instance_id","mc-another-install","task_ids",List.of())));
        code("GAME_RETENTION_DEPENDENCY_INSTANCE",()->JournalMaintenanceCli.run("--directory",root.toString(),"--action","preview","--protect",file.toString()));
    }
    @Test void cliPlanFileBudgetIsBoundedAndNeverDeletesOlderPlans()throws Exception {
        seed();Path directory=root.resolve("maintenance");Files.createDirectories(directory);for(int i=0;i<JournalMaintenanceCli.PLAN_FILES;i++)Files.writeString(directory.resolve("kept-"+i+".json"),"{}");
        code("GAME_RETENTION_PLAN_FILE_LIMIT",()->JournalMaintenanceCli.run("--directory",root.toString(),"--action","preview"));try(var files=Files.list(directory)){assertEquals(JournalMaintenanceCli.PLAN_FILES,files.count());}
    }
    @Test void databaseStructureChangesAlsoInvalidateTheReviewedPlan()throws Exception {
        seed();try(LocalJournal journal=LocalJournal.openForMaintenance(root)){JsonObject plan=plan(journal);write("CREATE INDEX fixture_added_after_review ON tasks(state)");code("GAME_RETENTION_PLAN_CHANGED",()->apply(journal,plan));assertEquals(0,backups());}
    }
    @Test void emptyPlansDoNotConsumeBackupOrRunCapacity()throws Exception {
        seed();write("UPDATE reliable SET acked_at=NULL");try(LocalJournal journal=LocalJournal.openForMaintenance(root)){JsonObject plan=plan(journal);code("GAME_RETENTION_NOTHING_TO_APPLY",()->apply(journal,plan));assertEquals(0,backups());assertEquals(0,count("SELECT count(*) FROM journal_retention_runs"));}
    }
    @Test void tombstoneCapacityProtectsExistingProofAndLeavesTheTaskIntact()throws Exception {
        seed();try(Connection db=sql();PreparedStatement q=db.prepareStatement("INSERT INTO journal_retired_tasks VALUES('retired-world',?,?,?,1,'{}')")) {
            db.setAutoCommit(false);for(int i=0;i<JournalRetention.TOMBSTONE_LIMIT;i++){q.setString(1,"request-"+i);q.setString(2,"retired-"+i);q.setString(3,"0".repeat(64));q.addBatch();if(i%1000==999)q.executeBatch();}db.commit();
        }
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)){code("GAME_RETENTION_TOMBSTONE_LIMIT",()->plan(journal));assertEquals(1,count("SELECT count(*) FROM tasks"));assertEquals(JournalRetention.TOMBSTONE_LIMIT,count("SELECT count(*) FROM journal_retired_tasks"));}
    }
    @Test void summaryCapacityRefusesNewGroupsWithoutDroppingOlderSummaries()throws Exception {
        seed();try(Connection db=sql();PreparedStatement q=db.prepareStatement("INSERT INTO journal_summaries VALUES(?,'{}')")) {
            db.setAutoCommit(false);for(int i=0;i<JournalRetention.SUMMARY_LIMIT;i++){q.setString(1,"kept-"+i);q.addBatch();}q.executeBatch();db.commit();
        }
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)){code("GAME_RETENTION_SUMMARY_LIMIT",()->plan(journal));assertEquals(JournalRetention.SUMMARY_LIMIT,count("SELECT count(*) FROM journal_summaries"));assertEquals(4,count("SELECT count(*) FROM reliable"));}
    }
    @Test void schemaTwoMigrationRefusesWhenItsRequiredBackupCannotBeRetained()throws Exception {
        seed();schema2Fixture();Files.createDirectories(root.resolve("backups"));for(int i=0;i<8;i++)Files.write(root.resolve("backups/kept-"+i+".sqlite3"),new byte[]{1});
        code("GAME_LOCAL_BACKUP_LIMIT",()->LocalJournal.openForMaintenance(root));assertEquals(2,count("PRAGMA user_version"));assertEquals(1,count("SELECT count(*) FROM tasks"));assertEquals(0,count("SELECT count(*) FROM sqlite_master WHERE name='journal_retired_tasks'"));
    }
    @Test void schemaTwoBackupRestoreKeepsLaterRetiredRequestsAndUpgradesAtomically()throws Exception {
        seed();schema2Fixture();try(LocalJournal journal=LocalJournal.openForMaintenance(root)){apply(journal,plan(journal));}
        Path source;try(var paths=Files.list(root.resolve("backups"))){source=paths.filter(p->p.getFileName().toString().startsWith("schema-v2-")&&p.toString().endsWith(".sqlite3")).findFirst().orElseThrow();}
        LocalJournal.restore(root,source.getFileName().toString());assertEquals(3,count("PRAGMA user_version"));assertEquals(0,count("SELECT count(*) FROM tasks"));assertEquals(1,count("SELECT count(*) FROM journal_retired_tasks"));
        try(LocalJournal journal=new LocalJournal(root)){code("GAME_TASK_HISTORY_EXPIRED",()->journal.find("old-world","req-task-one"));}
    }
    @Test void cliRestoreChecksTheReviewedBackupHashBeforeAnyReplacement()throws Exception {
        seed();Path source;try(LocalJournal journal=LocalJournal.openForMaintenance(root)){source=journal.backup();apply(journal,plan(journal));}
        String before=data();code("GAME_LOCAL_BACKUP_MISMATCH",()->JournalMaintenanceCli.run("--directory",root.toString(),"--action","restore","--backup",source.getFileName().toString(),"--sha256","0".repeat(64)));assertEquals(before,data());
        JsonObject result=JournalMaintenanceCli.run("--directory",root.toString(),"--action","restore","--backup",source.getFileName().toString(),"--sha256",fileHash(source));assertTrue(result.get("restored").getAsBoolean());assertFalse(result.get("auto_granted").getAsBoolean());assertEquals(1,count("SELECT count(*) FROM journal_retired_tasks"));
    }
    @Test void nativeCliProcessLoadsOnlyTheJournalAndReleasesItsOwner()throws Exception {
        seed();List<String> paths=new ArrayList<>();for(Class<?> type:List.of(LocalJournal.class,JsonObject.class,org.sqlite.JDBC.class,org.slf4j.LoggerFactory.class))paths.add(Path.of(type.getProtectionDomain().getCodeSource().getLocation().toURI()).toString());
        Path nativeDir=root.resolve("child-native");Files.createDirectories(nativeDir);Path java=Path.of(System.getProperty("java.home"),"bin","java.exe");
        Process process=new ProcessBuilder(java.toString(),"-Xmx256m","-Dorg.sqlite.tmpdir="+nativeDir,"-cp",String.join(File.pathSeparator,paths),JournalMaintenanceCli.class.getName(),"--directory",root.toString(),"--action","status").redirectError(root.resolve("cli-stderr.log").toFile()).start();
        try {assertTrue(process.waitFor(20,TimeUnit.SECONDS));assertEquals(0,process.exitValue(),Files.readString(root.resolve("cli-stderr.log")));JsonObject status=JsonParser.parseString(new String(process.getInputStream().readAllBytes(),StandardCharsets.UTF_8)).getAsJsonObject();assertEquals(3,num(status,"schema_version"));assertEquals(1,num(status,"tasks"));}
        finally{if(process.isAlive()){process.destroyForcibly();assertTrue(process.waitFor(10,TimeUnit.SECONDS));}}
        try(LocalJournal ignored=LocalJournal.openForMaintenance(root)){assertEquals(1,count("SELECT count(*) FROM tasks"));}
    }
}

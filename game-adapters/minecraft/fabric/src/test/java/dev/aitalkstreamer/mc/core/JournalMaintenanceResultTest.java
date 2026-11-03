package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import org.junit.jupiter.api.*;
import org.junit.jupiter.api.io.TempDir;
import java.nio.file.*;
import java.security.MessageDigest;
import java.sql.*;
import java.util.*;
import static org.junit.jupiter.api.Assertions.*;
import static dev.aitalkstreamer.mc.core.Json.*;

class JournalMaintenanceResultTest {
    @TempDir Path root;
    private String fileHash(Path file)throws Exception {
        byte[] value=MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(file));return HexFormat.of().formatHex(value);
    }
    private JsonObject preview()throws Exception {MaintenanceCoordinatorFixture.seed(root);return JournalMaintenanceCli.run("--directory",root.toString(),"--action","preview");}
    private JsonObject call(String action,JsonObject plan)throws Exception {return JournalMaintenanceCli.run("--directory",root.toString(),"--action",action,"--plan",str(plan,"plan_file"),"--sha256",str(plan,"plan_sha256"));}
    private long count(String sql)throws Exception {try(Connection db=DriverManager.getConnection("jdbc:sqlite:"+root.resolve("mc-control.sqlite3"));Statement q=db.createStatement();ResultSet rows=q.executeQuery(sql)){assertTrue(rows.next());return rows.getLong(1);}}
    private JsonObject rewrite(JsonObject preview,java.util.function.Consumer<JsonObject> change)throws Exception {
        Path file=root.resolve("maintenance").resolve(str(preview,"plan_file"));JsonObject plan=JsonParser.parseString(Files.readString(file)).getAsJsonObject();change.accept(plan);
        Files.writeString(file,canonical(plan)+"\n");JsonObject updated=preview.deepCopy();updated.addProperty("plan_sha256",fileHash(file));return updated;
    }
    @Test void missingRunIsAnObservationAndDoesNotApplyThePlan()throws Exception {
        JsonObject plan=preview(),result=call("result",plan);assertFalse(result.get("found").getAsBoolean());assertTrue(result.get("result").isJsonNull());
        assertFalse(result.get("apply_command_dispatched").getAsBoolean());assertEquals(2,count("SELECT count(*) FROM tasks"));assertEquals(0,count("SELECT count(*) FROM journal_retention_runs"));
        assertFalse(Files.exists(root.resolve("backups")));assertEquals(str(plan,"game_instance_id"),str(result,"game_instance_id"));
    }
    @Test void committedRunIsReadBackWithoutAnotherBackupOrCommit()throws Exception {
        JsonObject plan=preview(),applied=call("apply",plan),result=call("result",plan);assertEquals(applied,result.getAsJsonObject("result"));assertTrue(result.get("found").getAsBoolean());
        assertEquals(result,withoutObserved(call("result",plan),result));assertEquals(1,count("SELECT count(*) FROM journal_retention_runs"));
        try(var paths=Files.list(root.resolve("backups"))){assertEquals(1,paths.filter(p->p.toString().endsWith(".sqlite3")).count());}
        assertEquals(str(plan,"game_instance_id"),str(JournalMaintenanceCli.run("--directory",root.toString(),"--action","status"),"game_instance_id"));
    }
    private JsonObject withoutObserved(JsonObject actual,JsonObject expected){actual.add("observed_at",expected.get("observed_at"));return actual;}
    @Test void foreignInstanceCannotObserveAnUnrelatedRun()throws Exception {
        JsonObject plan=rewrite(preview(),value->value.addProperty("game_instance_id","different-instance"));
        assertEquals("GAME_RETENTION_DEPENDENCY_INSTANCE",assertThrows(Json.Rejected.class,()->call("result",plan)).code);assertEquals(2,count("SELECT count(*) FROM tasks"));
    }
    @Test void fileDigestMustMatchEvenForAReadOnlyResult()throws Exception {
        JsonObject plan=preview();plan.addProperty("plan_sha256","0".repeat(64));assertEquals("GAME_RETENTION_PLAN_HASH",assertThrows(Json.Rejected.class,()->call("result",plan)).code);
    }
    @Test void changedContentsCannotImpersonateAnAlreadyCommittedRun()throws Exception {
        JsonObject plan=preview();call("apply",plan);JsonObject changed=rewrite(plan,value->value.addProperty("created_at_ms",num(value,"created_at_ms")-1));
        assertEquals("GAME_RETENTION_RUN_CONFLICT",assertThrows(Json.Rejected.class,()->call("result",changed)).code);assertEquals(1,count("SELECT count(*) FROM journal_retention_runs"));
    }
    @Test void liveBridgeOwnerExcludesResultLookup()throws Exception {
        JsonObject plan=preview();try(LocalJournal owner=new LocalJournal(root)){assertEquals("GAME_LOCAL_STORE_BUSY",assertThrows(java.io.IOException.class,()->call("result",plan)).getMessage());}
    }
    @Test void ordinaryBridgeHandleCannotUseMaintenanceResult()throws Exception {
        JsonObject preview=preview();JsonObject plan=JsonParser.parseString(Files.readString(root.resolve("maintenance").resolve(str(preview,"plan_file")))).getAsJsonObject();
        try(LocalJournal ordinary=new LocalJournal(root)){assertEquals("GAME_JOURNAL_OFFLINE_REQUIRED",assertThrows(Json.Rejected.class,()->ordinary.retentionResult(plan,hash(canonical(plan)))).code);}
    }
}

package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.sql.*;
import java.time.Instant;
import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Synthetic journal for the Java/Node integration test. Never included in the mod. */
public final class MaintenanceHistoryFixture {
    private static JsonObject sample(String name)throws Exception {
        try(var input=MaintenanceHistoryFixture.class.getResourceAsStream("/mc-contracts/examples.json")) {
            for(var item:JsonParser.parseString(new String(input.readAllBytes(),StandardCharsets.UTF_8)).getAsJsonObject().getAsJsonArray("cases")) {
                JsonObject value=item.getAsJsonObject();if(str(value,"name").equals(name))return value.getAsJsonObject("value").deepCopy();
            }
        }throw new IllegalArgumentException("fixture example missing");
    }
    private static void write(Path root,String sql,Object...args)throws Exception {
        try(Connection db=DriverManager.getConnection("jdbc:sqlite:"+root.resolve("mc-control.sqlite3"));PreparedStatement q=db.prepareStatement(sql)) {
            for(int i=0;i<args.length;i++)q.setObject(i+1,args[i]);q.executeUpdate();
        }
    }
    public static void main(String[] args)throws Exception {
        Path root=Path.of(args[0]);String action=args[1];
        if(action.equals("restore")) {
            JsonObject result=JsonParser.parseString(Files.readString(root.resolve("fixture-retention-1.json"))).getAsJsonObject();
            Path backup=root.resolve("backups").resolve(str(result,"backup_file"));
            JsonObject receipt=JsonParser.parseString(Files.readString(backup.resolveSibling(backup.getFileName()+".json"))).getAsJsonObject();
            LocalJournal.restore(root,backup.getFileName().toString(),str(receipt,"sha256"));
            System.out.println(canonical(obj("restored",true,"fixture_only",true)));return;
        }
        require(Set.of("1","2").contains(action),"GAME_FIXTURE_ARGUMENTS");
        long now=System.currentTimeMillis();Path timeFile=root.resolve("fixture-history-time.txt");
        Files.createDirectories(root);
        if(action.equals("1"))Files.writeString(timeFile,Long.toString(now-45*JournalRetention.DAY),StandardOpenOption.CREATE_NEW);
        long old=Long.parseLong(Files.readString(timeFile));
        // Both rounds deliberately share the same historical UTC group.
        String oldTime=Instant.ofEpochMilli(old).toString(),world="old-maintenance-world",boot="old-maintenance-boot-"+action;
        try(LocalJournal journal=new LocalJournal(root)) {
            journal.activateContext(boot,world);
            JsonObject task=sample("task-complete");
            task.addProperty("task_id","retired-fixture-"+action);task.addProperty("request_id","retired-fixture-request-"+action);
            task.addProperty("game_instance_id",journal.instance());task.addProperty("bridge_boot_id",boot);
            task.addProperty("world_id","stable-maintenance-world");task.addProperty("world_session_id",world);
            task.addProperty("created_at",oldTime);task.addProperty("updated_at",oldTime);
            for(var evidence:task.getAsJsonArray("evidence"))evidence.getAsJsonObject().addProperty("world_session_id",world);
            new Wire().validate("Task",task);
            journal.accept(world,obj("request_id",task.get("request_id")),task,boot);
            JsonObject event=sample("bridge-game_event").getAsJsonObject("payload");
            event.addProperty("event_id","historical-fixture-event-"+action);event.addProperty("world_session_id",world);event.addProperty("occurred_at",oldTime);
            new Wire().validate("HistoryEventPayload",event);
            journal.reliable("game_event",boot,world,event);
            journal.ack(boot,world,"events",1);journal.ack(boot,world,"task_transitions",1);
            journal.activateContext("maintenance-fixture-current-"+action,"maintenance-fixture-current-world");
        }
        write(root,"UPDATE reliable SET created_at=?,acked_at=? WHERE world=?",old,old,world);
        write(root,"UPDATE task_transitions SET recorded_at=?",old);
        write(root,"UPDATE contexts SET closed_at=? WHERE boot=?",old,boot);
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)) {
            JsonObject plan=journal.retentionPlan(now,Set.of()),result=journal.applyRetention(plan,hash(canonical(plan)));
            Files.writeString(root.resolve("fixture-retention-"+action+".json"),canonical(result),StandardOpenOption.CREATE_NEW);
            System.out.println(canonical(result));
        }
    }
}

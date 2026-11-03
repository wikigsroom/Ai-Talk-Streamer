package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.sql.*;
import java.time.Instant;
import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Two old verified tasks, for native offline A/B coordination checks only. */
public final class MaintenanceCoordinatorFixture {
    private static JsonObject sample(String name)throws Exception {
        try(var input=MaintenanceCoordinatorFixture.class.getResourceAsStream("/mc-contracts/examples.json")) {
            for(var item:JsonParser.parseString(new String(input.readAllBytes(),StandardCharsets.UTF_8)).getAsJsonObject().getAsJsonArray("cases")) {
                JsonObject value=item.getAsJsonObject();if(str(value,"name").equals(name))return value.getAsJsonObject("value").deepCopy();
            }
        }throw new IllegalArgumentException("fixture example missing");
    }
    public static JsonObject seed(Path root)throws Exception {
        long old=System.currentTimeMillis()-45*JournalRetention.DAY;String time=Instant.ofEpochMilli(old).toString();
        String boot="coordinator-old-boot",world="coordinator-old-world",instance;
        try(LocalJournal journal=new LocalJournal(root)) {
            instance=journal.instance();journal.activateContext(boot,world);
            for(String id:List.of("task-protected","task-retirable")) {
                JsonObject task=sample("task-complete");task.addProperty("task_id",id);task.addProperty("request_id","request-"+id);
                task.addProperty("game_instance_id",instance);task.addProperty("bridge_boot_id",boot);task.addProperty("world_id","coordinator-world");
                task.addProperty("world_session_id",world);task.addProperty("created_at",time);task.addProperty("updated_at",time);
                for(var evidence:task.getAsJsonArray("evidence"))evidence.getAsJsonObject().addProperty("world_session_id",world);
                new Wire().validate("Task",task);journal.accept(world,obj("request_id",task.get("request_id")),task,boot);
                JsonObject event=sample("bridge-game_event").getAsJsonObject("payload");event.addProperty("event_id","event-"+id);
                event.addProperty("world_session_id",world);event.addProperty("occurred_at",time);event.getAsJsonObject("data").addProperty("task_id",id);
                journal.reliable("game_event",boot,world,event);
            }
            journal.ack(boot,world,"events",2);journal.ack(boot,world,"task_transitions",2);
            journal.activateContext("coordinator-current-boot","coordinator-current-world");
        }
        try(Connection db=DriverManager.getConnection("jdbc:sqlite:"+root.resolve("mc-control.sqlite3"))) {
            for(String sql:List.of("UPDATE reliable SET created_at=?,acked_at=?","UPDATE task_transitions SET recorded_at=?","UPDATE contexts SET closed_at=? WHERE boot='coordinator-old-boot'"))
                try(PreparedStatement q=db.prepareStatement(sql)){q.setLong(1,old);if(sql.contains("acked_at"))q.setLong(2,old);q.executeUpdate();}
        }
        return obj("game_instance_id",instance,"task_ids",List.of("task-protected","task-retirable"));
    }
    public static void main(String[] args)throws Exception {System.out.println(canonical(seed(Path.of(args[0]))));}
}

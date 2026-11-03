package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.*;
import java.time.Instant;
import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Offline, deterministic retention. Does not call a game port, model or memory writer. */
final class JournalRetention {
    static final long DAY = 86_400_000L, PLAN_TTL = 600_000L;
    static final int TOMBSTONE_LIMIT = 100_000, SUMMARY_LIMIT = 20_000, RUN_LIMIT = 512, PROTECTED_LIMIT = 20_000;
    private static final Set<String> TERMINAL = Set.of("succeeded", "failed", "cancelled", "rejected");
    private JournalRetention() {}
    private static PreparedStatement query(Connection db, String sql, Object... args) throws SQLException {
        PreparedStatement statement = db.prepareStatement(sql);
        try { for(int i=0;i<args.length;i++) statement.setObject(i+1,args[i]); return statement; }
        catch(SQLException error) { statement.close(); throw error; }
    }
    private static long count(Connection db, String sql, Object... args) throws SQLException {
        try(var q=query(db,sql,args);var rows=q.executeQuery()) { require(rows.next(),"GAME_RETENTION_DATABASE");return rows.getLong(1); }
    }
    private static String text(Connection db, String sql, Object... args) throws SQLException {
        try(var q=query(db,sql,args);var rows=q.executeQuery()) { return rows.next()?rows.getString(1):null; }
    }
    private static void write(Connection db,String sql,Object...args)throws SQLException {try(var q=query(db,sql,args)){q.executeUpdate();}}
    private static JsonObject parse(String raw) {return JsonParser.parseString(raw).getAsJsonObject();}
    static void createSchema(Connection db)throws SQLException {
        write(db,"CREATE TABLE journal_retired_tasks(world TEXT NOT NULL,request_id TEXT NOT NULL,task_id TEXT NOT NULL UNIQUE,body_hash TEXT NOT NULL,retired_at INTEGER NOT NULL,summary TEXT NOT NULL CHECK(json_valid(summary)),PRIMARY KEY(world,request_id))");
        write(db,"CREATE TABLE journal_summaries(summary_key TEXT PRIMARY KEY,value TEXT NOT NULL CHECK(json_valid(value)))");
        write(db,"CREATE TABLE journal_retention_runs(run_id TEXT PRIMARY KEY,plan_hash TEXT NOT NULL UNIQUE,result TEXT NOT NULL CHECK(json_valid(result)))");
        write(db,"INSERT INTO metadata VALUES('history_reliable_highwater',?),('history_tasks_highwater',?),('retention_generation','0')",
            Long.toString(count(db,"SELECT coalesce(max(rowid),0) FROM reliable")),Long.toString(count(db,"SELECT coalesce(max(rowid),0) FROM task_transitions")));
    }
    private static long timestamp(JsonObject value,String key) {
        try {return Instant.parse(str(value,key)).toEpochMilli();}catch(RuntimeException error){return -1;}
    }
    private static boolean aged(long time,long cutoff) {return time>0&&time<cutoff;}
    private static void protect(Map<String,Integer> counts,String reason) {counts.merge(reason,1,Integer::sum);}
    private static String context(String boot,String world) {return canonical(obj("boot",boot,"world",world));}
    private static Set<String> references(JsonElement value,Set<String> known) {
        Set<String> found=new HashSet<>();references(value,known,found,0);return found;
    }
    private static void references(JsonElement value,Set<String> known,Set<String> found,int depth) {
        require(depth<=32,"GAME_RETENTION_NESTING");
        if(value.isJsonObject())for(var entry:value.getAsJsonObject().entrySet())references(entry.getValue(),known,found,depth+1);
        else if(value.isJsonArray())for(var entry:value.getAsJsonArray())references(entry,known,found,depth+1);
        else if(value.isJsonPrimitive()&&value.getAsJsonPrimitive().isString()&&known.contains(value.getAsString()))found.add(value.getAsString());
    }
    private static String snapshot(Connection db)throws SQLException {
        try {
            MessageDigest digest=MessageDigest.getInstance("SHA-256");
            try(var q=query(db,"SELECT type,name,tbl_name,coalesce(sql,'') FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY name");var rows=q.executeQuery()) {
                while(rows.next())for(int i=1;i<=4;i++){byte[] bytes=rows.getString(i).getBytes(StandardCharsets.UTF_8);digest.update((bytes.length+":").getBytes(StandardCharsets.UTF_8));digest.update(bytes);}
            }
            for(String table:List.of("metadata","worlds","tasks","task_transitions","contexts","streams","reliable","journal_retired_tasks","journal_summaries","journal_retention_runs")) {
                digest.update((table+"\n").getBytes(StandardCharsets.UTF_8));
                try(var q=query(db,"SELECT rowid,* FROM "+table+" ORDER BY rowid");var rows=q.executeQuery()) {
                    int columns=rows.getMetaData().getColumnCount();
                    while(rows.next())for(int i=1;i<=columns;i++) {
                        String value=rows.getString(i);byte[] bytes=value==null?new byte[0]:value.getBytes(StandardCharsets.UTF_8);
                        digest.update((value==null?"null:":bytes.length+":").getBytes(StandardCharsets.UTF_8));digest.update(bytes);digest.update((byte)'\n');
                    }
                }
            }
            return HexFormat.of().formatHex(digest.digest());
        }catch(java.security.NoSuchAlgorithmException error){throw new IllegalStateException(error);}
    }
    static JsonObject plan(Connection db,String instance,long now,Set<String> protectedTasks,String runId)throws SQLException {
        require(now>30*DAY&&now<=System.currentTimeMillis()+5000,"GAME_RETENTION_CLOCK");
        require(protectedTasks!=null&&protectedTasks.size()<=PROTECTED_LIMIT,"GAME_RETENTION_DEPENDENCY_LIMIT");
        for(String id:protectedTasks)require(id!=null&&id.matches("[A-Za-z0-9_.:-]{1,128}"),"GAME_RETENTION_DEPENDENCY_ID");
        long eventCutoff=now-7*DAY,taskCutoff=now-30*DAY;
        String activeBoot=text(db,"SELECT value FROM metadata WHERE key='active_boot'"),activeWorld=text(db,"SELECT value FROM metadata WHERE key='active_world'");
        Map<String,Long> closed=new HashMap<>();
        try(var q=query(db,"SELECT boot,world,closed_at FROM contexts WHERE closed_at IS NOT NULL");var rows=q.executeQuery()) {
            while(rows.next())closed.put(context(rows.getString(1),rows.getString(2)),rows.getLong(3));
        }
        Map<String,JsonObject> tasks=new LinkedHashMap<>();Map<String,String> requestHashes=new HashMap<>();
        Map<String,String> blockedTasks=new HashMap<>();Map<String,Integer> protectedCounts=new TreeMap<>();
        try(var q=query(db,"SELECT task_id,body_hash,task FROM tasks ORDER BY rowid");var rows=q.executeQuery()) {
            while(rows.next()) {String id=rows.getString(1);tasks.put(id,parse(rows.getString(3)));requestHashes.put(id,rows.getString(2));}
        }
        Set<String> known=tasks.keySet(),dependent=new HashSet<>(protectedTasks);
        // A recent/unconfirmed delivery or event may still be needed to recover a task.
        try(var q=query(db,"SELECT boot,world,created_at,acked_at,payload,type FROM reliable ORDER BY rowid");var rows=q.executeQuery()) {
            while(rows.next()) {
                long created=rows.getLong(3),acked=rows.getLong(4);
                try {
                    JsonObject payload=parse(rows.getString(5));
                    require(!rows.getString(6).equals("task_update")||textTaskId(rows.getString(5))!=null,"GAME_RETENTION_DEPENDENCY");
                    Set<String> referenced=references(payload,known);
                    if(!aged(created,taskCutoff)||!aged(acked,taskCutoff)||(Objects.equals(activeBoot,rows.getString(1))&&Objects.equals(activeWorld,rows.getString(2))))dependent.addAll(referenced);
                }
                catch(RuntimeException error) {dependent.addAll(known);protect(protectedCounts,"unreadable_dependency_payload");}
            }
        }
        for(var entry:tasks.entrySet()) {
            String id=entry.getKey();JsonObject task=entry.getValue();String reason=null;
            try {
                String boot=str(task,"bridge_boot_id"),world=str(task,"world_session_id");
                if(dependent.contains(id))reason="explicit_or_recent_dependency";
                else if(!TERMINAL.contains(str(task,"state")))reason="unfinished_task";
                else if(!Set.of("none","verified").contains(nullable(task,"effect_status")))reason="unknown_task_effect";
                else if(Objects.equals(activeBoot,boot)&&Objects.equals(activeWorld,world))reason="current_context";
                else if(!aged(closed.getOrDefault(context(boot,world),-1L),taskCutoff))reason="unclosed_or_recent_context";
                else if(!aged(timestamp(task,"created_at"),taskCutoff)||!aged(timestamp(task,"updated_at"),taskCutoff))reason="recent_or_legacy_task_time";
                else if(count(db,"SELECT count(*) FROM task_transitions WHERE task_id=? AND (recorded_at<=0 OR recorded_at>=?)",id,taskCutoff)>0)reason="recent_task_version";
                else if(count(db,"SELECT count(*) FROM reliable WHERE type='task_update' AND json_extract(payload,'$.task.task_id')=? AND (created_at<=0 OR created_at>=? OR acked_at IS NULL OR acked_at<=0 OR acked_at>=?)",id,taskCutoff,taskCutoff)>0)reason="unconfirmed_or_recent_task_delivery";
            }catch(RuntimeException error){reason="legacy_or_invalid_task";}
            if(reason!=null) {blockedTasks.put(id,reason);protect(protectedCounts,reason);}
        }
        JsonArray taskIds=new JsonArray(),eventRows=new JsonArray(),taskDeliveries=new JsonArray(),versionRows=new JsonArray(),retired=new JsonArray();
        Map<String,JsonObject> summaries=new TreeMap<>();
        for(var entry:tasks.entrySet())if(!blockedTasks.containsKey(entry.getKey())) {
            String id=entry.getKey();JsonObject task=entry.getValue();taskIds.add(id);
            JsonObject summary=obj("task_id",id,"world_session_id",task.get("world_session_id"),"bridge_boot_id",task.get("bridge_boot_id"),
                "world_id",task.get("world_id"),"version",task.get("version"),"state",task.get("state"),"effect_status",task.get("effect_status"),
                "created_at",task.get("created_at"),"updated_at",task.get("updated_at"),"skill",task.has("goal")?task.getAsJsonObject("goal").get("skill"):null);
            retired.add(obj("world",task.get("world_session_id"),"request_id",task.get("request_id"),"task_id",id,"body_hash",requestHashes.get(id),"summary",summary));
            addSummary(summaries,str(task,"world_session_id"),"task",str(task,"state"),timestamp(task,"updated_at"));
            try(var q=query(db,"SELECT rowid FROM task_transitions WHERE task_id=? ORDER BY rowid",id);var rows=q.executeQuery()) {while(rows.next())versionRows.add(rows.getLong(1));}
        }
        Set<String> selected=new HashSet<>();for(var value:taskIds)selected.add(value.getAsString());
        try(var q=query(db,"SELECT rowid,boot,world,type,payload,created_at,acked_at FROM reliable ORDER BY rowid");var rows=q.executeQuery()) {
            while(rows.next()) {
                long id=rows.getLong(1),created=rows.getLong(6),acked=rows.getLong(7);String world=rows.getString(3);
                if(rows.getString(4).equals("task_update")) {
                    String task=textTaskId(rows.getString(5));
                    if(selected.contains(task))taskDeliveries.add(id);
                    else protect(protectedCounts,"protected_task_delivery");
                    continue;
                }
                String reason=null;JsonObject payload=null;
                if(!aged(created,eventCutoff)||!aged(acked,eventCutoff))reason="unconfirmed_or_recent_event";
                else if(Objects.equals(activeBoot,rows.getString(2))&&Objects.equals(activeWorld,world))reason="current_context_event";
                else if(!aged(closed.getOrDefault(context(rows.getString(2),world),-1L),eventCutoff))reason="unclosed_or_recent_event_context";
                else try {
                    payload=parse(rows.getString(5));
                    if(!aged(timestamp(payload,"occurred_at"),eventCutoff)||nullable(payload,"kind")==null||str(payload,"kind").length()>80)reason="legacy_or_invalid_event";
                    else if(references(payload,known).stream().anyMatch(blockedTasks::containsKey))reason="event_task_dependency";
                }catch(RuntimeException error){reason="legacy_or_invalid_event";}
                if(reason!=null)protect(protectedCounts,reason);
                else {eventRows.add(id);addSummary(summaries,world,"event",str(payload,"kind"),created);}
            }
        }
        int newSummaries=0;
        for(String key:summaries.keySet())if(count(db,"SELECT count(*) FROM journal_summaries WHERE summary_key=?",key)==0)newSummaries++;
        require(count(db,"SELECT count(*) FROM journal_retired_tasks")+taskIds.size()<=TOMBSTONE_LIMIT,"GAME_RETENTION_TOMBSTONE_LIMIT");
        require(count(db,"SELECT count(*) FROM journal_summaries")+newSummaries<=SUMMARY_LIMIT,"GAME_RETENTION_SUMMARY_LIMIT");
        require(count(db,"SELECT count(*) FROM journal_retention_runs")<RUN_LIMIT,"GAME_RETENTION_RUN_LIMIT");
        JsonArray summaryDeltas=new JsonArray();summaries.forEach((key,value)->summaryDeltas.add(obj("key",key,"value",value)));
        return obj("format_version",1,"schema_version",LocalJournal.SCHEMA_VERSION,"game_instance_id",instance,"run_id",runId,
            "created_at_ms",now,"expires_at_ms",Math.addExact(now,PLAN_TTL),"event_cutoff_ms",eventCutoff,"task_cutoff_ms",taskCutoff,
            "snapshot_sha256",snapshot(db),"protected_task_ids",new TreeSet<>(protectedTasks),"protected",protectedCounts,
            "counts",obj("events",eventRows.size(),"tasks",taskIds.size(),"task_deliveries",taskDeliveries.size(),"task_versions",versionRows.size(),"summary_groups",summaryDeltas.size()),
            "events",eventRows,"tasks",taskIds,"task_deliveries",taskDeliveries,"task_versions",versionRows,"retired",retired,"summary_deltas",summaryDeltas);
    }
    private static String textTaskId(String raw) {
        try{return str(parse(raw).getAsJsonObject("task"),"task_id");}catch(RuntimeException error){return null;}
    }
    private static void addSummary(Map<String,JsonObject> groups,String world,String source,String kind,long at) {
        JsonObject scope=obj("world_session_id",world,"source",source,"kind",kind,"utc_day",Instant.ofEpochMilli(at).toString().substring(0,10));
        String key=hash(canonical(scope));JsonObject value=groups.get(key);
        if(value==null){value=scope;value.addProperty("count",0);value.addProperty("first_recorded_at",at);value.addProperty("last_recorded_at",at);groups.put(key,value);}
        value.addProperty("count",Math.addExact(num(value,"count"),1));value.addProperty("first_recorded_at",Math.min(num(value,"first_recorded_at"),at));value.addProperty("last_recorded_at",Math.max(num(value,"last_recorded_at"),at));
    }
    static JsonObject previous(Connection db,String run,String digest)throws SQLException {
        try(var q=query(db,"SELECT plan_hash,result FROM journal_retention_runs WHERE run_id=?",run);var rows=q.executeQuery()) {
            if(!rows.next())return null;require(rows.getString(1).equals(digest),"GAME_RETENTION_RUN_CONFLICT");return parse(rows.getString(2));
        }
    }
    static void validatePlan(Connection db,String instance,JsonObject proposed)throws SQLException {
        long now=System.currentTimeMillis();require(num(proposed,"created_at_ms")<=now+5000&&num(proposed,"expires_at_ms")>now,"GAME_RETENTION_PLAN_EXPIRED");
        require(str(proposed,"run_id").matches("retention-[0-9a-f-]{36}"),"GAME_RETENTION_RUN_ID");
        Set<String> dependencies=new HashSet<>();for(var value:proposed.getAsJsonArray("protected_task_ids"))require(dependencies.add(value.getAsString()),"GAME_RETENTION_DEPENDENCY_ID");
        JsonObject actual=plan(db,instance,num(proposed,"created_at_ms"),dependencies,str(proposed,"run_id"));
        require(canonical(actual).equals(canonical(proposed)),"GAME_RETENTION_PLAN_CHANGED");
    }
    static JsonObject apply(Connection db,JsonObject plan,String digest,String backup)throws SQLException {
        for(var entry:plan.getAsJsonArray("retired")) {
            JsonObject value=entry.getAsJsonObject();write(db,"INSERT INTO journal_retired_tasks VALUES(?,?,?,?,?,?)",str(value,"world"),str(value,"request_id"),str(value,"task_id"),str(value,"body_hash"),System.currentTimeMillis(),canonical(value.get("summary")));
        }
        for(var entry:plan.getAsJsonArray("summary_deltas")) {
            JsonObject delta=entry.getAsJsonObject(),value=delta.getAsJsonObject("value").deepCopy();String key=str(delta,"key"),old=text(db,"SELECT value FROM journal_summaries WHERE summary_key=?",key);
            if(old!=null){JsonObject prior=parse(old);value.addProperty("count",Math.addExact(num(value,"count"),num(prior,"count")));value.addProperty("first_recorded_at",Math.min(num(value,"first_recorded_at"),num(prior,"first_recorded_at")));value.addProperty("last_recorded_at",Math.max(num(value,"last_recorded_at"),num(prior,"last_recorded_at")));}
            write(db,"INSERT INTO journal_summaries VALUES(?,?) ON CONFLICT(summary_key) DO UPDATE SET value=excluded.value",key,canonical(value));
        }
        for(String key:List.of("events","task_deliveries"))for(var id:plan.getAsJsonArray(key))write(db,"DELETE FROM reliable WHERE rowid=?",id.getAsLong());
        for(var id:plan.getAsJsonArray("task_versions"))write(db,"DELETE FROM task_transitions WHERE rowid=?",id.getAsLong());
        for(var id:plan.getAsJsonArray("tasks"))write(db,"DELETE FROM tasks WHERE task_id=?",id.getAsString());
        long generation=Long.parseLong(text(db,"SELECT value FROM metadata WHERE key='retention_generation'"))+1;
        write(db,"UPDATE metadata SET value=? WHERE key='retention_generation'",Long.toString(generation));
        JsonObject result=obj("run_id",plan.get("run_id"),"plan_sha256",digest,"game_instance_id",plan.get("game_instance_id"),"generation",generation,
            "counts",plan.get("counts"),"backup_file",backup,"completed_at",Instant.now().toString(),"originals_in_backup",true,"disk_bytes_reclaimed",false);
        write(db,"INSERT INTO journal_retention_runs VALUES(?,?,?)",str(plan,"run_id"),digest,canonical(result));return result;
    }
    /** Old backup contents cannot remove later compact request tombstones. */
    static void restoreProtection(Connection target,Connection safety)throws SQLException {
        if(count(target,"PRAGMA user_version")==2){createSchema(target);write(target,"PRAGMA user_version=3");}
        try(var q=query(safety,"SELECT world,request_id,task_id,body_hash,retired_at,summary FROM journal_retired_tasks ORDER BY rowid");var rows=q.executeQuery()) {
            while(rows.next()) {
                String world=rows.getString(1),request=rows.getString(2),id=rows.getString(3),body=rows.getString(4);
                try(var check=query(target,"SELECT world,request_id,task_id,body_hash,summary FROM journal_retired_tasks WHERE (world=? AND request_id=?) OR task_id=?",world,request,id);var existing=check.executeQuery()) {
                    while(existing.next())require(world.equals(existing.getString(1))&&request.equals(existing.getString(2))&&id.equals(existing.getString(3))&&body.equals(existing.getString(4))&&canonical(parse(rows.getString(6))).equals(canonical(parse(existing.getString(5)))),"GAME_RETENTION_RESTORE_CONFLICT");
                }
                try(var check=query(target,"SELECT world,request_id,task_id,body_hash FROM tasks WHERE (world=? AND request_id=?) OR task_id=?",world,request,id);var existing=check.executeQuery()) {
                    while(existing.next())require(world.equals(existing.getString(1))&&request.equals(existing.getString(2))&&id.equals(existing.getString(3))&&body.equals(existing.getString(4)),"GAME_RETENTION_RESTORE_CONFLICT");
                }
                write(target,"DELETE FROM reliable WHERE type='task_update' AND json_extract(payload,'$.task.task_id')=?",id);
                write(target,"DELETE FROM task_transitions WHERE task_id=?",id);write(target,"DELETE FROM tasks WHERE task_id=?",id);
                write(target,"INSERT INTO journal_retired_tasks VALUES(?,?,?,?,?,?) ON CONFLICT(world,request_id) DO NOTHING",world,request,id,body,rows.getLong(5),rows.getString(6));
            }
        }
        require(count(target,"SELECT count(*) FROM journal_retired_tasks")<=TOMBSTONE_LIMIT,"GAME_RETENTION_TOMBSTONE_LIMIT");
        for(String key:List.of("history_reliable_highwater","history_tasks_highwater")) {
            long incoming=Long.parseLong(text(safety,"SELECT value FROM metadata WHERE key=?",key)),restored=Long.parseLong(text(target,"SELECT value FROM metadata WHERE key=?",key));
            write(target,"UPDATE metadata SET value=? WHERE key=?",Long.toString(Math.max(incoming,restored)),key);
        }
        write(target,"INSERT INTO metadata VALUES('restore_retired_protection',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",Long.toString(count(safety,"SELECT count(*) FROM journal_retired_tasks")));
    }
    static JsonObject status(Connection db)throws SQLException {
        JsonArray summaries=new JsonArray(),runs=new JsonArray();
        try(var q=query(db,"SELECT summary_key,value FROM journal_summaries ORDER BY rowid DESC LIMIT 50");var rows=q.executeQuery()){while(rows.next())summaries.add(obj("key",rows.getString(1),"value",parse(rows.getString(2))));}
        try(var q=query(db,"SELECT result FROM journal_retention_runs ORDER BY rowid DESC LIMIT 8");var rows=q.executeQuery()){while(rows.next())runs.add(parse(rows.getString(1)));}
        return obj("schema_version",LocalJournal.SCHEMA_VERSION,"tasks",count(db,"SELECT count(*) FROM tasks"),"reliable",count(db,"SELECT count(*) FROM reliable"),
            "task_versions",count(db,"SELECT count(*) FROM task_transitions"),"retired_tasks",count(db,"SELECT count(*) FROM journal_retired_tasks"),
            "summary_groups",count(db,"SELECT count(*) FROM journal_summaries"),"runs",count(db,"SELECT count(*) FROM journal_retention_runs"),"latest_summaries",summaries,"latest_runs",runs,
            "limits",obj("retired_tasks",TOMBSTONE_LIMIT,"summary_groups",SUMMARY_LIMIT,"runs",RUN_LIMIT,"protected_tasks",PROTECTED_LIMIT,"plan_ttl_ms",PLAN_TTL));
    }
}

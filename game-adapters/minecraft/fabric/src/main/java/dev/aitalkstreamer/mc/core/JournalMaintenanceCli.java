package dev.aitalkstreamer.mc.core;

import com.google.gson.*;
import java.io.*;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.security.MessageDigest;
import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Native offline entry point. It acquires the same owner.lock as the Minecraft bridge. */
public final class JournalMaintenanceCli {
    static final long PLAN_BYTES=32L*1024*1024, PLAN_TOTAL_BYTES=128L*1024*1024;
    static final int PLAN_FILES=16;
    private JournalMaintenanceCli() {}
    private static String digest(byte[] value) {
        try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value));}
        catch(java.security.NoSuchAlgorithmException error){throw new IllegalStateException(error);}
    }
    private static JsonObject parse(byte[] value) {return JsonParser.parseString(new String(value,StandardCharsets.UTF_8)).getAsJsonObject();}
    private static Path plans(Path root)throws IOException {
        Path directory=root.resolve("maintenance");
        require(!Files.isSymbolicLink(directory),"GAME_RETENTION_PLAN_PATH");Files.createDirectories(directory);
        require(directory.toRealPath().getParent().equals(root.toRealPath()),"GAME_RETENTION_PLAN_PATH");return directory;
    }
    private static byte[] read(Path path,long maximum)throws IOException {
        require(Files.isRegularFile(path)&&!Files.isSymbolicLink(path)&&Files.size(path)<=maximum,"GAME_RETENTION_INPUT_FILE");
        byte[] value=Files.readAllBytes(path);require(value.length<=maximum,"GAME_RETENTION_INPUT_FILE");return value;
    }
    private static Set<String> protectedTasks(Path path,String instance)throws IOException {
        if(path==null)return Set.of();JsonObject value=parse(read(path,4L*1024*1024));
        require(value.keySet().equals(Set.of("game_instance_id","task_ids"))&&str(value,"game_instance_id").equals(instance),"GAME_RETENTION_DEPENDENCY_INSTANCE");
        Set<String> tasks=new HashSet<>();for(var id:value.getAsJsonArray("task_ids"))require(tasks.add(id.getAsString()),"GAME_RETENTION_DEPENDENCY_ID");return tasks;
    }
    public static JsonObject run(String...args)throws IOException {
        Map<String,String> options=new HashMap<>();
        for(int i=0;i<args.length;i+=2)require(i+1<args.length&&Set.of("--directory","--action","--protect","--plan","--sha256","--backup").contains(args[i])&&options.putIfAbsent(args[i],args[i+1])==null,"GAME_RETENTION_ARGUMENTS");
        require(options.containsKey("--directory")&&options.containsKey("--action"),"GAME_RETENTION_ARGUMENTS");
        String action=options.get("--action");require(Set.of("preview","apply","status","restore","result").contains(action),"GAME_RETENTION_ARGUMENTS");
        Set<String> allowed=new HashSet<>(Set.of("--directory","--action"));
        if(action.equals("preview"))allowed.add("--protect");if(action.equals("apply")||action.equals("result"))allowed.addAll(Set.of("--plan","--sha256"));
        if(action.equals("restore"))allowed.addAll(Set.of("--backup","--sha256"));
        require(allowed.containsAll(options.keySet()),"GAME_RETENTION_ARGUMENTS");
        Path root=Path.of(options.get("--directory"));require(root.isAbsolute(),"GAME_RETENTION_ABSOLUTE_DIRECTORY");root=root.normalize();
        if(action.equals("restore")) {
            require(options.containsKey("--backup")&&options.containsKey("--sha256")&&options.get("--sha256").matches("[0-9a-f]{64}"),"GAME_RETENTION_ARGUMENTS");
            Path before=LocalJournal.restore(root,options.get("--backup"),options.get("--sha256"));
            return obj("restored",true,"source_backup",options.get("--backup"),"pre_restore_backup",before.getFileName().toString(),"retired_request_protection_preserved",true,"auto_granted",false);
        }
        try(LocalJournal journal=LocalJournal.openForMaintenance(root)) {
            if(action.equals("status"))return journal.retentionStatus();
            Path directory=plans(root);
            if(action.equals("preview")) {
                long total=0;int files=0;
                try(var paths=Files.list(directory)){for(Path path:paths.toList())if(path.getFileName().toString().endsWith(".json")){require(Files.isRegularFile(path)&&!Files.isSymbolicLink(path),"GAME_RETENTION_PLAN_PATH");files++;total=Math.addExact(total,Files.size(path));}}
                require(files<PLAN_FILES,"GAME_RETENTION_PLAN_FILE_LIMIT");
                JsonObject plan=journal.retentionPlan(System.currentTimeMillis(),protectedTasks(options.containsKey("--protect")?Path.of(options.get("--protect")):null,journal.instance()));
                byte[] bytes=(canonical(plan)+"\n").getBytes(StandardCharsets.UTF_8);
                require(bytes.length<=PLAN_BYTES&&total+bytes.length<=PLAN_TOTAL_BYTES,"GAME_RETENTION_PLAN_BYTE_LIMIT");
                String name=str(plan,"run_id")+".json";
                try(FileChannel file=FileChannel.open(directory.resolve(name),StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE)) {
                    ByteBuffer buffer=ByteBuffer.wrap(bytes);while(buffer.hasRemaining())file.write(buffer);file.force(true);
                }
                return obj("plan_file",name,"plan_sha256",digest(bytes),"game_instance_id",journal.instance(),"expires_at_ms",plan.get("expires_at_ms"),
                    "counts",plan.get("counts"),"protected",plan.get("protected"),"additional_task_protection_supplied",options.containsKey("--protect"),"applied",false);
            }
            require(options.containsKey("--plan")&&options.containsKey("--sha256")&&options.get("--plan").matches("retention-[0-9a-f-]{36}\\.json")&&options.get("--sha256").matches("[0-9a-f]{64}"),"GAME_RETENTION_ARGUMENTS");
            Path path=directory.resolve(options.get("--plan"));byte[] bytes=read(path,PLAN_BYTES);
            require(path.toRealPath().getParent().equals(directory.toRealPath()),"GAME_RETENTION_PLAN_PATH");
            require(digest(bytes).equals(options.get("--sha256")),"GAME_RETENTION_PLAN_HASH");JsonObject plan=parse(bytes);
            if(action.equals("result")) {
                JsonObject value=journal.retentionResult(plan,hash(canonical(plan)));
                return obj("game_instance_id",journal.instance(),"run_id",str(plan,"run_id"),"plan_file_sha256",digest(bytes),
                    "found",value!=null,"result",value,"observed_at",java.time.Instant.now().toString(),"apply_command_dispatched",false);
            }
            return journal.applyRetention(plan,hash(canonical(plan)));
        }
    }
    public static void main(String[] args) {
        try {System.out.println(GSON.toJson(run(args)));}
        catch(Exception error) {
            String code=error instanceof Json.Rejected rejected?rejected.code:error.getMessage();
            if(code==null||!code.matches("GAME_[A-Z0-9_]{1,100}"))code="GAME_RETENTION_FAILED";
            System.err.println(GSON.toJson(obj("error",code,"applied",false)));System.exit(2);
        }
    }
}

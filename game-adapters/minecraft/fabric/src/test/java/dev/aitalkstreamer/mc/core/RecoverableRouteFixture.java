package dev.aitalkstreamer.mc.core;

import com.google.gson.JsonObject;
import java.util.*;
import java.util.concurrent.atomic.AtomicLong;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Real session/arbiter, fixture driver only. No game, world writes or inference. */
public final class RecoverableRouteFixture {
    static final class Harness implements ExecutorTaskSession.Runtime {
        final AtomicLong now=new AtomicLong(1000);
        final ControlArbiter control=new ControlArbiter(now::get,()->{});
        final List<JsonObject> results=new ArrayList<>();
        final List<Runnable> signals=new ArrayList<>();
        final ExecutorTaskSession session=new ExecutorTaskSession(this);
        RuntimeException failure;boolean cleanupFails,held,targeted;int cancels;String skill="gather",purpose="equip";
        Harness() {
            control.world("session-1");control.attach("controller-1");control.release(control.epoch(),()->{});control.observe(1);
            control.beginAuto("controller-1","session-1",control.epoch(),true);
            control.grant("controller-1",control.lease(),control.epoch(),1,control.heartbeat(),10000);
        }
        JsonObject position(){return obj("dimension","minecraft:overworld","x",0,"y",64,"z",0);}
        JsonObject observed(int seq){return obj("game_instance_id","instance-1","bridge_boot_id","boot-1","world_id","world-1",
            "world_session_id","session-1","control_epoch",control.epoch(),"seq",seq,"screen","gameplay",
            "player",obj("position",position()),"inventory",List.of(obj("item_id","minecraft:oak_log","count",1)));}
        void begin(String id,int seq){
            var goal=List.of("gather","craft").contains(skill)?obj("skill",skill,"item_id","minecraft:cobblestone","count",1)
                :skill.equals("use_item")?obj("skill",skill,"item_id","minecraft:oak_log","purpose",purpose)
                :obj("skill","navigate","target",position(),"radius",1);
            if(skill.equals("use_item") && targeted)goal.add("target",position());
            session.start(obj("task_id",id,"game_instance_id","instance-1","bridge_boot_id","boot-1","world_id","world-1",
                "world_session_id","session-1","control_epoch",control.epoch(),"goal",goal),observed(seq),control,results::add);
        }
        public void start(JsonObject task,ControlArbiter control,ControlArbiter.Permit permit,InventoryTarget target,BaseTarget base,Runnable done){held=true;signals.add(done);}
        public void tick(){if(failure!=null)throw failure;}
        public void cancel(){cancels++;if(cleanupFails)throw new IllegalStateException("fixture cleanup");held=false;}
    }
    static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    static void fatal(Harness h){boolean thrown=false;try{h.session.tick(h.observed(2));}catch(RuntimeException expected){thrown=true;}check(thrown,"fatal error swallowed");}
    public static void main(String[] args){
        for(var reason:List.of(LocalTaskFailure.Reason.GATHER_RESOURCE_UNAVAILABLE,LocalTaskFailure.Reason.GATHER_TOOL_UNAVAILABLE,
            LocalTaskFailure.Reason.GATHER_NO_PROGRESS,
            LocalTaskFailure.Reason.NAVIGATION_NO_ROUTE,LocalTaskFailure.Reason.NAVIGATION_NO_PROGRESS,
            LocalTaskFailure.Reason.NAVIGATION_MOVEMENT_BLOCKED,LocalTaskFailure.Reason.DEFENSE_RETREAT_COMPLETE,
            LocalTaskFailure.Reason.DEFENSE_TIMEOUT,LocalTaskFailure.Reason.DEFENSE_NO_PROGRESS,
            LocalTaskFailure.Reason.DEFENSE_ESCAPE_TIMEOUT,LocalTaskFailure.Reason.DEFENSE_RANGE_LIMIT,
            LocalTaskFailure.Reason.SUPPLY_NO_PROGRESS,LocalTaskFailure.Reason.SUPPLY_RANGE_LIMIT,
            LocalTaskFailure.Reason.DEFENSE_HAZARD_INTERRUPTED)){
            var h=new Harness();h.failure=new LocalTaskFailure(reason);h.begin("task-1",1);long epoch=h.control.epoch();
            h.session.tick(h.observed(2));check(!h.held && h.cancels==1 && !h.session.active(),"failed inputs not cleaned");
            check(h.results.size()==1 && str(h.results.getFirst(),"state").equals("failed")
                && str(h.results.getFirst(),"effect_status").equals("unknown"),"failed effect rewritten");
            check(h.control.allowed() && h.control.epoch()==epoch,"known failure revoked authority");
            h.failure=null;h.begin("task-2",3);h.signals.getFirst().run();h.session.tick(h.observed(4));h.session.tick(h.observed(5));
            check(h.session.active() && h.results.size()==1,"old completion resurrected");h.session.cancel("FIXTURE_END");
        }
        var unknown=new Harness();unknown.failure=new IllegalStateException("not a route failure");unknown.begin("task-1",1);fatal(unknown);check(!unknown.held,"unknown failure leaked input");
        var timeout=new Harness();timeout.failure=new LocalTaskFailure(LocalTaskFailure.Reason.GATHER_SERVER_TIMEOUT);timeout.begin("task-1",1);fatal(timeout);
        for(var reason:List.of(LocalTaskFailure.Reason.SURVIVAL_ENVIRONMENT_UNSUPPORTED,
                LocalTaskFailure.Reason.SUPPLY_TIMEOUT,LocalTaskFailure.Reason.EATING_SERVER_TIMEOUT)) {
            var h=new Harness();h.failure=new LocalTaskFailure(reason);h.begin("task-1",1);fatal(h);
        }
        for(String skill:List.of("craft","use_item")) {
            var h=new Harness();h.skill=skill;h.failure=new LocalTaskFailure(LocalTaskFailure.Reason.DEFENSE_HAZARD_INTERRUPTED);
            h.begin("hazard-task",1);h.session.tick(h.observed(2));
            check(!h.session.active() && !h.held && h.control.allowed(),"clean work interruption did not replan");
            check(str(h.results.getFirst(),"state").equals("failed") && str(h.results.getFirst(),"effect_status").equals("unknown"),"hazard interruption forged success");
        }
        for(var reason:List.of(LocalTaskFailure.Reason.ITEM_PLACEMENT_SITE_CHANGED,
                LocalTaskFailure.Reason.ITEM_PLANT_SITE_CHANGED,LocalTaskFailure.Reason.ITEM_BLOCK_TARGET_CHANGED)) {
            var h=new Harness();h.skill="use_item";h.purpose="activate";h.targeted=true;
            h.failure=new LocalTaskFailure(reason);h.begin("placement-task",1);long epoch=h.control.epoch();h.session.tick(h.observed(2));
            check(!h.session.active() && !h.held && h.cancels==1 && h.control.allowed() && h.control.epoch()==epoch,"known pre-effect placement failure stopped autonomy");
            check(h.results.size()==1 && str(h.results.getFirst(),"state").equals("failed")
                && str(h.results.getFirst(),"effect_status").equals("unknown")
                && str(h.results.getFirst(),"reason").equals("GAME_"+reason.name()),"placement failure forged an effect");
            for(String mismatch:List.of("skill","purpose","target","raw","cleanup")) {
                var bad=new Harness();bad.skill=mismatch.equals("skill")?"gather":"use_item";
                bad.purpose=mismatch.equals("purpose")?"equip":"activate";bad.targeted=!mismatch.equals("target");
                bad.failure=mismatch.equals("raw")?new Json.Rejected("GAME_"+reason.name()):new LocalTaskFailure(reason);
                bad.cleanupFails=mismatch.equals("cleanup");bad.begin("bad-placement",1);fatal(bad);
                if(bad.cleanupFails)check(bad.results.isEmpty(),"placement cleanup failure was accepted");
            }
        }
        var mismatched=new Harness();mismatched.skill="navigate";mismatched.failure=new LocalTaskFailure(LocalTaskFailure.Reason.GATHER_RESOURCE_UNAVAILABLE);mismatched.begin("task-1",1);fatal(mismatched);
        var wrongProgress=new Harness();wrongProgress.skill="navigate";wrongProgress.failure=new LocalTaskFailure(LocalTaskFailure.Reason.GATHER_NO_PROGRESS);wrongProgress.begin("task-1",1);fatal(wrongProgress);
        var cleanup=new Harness();cleanup.failure=new LocalTaskFailure(LocalTaskFailure.Reason.GATHER_RESOURCE_UNAVAILABLE);cleanup.cleanupFails=true;cleanup.begin("task-1",1);fatal(cleanup);check(cleanup.results.isEmpty(),"cleanup failure delivered as recoverable");
        var revoked=new Harness();revoked.failure=new LocalTaskFailure(LocalTaskFailure.Reason.GATHER_RESOURCE_UNAVAILABLE);revoked.begin("task-1",1);
        revoked.control.stop(ControlArbiter.Mode.MANUAL_COMMENTARY,"PHYSICAL_INPUT");revoked.session.tick(revoked.observed(2));
        check(str(revoked.results.getFirst(),"state").equals("cancelled") && str(revoked.results.getFirst(),"reason").equals("PHYSICAL_INPUT") && !revoked.control.allowed(),"physical stop revived");
        System.out.println("PASS: 17 known route/defense/supply/interruption/targeted-placement outcomes retain failed/unknown after cleanup; 2 clean work interruptions; fresh replacement, stale callback, placement skill/purpose/target/raw/cleanup, unsupported lava/oxygen, unknown/server-timeout/mismatched/cleanup/physical stop fences checked");
    }
}

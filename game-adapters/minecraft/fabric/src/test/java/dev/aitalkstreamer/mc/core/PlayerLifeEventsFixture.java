package dev.aitalkstreamer.mc.core;

import com.google.gson.JsonObject;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Native JVM protocol fixture only: never starts Minecraft, changes inventory or kills a player. */
public final class PlayerLifeEventsFixture {
    private static JsonObject sample(String world, long seq, Object health, String screen) {
        return obj("world_session_id", world, "seq", seq, "observed_at", "2026-11-01T16:00:00Z", "screen", screen,
                "player", obj("health", health, "position", obj("dimension", "minecraft:overworld", "x", 1, "y", 64, "z", 2)));
    }
    private static void check(boolean value, String reason) { if (!value) throw new AssertionError(reason); }
    private static void kind(JsonObject event, String kind) { check(event != null && kind.equals(str(event,"kind")), kind); }
    public static void main(String[] args) {
        PlayerLifeEvents tracker = new PlayerLifeEvents();
        check(tracker.observe(sample("world-a",1,20,"gameplay"),null)==null,"initial healthy is not respawn");
        check(tracker.observe(sample("world-a",2,5,"gameplay"),null)==null,"damage is not death");
        JsonObject dead=tracker.observe(sample("world-a",3,0,"death"),"task-original"); kind(dead,"player_death");
        check("critical".equals(str(dead,"severity")) && "task-original".equals(str(dead,"task_id")),"severity and original task");
        check(num(dead.getAsJsonObject("data"),"previous_observation_seq")==2,"original sequence retained");
        check(tracker.observe(sample("world-a",4,0,"death"),null)==null,"death screen does not repeat events");
        JsonObject respawn=tracker.observe(sample("world-a",5,20,"gameplay"),null);kind(respawn,"player_respawn");
        check(!respawn.getAsJsonObject("data").get("inventory_restored_verified").getAsBoolean(),"respawn never proves stock recovery");
        check(!dead.getAsJsonObject("data").get("cause_known").getAsBoolean(),"cause unknown");
        check(tracker.observe(sample("world-b",1,20,"gameplay"),null)==null,"world change is not respawn");
        JsonObject source=sample("world-b",2,0,"death"), event=tracker.observe(source,null);kind(event,"player_death");
        source.getAsJsonObject("player").getAsJsonObject("position").addProperty("x",999);
        check(num(event.getAsJsonObject("data").getAsJsonObject("position"),"x")==1,"immutable originating observation");
        kind(tracker.observe(sample("world-b",3,20,"gameplay"),null),"player_respawn");
        tracker.reset();kind(tracker.observe(sample("world-b",4,0,"death"),null),"player_dead_observed");
        tracker.observe(sample("world-b",5,null,"unknown"),null);
        check(tracker.observe(sample("world-b",6,20,"gameplay"),null)==null,"unknown breaks continuity");
        kind(tracker.observe(sample("world-b",7,null,"death"),null),"player_death");
        JsonObject absent=sample("world-b",8,null,"unknown");absent.add("player",com.google.gson.JsonNull.INSTANCE);
        check(tracker.observe(absent,null)==null,"absent player is unknown");
        check(tracker.observe(sample("world-b",9,20,"gameplay"),null)==null,"missing player cannot prove respawn");
        tracker.reset();
        for (int i=1;i<=23;i++) check(tracker.observe(sample("saved-dead",i,20,"menu"),null)==null,
                "loading default health cannot establish living baseline");
        JsonObject loadedDeath=tracker.observe(sample("saved-dead",24,0,"death"),null);
        kind(loadedDeath,"player_dead_observed");
        check(loadedDeath.getAsJsonObject("data").get("previous_observation_seq").isJsonNull(),
                "loading health is not a confirmed prior life");
        kind(tracker.observe(sample("saved-dead",25,20,"menu"),null),"player_respawn");
        check(tracker.observe(sample("saved-dead",26,20,"menu"),null)==null,"paused life does not repeat respawn");
        kind(tracker.observe(sample("saved-dead",27,0,"death"),null),"player_death");
        for (String screen : new String[]{"gameplay","inventory","container"}) {
            tracker.reset();
            check(tracker.observe(sample("known-alive",1,20,screen),null)==null,"visible player establishes baseline");
            check(tracker.observe(sample("known-alive",2,20,"menu"),null)==null,"ordinary pause preserves known life");
            kind(tracker.observe(sample("known-alive",3,0,"death"),null),"player_death");
        }
        System.out.println("PASS: initial, damage, death, dedup, rapid respawn, task/world/sequence, unknown, immutable facts, saved-death loading transient and established menu continuity; PROTOCOL_FIXTURE_NOT_REAL_GAME");
    }
}

package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import java.util.List;
import static org.junit.jupiter.api.Assertions.*;

/** Real prepared upstream and compiled native wiring, without initializing a game. */
class DefenseBindingTest {
    final HeldNativeProtocolTest bytecode=new HeldNativeProtocolTest();
    @Test void bothUpstreamPursuitSelectionsUseOneControlledEncounterInsteadOfAClassWideKillTask() throws Exception {
        var calls=bytecode.calls("adris/altoclef/chains/MobDefenseChain").get("getPriorityInner()F");
        assertEquals(2,calls.stream().filter(c->c.startsWith("dev/aitalkstreamer/mc/survival/ControlledDefenseTask:select")).count());
        assertFalse(calls.stream().anyMatch(c->c.startsWith("adris/altoclef/tasks/entity/KillEntitiesTask:<init>")));
    }
    @Test void actualUpstreamRangeAndAttackPreflightUseNativeAdmission() throws Exception {
        var calls=bytecode.calls("adris/altoclef/control/PlayerExtraController");
        assertTrue(calls.get("inRange(Lnet/minecraft/entity/Entity;)Z").stream().anyMatch(c->c.startsWith("dev/aitalkstreamer/mc/survival/SurvivalActions:entityInReach")));
        assertTrue(calls.get("attack(Lnet/minecraft/entity/Entity;)V").stream().anyMatch(c->c.startsWith("dev/aitalkstreamer/mc/survival/SurvivalActions:readyToAttack")));
        assertFalse(calls.get("inRange(Lnet/minecraft/entity/Entity;)Z").stream().anyMatch(c->c.contains("getEntityReachRange")));
    }
    @Test void theActualDefenseUsesOneEntityChildRealEscapeAndOriginalAuthority() throws Exception {
        var methods=bytecode.calls("dev/aitalkstreamer/mc/survival/ControlledDefenseTask");
        var all=methods.values().stream().flatMap(List::stream).toList();
        for(String expected:List.of("adris/altoclef/tasks/entity/KillEntityTask:<init>(Lnet/minecraft/entity/Entity;)V",
                "adris/altoclef/tasks/movement/RunAwayFromHostilesTask:<init>(DZ)V",
                "dev/aitalkstreamer/mc/survival/SurvivalAuthority:session()Ldev/aitalkstreamer/mc/survival/SurvivalAuthority$Session;"))
            assertTrue(all.contains(expected),expected);
        assertTrue(all.stream().anyMatch(c->c.startsWith("dev/aitalkstreamer/mc/survival/DefensePolicy:observe")));
        assertTrue(all.stream().anyMatch(c->c.startsWith("dev/aitalkstreamer/mc/survival/SurvivalAuthority:owned")));
        assertFalse(methods.get("onStart()V").stream().anyMatch(c->c.startsWith("dev/aitalkstreamer/mc/survival/DefensePolicy:<init>")));
        var tick=bytecode.calls("dev/aitalkstreamer/mc/survival/ControlledAltoClefDriver$1").get("tick()V");
        int checkpoint=tick.indexOf("dev/aitalkstreamer/mc/survival/ControlledDefenseTask:checkpoint()V");
        int upstream=tick.indexOf("adris/altoclef/AltoClef:onClientTick()V");
        assertTrue(checkpoint>=0 && upstream>checkpoint,"The original root checks the encounter before other chains can preempt it.");
    }
    @Test void directAndVanillaEntityAttacksShareTheSamePacerAndEncounterPolicy() throws Exception {
        var all=bytecode.calls("dev/aitalkstreamer/mc/survival/SurvivalActions").values().stream().flatMap(List::stream).toList();
        assertEquals(2,all.stream().filter(c->c.startsWith("dev/aitalkstreamer/mc/survival/AttackPacer:issue")).count());
        assertEquals(3,all.stream().filter(c->c.startsWith("dev/aitalkstreamer/mc/survival/ControlledDefenseTask:attackAllowed")).count());
        assertTrue(all.stream().anyMatch(c->c.startsWith("net/minecraft/client/network/ClientPlayerEntity:getAttackCooldownProgress")));
    }
}

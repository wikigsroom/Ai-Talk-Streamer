package dev.aitalkstreamer.mc.survival;

import org.junit.jupiter.api.Test;
import dev.aitalkstreamer.mc.core.LocalTaskFailure.Reason;
import static org.junit.jupiter.api.Assertions.*;
import static dev.aitalkstreamer.mc.survival.DefensePolicy.Mode.*;

class DefensePolicyTest {
    static final class Scene {
        boolean present=true, alive=true, ordinary=true, water=false, fire=false, lava=false, dangerous=false, sword=true;
        double targetHealth=20, distance=25, anchor=0, health=20, maxHealth=20, closest=25;
        int food=20, air=300, armor=0, threats=1;
        DefensePolicy.Facts facts() { return new DefensePolicy.Facts(present,alive,ordinary,targetHealth,distance,anchor,
                health,maxHealth,food,air,water,fire,lava,dangerous,sword,armor,threats,closest); }
    }
    @Test void healthyEquippedPlayerMayDefendAgainstTheSelectedOrdinaryHostile() {
        var scene=new Scene();var policy=new DefensePolicy(0);
        assertEquals(FIGHT,policy.observe(0,scene.facts()).mode());assertEquals(FIGHT,policy.observe(5999,scene.facts()).mode());
    }
    @Test void aStationaryTargetCannotResetNoProgressThroughTinyDistanceJitter() {
        var scene=new Scene();var policy=new DefensePolicy(0);policy.observe(0,scene.facts());
        scene.distance=24.8;policy.observe(5999,scene.facts());
        assertEquals(Reason.DEFENSE_NO_PROGRESS,policy.observe(6000,scene.facts()).reason());
    }
    @Test void approachingTheActualTargetExtendsTheProgressWindow() {
        var scene=new Scene();var policy=new DefensePolicy(0);policy.observe(0,scene.facts());
        scene.distance=16;assertEquals(FIGHT,policy.observe(5000,scene.facts()).mode());
        assertEquals(FIGHT,policy.observe(10999,scene.facts()).mode());
        assertEquals(Reason.DEFENSE_NO_PROGRESS,policy.observe(11000,scene.facts()).reason());
    }
    @Test void actualTargetHealthDecreaseCountsAsProgressButHealingDoesNot() {
        var scene=new Scene();var policy=new DefensePolicy(0);policy.observe(0,scene.facts());
        scene.targetHealth=16;policy.observe(5000,scene.facts());scene.targetHealth=20;policy.observe(10000,scene.facts());
        assertEquals(Reason.DEFENSE_NO_PROGRESS,policy.observe(11000,scene.facts()).reason());
    }
    @Test void losingPlayerHealthIsNotOffensiveProgressAndTriggersEscape() {
        var scene=new Scene();var policy=new DefensePolicy(0);policy.observe(0,scene.facts());
        scene.health=8;assertEquals(RETREAT,policy.observe(5000,scene.facts()).mode());
        scene.health=20;assertEquals(RETREAT,policy.observe(6000,scene.facts()).mode());
    }
    @Test void aHighMaximumHealthStillUsesItsCriticalHealthFraction() {
        var scene=new Scene();scene.maxHealth=60;scene.health=15;
        assertEquals(RETREAT,new DefensePolicy(0).observe(0,scene.facts()).mode());
    }
    @Test void unarmedHungryOrOverwhelmedPlayersRetreatInsteadOfPursuing() {
        for(int cause=0;cause<3;cause++) {
            var scene=new Scene();if(cause==0)scene.sword=false;if(cause==1)scene.food=6;if(cause==2)scene.threats=2;
            assertEquals(RETREAT,new DefensePolicy(0).observe(0,scene.facts()).mode());
        }
        var equipped=new Scene();equipped.armor=16;equipped.threats=3;
        assertEquals(FIGHT,new DefensePolicy(0).observe(0,equipped.facts()).mode());
    }
    @Test void fireLavaAndLowUnderwaterAirTakePriorityOverCombat() {
        for(int cause=0;cause<3;cause++) {
            var scene=new Scene();scene.fire=cause==0;scene.lava=cause==1;scene.water=cause==2;scene.air=59;
            assertEquals(RETREAT,new DefensePolicy(0).observe(0,scene.facts()).mode());
        }
        var scene=new Scene();scene.air=0;assertEquals(FIGHT,new DefensePolicy(0).observe(0,scene.facts()).mode());
    }
    @Test void dangerousOrNonHostileTargetsAreNotOrdinaryDefensivePursuit() {
        var scene=new Scene();scene.dangerous=true;
        assertEquals(RETREAT,new DefensePolicy(0).observe(0,scene.facts()).mode());
        scene.dangerous=false;scene.ordinary=false;
        assertEquals(RETREAT,new DefensePolicy(0).observe(0,scene.facts()).mode());
    }
    @Test void despawnWithOtherThreatsLeavesTheEncounterWithoutSubstitutingAnotherTarget() {
        var scene=new Scene();scene.present=false;
        assertEquals(RETREAT,new DefensePolicy(0).observe(0,scene.facts()).mode());
    }
    @Test void lossOfTheTargetAndAllNearbyThreatsFinishesOnlyThisDefenseSubtask() {
        var scene=new Scene();var policy=new DefensePolicy(0);policy.observe(0,scene.facts());
        scene.alive=false;scene.threats=0;
        assertEquals(FINISHED,policy.observe(1000,scene.facts()).mode());
        scene.alive=true;scene.threats=1;assertEquals(FINISHED,policy.observe(2000,scene.facts()).mode());
    }
    @Test void escapingFinishesWhenBothSelectedTargetAndOtherThreatsAreFarEnough() {
        var scene=new Scene();scene.health=6;var policy=new DefensePolicy(0);policy.observe(0,scene.facts());
        scene.distance=289;scene.closest=289;
        assertEquals(FINISHED,policy.observe(9999,scene.facts()).mode());
    }
    @Test void retreatHasItsOwnDeadlineAndCannotOscillateBackIntoCombat() {
        var scene=new Scene();scene.health=6;var policy=new DefensePolicy(0);policy.observe(0,scene.facts());
        scene.health=20;assertEquals(RETREAT,policy.observe(9999,scene.facts()).mode());
        assertEquals(Reason.DEFENSE_ESCAPE_TIMEOUT,policy.observe(10000,scene.facts()).reason());
        scene.threats=0;scene.present=false;assertEquals(FAILED,policy.observe(11000,scene.facts()).mode());
    }
    @Test void continualDamageCannotExtendTheAbsoluteEncounterDeadline() {
        var scene=new Scene();var policy=new DefensePolicy(0);
        for(int second=0;second<30;second++) { scene.targetHealth=20-second*.1;assertEquals(FIGHT,policy.observe(second*1000,scene.facts()).mode()); }
        assertEquals(Reason.DEFENSE_TIMEOUT,policy.observe(30000,scene.facts()).reason());
    }
    @Test void aDistantOpponentStartsEscapeAndExcessiveRouteDistanceStopsTheTask() {
        var scene=new Scene();scene.distance=289;var policy=new DefensePolicy(0);
        assertEquals(RETREAT,policy.observe(0,scene.facts()).mode());scene.anchor=2401;
        assertEquals(Reason.DEFENSE_RANGE_LIMIT,policy.observe(1000,scene.facts()).reason());
    }
    @Test void invalidOrRegressingFactsCannotCreateAHealthyOpponentOrExtendTime() {
        var scene=new Scene();scene.health=Double.NaN;assertThrows(IllegalArgumentException.class,scene::facts);
        scene.health=20;scene.distance=-1;assertThrows(IllegalArgumentException.class,scene::facts);
        scene.distance=25;var policy=new DefensePolicy(10);policy.observe(10,scene.facts());
        assertThrows(IllegalArgumentException.class,()->policy.observe(9,scene.facts()));
    }
    @Test void reflexAttacksFollowTheEncounterAndRetreatOnlyAllowsProjectileReflection() {
        var scene=new Scene();var policy=new DefensePolicy(0);
        assertFalse(policy.permitsAttack(true,true));policy.observe(0,scene.facts());
        assertTrue(policy.permitsAttack(true,false));assertFalse(policy.permitsAttack(false,false));assertTrue(policy.permitsAttack(false,true));
        scene.health=8;policy.observe(1000,scene.facts());
        assertFalse(policy.permitsAttack(true,false));assertTrue(policy.permitsAttack(false,true));
        policy.observe(11000,scene.facts());assertFalse(policy.permitsAttack(true,true));
    }
    @Test void aSafelyFinishedEncounterNoLongerBlocksTheOriginalResourceTask() {
        var scene=new Scene();var policy=new DefensePolicy(0);policy.observe(0,scene.facts());
        scene.present=false;scene.threats=0;policy.observe(1000,scene.facts());
        assertTrue(policy.permitsAttack(false,false));assertTrue(policy.permitsAttack(false,true));
    }
}

package dev.aitalkstreamer.mc.neoforge;

import java.util.*;
import static dev.aitalkstreamer.mc.neoforge.NativeWalkPlanner.*;

/** Regression for an admitted arrival region with an obstructed target cell. */
public final class ArrivalRadiusFixture {
    private static void require(boolean value, String reason) {
        if (!value) throw new AssertionError(reason);
    }
    public static void main(String[] arguments) {
        Point origin = new Point(0, 75, 0), target = new Point(4, 75, 0);
        Terrain blockedCenter = new Terrain() {
            public boolean stand(Point point) { return point.y() == 75 && point.z() == 0 && point.x() >= 0 && point.x() < 4; }
            public boolean step(Point from, Point to) { return from.y() == to.y() && Math.abs(from.x() - to.x()) == 1; }
        };
        Route accepted = find(blockedCenter, origin, target, 1, 64);
        require(accepted.reachesGoal(), "REACHABLE_RADIUS_WAS_REJECTED");
        require(accepted.points().getLast().equals(new Point(3, 75, 0)), "OBSTRUCTED_CENTER_WAS_ENTERED");
        require(!find(blockedCenter, origin, target, 0, 64).reachesGoal(), "EXACT_STANCE_WAS_RELAXED");
        require(find(blockedCenter, new Point(3, 75, 0), target, 1, 64).points().size() == 1, "ALREADY_ARRIVED_NEEDS_MOVEMENT");
        require(!find(blockedCenter, origin, new Point(4, 78, 0), 1, 64).reachesGoal(), "VERTICAL_GAP_WAS_IGNORED");
        Terrain noEdge = new Terrain() {
            public boolean stand(Point point) { return true; }
            public boolean step(Point from, Point to) { return false; }
        };
        require(find(noEdge, origin, target, 1, 64).points().isEmpty(), "BLOCKED_EDGE_WAS_BYPASSED");
        var observed=reachable(blockedCenter,origin,8,256);
        require(observed.contains(new Point(3,75,0)) && !observed.contains(target),"OBSERVED_FRONTIER_CROSSED_OBSTRUCTION");
        require(reachable(noEdge,origin,8,256).isEmpty(),"UNREACHABLE_CELL_WAS_OBSERVED");
        require(reachable(blockedCenter,origin,1,256).equals(List.of(new Point(1,75,0))),"OBSERVATION_RANGE_ESCAPED");
        boolean immutable=false;try{observed.add(target);}catch(UnsupportedOperationException expected){immutable=true;}
        require(immutable,"OBSERVATION_MUTABLE");
        var clock=new java.util.concurrent.atomic.AtomicLong(1000);boolean[] current={true};
        var receipt=new NativeStepReceipt(new Point(1,75,0),()->current[0],clock::get);
        require(!receipt.confirmed(true),"PREDICTION_BECAME_SERVER_ACK");
        receipt.packet(new Point(2,75,0),true);require(!receipt.confirmed(true),"OTHER_BLOCK_ACK_ACCEPTED");
        receipt.packet(new Point(1,75,0),true);require(!receipt.confirmed(false),"LIVE_OBSTRUCTION_IGNORED");
        require(receipt.confirmed(true),"MATCHED_LEAF_ACK_MISSING");
        current[0]=false;boolean revoked=false;
        try{receipt.confirmed(true);}catch(dev.aitalkstreamer.mc.core.LocalTaskFailure expected){revoked=true;}
        require(revoked,"REVOKED_LEAF_CLEARANCE_CONTINUED");receipt.close();
        var stock=new ArrayList<NativeToolPlan.Candidate>(Collections.nCopies(37,null));
        stock.set(36,new NativeToolPlan.Candidate(true,2,44));
        require(NativeToolPlan.choose(stock,0)==36,"OFFHAND_TOOL_WAS_UNAVAILABLE");
        System.out.println("PASS arrival radius around an obstructed center, exact stance, already arrived, vertical gap and blocked edges");
        System.out.println("PASS bounded reachable observations and leaf-clearance server/world/context receipt fences");
    }
}

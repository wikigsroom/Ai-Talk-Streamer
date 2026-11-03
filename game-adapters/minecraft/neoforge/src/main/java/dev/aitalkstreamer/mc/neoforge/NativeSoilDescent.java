package dev.aitalkstreamer.mc.neoforge;

import java.util.*;
import static dev.aitalkstreamer.mc.neoforge.NativeWalkPlanner.Point;
import static dev.aitalkstreamer.mc.neoforge.NativeStepPlan.*;

/** One supported downward step towards received stone; only the soil adapter can admit cuts. */
public final class NativeSoilDescent {
    private NativeSoilDescent() { }
    public static Step choose(Terrain terrain, Point start, Point source, boolean knownSource) {
        Objects.requireNonNull(terrain);Objects.requireNonNull(start);Objects.requireNonNull(source);
        long drop=(long)start.y()-source.y();
        if(!knownSource || drop<1 || drop>12 || Math.abs((long)start.x()-source.x())>12
                || Math.abs((long)start.z()-source.z())>12 || start.y()<=Integer.MIN_VALUE+2
                || start.y()>=Integer.MAX_VALUE-2 || !terrain.destination(start)
                || terrain.clearance(new Point(start.x(),start.y()+1,start.z()))!=Cell.CLEAR) return null;
        Step best=null;
        for(int[] d:new int[][]{{1,0},{-1,0},{0,1},{0,-1}}) {
            long x=(long)start.x()+d[0],z=(long)start.z()+d[1];
            if(x<Integer.MIN_VALUE || x>Integer.MAX_VALUE || z<Integer.MIN_VALUE || z>Integer.MAX_VALUE)continue;
            Point next=new Point((int)x,start.y()-1,(int)z);
            if(next.distanceSquared(source)>=start.distanceSquared(source)
                    || new Point(next.x(),next.y()-1,next.z()).equals(source)
                    || !terrain.support(new Point(next.x(),next.y()-1,next.z())))continue;
            var cuts=new ArrayList<Point>();boolean blocked=false;
            // Include the upper sweep before the head/body cells. Never remove
            // either the current support or the proposed landing support.
            for(Point cell:List.of(new Point(next.x(),start.y()+1,next.z()),
                    new Point(next.x(),start.y(),next.z()),next)) {
                Cell value=terrain.clearance(cell);
                if(value==Cell.BLOCKED){blocked=true;break;}
                if(value==Cell.CUT)cuts.add(cell);
            }
            if(blocked)continue;
            Step candidate=new Step(start,next,cuts);
            if(best==null || next.distanceSquared(source)<best.to().distanceSquared(source)
                    || next.distanceSquared(source)==best.to().distanceSquared(source) && cuts.size()<best.cuts().size())best=candidate;
        }
        return best;
    }
}

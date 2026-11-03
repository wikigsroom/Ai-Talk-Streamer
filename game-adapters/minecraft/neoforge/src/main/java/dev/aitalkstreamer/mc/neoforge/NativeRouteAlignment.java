package dev.aitalkstreamer.mc.neoforge;

import java.util.HashMap;
import java.util.Map;
import static dev.aitalkstreamer.mc.neoforge.NativeWalkPlanner.Point;

/** A task-local ordinary-input budget. Terrain and input authority stay with the native adapter. */
public final class NativeRouteAlignment {
    public static final int MAX_EPISODE_TICKS=40, MAX_TASK_TICKS=120, MAX_EPISODES=6;
    public static final double CENTER_DISTANCE_SQUARED=.01;
    public enum State { IDLE, MOVING, ALIGNED, BLOCKED, TIMED_OUT }
    private Point anchor;
    private int episodeTicks,totalTicks,episodes;
    private final Map<Point,Integer> attempts=new HashMap<>();
    public void reset(){anchor=null;episodeTicks=totalTicks=episodes=0;attempts.clear();}
    public static boolean centered(Point p,double x,double z){
        return Double.isFinite(x)&&Double.isFinite(z)
                && Math.pow(p.x()+.5-x,2)+Math.pow(p.z()+.5-z,2)<=CENTER_DISTANCE_SQUARED;
    }
    public boolean begin(Point p,double x,double z,boolean admitted){
        if(anchor!=null || !admitted || !Double.isFinite(x) || !Double.isFinite(z) || centered(p,x,z) || episodes>=MAX_EPISODES
                || totalTicks>=MAX_TASK_TICKS || attempts.getOrDefault(p,0)>=2)return false;
        anchor=p;episodeTicks=0;episodes++;attempts.merge(p,1,Integer::sum);return true;
    }
    public State observe(Point p,double x,double z,boolean admitted){
        if(anchor==null)return State.IDLE;
        if(!anchor.equals(p) || !admitted || !Double.isFinite(x) || !Double.isFinite(z)){
            anchor=null;return State.BLOCKED;
        }
        if(centered(p,x,z)){anchor=null;return State.ALIGNED;}
        if(episodeTicks>=MAX_EPISODE_TICKS || totalTicks>=MAX_TASK_TICKS){anchor=null;return State.TIMED_OUT;}
        episodeTicks++;totalTicks++;return State.MOVING;
    }
    public boolean active(){return anchor!=null;}
    public Point anchor(){return anchor;}
    public int episodeTicks(){return episodeTicks;}
    public int totalTicks(){return totalTicks;}
    public int episodes(){return episodes;}
}

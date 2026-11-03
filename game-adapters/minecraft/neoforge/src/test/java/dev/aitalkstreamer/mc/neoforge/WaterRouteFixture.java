package dev.aitalkstreamer.mc.neoforge;

import java.util.*;
import static dev.aitalkstreamer.mc.neoforge.NativeWalkPlanner.*;

/** Real route admission and search, fixture terrain only; never counts as actual swimming. */
public final class WaterRouteFixture {
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
    public static void main(String[] args) {
        Point start=new Point(0,64,0),water=new Point(1,64,0),shore=new Point(2,65,0);
        Set<Point> cells=Set.of(start,water,shore);
        Terrain terrain=new Terrain(){public boolean stand(Point p){return cells.contains(p);}
            public boolean step(Point a,Point b){return cells.contains(a) && cells.contains(b);}};
        Route route=NativeWalkPlanner.find(terrain,start,shore,0,256);
        check(NativeWaterRoute.admissible(start,shore,true,route),"reachable dry bank");
        check(!NativeWaterRoute.admissible(start,shore,false,route),"water is not arrival");
        check(!NativeWaterRoute.admissible(start,start,true,new Route(List.of(start),true,0)),"no in-place success");
        check(!NativeWaterRoute.admissible(start,shore,true,new Route(List.of(start,water),false,2)),"no partial promise");
        check(!NativeWaterRoute.admissible(start,shore,true,new Route(List.of(start,new Point(9,64,0),shore),true,3)),"all route cells bounded");
        Terrain blocked=new Terrain(){public boolean stand(Point p){return cells.contains(p);}
            public boolean step(Point a,Point b){return false;}};
        check(!NativeWaterRoute.admissible(start,shore,true,NativeWalkPlanner.find(blocked,start,shore,0,256)),"collision blocked");
        check(!NativeWaterRoute.admissible(start,new Point(9,65,0),true,route),"distant bank rejected");
        check(!NativeWaterRoute.admissible(start,shore,true,new Route(List.of(water,shore),true,2)),"original player origin required");
        System.out.println("PASS 8 water route admission boundaries; fixture terrain, no actual swimming");
    }
}

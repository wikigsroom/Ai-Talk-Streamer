package dev.aitalkstreamer.mc.neoforge;

import java.util.*;
import static dev.aitalkstreamer.mc.neoforge.NativeWalkPlanner.Point;

/** Regression: directional sampling alone exhausts visits on a roof while omitting its descent. */
public final class FrontierFixture {
    private static int checks;
    private static void check(boolean value) { checks++; if (!value) throw new AssertionError("FRONTIER_REGRESSION_"+checks); }
    public static void main(String[] args) {
        var origin=new Point(0,79,0); var ground=new Point(1,75,1); var lowerLeaf=new Point(0,74,1);
        var wet=new Point(0,73,2); var cells=new ArrayList<Point>(List.of(ground,lowerLeaf,wet));
        for(int x=-7;x<=7;x++)for(int z=-7;z<=7;z++)if(x!=0 || z!=0)cells.add(new Point(x,79,z));
        var selected=NativeFrontiers.select(origin,cells,p->!p.equals(wet),p->!p.equals(lowerLeaf));
        check(selected.get(0).equals(ground)); check(selected.size()<=8);
        check(cells.containsAll(selected)); check(new HashSet<>(selected).size()==selected.size());
        check(!selected.contains(wet));
        check(NativeFrontiers.select(origin,List.of(),p->true,p->true).isEmpty());
        var flat=NativeFrontiers.select(origin,cells.stream().filter(p->p.y()==79).toList(),p->true,p->true);
        check(flat.size()==8); check(flat.stream().allMatch(p->p.y()==79));
        var unsafe=NativeFrontiers.select(origin,List.of(ground),p->false,p->true);
        check(unsafe.isEmpty());
        System.out.println("PASS "+checks+" frontier regression checks; no world writes or input");
    }
}

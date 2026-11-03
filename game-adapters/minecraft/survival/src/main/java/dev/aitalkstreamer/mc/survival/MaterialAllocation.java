package dev.aitalkstreamer.mc.survival;

import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;

/** Shared capacity allocation for pending materials and retained outputs; no inventory effects. */
final class MaterialAllocation {
    static final int MAX_NEEDS=640, MAX_UNITS=2_621_440, MAX_STEPS=2_000_000;
    record Need(String key,int count,Set<Integer> slots,boolean retained) {
        Need {
            require(key!=null && !key.isBlank() && key.length()<=256 && count>=0 && count<=MAX_UNITS,"GAME_MATERIAL_REQUIREMENT_INVALID");
            slots=Set.copyOf(slots);require(slots.stream().allMatch(s->s>=0 && s<36),"GAME_MATERIAL_REQUIREMENT_INVALID");
        }
    }
    record Assigned(String key,int slot,int count) { }
    record Limit(Set<Integer> slots,int maximum) {
        Limit {
            require(slots!=null && maximum>=0,"GAME_MATERIAL_REQUIREMENT_INVALID");slots=Set.copyOf(slots);
            require(slots.stream().allMatch(s->s>=0 && s<36),"GAME_MATERIAL_REQUIREMENT_INVALID");
        }
    }
    record Result(List<Assigned> assignments,Map<String,Integer> missing) {
        Result {assignments=List.copyOf(assignments);missing=Collections.unmodifiableMap(new LinkedHashMap<>(missing));}
        boolean complete() {return missing.isEmpty();}
    }
    private static final class Edge {
        final int to,reverse;int capacity;
        Edge(int to,int reverse,int capacity) {this.to=to;this.reverse=reverse;this.capacity=capacity;}
    }
    private final List<List<Edge>> graph;
    private static final class Budget {
        int steps;
        void step() {require(++steps<=MAX_STEPS,"GAME_MATERIAL_ALLOCATION_LIMIT");}
    }
    private int[] level,next;private final Budget budget;
    private MaterialAllocation(int nodes) {this(nodes,new Budget());}
    private MaterialAllocation(int nodes,Budget budget) {this.budget=budget;graph=new ArrayList<>();for(int i=0;i<nodes;i++) graph.add(new ArrayList<>());}
    private void step() {budget.step();}
    private Edge edge(int from,int to,int count) {
        var forward=new Edge(to,graph.get(to).size(),count);var reverse=new Edge(from,graph.get(from).size(),0);
        graph.get(from).add(forward);graph.get(to).add(reverse);return forward;
    }
    private int flow(Edge edge) {return graph.get(edge.to).get(edge.reverse).capacity;}
    private boolean levels(int source,int sink) {
        level=new int[graph.size()];Arrays.fill(level,-1);level[source]=0;var queue=new ArrayDeque<Integer>();queue.add(source);
        while(!queue.isEmpty()) {int from=queue.removeFirst();for(var edge:graph.get(from)) {step();if(edge.capacity>0 && level[edge.to]<0) {level[edge.to]=level[from]+1;queue.add(edge.to);}}}
        return level[sink]>=0;
    }
    private int push(int from,int sink,int limit) {
        if(from==sink) return limit;
        for(;next[from]<graph.get(from).size();next[from]++) {
            step();var edge=graph.get(from).get(next[from]);
            if(edge.capacity<=0 || level[edge.to]!=level[from]+1) continue;
            int amount=push(edge.to,sink,Math.min(limit,edge.capacity));
            if(amount>0) {edge.capacity-=amount;graph.get(edge.to).get(edge.reverse).capacity+=amount;return amount;}
        }
        return 0;
    }
    private void maximize(int source,int sink) {
        while(levels(source,sink)) {next=new int[graph.size()];while(push(source,sink,MAX_UNITS)>0) { }}
    }
    static Result allocate(List<CraftPlan.Supply> inventory,List<Need> requirements) {
        require(inventory.size()<=36 && inventory.stream().map(CraftPlan.Supply::inventorySlot).distinct().count()==inventory.size(),"GAME_CRAFT_INVENTORY_INVALID");
        require(requirements.size()<=MAX_NEEDS && requirements.stream().map(Need::key).distinct().count()==requirements.size(),"GAME_MATERIAL_REQUIREMENT_INVALID");
        long total=requirements.stream().mapToLong(Need::count).sum();require(total<=MAX_UNITS,"GAME_MATERIAL_REQUIREMENT_LIMIT");
        var stock=inventory.stream().sorted(Comparator.comparingInt(CraftPlan.Supply::inventorySlot)).toList();
        var needs=requirements.stream().sorted(Comparator.comparing(Need::retained).reversed().thenComparingInt(n->n.slots().size()).thenComparing(Need::key)).toList();
        int start=1+stock.size(),sink=start+needs.size();var solver=new MaterialAllocation(sink+1);
        var supplyEdges=new ArrayList<List<Edge>>();var sinks=new ArrayList<Edge>();
        for(int s=0;s<stock.size();s++) solver.edge(0,s+1,Math.min(stock.get(s).count(),(int)total));
        for(int n=0;n<needs.size();n++) {
            var need=needs.get(n);var edges=new ArrayList<Edge>();
            for(int s=0;s<stock.size();s++) edges.add(need.slots().contains(stock.get(s).inventorySlot())?solver.edge(s+1,start+n,need.count()):null);
            supplyEdges.add(edges);sinks.add(solver.edge(start+n,sink,need.retained()?need.count():0));
        }
        // First retain existing outputs. Their total flow cannot be taken back by
        // later material allocation, but residual paths may choose another equal stack.
        solver.maximize(0,sink);
        for(int n=0;n<needs.size();n++) if(needs.get(n).retained()) require(sinks.get(n).capacity==0,"GAME_MATERIAL_HOLD_UNAVAILABLE");
        for(int n=0;n<needs.size();n++) if(!needs.get(n).retained()) sinks.get(n).capacity=needs.get(n).count();
        solver.maximize(0,sink);
        var assigned=new ArrayList<Assigned>();var missing=new LinkedHashMap<String,Integer>();
        for(int n=0;n<needs.size();n++) {
            var need=needs.get(n);if(sinks.get(n).capacity>0) missing.put(need.key(),sinks.get(n).capacity);
            for(int s=0;s<stock.size();s++) {var edge=supplyEdges.get(n).get(s);if(edge!=null && solver.flow(edge)>0) assigned.add(new Assigned(need.key(),stock.get(s).inventorySlot(),solver.flow(edge)));}
        }
        return new Result(assigned,missing);
    }

    /** Joint consumption under absolute, possibly overlapping inventory conditions. No item is held twice. */
    static Result constrained(List<CraftPlan.Supply> inventory,List<Need> requirements,List<Limit> limits) {
        require(inventory.size()<=36 && inventory.stream().map(CraftPlan.Supply::inventorySlot).distinct().count()==inventory.size(),"GAME_CRAFT_INVENTORY_INVALID");
        require(requirements.size()<=MAX_NEEDS && requirements.stream().map(Need::key).distinct().count()==requirements.size()
                && requirements.stream().noneMatch(Need::retained) && limits.size()<=MaterialReservations.MAX_OUTPUTS,"GAME_MATERIAL_REQUIREMENT_INVALID");
        long requested=requirements.stream().mapToLong(Need::count).sum();require(requested<=MAX_UNITS,"GAME_MATERIAL_REQUIREMENT_LIMIT");
        var stock=inventory.stream().sorted(Comparator.comparingInt(CraftPlan.Supply::inventorySlot)).toList();
        var needs=requirements.stream().sorted(Comparator.comparingInt((Need n)->n.slots().size()).thenComparing(Need::key)).toList();
        var distinct=new HashMap<Set<Integer>,Integer>();
        for(var limit:limits) {
            var slots=new TreeSet<Integer>();long have=0;
            for(var s:stock) if(limit.slots().contains(s.inventorySlot()) && s.count()>0) {slots.add(s.inventorySlot());have+=s.count();}
            if(!slots.isEmpty() && limit.maximum()<have) distinct.merge(Set.copyOf(slots),limit.maximum(),Math::min);
        }
        var conditions=distinct.entrySet().stream().map(e->new Limit(e.getKey(),e.getValue()))
                .sorted(Comparator.comparingInt((Limit l)->l.slots().size()).thenComparing(l->l.slots().stream().sorted().toList().toString())).toList();
        var laminar=new ArrayList<Limit>();
        for(var candidate:conditions) if(laminar.stream().allMatch(other->Collections.disjoint(candidate.slots(),other.slots())
                || candidate.slots().containsAll(other.slots()) || other.slots().containsAll(candidate.slots()))) laminar.add(candidate);
        var budget=new Budget();var pending=new ArrayDeque<int[]>();var seen=new HashSet<String>();int[] initial=new int[36];
        for(var s:stock) initial[s.inventorySlot()]=Math.min(s.count(),(int)requested);
        pending.push(initial);seen.add(Arrays.toString(initial));
        var missing=new LinkedHashMap<String,Integer>();for(var need:needs) if(need.count()>0) missing.put(need.key(),need.count());
        Result best=new Result(List.of(),missing);int bestUnits=0;
        while(!pending.isEmpty()) {
            budget.step();int[] bounds=pending.pop();var result=bounded(stock,needs,laminar,bounds,budget);
            int[] used=new int[36];int units=0;
            for(var assigned:result.assignments()) {used[assigned.slot()]=Math.addExact(used[assigned.slot()],assigned.count());units=Math.addExact(units,assigned.count());}
            if(units<=bestUnits) continue;
            Limit violation=null;int excess=0;
            for(var condition:conditions) {
                int consumed=0;for(int slot:condition.slots()) {budget.step();consumed+=used[slot];}
                if(consumed>condition.maximum()) {violation=condition;excess=consumed-condition.maximum();break;}
            }
            if(violation==null) {best=result;bestUnits=units;if(units==requested)return best;continue;}
            var active=violation.slots().stream().filter(s->used[s]>0).sorted(Comparator.reverseOrder()).toList();
            // Any feasible alternative reduces at least one of these slots by ceil(excess / active slots).
            int reduction=(excess+active.size()-1)/active.size();
            for(int slot:active) if(used[slot]>=reduction) {
                int[] child=bounds.clone();child[slot]=used[slot]-reduction;
                if(seen.add(Arrays.toString(child))) {require(seen.size()<=4096,"GAME_MATERIAL_ALLOCATION_LIMIT");pending.push(child);}
            }
        }
        return best;
    }
    private static Result bounded(List<CraftPlan.Supply> stock,List<Need> needs,List<Limit> groups,int[] bounds,Budget budget) {
        int start=1+groups.size(),needStart=start+stock.size(),sink=needStart+needs.size();var solver=new MaterialAllocation(sink+1,budget);
        for(int i=0;i<groups.size();i++) {
            int parent=-1;
            for(int j=0;j<groups.size();j++) if(i!=j && groups.get(j).slots().containsAll(groups.get(i).slots())
                    && (parent<0 || groups.get(j).slots().size()<groups.get(parent).slots().size()))parent=j;
            solver.edge(parent<0?0:parent+1,i+1,groups.get(i).maximum());
        }
        for(int s=0;s<stock.size();s++) {
            int parent=-1,slot=stock.get(s).inventorySlot();
            for(int g=0;g<groups.size();g++) if(groups.get(g).slots().contains(slot)
                    && (parent<0 || groups.get(g).slots().size()<groups.get(parent).slots().size()))parent=g;
            solver.edge(parent<0?0:parent+1,start+s,bounds[slot]);
        }
        var edges=new ArrayList<List<Edge>>();var sinks=new ArrayList<Edge>();
        for(int n=0;n<needs.size();n++) {
            var need=needs.get(n);var supplied=new ArrayList<Edge>();
            for(int s=0;s<stock.size();s++) supplied.add(need.slots().contains(stock.get(s).inventorySlot())?solver.edge(start+s,needStart+n,need.count()):null);
            edges.add(supplied);sinks.add(solver.edge(needStart+n,sink,need.count()));
        }
        solver.maximize(0,sink);var assigned=new ArrayList<Assigned>();var missing=new LinkedHashMap<String,Integer>();
        for(int n=0;n<needs.size();n++) {
            if(sinks.get(n).capacity>0)missing.put(needs.get(n).key(),sinks.get(n).capacity);
            for(int s=0;s<stock.size();s++) {var edge=edges.get(n).get(s);if(edge!=null && solver.flow(edge)>0)assigned.add(new Assigned(needs.get(n).key(),stock.get(s).inventorySlot(),solver.flow(edge)));}
        }
        return new Result(assigned,missing);
    }
}

package dev.aitalkstreamer.mc.neoforge;

import com.google.gson.JsonObject;
import com.google.gson.JsonArray;
import dev.aitalkstreamer.mc.core.*;
import net.minecraft.client.Minecraft;
import net.minecraft.core.BlockPos;
import net.minecraft.core.Direction;
import net.minecraft.core.registries.BuiltInRegistries;
import net.minecraft.resources.ResourceLocation;
import net.minecraft.tags.BlockTags;
import net.minecraft.tags.FluidTags;
import net.minecraft.world.entity.item.ItemEntity;
import net.minecraft.world.entity.monster.Monster;
import net.minecraft.world.item.*;
import net.minecraft.world.level.ClipContext;
import net.minecraft.world.level.block.*;
import net.minecraft.world.level.block.state.BlockState;
import net.minecraft.world.phys.*;
import java.util.*;
import static dev.aitalkstreamer.mc.core.Json.*;
import static dev.aitalkstreamer.mc.core.LocalTaskFailure.Reason.*;
import static dev.aitalkstreamer.mc.neoforge.NativeWalkPlanner.Point;

/** Walking and collection on the original player, through one task-owned input scope. */
final class NativeTravel implements ExecutorTaskSession.Runtime {
    private final Minecraft client;
    private final NativeInputOwner inputs;
    private final ArrayDeque<Point> path = new ArrayDeque<>();
    private JsonObject task;
    private ControlArbiter control;
    private ControlArbiter.Permit permit;
    private NativeInputOwner.Scope scope;
    private Runnable finished;
    private InventoryTarget inventoryTarget;
    private NativeToolBelt tools;
    private Point destination, pathGoal;
    private double radius, pathRadius;
    private Object world, player, connection;
    private boolean closed = true, gather;
    private Item wanted;
    private BlockPos blockTarget;
    private BlockPos coverTarget;
    private Point coverApproach;
    private BlockPos leafCut;
    private NativeStepReceipt leafReceipt;
    private final Set<BlockPos> leafCuts = new HashSet<>();
    private JsonObject navigationCache;
    private Object navigationWorld, navigationPlayer, navigationConnection;
    private BlockPos navigationFeet;
    private long navigationAt;
    private final Set<BlockPos> excavatedCover = new HashSet<>();
    private Point miningStance;
    private final Set<BlockPos> skippedSources = new HashSet<>();
    private final Map<BlockPos,Long> blockedSources = new LinkedHashMap<>();
    private Object resourceWorld;
    private int stalledApproaches;
    private final Set<UUID> skippedDrops = new HashSet<>();
    private Point pickupExclusionFeet, gatherRouteGoal;
    private int ticks, searches, walked, attemptedBlocks, inventoryPackets;
    private int confirmedInventory;
    private int arrivalTicks;
    private long progressAt, miningAt, pickupUntil;
    private Vec3 lastProgress;
    private int lastInventory;
    private NativeStepPlan.Step stair;
    private NativeStepReceipt stairReceipt;
    private BlockPos stairCut;
    private int stairSteps, stairCuts, stairPackets;
    private long stairStarted;
    private final Set<BlockPos> stairCleared = new HashSet<>();
    private final List<JsonObject> stairEvidence = new ArrayList<>();
    private JsonObject routePreflight;
    private JsonObject movementBlocked;
    private JsonObject routeFailure;
    private int waterTicks;
    private boolean waterRoute;
    private boolean navigationSwimming;
    private int escapeSprintTicks;
    private static final int MAX_ROUTE_RECOVERIES = 4;
    private int routeRecoveries;
    private JsonObject lastRouteRecovery;

    NativeTravel(Minecraft client, NativeInputOwner inputs) {
        this.client = client; this.inputs = inputs;
    }
    private static long now() { return System.nanoTime() / 1_000_000; }
    private static BlockPos pos(Point p) { return new BlockPos(p.x(), p.y(), p.z()); }
    private static Point point(BlockPos p) { return new Point(p.getX(), p.getY(), p.getZ()); }
    private Point feet() { return point(client.player.blockPosition()); }
    private void ready(boolean allowWater) {
        require(client.isSameThread(), "GAME_WRONG_THREAD");
        require(client.level != null && client.player != null && client.getConnection() != null && client.gameMode != null,
                "GAME_WORLD_UNAVAILABLE");
        require(client.player.isAlive() && client.isWindowActive() && !client.isPaused() && client.screen == null,
                "GAME_GUI_BLOCKED");
        require(!client.player.getAbilities().instabuild && !client.player.isSpectator(), "GAME_SURVIVAL_REQUIRED");
        if (client.player.isPassenger() || client.player.isFallFlying() || client.player.isInWater() && !allowWater
                || client.player.isInLava() || client.player.onClimbable()) {
            movementBlocked = obj("observed_at",java.time.Instant.now().toString(),
                    "passenger",client.player.isPassenger(),"fall_flying",client.player.isFallFlying(),
                    "in_water",client.player.isInWater(),"in_lava",client.player.isInLava(),
                    "climbable",client.player.onClimbable(),"on_ground",client.player.onGround(),
                    "feet_block",BuiltInRegistries.BLOCK.getKey(client.level.getBlockState(client.player.blockPosition()).getBlock()).toString());
            throw new LocalTaskFailure(NAVIGATION_MOVEMENT_BLOCKED);
        }
        require(!client.player.isUsingItem() && client.player.containerMenu == client.player.inventoryMenu,
                "GAME_MOVEMENT_CONTEXT_UNSUPPORTED");
    }
    private Point destination(JsonObject goal, BaseTarget base) {
        if (str(goal, "skill").equals("return_base")) {
            require(base != null, "GAME_BASE_TARGET_REQUIRED");
            require(base.dimension().equals(client.level.dimension().location().toString()), "GAME_BASE_DIMENSION_CHANGED");
            return new Point(base.x(), base.y(), base.z());
        }
        var target = goal.getAsJsonObject("target");
        require(str(target, "dimension").equals(client.level.dimension().location().toString()), "GAME_DIMENSION_CHANGED");
        return new Point(Math.toIntExact(num(target, "x")), Math.toIntExact(num(target, "y")), Math.toIntExact(num(target, "z")));
    }
    JsonObject check(JsonObject goal, BaseTarget base) {
        String reason = null;
        try {
            String skill = str(goal, "skill"); ready(!skill.equals("gather"));
            require(List.of("navigate", "return_base", "gather").contains(skill), "GAME_CAPABILITY_UNAVAILABLE");
            if (skill.equals("gather")) {
                Item item = item(goal); require(resourceSupported(item), "GAME_GATHER_UNSUPPORTED");
                require(client.player.getInventory().getFreeSlot() >= 0 || inventoryCount(item) > 0, "GAME_INVENTORY_FULL");
                // A nearby block alone does not establish a safe mining approach. This
                // read-only check uses fresh exclusions rather than the previous task's.
                require(!drops(item).isEmpty() || findBlock(item, Set.of()) != null, "GAME_GATHER_RESOURCE_UNAVAILABLE");
                require(gatherReachable(item), "GAME_NAVIGATION_NO_ROUTE");
            } else {
                Point target = destination(goal, base);
                double distance = base == null ? goal.get("radius").getAsDouble() : base.radius();
                boolean swimming=client.player.isInWater();
                var route = NativeWalkPlanner.find(swimming ? waterTerrain() : terrain(true), feet(), target, swimming ? 0 : distance, swimming ? 256 : 1024);
                var step=swimming || route.reachesGoal()?null:stepPlan(target);
                if (swimming) require(NativeWaterRoute.admissible(feet(),target,stand(target),route), "GAME_NAVIGATION_NO_ROUTE");
                routePreflight=obj("target",obj("x",target.x(),"y",target.y(),"z",target.z()),
                        "goal_standable",stand(target),"route_reaches_goal",route.reachesGoal(),"step_available",step!=null);
                require(!route.points().isEmpty() && (feet().distanceSquared(target) > 24 * 24 || route.reachesGoal())
                                || step != null,
                        "GAME_NAVIGATION_NO_ROUTE");
            }
        } catch (Rejected denied) { reason = denied.code; }
        catch (LocalTaskFailure denied) { reason = denied.code(); }
        return obj("allowed", reason == null, "reason", reason, "source", "runtime_client", "unknown_fields",
                List.of("unloaded_route", "server_movement_restrictions", "server_block_rules", "future_drops_and_inventory_causality"));
    }
    @Override public void start(JsonObject accepted, ControlArbiter control, ControlArbiter.Permit permit,
                                InventoryTarget target, BaseTarget base, Runnable finished) {
        JsonObject goal = accepted.getAsJsonObject("goal"); String skill = str(goal, "skill");
        ready(!skill.equals("gather")); require(closed, "GAME_TASK_BUSY");
        this.task = accepted.deepCopy(); this.control = control; this.permit = permit; this.finished = finished;
        world = client.level; player = client.player; connection = client.getConnection();
        if(resourceWorld!=world){blockedSources.clear();resourceWorld=world;}
        blockedSources.entrySet().removeIf(row -> now()-row.getValue()>60000);
        scope = inputs.scope(); path.clear(); pathGoal = destination = null; blockTarget = null;
        miningStance = null; coverTarget=null;coverApproach=null;excavatedCover.clear();skippedSources.clear(); skippedDrops.clear();
        pickupExclusionFeet=feet();gatherRouteGoal=null;
        leafCut=null;leafReceipt=null;leafCuts.clear();
        stalledApproaches=0;
        ticks = searches = walked = attemptedBlocks = inventoryPackets = arrivalTicks = escapeSprintTicks = 0; confirmedInventory = -1;
        waterTicks=0;waterRoute=false;
        routeFailure=null;
        routeRecoveries=0;lastRouteRecovery=null;
        stair=null;stairReceipt=null;stairCut=null;stairSteps=stairCuts=stairPackets=0;stairStarted=0;stairCleared.clear();stairEvidence.clear();
        inventoryTarget = target; gather = skill.equals("gather");
        progressAt = now(); lastProgress = client.player.position(); miningAt = pickupUntil = 0;
        if (gather) {
            wanted = item(goal); require(resourceSupported(wanted) && target != null, "GAME_GATHER_UNSUPPORTED");
            lastInventory = inventoryCount(wanted);
            require(lastInventory == target.baseline(), "GAME_GATHER_INVENTORY_CHANGED");
        } else {
            destination = destination(goal, base); radius = base == null ? goal.get("radius").getAsDouble() : base.radius();
        }
        closed = false;
        tools=new NativeToolBelt(client,scope,control,permit,()->!closed && client.level==world && client.player==player && client.getConnection()==connection);
    }
    private Item item(JsonObject goal) {
        ResourceLocation id = ResourceLocation.tryParse(str(goal, "item_id"));
        require(id != null && BuiltInRegistries.ITEM.containsKey(id), "GAME_ITEM_UNKNOWN");
        return BuiltInRegistries.ITEM.get(id);
    }
    private int inventoryCount(Item item) {
        int result = 0;
        for (int i = 0; i < client.player.getInventory().getContainerSize(); i++) {
            var stack = client.player.getInventory().getItem(i); if (stack.is(item)) result += stack.getCount();
        }
        return result;
    }
    void inventoryPacket() {
        if (!closed && gather && client.player == player && client.level == world && client.getConnection() == connection) {
            inventoryPackets++; confirmedInventory = inventoryCount(wanted);
        }
    }
    @Override public void tick() {
        if (closed) return;
        ready(!gather); scope.current();
        if (client.level != world || client.player != player || client.getConnection() != connection)
            throw new LocalTaskFailure(gather ? GATHER_CONTEXT_CHANGED : NAVIGATION_CONTEXT_CHANGED);
        ticks++;
        if (client.player.isInWater() && ++waterTicks > NativeWaterRoute.MAX_WATER_TICKS)
            throw new LocalTaskFailure(NAVIGATION_NO_PROGRESS);
        tools.tick();if(tools.pending()){scope.move(0,false,control,permit);return;}
        if (gather) collect();
        else if (walk(destination, radius)) { stop(); finished.run(); return; }
        if (closed) return;
        int count = gather ? inventoryCount(wanted) : 0;
        if (client.player.position().distanceToSqr(lastProgress) > .16 || count != lastInventory) {
            progressAt = now(); lastProgress = client.player.position(); lastInventory = count;
        }
        if (now() - progressAt > (gather || stair != null ? 18000 : 8000))
            // Lack of movement/inventory progress is not a missing server acknowledgement.
            // The separate per-block acknowledgement deadline below remains fatal.
            throw new LocalTaskFailure(gather ? GATHER_NO_PROGRESS : NAVIGATION_NO_PROGRESS);
    }
    private boolean hazardous(BlockState state) {
        Block block = state.getBlock();
        return block instanceof BaseFireBlock || block instanceof CactusBlock || block instanceof MagmaBlock
                || block instanceof CampfireBlock || block instanceof SweetBerryBushBlock || block instanceof WitherRoseBlock
                || block instanceof NetherPortalBlock || block instanceof EndPortalBlock || block instanceof PowderSnowBlock
                || block instanceof WebBlock || block instanceof PointedDripstoneBlock;
    }
    private boolean stand(Point point) { return stand(point, false); }
    private double shallowSurfaceY(Point point) {
        BlockPos at=pos(point);
        if(!client.level.hasChunkAt(at))return Double.NaN;
        BlockState state=client.level.getBlockState(at);
        boolean known=state.is(Blocks.DIRT_PATH) || state.is(Blocks.FARMLAND);
        if(!known || !state.getFluidState().isEmpty() || state.hasBlockEntity())return Double.NaN;
        var boxes=state.getCollisionShape(client.level,at).toAabbs();
        if(boxes.size()!=1)return Double.NaN;
        var box=boxes.getFirst();
        return NativePartialFooting.shallowSurfaceY(point.y(),known,true,
                box.minX,box.minY,box.minZ,box.maxX,box.maxY,box.maxZ);
    }
    private double footY(Point point) {
        double shallow=shallowSurfaceY(point);
        return Double.isFinite(shallow)?shallow:point.y();
    }
    private boolean stand(Point point, boolean leaves) {
        // A grave/slab can support the actual feet above the integer cell floor.
        // This exception describes the real current player, never an unvisited
        // cell or an assumed center position inside that obstacle.
        if(point.equals(feet()) && partialFooting()) return true;
        BlockPos at = pos(point);
        if (at.getY() <= client.level.getMinBuildHeight() || at.getY() + 2 >= client.level.getMaxBuildHeight()
                || !client.level.getWorldBorder().isWithinBounds(at)) return false;
        for (int dy = -1; dy <= 2; dy++) {
            BlockPos p = at.offset(0, dy, 0);
            if (!client.level.hasChunkAt(p)) return false;
            BlockState state = client.level.getBlockState(p);
            if (!state.getFluidState().isEmpty() || hazardous(state)) return false;
        }
        BlockPos below = at.below();
        var support = client.level.getBlockState(below);
        // Leaves have a real full-height collision surface despite not accepting sturdy-face attachments.
        var shape = support.getCollisionShape(client.level, below);
        var landing = new AABB(at.getX()+.19,at.getY()-.02,at.getZ()+.19,
                at.getX()+.81,at.getY()+.01,at.getZ()+.81);
        boolean stairFloor = support.is(BlockTags.STAIRS) && !shape.isEmpty() && shape.max(Direction.Axis.Y)==1
                && shape.toAabbs().stream().anyMatch(box -> box.move(below).intersects(landing));
        double shallow=shallowSurfaceY(point),feetY=Double.isFinite(shallow)?shallow:point.y();
        boolean floor = Double.isFinite(shallow) || support.isFaceSturdy(client.level, below, Direction.UP)
                || support.is(BlockTags.LEAVES) && !shape.isEmpty() && shape.max(Direction.Axis.Y) == 1 || stairFloor;
        if (!floor) return supportedIntegerOrigin(point);
        var body = new AABB(at.getX() + .19, feetY + .01, at.getZ() + .19,
                at.getX() + .81, feetY + 1.81, at.getZ() + .81);
        return client.level.noCollision(client.player, body) || leaves && leafSpace(body) || supportedIntegerOrigin(point);
    }
    private boolean loadedDry(AABB area) {
        for(int x=(int)Math.floor(area.minX);x<=(int)Math.floor(area.maxX);x++)
            for(int y=(int)Math.floor(area.minY);y<=(int)Math.floor(area.maxY);y++)
                for(int z=(int)Math.floor(area.minZ);z<=(int)Math.floor(area.maxZ);z++) {
                    var at=new BlockPos(x,y,z);
                    if(y<client.level.getMinBuildHeight() || y>=client.level.getMaxBuildHeight()
                            || !client.level.hasChunkAt(at) || !client.level.getWorldBorder().isWithinBounds(at))return false;
                    var state=client.level.getBlockState(at);
                    if(hazardous(state) || !state.getFluidState().isEmpty())return false;
                }
        return true;
    }
    private boolean clearSpace(AABB area,boolean leaves) {
        return loadedDry(area) && (client.level.noCollision(client.player,area) || leaves && leafSpace(area));
    }
    private boolean partialFooting() {
        var body=client.player.getBoundingBox();
        if(!NativePartialFooting.admissible(feet().y(),body.minY,body.getYsize(),
                client.player.onGround(),true,true,true))return false;
        return NativePartialFooting.admissible(feet().y(),body.minY,body.getYsize(),client.player.onGround(),
                client.level.noCollision(client.player,body),
                !client.level.noCollision(client.player,body.move(0,-.025,0)),
                loadedDry(body.move(0,-.025,0)));
    }
    private boolean supportedIntegerOrigin(Point point) {
        if (!point.equals(feet())) return false;
        var body=client.player.getBoundingBox();
        if (!NativePartialFooting.supportedIntegerOrigin(point.y(),body.minY,body.getYsize(),
                client.player.onGround(),true,true,true)) return false;
        return NativePartialFooting.supportedIntegerOrigin(point.y(),body.minY,body.getYsize(),client.player.onGround(),
                client.level.noCollision(client.player,body),
                !client.level.noCollision(client.player,body.move(0,-.025,0)),
                loadedDry(body.move(0,-.025,0)));
    }
    private boolean leafSpace(AABB area) {
        boolean found = false;
        for (int x = (int)Math.floor(area.minX); x <= (int)Math.floor(area.maxX); x++)
            for (int y = (int)Math.floor(area.minY); y <= (int)Math.floor(area.maxY); y++)
                for (int z = (int)Math.floor(area.minZ); z <= (int)Math.floor(area.maxZ); z++) {
                    var at = new BlockPos(x, y, z);
                    if (!client.level.hasChunkAt(at)) return false;
                    var state = client.level.getBlockState(at);
                    if (!state.getFluidState().isEmpty() || hazardous(state)) return false;
                    if (state.is(BlockTags.LEAVES)) found = true;
                    else if (!state.getCollisionShape(client.level, at).isEmpty()) return false;
                }
        return found;
    }
    private AABB edge(Point a, Point b) {
        var actual=a.equals(feet()) ? client.player.getBoundingBox() : null;
        double fromY=actual==null ? footY(a) : actual.minY,toY=footY(b);
        double top=Math.max(actual==null ? fromY+1.81 : actual.maxY+.01,toY+1.81);
        double bottom=toY>fromY ? toY+.01 : fromY+.01;
        return new AABB(Math.min(actual==null ? a.x()+.19 : actual.minX,b.x()+.19),bottom,
                Math.min(actual==null ? a.z()+.19 : actual.minZ,b.z()+.19),
                Math.max(actual==null ? a.x()+.81 : actual.maxX,b.x()+.81),top,
                Math.max(actual==null ? a.z()+.81 : actual.maxZ,b.z()+.81));
    }
    private boolean walkEdge(Point a,Point b,boolean leaves) {
        boolean current=a.equals(feet());double fromY=current ? client.player.getY() : footY(a),toY=footY(b);
        if(fromY-toY>2 && !dryDescent(a,b))return false;
        if(current && toY>fromY) {
            var body=client.player.getBoundingBox();
            var lift=new AABB(body.minX,body.minY+.01,body.minZ,body.maxX,toY+body.getYsize()+.01,body.maxZ);
            if(!clearSpace(lift,leaves))return false;
        }
        return clearSpace(edge(a,b),leaves);
    }
    private NativeWalkPlanner.Terrain terrain(boolean leaves) {
        var cache = new HashMap<Point, Boolean>();
        return new NativeWalkPlanner.Terrain() {
            public boolean stand(Point p) { return cache.computeIfAbsent(p, value -> NativeTravel.this.stand(value, leaves)); }
            public boolean step(Point a, Point b) {
                // Swept head/body space prevents corner clipping, ceiling jumps and hidden liquids.
                return walkEdge(a,b,leaves);
            }
        };
    }
    private boolean dryDescent(Point from, Point to) {
        double fromY=from.equals(feet()) ? client.player.getY() : from.y();
        if (!NativeDryDescent.admissible(from,to,client.player.getHealth(),true,fromY) || !stand(to)) return false;
        // Check the entire fall column at the neighboring landing, including
        // intermediate water, ceilings and hazards omitted by a level-only sweep.
        var area=new AABB(to.x()+.19,footY(to)+.01,to.z()+.19,to.x()+.81,fromY+1.81,to.z()+.81);
        if (!clearSpace(area,false)) return false;
        for (int y=to.y()-1;y<=from.y()+2;y++) {
            var at=new BlockPos(to.x(),y,to.z());
            if (!client.level.hasChunkAt(at) || !client.level.getWorldBorder().isWithinBounds(at)) return false;
            var state=client.level.getBlockState(at);
            if (hazardous(state) || !state.getFluidState().isEmpty()) return false;
        }
        return true;
    }
    private boolean waterCell(Point point) {
        BlockPos at=pos(point);
        if (at.getY()<=client.level.getMinBuildHeight() || at.getY()+2>=client.level.getMaxBuildHeight()
                || !client.level.getWorldBorder().isWithinBounds(at)) return false;
        boolean water=false;
        for (int dy=-1;dy<=2;dy++) {
            BlockPos p=at.offset(0,dy,0);if(!client.level.hasChunkAt(p))return false;
            var state=client.level.getBlockState(p);var fluid=state.getFluidState();
            if(hazardous(state) || !fluid.isEmpty() && !fluid.is(FluidTags.WATER))return false;
            if(dy<=0 && fluid.is(FluidTags.WATER))water=true;
        }
        return water && client.level.noCollision(client.player,new AABB(at.getX()+.19,at.getY()+.01,at.getZ()+.19,
                at.getX()+.81,at.getY()+1.81,at.getZ()+.81));
    }
    private boolean waterEdge(Point a,Point b) {
        if(!client.level.noCollision(client.player,edge(a,b)))return false;
        var area=edge(a,b);
        for(int x=(int)Math.floor(area.minX);x<=(int)Math.floor(area.maxX);x++)
            for(int y=(int)Math.floor(area.minY)-1;y<=(int)Math.floor(area.maxY);y++)
                for(int z=(int)Math.floor(area.minZ);z<=(int)Math.floor(area.maxZ);z++) {
                    var p=new BlockPos(x,y,z);if(!client.level.hasChunkAt(p))return false;
                    var state=client.level.getBlockState(p);var fluid=state.getFluidState();
                    if(hazardous(state) || !fluid.isEmpty() && !fluid.is(FluidTags.WATER))return false;
                }
        return true;
    }
    private NativeWalkPlanner.Terrain waterTerrain() {
        return new NativeWalkPlanner.Terrain() {
            public boolean stand(Point p){return NativeTravel.this.stand(p) || waterCell(p);}
            public boolean step(Point a,Point b){return a.y()-b.y()<=2 && waterEdge(a,b);}
        };
    }
    JsonObject navigation() {
        if (client.level==null || client.player==null || client.getConnection()==null) return null;
        var at=client.player.blockPosition();long sampled=now();
        if (navigationCache!=null && navigationWorld==client.level && navigationPlayer==client.player
                && navigationConnection==client.getConnection() && at.equals(navigationFeet)
                && navigationSwimming==client.player.isInWater() && sampled-navigationAt<2000)
            return navigationCache.deepCopy();
        boolean swimming=client.player.isInWater();
        var reachable=NativeWalkPlanner.reachable(swimming ? waterTerrain() : terrain(true),point(at),8,256);
        var selected=NativeFrontiers.select(point(at),reachable,
                candidate -> !swimming || stand(candidate),
                candidate -> stand(candidate) && !client.level.getBlockState(pos(candidate).below()).is(BlockTags.LEAVES));
        var frontiers=new JsonArray();String dimension=client.level.dimension().location().toString();
        for(Point candidate:selected)frontiers.add(obj("position",obj("dimension",dimension,
                "x",candidate.x(),"y",candidate.y(),"z",candidate.z())));
        navigationCache=obj("source","runtime_client","sampled_at",java.time.Instant.now().toString(),
                "origin",obj("dimension",dimension,"x",at.getX(),"y",at.getY(),"z",at.getZ()),
                "radius",8,"search_budget",256,"frontiers",frontiers,"action_precondition_required",true,
                "unknown_fields",List.of("outside_search_budget","unloaded_chunks","future_collisions","server_rules"));
        navigationWorld=client.level;navigationPlayer=client.player;navigationConnection=client.getConnection();
        navigationFeet=at.immutable();navigationAt=sampled;navigationSwimming=swimming;return navigationCache.deepCopy();
    }
    private boolean clearRouteLeaves(Point next) {
        AABB area = edge(feet(), next); BlockPos nearest = null; double distance = Double.POSITIVE_INFINITY;
        for (int x = (int)Math.floor(area.minX); x <= (int)Math.floor(area.maxX); x++)
            for (int y = (int)Math.floor(area.minY); y <= (int)Math.floor(area.maxY); y++)
                for (int z = (int)Math.floor(area.minZ); z <= (int)Math.floor(area.maxZ); z++) {
                    BlockPos at = new BlockPos(x, y, z);
                    if (!client.level.hasChunkAt(at) || !client.level.getBlockState(at).is(BlockTags.LEAVES) || !safeBreak(at)) continue;
                    double candidate = client.player.getEyePosition().distanceToSqr(Vec3.atCenterOf(at));
                    if (candidate < distance) { distance = candidate; nearest = at; }
                }
        if (nearest == null) return false;
        var visible = client.level.clip(new ClipContext(client.player.getEyePosition(), Vec3.atCenterOf(nearest),
                ClipContext.Block.OUTLINE, ClipContext.Fluid.NONE, client.player));
        if (visible.getType() != HitResult.Type.BLOCK || !client.level.getBlockState(visible.getBlockPos()).is(BlockTags.LEAVES)
                || !safeBreak(visible.getBlockPos()) || client.player.getEyePosition().distanceToSqr(visible.getLocation())
                    > Math.pow(client.player.blockInteractionRange(), 2)) return false;
        // Neither the destination floor nor the current player's support belongs to this corridor.
        if (visible.getBlockPos().equals(pos(next).below())) return false;
        if (leafCuts.size() >= (gather ? 64 : 16)) throw new LocalTaskFailure(NAVIGATION_NO_PROGRESS);
        leafCut=visible.getBlockPos().immutable();leafCuts.add(leafCut);
        leafReceipt=new NativeStepReceipt(point(leafCut),this::stairContext,NativeTravel::now);
        attemptedBlocks++;return continueLeafCut();
    }
    private boolean continueLeafCut() {
        if (leafReceipt==null) return false;
        var state=client.level.getBlockState(leafCut);
        if (leafReceipt.confirmed(state.isAir())) {
            scope.stopMining(control,permit);leafReceipt.close();leafReceipt=null;leafCut=null;progressAt=now();return false;
        }
        scope.move(0,false,control,permit);
        if (state.isAir()) { scope.stopMining(control,permit);return true; }
        if (!state.is(BlockTags.LEAVES) || !safeBreak(leafCut)) throw new LocalTaskFailure(NAVIGATION_NO_ROUTE);
        var hit=sight(leafCut);if(hit==null)throw new LocalTaskFailure(NAVIGATION_NO_ROUTE);
        aim(hit.getLocation());scope.mine(leafCut,hit.getDirection(),control,permit);return true;
    }
    private JsonObject stepDiagnostics(Point next) {
        if (next == null) return null;
        var swept=edge(feet(),next);var body=client.player.getBoundingBox();
        return obj("next_standable",stand(next),"next_standable_with_leaves",stand(next,true),
                "next_block",BuiltInRegistries.BLOCK.getKey(client.level.getBlockState(pos(next)).getBlock()).toString(),
                "next_support",BuiltInRegistries.BLOCK.getKey(client.level.getBlockState(pos(next).below()).getBlock()).toString(),
                "edge_loaded_dry",loadedDry(swept),"edge_body_clear",client.level.noCollision(client.player,swept),
                "actual_body_clear",client.level.noCollision(client.player,body),
                "actual_support_below",!client.level.noCollision(client.player,body.move(0,-.025,0)),
                "actual_feet_y",client.player.getY(),"next_surface_y",footY(next));
    }
    private LocalTaskFailure routeFailure(String stage, Point goal, Point next) {
        routeFailure = obj("observed_at", java.time.Instant.now().toString(), "stage", stage,
                "task_id", task.get("task_id"), "on_ground", client.player.onGround(),
                "position", obj("x", client.player.getX(), "y", client.player.getY(), "z", client.player.getZ()),
                "goal", obj("x", goal.x(), "y", goal.y(), "z", goal.z()),
                "next", next == null ? null : obj("x", next.x(), "y", next.y(), "z", next.z()),
                "feet_standable", stand(feet()), "horizontal_collision", client.player.horizontalCollision,
                "path_points_remaining", path.size(), "searches", searches,
                "step_diagnostics",stepDiagnostics(next),"route_recoveries",routeRecoveries);
        return new LocalTaskFailure(NAVIGATION_NO_ROUTE);
    }
    private Point recoverRoute(Point goal, double distance, Point rejected) {
        var diagnostics=stepDiagnostics(rejected);
        // Retry inside the same task, world, permit and input scope. The original
        // no-progress clock and task deadline keep running; a search is not progress.
        scope.stopMining(control,permit);scope.move(0,false,control,permit);
        String outcome="not_dry_grounded";
        Point next=null;
        if (!waterRoute && !client.player.isInWater() && !client.player.isInLava() && client.player.onGround()) {
            outcome="recovery_budget_exhausted";
            if (routeRecoveries<MAX_ROUTE_RECOVERIES) {
                routeRecoveries++;searches++;
                var route=NativeWalkPlanner.find(terrain(false),feet(),goal,distance,1024);
                outcome="no_safe_alternative";
                if (route.points().size()>1 && (route.reachesGoal() || feet().distanceSquared(goal)>24*24)) {
                    Point candidate=route.points().get(1);
                    if (stand(candidate) && walkEdge(feet(),candidate,false)) {
                        path.clear();path.addAll(route.points());path.remove();
                        pathGoal=goal;pathRadius=distance;next=path.peek();outcome="new_route_admitted";
                    }
                }
            }
        }
        lastRouteRecovery=obj("observed_at",java.time.Instant.now().toString(),"task_id",task.get("task_id"),
                "attempts",routeRecoveries,"limit",MAX_ROUTE_RECOVERIES,"outcome",outcome,
                "rejected_step",obj("x",rejected.x(),"y",rejected.y(),"z",rejected.z()),
                "step_diagnostics",diagnostics,"original_deadline_retained",true,"progress_clock_reset",false);
        return next;
    }
    private boolean walk(Point goal, double distance) {
        if(gather)gatherRouteGoal=goal;
        boolean swimming=client.player.isInWater();
        if(swimming && !waterRoute) {
            var route=NativeWalkPlanner.find(waterTerrain(),feet(),goal,0,256);searches++;
            if(!NativeWaterRoute.admissible(feet(),goal,stand(goal),route))throw new LocalTaskFailure(NAVIGATION_NO_ROUTE);
            path.clear();path.addAll(route.points());if(!path.isEmpty())path.remove();
            pathGoal=goal;pathRadius=distance;waterRoute=true;
        }
        if(waterRoute && !swimming && client.player.onGround() && stand(feet())) {
            waterRoute=false;path.clear();pathGoal=null;
        }
        if (continueLeafCut()) return false;
        if (stair != null && !clearStair()) return false;
        if (!goal.equals(pathGoal)) arrivalTicks = 0;
        boolean inGoal = feet().distanceSquared(goal) <= distance * distance;
        double centerX = goal.x() + .5 - client.player.getX(), centerZ = goal.z() + .5 - client.player.getZ();
        // The admitted radius is the arrival region, including when the exact
        // target cell is occupied. Gathering still requires its precise stance.
        // Stop and observe three grounded, settled ticks before completing.
        if (inGoal && stand(feet()) && (distance > 0 || centerX * centerX + centerZ * centerZ < .09
                && Math.abs(footY(goal) - client.player.getY()) < .3)) {
            scope.move(0, false, control, permit); path.clear(); pathGoal = goal; pathRadius = distance;
            Vec3 speed = client.player.getDeltaMovement();
            arrivalTicks = client.player.onGround() && speed.x * speed.x + speed.z * speed.z < .0025 ? arrivalTicks + 1 : 0;
            return arrivalTicks >= 3;
        }
        arrivalTicks = 0;
        Point next = path.peek();
        if (next != null) {
            double dx = next.x() + .5 - client.player.getX(), dz = next.z() + .5 - client.player.getZ();
            // Keep the admitted landing waypoint during a jump/knockback.
            // Advancing it in midair can trigger a fresh grounded-only search
            // from an unsupported integer cell and falsely report no route.
            if ((swimming || client.player.onGround()) && dx * dx + dz * dz < .10
                    && Math.abs(footY(next) - client.player.getY()) < .6) {
                if(stair!=null && next.equals(stair.to())) {
                    if(!client.player.onGround() || Math.abs(next.y()-client.player.getY())>.15) return false;
                    stairSteps++;stair=null;stairCleared.clear();progressAt=now();
                }
                path.remove(); next = path.peek(); walked++;
            }
        }
        if (!goal.equals(pathGoal) || pathRadius != distance || next == null
                || !(waterRoute ? stand(next) || waterCell(next) : stand(next, true)) || feet().distanceSquared(next) > 12) {
            var route = NativeWalkPlanner.find(waterRoute ? waterTerrain() : terrain(true), feet(), goal, waterRoute ? 0 : distance, waterRoute ? 256 : 1024); searches++;
            if(waterRoute && !NativeWaterRoute.admissible(feet(),goal,stand(goal),route))throw new LocalTaskFailure(NAVIGATION_NO_ROUTE);
            if (!waterRoute && !route.reachesGoal() && goal.y()>feet().y() && beginStair(goal)) return false;
            if (route.points().isEmpty()) throw routeFailure("search_empty", goal, null);
            path.clear(); path.addAll(route.points()); if (!path.isEmpty()) path.remove();
            pathGoal = goal; pathRadius = distance; next = path.peek();
            if (next == null && feet().equals(goal)) next = goal;
            if (next == null) { scope.move(0, false, control, permit); return false; }
        }
        // Terrain changes between search and action are checked before each bounded input write.
        if (!(waterRoute ? (stand(next) || waterCell(next)) && waterEdge(feet(),next)
                : stand(next) && walkEdge(feet(),next,false))) {
            if (!waterRoute && clearRouteLeaves(next)) return false;
            Point rejected=next;
            next=recoverRoute(goal,distance,rejected);
            if (next==null) throw routeFailure("next_step_changed",goal,rejected);
        }
        scope.stopMining(control, permit);
        double dx = next.x() + .5 - client.player.getX(), dz = next.z() + .5 - client.player.getZ();
        float wantedYaw = (float) (Math.toDegrees(Math.atan2(-dx, dz)));
        float error = net.minecraft.util.Mth.wrapDegrees(wantedYaw - client.player.getYRot());
        float turn = net.minecraft.util.Mth.clamp(error, -25, 25);
        scope.look(client.player.getYRot() + turn, waterRoute ? -20 : 12, control, permit);
        boolean threatened = !client.level.getEntitiesOfClass(Monster.class, client.player.getBoundingBox().inflate(12),
                enemy -> enemy.isAlive() && client.player.distanceToSqr(enemy) <= 144).isEmpty();
        float throttle = NativeEscapeMotion.throttle(threatened, next.equals(goal), dx * dx + dz * dz);
        float forward = Math.abs(error) < 55 ? throttle : 0;
        boolean sprint = NativeEscapeMotion.sprint(threatened, client.player.onGround(), swimming, client.player.isInLava(),
                client.player.isUsingItem(), client.player.horizontalCollision, client.player.getFoodData().getFoodLevel(),
                forward, error, footY(next) - client.player.getY());
        scope.move(forward, swimming || footY(next) > client.player.getY() + .35 && client.player.onGround(),
                sprint, control, permit);
        if (sprint) escapeSprintTicks++;
        return false;
    }
    private boolean stairContext() {
        return !closed && client.isSameThread() && client.level==world && client.player==player && client.getConnection()==connection
                && control.allowed() && control.epoch()==permit.epoch()
                && client.player.isAlive() && client.player.containerMenu==client.player.inventoryMenu
                && client.screen==null && client.isWindowActive() && !client.isPaused();
    }
    private boolean plainRockOrSoil(BlockState state) {
        return Set.of(Blocks.STONE,Blocks.DEEPSLATE,Blocks.TUFF,Blocks.GRANITE,Blocks.DIORITE,Blocks.ANDESITE,
                Blocks.DIRT,Blocks.GRASS_BLOCK,Blocks.COARSE_DIRT,Blocks.ROOTED_DIRT,Blocks.PODZOL,Blocks.MYCELIUM).contains(state.getBlock());
    }
    private NativeStepPlan.Step stepPlan(Point goal) {
        return NativeStepPlan.choose(new NativeStepPlan.Terrain() {
            public boolean destination(Point p) { return stand(p); }
            public boolean support(Point p) {
                BlockPos at=pos(p);
                if(!client.level.hasChunkAt(at) || !client.level.getWorldBorder().isWithinBounds(at))return false;
                BlockState state=client.level.getBlockState(at);
                return state.getFluidState().isEmpty() && !hazardous(state) && !(state.getBlock() instanceof FallingBlock)
                        && state.isCollisionShapeFullBlock(client.level,at) && state.isFaceSturdy(client.level,at,Direction.UP);
            }
            public NativeStepPlan.Cell clearance(Point p) {
                BlockPos at=pos(p);
                if(at.getY()<=client.level.getMinBuildHeight() || at.getY()+1>=client.level.getMaxBuildHeight()
                        || !client.level.hasChunkAt(at) || !client.level.getWorldBorder().isWithinBounds(at))return NativeStepPlan.Cell.BLOCKED;
                BlockState state=client.level.getBlockState(at);
                if(!state.getFluidState().isEmpty() || hazardous(state) || state.hasBlockEntity())return NativeStepPlan.Cell.BLOCKED;
                if(state.getCollisionShape(client.level,at).isEmpty())return NativeStepPlan.Cell.CLEAR;
                return plainRockOrSoil(state) && safeBreak(at)?NativeStepPlan.Cell.CUT:NativeStepPlan.Cell.BLOCKED;
            }
        },feet(),goal);
    }
    private boolean beginStair(Point goal) {
        if(stairSteps>=8 || stairCuts>=24 || stairStarted!=0 && now()-stairStarted>120000)return false;
        if(!client.player.onGround()) { scope.move(0,false,control,permit);return true; }
        var plan=stepPlan(goal);if(plan==null)return false;
        scope.move(0,false,control,permit);scope.stopMining(control,permit);
        stair=plan;stairCleared.clear();path.clear();pathGoal=goal;pathRadius=radius;
        if(stairStarted==0)stairStarted=now();progressAt=now();return true;
    }
    private boolean clearStair() {
        scope.move(0,false,control,permit);
        if(now()-stairStarted>120000)throw new LocalTaskFailure(NAVIGATION_NO_PROGRESS);
        if(stairCut!=null) {
            BlockState state=client.level.getBlockState(stairCut);
            if(stairReceipt.confirmed(state.isAir())) {
                scope.stopMining(control,permit);stairPackets+=stairReceipt.packets();
                stairEvidence.add(obj("x",stairCut.getX(),"y",stairCut.getY(),"z",stairCut.getZ(),"server_packets",stairReceipt.packets(),"server_confirmed_clear",true));
                stairCleared.add(stairCut);stairReceipt.close();stairReceipt=null;stairCut=null;progressAt=now();
            } else if(state.isAir()) {
                scope.stopMining(control,permit);return false;
            }
        }
        for(Point cell:stair.cuts()) {
            BlockPos at=pos(cell);
            if(stairCleared.contains(at)) {
                if(!client.level.getBlockState(at).isAir())throw new LocalTaskFailure(NAVIGATION_NO_ROUTE);
                continue;
            }
            // A different actor's clearing is not a receipt for this task's pending swing.
            if(client.level.getBlockState(at).isAir() && !at.equals(stairCut))throw new LocalTaskFailure(NAVIGATION_NO_ROUTE);
        }
        if(stairCleared.size()==stair.cuts().size()) {
            scope.stopMining(control,permit);
            if(!stand(stair.to()) || !client.level.noCollision(client.player,edge(stair.from(),stair.to())))throw new LocalTaskFailure(NAVIGATION_NO_ROUTE);
            if(path.isEmpty())path.add(stair.to());return true;
        }
        BlockHitResult hit=null;
        for(Point cell:stair.cuts()) {
            BlockPos target=pos(cell);if(stairCleared.contains(target))continue;
            var ray=client.level.clip(new ClipContext(client.player.getEyePosition(),Vec3.atCenterOf(target),ClipContext.Block.OUTLINE,ClipContext.Fluid.NONE,client.player));
            if(ray.getType()==HitResult.Type.BLOCK && stair.cuts().contains(point(ray.getBlockPos())) && !stairCleared.contains(ray.getBlockPos())
                    && (stairCut==null || stairCut.equals(ray.getBlockPos()))) { hit=ray;break; }
        }
        if(hit==null || !safeBreak(hit.getBlockPos()) || !plainRockOrSoil(client.level.getBlockState(hit.getBlockPos()))
                || client.player.getEyePosition().distanceToSqr(hit.getLocation())>Math.pow(client.player.blockInteractionRange(),2))
            throw new LocalTaskFailure(NAVIGATION_NO_ROUTE);
        int selected=tools.prepare(client.level.getBlockState(hit.getBlockPos()));if(selected<0)return false;
        scope.select(selected,control,permit);aim(hit.getLocation());
        if(stairCut==null) {
            if(stairCuts>=24)throw new LocalTaskFailure(NAVIGATION_NO_PROGRESS);
            stairCut=hit.getBlockPos().immutable();stairReceipt=new NativeStepReceipt(point(stairCut),this::stairContext,NativeTravel::now);stairCuts++;
        }
        scope.mine(stairCut,hit.getDirection(),control,permit);return false;
    }
    void block(BlockPos at,BlockState state) {
        // A real terrain update can make a previously excluded drop reachable.
        skippedDrops.clear();
        if(stairReceipt!=null)stairReceipt.packet(point(at),state.isAir());
        if(leafReceipt!=null)leafReceipt.packet(point(at),state.isAir());
    }
    private static boolean resourceSupported(Item item) {
        if (NativeFoodPlan.gatherable(BuiltInRegistries.ITEM.getKey(item).toString())) return true;
        if (item instanceof BlockItem block) {
            Block state = block.getBlock();
            return state.defaultBlockState().is(BlockTags.LOGS) || state.defaultBlockState().is(BlockTags.PLANKS)
                    || Set.of(Blocks.DIRT, Blocks.COARSE_DIRT, Blocks.ROOTED_DIRT, Blocks.COBBLESTONE,
                        Blocks.COBBLED_DEEPSLATE, Blocks.NETHERRACK, Blocks.END_STONE).contains(state);
        }
        return Set.of(Items.COAL, Items.RAW_IRON, Items.RAW_COPPER, Items.RAW_GOLD, Items.DIAMOND,
                Items.EMERALD, Items.LAPIS_LAZULI, Items.REDSTONE, Items.QUARTZ).contains(item);
    }
    private boolean source(BlockState state, Item item) {
        Block block = state.getBlock();
        if (state.hasBlockEntity() || block instanceof FallingBlock) return false;
        if (NativeFoodPlan.gatherable(BuiltInRegistries.ITEM.getKey(item).toString()))
            return BuiltInRegistries.ITEM.getKey(item).toString().equals(NativeFoodSources.harvest(state));
        if (item == Items.COBBLESTONE) return block == Blocks.COBBLESTONE || block == Blocks.STONE;
        if (item == Items.COBBLED_DEEPSLATE) return block == Blocks.COBBLED_DEEPSLATE || block == Blocks.DEEPSLATE;
        if (item == Items.DIRT) return block == Blocks.DIRT || block == Blocks.GRASS_BLOCK || block == Blocks.MYCELIUM || block == Blocks.PODZOL;
        if (item instanceof BlockItem value) return block == value.getBlock();
        return item == Items.COAL && (block == Blocks.COAL_ORE || block == Blocks.DEEPSLATE_COAL_ORE)
                || item == Items.RAW_IRON && (block == Blocks.IRON_ORE || block == Blocks.DEEPSLATE_IRON_ORE)
                || item == Items.RAW_COPPER && (block == Blocks.COPPER_ORE || block == Blocks.DEEPSLATE_COPPER_ORE)
                || item == Items.RAW_GOLD && (block == Blocks.GOLD_ORE || block == Blocks.DEEPSLATE_GOLD_ORE)
                || item == Items.DIAMOND && (block == Blocks.DIAMOND_ORE || block == Blocks.DEEPSLATE_DIAMOND_ORE)
                || item == Items.EMERALD && (block == Blocks.EMERALD_ORE || block == Blocks.DEEPSLATE_EMERALD_ORE)
                || item == Items.LAPIS_LAZULI && (block == Blocks.LAPIS_ORE || block == Blocks.DEEPSLATE_LAPIS_ORE)
                || item == Items.REDSTONE && (block == Blocks.REDSTONE_ORE || block == Blocks.DEEPSLATE_REDSTONE_ORE)
                || item == Items.QUARTZ && block == Blocks.NETHER_QUARTZ_ORE;
    }
    private List<ItemEntity> drops(Item item) {
        return client.level.getEntitiesOfClass(ItemEntity.class, client.player.getBoundingBox().inflate(12),
                entity -> entity.isAlive() && !entity.hasPickUpDelay() && entity.getItem().is(item)).stream()
                .sorted(Comparator.comparingDouble(client.player::distanceToSqr)).toList();
    }
    private BlockPos findBlock(Item item) {
        return findBlock(item, skippedSources);
    }
    private BlockPos findBlock(Item item, Set<BlockPos> excluded) {
        blockedSources.entrySet().removeIf(row -> now()-row.getValue()>60000);
        BlockPos origin = client.player.blockPosition(), closest = null; double distance = Double.POSITIVE_INFINITY;
        int depth=item==Items.COBBLESTONE?12:6;
        for (int y = -depth; y <= 6; y++) for (int x = -12; x <= 12; x++) for (int z = -12; z <= 12; z++) {
            BlockPos at = origin.offset(x, y, z);
            if (excluded.contains(at) || blockedSources.containsKey(at) || !client.level.hasChunkAt(at)
                    || !source(client.level.getBlockState(at), item) || !safeBreak(at)) continue;
            int access=access(at,item);if(access<0)continue;
            // Prefer an actually visible source in reach over a closer enclosed
            // trunk. Reaching a hypothetical stance is not mining progress.
            boolean visible=client.player.getEyePosition().distanceToSqr(targetPoint(at))<36 && sight(at)!=null;
            double value = at.distSqr(origin)+access*4096+(visible?0:1024);
            if (value < distance) { closest = at.immutable(); distance = value; }
        }
        return closest;
    }
    private boolean gatherReachable(Item item) {
        // Match one executor search batch. More distant/complex approaches remain
        // unknown; a query must not mine, move or retain task-specific exclusions.
        for (var loose : drops(item).stream().limit(3).toList())
            if (pickupStance(loose) != null) return true;
        var excluded = new HashSet<BlockPos>();
        for (int search = 0; search < 3; search++) {
            var target = findBlock(item, excluded);
            if (target == null) return false;
            if (sight(target) != null || stance(target) != null || soilCover(target, item) != null) return true;
            excluded.add(target);
        }
        return false;
    }
    private boolean soil(BlockState state){return Set.of(Blocks.DIRT,Blocks.GRASS_BLOCK,Blocks.COARSE_DIRT,Blocks.ROOTED_DIRT,Blocks.PODZOL,Blocks.MYCELIUM).contains(state.getBlock());}
    /** Enclosed rock is unavailable; logs behind real leaves use the existing visible-leaf approach. */
    private int access(BlockPos at,Item item){
        boolean cover=false;
        boolean log=client.level.getBlockState(at).is(BlockTags.LOGS);
        for(Direction face:Direction.values()){
            var near=at.relative(face);if(!client.level.hasChunkAt(near))continue;var state=client.level.getBlockState(near);
            if(state.getFluidState().isEmpty() && !hazardous(state) && state.getCollisionShape(client.level,near).isEmpty())return 0;
            cover|=item==Items.COBBLESTONE && soil(state) || log && state.is(BlockTags.LEAVES);
        }return cover?1:-1;
    }
    private BlockHitResult soilCover(BlockPos source, Item item){
        if(item!=Items.COBBLESTONE)return null;
        var hit=client.level.clip(new ClipContext(client.player.getEyePosition(),Vec3.atCenterOf(source),ClipContext.Block.OUTLINE,ClipContext.Fluid.NONE,client.player));
        if(hit.getType()!=HitResult.Type.BLOCK || hit.getBlockPos().equals(source) || !soil(client.level.getBlockState(hit.getBlockPos()))
                || !safeBreak(hit.getBlockPos()) || client.player.getEyePosition().distanceToSqr(hit.getLocation())>Math.pow(client.player.blockInteractionRange(),2))return null;
        return hit;
    }
    private boolean clearSoilCover(BlockPos source){
        if(excavatedCover.size()>=24)return false;
        var hit=soilCover(source,wanted);if(hit==null)return false;
        // Only the first actual obstruction on the ray to known stone, never the player's support or an unknown tunnel.
        coverTarget=hit.getBlockPos().immutable();excavatedCover.add(coverTarget);
        scope.move(0,false,control,permit);int selected=tool(client.level.getBlockState(coverTarget));
        if(selected<0)return true;scope.select(selected,control,permit);aim(hit.getLocation());scope.mine(coverTarget,hit.getDirection(),control,permit);return true;
    }
    private boolean safeBreak(BlockPos at) {
        if (!client.level.hasChunkAt(at) || !client.level.getWorldBorder().isWithinBounds(at)) return false;
        var state = client.level.getBlockState(at);
        if (state.isAir() || state.hasBlockEntity() || hazardous(state) || !state.getFluidState().isEmpty()
                || state.getBlock() instanceof FallingBlock || state.getDestroySpeed(client.level, at) < 0) return false;
        // Never mine the support beneath the current player or a falling/fluid neighbor.
        if (new AABB(at).intersects(client.player.getBoundingBox().inflate(.15, .1, .15))
                && !(state.is(BlockTags.LEAVES) && at.getY()>=client.player.blockPosition().getY())) return false;
        for (Direction side : Direction.values()) {
            BlockPos neighbor = at.relative(side);
            if (!client.level.hasChunkAt(neighbor)) return false;
            var adjacent = client.level.getBlockState(neighbor);
            if (!adjacent.getFluidState().isEmpty() || side == Direction.UP && adjacent.getBlock() instanceof FallingBlock) return false;
        }
        return true;
    }
    private int tool(BlockState state) {
        return tools.prepare(state);
    }
    private Vec3 targetPoint(BlockPos at) {
        return NativeFoodSources.aimPoint(at, client.level.getBlockState(at).getShape(client.level, at));
    }
    private BlockHitResult sight(BlockPos at) {
        Vec3 eye = client.player.getEyePosition(), center = targetPoint(at);
        var hit = client.level.clip(new ClipContext(eye, center, ClipContext.Block.OUTLINE, ClipContext.Fluid.NONE, client.player));
        return hit.getType() == HitResult.Type.BLOCK && hit.getBlockPos().equals(at)
                && eye.distanceToSqr(hit.getLocation()) <= Math.pow(client.player.blockInteractionRange(), 2) ? hit : null;
    }
    private Point stance(BlockPos target) {
        var candidates = new ArrayList<Point>();
        Vec3 targetPoint = targetPoint(target);
        double reach = client.player.blockInteractionRange() - .15;
        for (int dy = -4; dy <= 4; dy++) for (int dx = -4; dx <= 4; dx++) for (int dz = -4; dz <= 4; dz++) {
            Point candidate = point(target.offset(dx, dy, dz));
            Vec3 eye = new Vec3(candidate.x() + .5, candidate.y() + client.player.getEyeHeight(), candidate.z() + .5);
            // A mining endpoint must have a clear body, even when its route
            // may clear real leaves. A stance inside foliage never settles.
            if (eye.distanceToSqr(targetPoint) > reach * reach || !stand(candidate)) continue;
            var body = new AABB(candidate.x() + .19, candidate.y() - .1, candidate.z() + .19,
                    candidate.x() + .81, candidate.y() + 1.81, candidate.z() + .81);
            if (new AABB(target).intersects(body)) continue;
            var visible = client.level.clip(new ClipContext(eye, targetPoint, ClipContext.Block.OUTLINE,
                    ClipContext.Fluid.NONE, client.player));
            if (visible.getType() != HitResult.Type.BLOCK) continue;
            if (!visible.getBlockPos().equals(target) && (!client.level.getBlockState(visible.getBlockPos()).is(BlockTags.LEAVES)
                    || !safeBreak(visible.getBlockPos()) || new AABB(visible.getBlockPos()).intersects(body))) continue;
            candidates.add(candidate);
        }
        Point origin = feet(); candidates.sort(Comparator.comparingDouble(origin::distanceSquared));
        for (Point candidate : candidates) {
            var route = NativeWalkPlanner.find(terrain(true), origin, candidate, 0, 1024);
            if (route.reachesGoal()) return candidate;
        }
        return null;
    }
    private Point pickupStance(ItemEntity entity) {
        var candidates = new ArrayList<Point>();
        for (int dy = -1; dy <= 1; dy++) for (int dx = -1; dx <= 1; dx++) for (int dz = -1; dz <= 1; dz++) {
            Point candidate = point(entity.blockPosition().offset(dx, dy, dz));
            if (!stand(candidate, true)) continue;
            var body = new AABB(candidate.x() + .2, candidate.y(), candidate.z() + .2,
                    candidate.x() + .8, candidate.y() + 1.8, candidate.z() + .8).inflate(.9, .4, .9);
            if (body.intersects(entity.getBoundingBox())) candidates.add(candidate);
        }
        Point origin = feet(); candidates.sort(Comparator.comparingDouble(origin::distanceSquared));
        for (Point candidate : candidates) {
            if (NativeWalkPlanner.find(terrain(true), origin, candidate, 0, 1024).reachesGoal()
                    || candidate.y()>origin.y() && stepPlan(candidate)!=null) return candidate;
        }
        return null;
    }
    private void collect() {
        if(!feet().equals(pickupExclusionFeet)){skippedDrops.clear();pickupExclusionFeet=feet();}
        // Keep the admitted collection approach fixed while a bounded, server-
        // acknowledged stair step is in progress; a new drop cannot redirect it.
        if(stair!=null && gatherRouteGoal!=null){walk(gatherRouteGoal,0);return;}
        if(coverTarget!=null && !soil(client.level.getBlockState(coverTarget))){
            scope.stopMining(control,permit);
            Point next=point(coverTarget);
            if(stand(next,true) && NativeWalkPlanner.find(terrain(true),feet(),next,0,256).reachesGoal())coverApproach=next;
            coverTarget=null;progressAt=now();
        }
        if(coverApproach!=null) {
            try {if(!walk(coverApproach,0))return;}
            catch(LocalTaskFailure changed){if(changed.reason!=NAVIGATION_NO_ROUTE)throw changed;
                scope.stopMining(control,permit);scope.move(0,false,control,permit);path.clear();}
            coverApproach=null;
        }
        if (confirmedInventory >= inventoryTarget.targetTotal() && inventoryPackets > 0
                && inventoryCount(wanted) >= inventoryTarget.targetTotal()) { stop(); finished.run(); return; }
        for (var loose : drops(wanted)) {
            if (skippedDrops.contains(loose.getUUID())) continue;
            Point pickup = pickupStance(loose);
            if (pickup == null) { skippedDrops.add(loose.getUUID()); continue; }
            blockTarget = null; miningStance = null;
            try { if (walk(pickup, 0)) scope.stopMining(control, permit); }
            catch (LocalTaskFailure changed) {
                if (changed.reason != NAVIGATION_NO_ROUTE) throw changed;
                skippedDrops.add(loose.getUUID()); path.clear(); scope.move(0, false, control, permit);
            }
            return;
        }
        if (pickupUntil > now()) { scope.move(0, false, control, permit); return; }
        if (blockTarget != null && !source(client.level.getBlockState(blockTarget), wanted)) {
            scope.stopMining(control, permit); blockTarget = null; miningStance = null; pickupUntil = now() + 1200; return;
        }
        if(blockTarget!=null && miningAt==0 && now()-progressAt>3500){
            // Do not spend the whole task centering against the same obstacle.
            // Exclude this real source across subsequent local retries too.
            blockedSources.put(blockTarget,now());skippedSources.add(blockTarget);
            while(blockedSources.size()>64)blockedSources.remove(blockedSources.keySet().iterator().next());
            scope.stopMining(control,permit);scope.move(0,false,control,permit);
            blockTarget=null;miningStance=null;path.clear();pathGoal=null;stalledApproaches++;
            progressAt=now();
            if(stalledApproaches>=8)throw new LocalTaskFailure(GATHER_NO_PROGRESS);
        }
        if (blockTarget == null) {
            for (int search = 0; search < 3; search++) {
                blockTarget = findBlock(wanted);
                if (blockTarget == null) throw new LocalTaskFailure(GATHER_RESOURCE_UNAVAILABLE);
                miningStance = sight(blockTarget) != null ? feet() : stance(blockTarget);
                if (miningStance != null) { miningAt = 0; break; }
                if(clearSoilCover(blockTarget)){blockTarget=null;return;}
                skippedSources.add(blockTarget); blockTarget = null;
                if(skippedSources.size()>=64)throw new LocalTaskFailure(GATHER_RESOURCE_UNAVAILABLE);
            }
            if (blockTarget == null) { scope.move(0, false, control, permit); return; }
        }
        if (!safeBreak(blockTarget)) {
            // A jump or pickup approach can put an earlier target inside the current body.
            // Release motion and discard that target; all other changed safety checks still fail closed.
            if (new AABB(blockTarget).intersects(client.player.getBoundingBox().inflate(.15,.1,.15))) {
                scope.stopMining(control,permit);scope.move(0,false,control,permit);
                skippedSources.add(blockTarget);blockTarget=null;miningStance=null;path.clear();
                if(skippedSources.size()>=64)throw new LocalTaskFailure(GATHER_RESOURCE_UNAVAILABLE);
                return;
            }
            throw new LocalTaskFailure(GATHER_BLOCK_FORBIDDEN);
        }
        BlockHitResult hit = sight(blockTarget);
        if (hit == null) {
            miningAt=0;
            if (miningStance == null || !stand(miningStance, true)) miningStance = stance(blockTarget);
            if (miningStance == null) {
                scope.stopMining(control, permit); skippedSources.add(blockTarget); blockTarget = null; return;
            }
            try {
                if (!walk(miningStance, 0)) return;
            } catch (LocalTaskFailure changed) {
                if (changed.reason != NAVIGATION_NO_ROUTE) throw changed;
                scope.stopMining(control, permit); scope.move(0, false, control, permit);
                skippedSources.add(blockTarget); blockTarget = null; miningStance = null; path.clear(); return;
            }
            if(clearSoilCover(blockTarget))return;
            // A wood target may be covered by foliage. Clear only the actual visible, non-support leaf.
            var visible = client.level.clip(new ClipContext(client.player.getEyePosition(), targetPoint(blockTarget),
                    ClipContext.Block.OUTLINE, ClipContext.Fluid.NONE, client.player));
            if (visible.getType() == HitResult.Type.BLOCK && client.level.getBlockState(visible.getBlockPos()).is(BlockTags.LEAVES)
                    && safeBreak(visible.getBlockPos()) && client.player.getEyePosition().distanceToSqr(visible.getLocation())
                    <= Math.pow(client.player.blockInteractionRange(), 2)) {
                scope.move(0, false, control, permit); aim(visible.getLocation());
                scope.mine(visible.getBlockPos(), visible.getDirection(), control, permit); attemptedBlocks++; return;
            }
            scope.stopMining(control, permit);
            skippedSources.add(blockTarget); blockTarget = null; miningStance = null; return;
        }
        scope.move(0, false, control, permit);
        int selected = tool(client.level.getBlockState(blockTarget));
        if (selected < 0) return;
        scope.select(selected, control, permit); aim(hit.getLocation());
        if (miningAt == 0) { miningAt = now(); attemptedBlocks++; }
        if (now() - miningAt > 15000) throw new LocalTaskFailure(GATHER_SERVER_TIMEOUT);
        scope.mine(blockTarget, hit.getDirection(), control, permit);
    }
    private void aim(Vec3 at) {
        Vec3 delta = at.subtract(client.player.getEyePosition());
        scope.look((float) Math.toDegrees(Math.atan2(-delta.x, delta.z)),
                (float) -Math.toDegrees(Math.atan2(delta.y, Math.hypot(delta.x, delta.z))), control, permit);
    }
    private void stop() { if(leafReceipt!=null)leafReceipt.close();if(stairReceipt!=null)stairReceipt.close();if(tools!=null)tools.close();if (scope != null) scope.release(); closed = true; path.clear(); }
    int clickRevision(int original){return tools==null?original:tools.clickRevision(original);}
    void inventory(net.minecraft.network.protocol.game.ClientboundContainerSetContentPacket packet){if(tools!=null)tools.inventory(packet);}
    @Override public void cancel() { stop(); }
    boolean activeGather() { return !closed && (gather || stair != null); }
    JsonObject proof() {
        return obj("task_id", task == null ? null : task.get("task_id"), "active", !closed, "gather", gather,
                "ticks", ticks, "arrival_ticks", arrivalTicks, "path_searches", searches, "walked_waypoints", walked, "block_attempts", attemptedBlocks,
                "escape_sprint_input_ticks", escapeSprintTicks, "ordinary_sprint_key", true,
                "route_recoveries",routeRecoveries,"route_recovery_limit",MAX_ROUTE_RECOVERIES,
                "last_route_recovery",lastRouteRecovery,
                "server_inventory_packets", inventoryPackets, "confirmed_inventory", confirmedInventory,
                "skipped_sources", skippedSources.size(), "skipped_drops", skippedDrops.size(),
                "stalled_approaches",stalledApproaches,"temporarily_blocked_sources",blockedSources.size(),
                "mining_stance",miningStance==null?null:obj("x",miningStance.x(),"y",miningStance.y(),"z",miningStance.z()),
                "mining_elapsed_ms",miningAt==0?0:now()-miningAt,
                "soil_cover_blocks_attempted",excavatedCover.size(),
                "route_leaves_attempted",leafCuts.size(),"route_leaf_ack_pending",leafReceipt!=null && !closed,
                "tool_belt",tools==null?null:tools.proof(),
                "step_exit",obj("steps",stairSteps,"cuts_attempted",stairCuts,"server_packets",stairPackets,
                        "pending_ack",stairReceipt!=null && !closed,"confirmed_cuts",stairEvidence),
                "route_preflight",routePreflight,
                "last_movement_blocked",movementBlocked,
                "last_route_failure",routeFailure,
                "water_escape",obj("active",!closed && waterRoute,"water_ticks",waterTicks,"maximum_water_ticks",NativeWaterRoute.MAX_WATER_TICKS,
                        "ordinary_owned_input",true,"velocity_or_position_written",false),
                "destination",destination==null?null:obj("x",destination.x(),"y",destination.y(),"z",destination.z(),"standable",client.level!=null && client.player!=null && stand(destination)),
                "nearby_resource_drops", wanted == null || client.level == null || client.player == null ? List.of()
                        : drops(wanted).stream().limit(8).map(e -> obj("x", e.getX(), "y", e.getY(), "z", e.getZ(),
                            "item_id", BuiltInRegistries.ITEM.getKey(e.getItem().getItem()).toString(), "count", e.getItem().getCount())).toList(),
                "block_target", blockTarget == null ? null
                        : obj("x", blockTarget.getX(), "y", blockTarget.getY(), "z", blockTarget.getZ()),
                "mining_stance", miningStance == null ? null : obj("x", miningStance.x(), "y", miningStance.y(), "z", miningStance.z()),
                "feet_standable", client.level != null && client.player != null && stand(feet()),
                "actual_feet_y",client.player==null?null:client.player.getY(),
                "expected_surface_y",client.level==null || client.player==null?null:footY(feet()),
                "shallow_path_surface",client.level!=null && client.player!=null && Double.isFinite(shallowSurfaceY(feet())),
                "partial_origin_footing",client.level!=null && client.player!=null && partialFooting(),
                "support_block", client.level == null || client.player == null ? null
                        : BuiltInRegistries.BLOCK.getKey(client.level.getBlockState(client.player.blockPosition().below()).getBlock()).toString());
    }
}

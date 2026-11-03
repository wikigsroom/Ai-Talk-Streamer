# 当前世界配方查询与DSH对接

工作分支为mc。本实现接通当前世界的配方读取，完整交付状态仍以[实现进度](实现进度.md)为准。

## 1. 实际调用链

DSH的game_get_recipe工具接收item_id与count，经GameManager的异步query进入现有WebSocket。BridgeCore将读取派回游戏线程，MinecraftPort读取当前NetworkHandler的RecipeManager及世界RegistryManager，再由RecipeCatalog形成有界JSON投影。结果回到原查询，经过Schema与语义核验后，DSH才能取得成功的查询操作。

读取不请求AUTO、不启动任务、不改库存、不触发合成，也不加载第二个主播人格。查询成功仅表示取得配方信息。实际合成仍须经过前置检查、唯一执行器、租约、真实任务和后置效果证据。

每次查询重新取得当前世界的管理器，不缓存跨世界配方表。游戏注册表中不存在的物品返回GAME_ITEM_UNKNOWN；当前客户端没有收到匹配的静态产出配方时，返回recipe_known=false，同时保留unreceived_server_recipes与dynamic_recipe_outputs未知项，不能解读为该物品永远无法合成。

## 2. 返回内容

| 字段 | 含义及约束 |
|---|---|
| world_session_id / based_on_seq | 查询所属世界及读取时已有的本地观测序号；不得早于受理观测。可能领先于尚未发出的下一份普通快照 |
| source / catalog_scope | 真实适配器为runtime_recipe_manager，范围仅为current_server_received；协议夹具明确标TEST_FIXTURE_ONLY |
| item_id / requested_count | 必须与请求一致，数量1–4096 |
| recipe_known / candidate_count / ambiguous | 有匹配静态产出、多配方及总候选数量；多配方不静默选一个 |
| recipes | 按完整recipe_id排序；保留原recipe_type、形状/无序/其他布局及形状宽高 |
| output_per_batch / batches / output_for_batches | 配方声明每批产量、按请求数量向上取整的批次及名义产量，不表示真实已产出 |
| slots | 按配方槽顺序提供物品ID选项；形状空槽保留，不能压缩后改变形状 |
| ingredients_known | 当前配方是否提供材料槽投影；特殊配方缺槽时明确false |
| alternatives_total / truncated | 原候选数量和截断标记；缺失项不能当成“不允许该材料” |
| inventory_checked | 固定false；没有求解重叠标签、背包材料或工作台是否足够 |
| ingredient_projection / unknown_fields | 仅投影物品ID，明确组件匹配、返还容器、解锁、服务器限制、库存分配、未收到及动态配方未知 |

形状/无序以实际配方类型识别；熔炼、切石、锻造及其他类型可按实际recipe_type描述已接收的静态产出及材料投影，但不据此增加游戏执行器技能。特殊/模组配方的动态输出及组件条件不能由通用物品ID投影完整表达。

## 3. 数量、线程及传输约束

每次最多扫描8192项；超过返回GAME_RECIPE_SCAN_LIMIT。匹配配方最多返回16项，每槽最多16个去重后的物品ID，单配方最多9槽。候选与选项总数保留；截断在顶层及材料槽明确标记。结果本体限制49152字节，按排序逐项计算字节预算并保留可装入的完整前缀，保留候选总数与截断说明；上下文封装后服务端限制51200字节，仍处于原128KiB帧上限内。

只有最终保留的匹配配方读取材料槽。客户端回调运行前及响应发送前复核世界、连接代次和已握手状态，旧连接的排队查询不能发到新连接。RecipeManager、ItemStack或Ingredient不跨线程传播，只有JSON进入I/O队列。

服务端另核对请求物品/数量、观测下界、配方ID唯一及排序、候选/歧义/截断一致性、批次算术、形状与槽位数量、空槽和材料选项数量，并要求保留全部未知项。异常结果不能作为成功工具结果暴露。

## 4. 契约、检查及完成边界

RecipeSlot、RecipeChoice和RecipeResult由[契约生成器](contracts/build_contracts.py)生成，原HTTP路径及内部协议主版本保持一致。game_get_recipe的工具说明同步指出歧义、截断和未知信息，避免模型把配方查询写成完成口播。

本地检查覆盖批次数量、形状空槽、候选排序与歧义、材料/字节截断、数据刷新、扫描限制、错误响应，以及实际Java核心和现有Node/DSH工具的往返。全部数据夹具均显式标注，不加载Minecraft客户端。

原生适配器已经编译并不等于真实服务器验收。仍须在真实客户端检查普通/数据包/模组配方、配方同步/重载、特殊配方与未知项、解锁/库存/工作台/组件规则，以及与实际合成执行的联合效果。完整生存候选预启动无条件拒绝仍保留；GUI、其他写点、输入接管及MinecraftPort生存能力对接继续按全范围实现。

// The public aliases keep the planning agent separate from the plugin's one
// persistent Minecraft session. Every call still runs through DSH tools.execute.
export const CANDIDATE_READ = new Set(['mc_status','mc_inventory','mc_scan','mc_map','mc_observe','mc_events','mc_diag','mc_recipe']);
export const CANDIDATE_ACTION = new Set(['mc_move','mc_act','mc_dig','mc_craft','mc_build','mc_equip','mc_attack','mc_drops','mc_chest','mc_furnace']);
export const CANDIDATE_ALIASES = new Set([...CANDIDATE_READ,...CANDIDATE_ACTION].map(name=>'game_'+name));
export const CANDIDATE_ACTION_ALIASES = new Set([...CANDIDATE_ACTION].map(name=>'game_'+name));

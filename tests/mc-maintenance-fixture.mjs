import { GameStore } from '../backend/game/store.mjs';

const store = new GameStore(process.argv[2]);
store.setMeta('bound_instance', process.argv[3] || 'mc-maintenance-fixture');
if (process.argv[4] === 'hold') {
  process.stdout.write(JSON.stringify({ ready: true, pid: process.pid }) + '\n');
  process.stdin.once('data', () => { store.close(); process.exit(0); });
  process.stdin.resume();
} else {
  store.close();
  process.stdout.write(JSON.stringify({ schema: 4, closed: true }) + '\n');
}

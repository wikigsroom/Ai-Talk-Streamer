import { parentPort, workerData } from 'node:worker_threads';
import jpeg from 'jpeg-js';

try {
  const image = jpeg.decode(new Uint8Array(workerData), { useTArray:true, formatAsRGBA:false,
    tolerantDecoding:false, maxResolutionInMP:2.1, maxMemoryUsageInMB:64 });
  parentPort.postMessage({ width:image.width, height:image.height });
} catch { parentPort.postMessage({ error:'GAME_FRAME_JPEG_INVALID' }); }

import fs from 'node:fs';
import {initSync,map_rays,evaluate_project} from '../../packages/web-sdk/wasm/rpi360_render.js';
initSync({module:fs.readFileSync(new URL('../../packages/web-sdk/wasm/rpi360_render_bg.wasm',import.meta.url))});
let input='';for await(const chunk of process.stdin)input+=chunk;const request=JSON.parse(input);
console.log(JSON.stringify(request.project?JSON.parse(evaluate_project(JSON.stringify(request.project),request.time_us)):JSON.parse(map_rays(input))));

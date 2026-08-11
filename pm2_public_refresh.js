const { spawn, spawnSync } = require('child_process');
const path = require('path');

// one-shot: regen public snapshot + push (gh-pages redeploy). pm2 cron_restart รันซ้ำทุกชั่วโมง.
const child = spawn('python', [path.join(__dirname, 'scripts', 'refresh_public_site.py')], {
  cwd: __dirname,
  stdio: 'inherit',
  env: Object.assign({}, process.env, { PYTHONUNBUFFERED: '1' }),
});

// ฆ่าลูกทั้ง tree ก่อน wrapper ตาย — กัน orphan python (ดู pm2_main.js)
let killed = false;
function killChild() {
  if (killed || !child.pid) return;
  killed = true;
  try { spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' }); } catch (e) {}
}
process.on('exit', killChild);
process.on('SIGINT', () => { killChild(); process.exit(0); });
process.on('SIGTERM', () => { killChild(); process.exit(0); });

child.on('close', (code) => { killed = true; process.exit(code ?? 0); });

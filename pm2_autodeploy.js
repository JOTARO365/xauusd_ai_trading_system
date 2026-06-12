const { spawn, spawnSync } = require('child_process');
const path = require('path');

const child = spawn('powershell.exe', [
  '-NonInteractive',
  '-ExecutionPolicy', 'Bypass',
  '-File', path.join(__dirname, 'scripts', 'auto_deploy.ps1'),
], {
  cwd: __dirname,
  stdio: 'inherit',
});

// ฆ่าลูกทั้ง tree ก่อน wrapper ตาย — กัน powershell ค้างเป็น orphan (ดู pm2_main.js)
let killed = false;
function killChild() {
  if (killed || !child.pid) return;
  killed = true;
  try { spawnSync('taskkill', ['/PID', String(child.pid), '/T', '/F'], { stdio: 'ignore' }); } catch (e) {}
}
process.on('exit', killChild);
process.on('SIGINT', () => { killChild(); process.exit(0); });
process.on('SIGTERM', () => { killChild(); process.exit(0); });

child.on('close', (code) => { killed = true; process.exit(code ?? 1); });

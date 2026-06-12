const { spawn, spawnSync } = require('child_process');
const path = require('path');

const child = spawn('python', [path.join(__dirname, 'main.py')], {
  cwd: __dirname,
  stdio: 'inherit',
  env: Object.assign({}, process.env, { PYTHONUNBUFFERED: '1' }),
});

// pm2 restart/stop ฆ่าแค่ node wrapper — ลูก python บน Windows ไม่ตายตาม
// → orphan ถือ logs/bot.pid ค้าง ทำให้ตัวใหม่ start ไม่ได้ (crash loop ↺ เป็นพัน)
// แก้: ฆ่าลูกทั้ง tree ก่อน wrapper ตายเสมอ (sync เท่านั้นที่รันได้ใน 'exit')
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

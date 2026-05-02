const { spawn } = require('child_process');
const path = require('path');

const child = spawn('python', [path.join(__dirname, 'dashboard', 'app.py')], {
  cwd: __dirname,
  stdio: 'inherit',
  env: Object.assign({}, process.env, { PYTHONUNBUFFERED: '1' }),
});

child.on('close', (code) => process.exit(code ?? 1));

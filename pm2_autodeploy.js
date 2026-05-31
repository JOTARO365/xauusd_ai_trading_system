const { spawn } = require('child_process');
const path = require('path');

const child = spawn('powershell.exe', [
  '-NonInteractive',
  '-ExecutionPolicy', 'Bypass',
  '-File', path.join(__dirname, 'scripts', 'auto_deploy.ps1'),
], {
  cwd: __dirname,
  stdio: 'inherit',
});

child.on('close', (code) => process.exit(code ?? 1));

const path = require('path');
const APP_DIR = path.resolve(__dirname);

module.exports = {
  apps: [
    {
      name: "main",
      script: "pm2_main.js",
      cwd: APP_DIR,
      autorestart: true,
      watch: false,
      max_restarts: 5,
      restart_delay: 3000,
    },
    {
      name: "dashboard",
      script: "pm2_dashboard.js",
      cwd: APP_DIR,
      autorestart: true,
      watch: false,
      max_restarts: 10,
      restart_delay: 1000,
    },
  ],
};

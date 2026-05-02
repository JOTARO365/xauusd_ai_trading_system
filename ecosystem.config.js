module.exports = {
  apps: [
    {
      name: "main",
      script: "pm2_main.js",
      cwd: "D:\\claude_workspace\\claude_trading_system",
      autorestart: true,
      watch: false,
      max_restarts: 5,
      restart_delay: 3000,
    },
    {
      name: "dashboard",
      script: "pm2_dashboard.js",
      cwd: "D:\\claude_workspace\\claude_trading_system",
      autorestart: true,
      watch: false,
      max_restarts: 10,
      restart_delay: 1000,
    },
  ],
};

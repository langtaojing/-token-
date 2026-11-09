# 公网 IP 部署记录（公开仓库版本：真实 IP 与服务器路径已替换为占位符，详见仓库历史）

- 公网入口：https://203.0.113.10
- ECS：Ubuntu 22.04，2 核 4 GiB；FastAPI 只监听 127.0.0.1:8000。
- Nginx：80 端口处理 ACME 验证并跳转 HTTPS，443 端口反代至 FastAPI。
- TLS：Let's Encrypt IP 地址短期证书，约 6 天有效；ai-team-hub-cert-renew.timer 每天两次检查自动续期。
- 服务器配置：/etc/<app>.env（600 权限），不在 GitHub。
- 数据：/var/lib/<app>/trial.sqlite3 和上传文件，不在 GitHub。需要定期备份。
- 管理员凭据：/root/<app>-admin.txt（600 权限），不在 GitHub。服务器使用随机强密码，不使用本机的 admin/admin。
- 注册：生产环境允许注册；每 IP 每小时限 5 次注册、30 次登录尝试。普通用户每天默认 20 次请求、20,000 Token。

服务检查：systemctl status ai-team-hub nginx。证书检查：/opt/certbot-venv/bin/certbot certificates。手动预演续期：/opt/certbot-venv/bin/certbot renew --dry-run --no-random-sleep-on-renew。

手机和电脑使用同一个 HTTPS 地址。桌面 EXE 仍是本机入口，不是云端必需组件。

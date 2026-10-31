# AI Team Hub · 邀请制朋友试用版

当前主页已经更新为真实登录与 MiniMax 调用。旧演示页面和模拟功能已移除。

## 本机启动

1. 在项目根目录创建 .env，参考 .env.example，填入 MiniMax API Key。不要把 .env 上传到 GitHub。
2. 首次使用时，在 PowerShell 中进入项目目录，运行：

   ./.venv/Scripts/python.exe -m backend.create_admin

   按提示创建管理员用户名和密码。密码输入时不会显示。
3. 运行 ./run-local.ps1，打开终端显示的网址。启动脚本会在 8000～8010 中选择空闲端口。
4. 用刚创建的管理员账号登录首页。

## 创建朋友账号

在项目目录运行：

./.venv/Scripts/python.exe -m backend.manage_users add friend1 --requests 20 --tokens 20000

命令会让你输入朋友的初始密码。通过私密渠道把用户名和密码交给朋友。查看账号：

./.venv/Scripts/python.exe -m backend.manage_users list

停用账号并撤销该用户的会话：

./.venv/Scripts/python.exe -m backend.manage_users disable friend1

## 试用范围和限制

- 服务默认仅监听 127.0.0.1，只供这台电脑访问。给朋友远程使用时，应通过可信的私有网络或带 HTTPS 的反向代理接入，不能直接把当前端口暴露到公网。
- 后端使用 SQLite 保存账号、密码哈希、会话和用量，不保存完整问题或回答。数据库位于 data/trial.sqlite3，已经被 Git 忽略。
- 每个账号的每日请求次数和 Token 上限由后端核对。单次输入上限为 12,000 字符。
- 目前只接一个 MiniMax 模型。实际 Token 由 MiniMax 返回；费用和支付尚未实现。
- API Key 只放在本机 .env，不会出现在网页或 GitHub。此前若曾在截图中暴露密钥，应在 MiniMax 控制台撤销并更换。
用户可在登录页点击“注册”自行创建账号；新账号默认每天 20 次请求、20,000 Token。管理员登录后可在页面底部调整额度、停用或启用账号。账号和密码由用户自行定义，不强制 12 位。
Agent 编排：每次请求会经过规划、执行、复查三个阶段，三个阶段都使用 MiniMax Token，因此 Token 和耗时会高于单次调用。

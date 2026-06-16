# 金狗雷达 · GMGN 特征分析

## 安装
```bash
pip install -r requirements.txt
npm install -g gmgn-cli   # 若未安装
```

## 配置
复制 `.env.example` 为 `.env` 并填写：金狗雷达后端地址、账号密码、链。
GMGN：把 `GMGN_API_KEY` 写到 `~/.config/gmgn/.env`（去 https://gmgn.ai/ai 创建）。

## 运行
```bash
# 加载 .env（PowerShell：见下）后：
python -m app.main all        # 采集器 + 看板一起跑
python -m app.main collector  # 只采集
python -m app.main api        # 只看板（读已有库）
```
看板：浏览器打开 http://127.0.0.1:8000

PowerShell 加载 .env：
```powershell
Get-Content .env | Where-Object { $_ -and $_ -notmatch '^#' } | ForEach-Object {
  $k,$v = $_ -split '=',2; [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim())
}
```

## 说明
- 入场指标在推送瞬间冻结；涨跌幅每分钟刷新，追踪 24 小时。
- 冷启动库为空，需等推送积累 + 过追踪期，分桶对比才稳。

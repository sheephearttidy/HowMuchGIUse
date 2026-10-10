# HowMuchGIUse

一个轻量级的网络流量监控与统计工具，帮助你在流量不够用的情况下精确掌控每一 MB 的消耗。

## 关于

`HowMuchGIUse` 诞生于一个很实际的痛点：**流量不够用**。

手机热点、移动宽带、按量计费的云服务器——这些场景下每一 MB 都是钱。但 Windows 自带的流量统计要么藏得太深，要么只能看最近 30 天，要么根本不按网卡分开算。开个视频会议、系统自动更新、后台同步……流量不知不觉就跑光了，月底账单吓一跳。

这个工具就是来解决这个问题的：

-   **实时看** — 当前下载/上传速度一目了然
-   **事后查** — 今天用了多少、这个月用了多少、哪一天用得最猛，全部可追溯
-   **数据归你** — 所有统计数据存在本地 SQLite 数据库里，不联网、不上传，完全离线
-   **轻量纯粹** — 只有一个 Python 文件和两个标准库依赖（`sqlite3`、`psutil`），不吃系统资源

把监控挂着，该干嘛干嘛。想看的时候看一眼，月底对账单心里有数。

## 功能

-   **实时监控** — 终端里实时显示上传/下载速度和今日累计用量
-   **每日统计** — 自动记录每天的流量消耗，支持查看最近 7 天趋势
-   **月度统计** — 汇总每月总用量，一眼看出哪个月最费流量
-   **小时级粒度** — 按小时记录，方便定位流量高峰时段
-   **数据持久化** — 所有统计数据保存为 SQLite 数据库文件，关闭电脑数据不丢失
-   **多网卡支持** — 可查看所有网络接口的流量信息

## 安装

```bash
# 克隆仓库
git clone https://github.com/sheephearttidy/HowMuchGIUse.git
cd HowMuchGIUse

# 安装依赖
python -m venv venv
source venv/bin/activate
# 安装依赖
pip install --upgrade pip
pip install -r requirements.txt
```

依赖：Python 3.7+ 和 `psutil`。

## 使用

### 启动实时监控

```bash
python network_monitor.py --monitor
```

终端会每秒刷新一次，显示当前的速度和今日累计量：

```
============================================================
         网络流量监控器 (按 Ctrl+C 退出)
============================================================
时间           下载速度        上传速度        今日下载        今日上传
------------------------------------------------------------
14:32:05      1.25 MB/s     156.30 KB/s       3.42 GB       892.15 MB
```

按 `Ctrl+C` 退出，数据会自动保存。

### 查看统计面板

```bash
python network_monitor.py
```

展示完整的流量报告：总用量、今日、本月、最近 7 天趋势、月度对比。

### 查看网络接口

```bash
python network_monitor.py --interfaces
```

列出所有网卡及其累计收发数据量。

### 自定义刷新间隔

```bash
# 每 5 秒刷新一次（省 CPU）
python network_monitor.py --monitor --interval 5
```

### 重置统计数据

```bash
python network_monitor.py --reset
```

## 数据存储

统计数据保存在 `data/traffic_stats.db`（SQLite 数据库）中，表结构如下：

| 字段 | 类型 | 说明 |
|---|---|---|
| `record_type` | TEXT | 记录类型：`daily` / `monthly` / `hourly` / `total` |
| `record_key` | TEXT | 记录键：如 `2026-10-10` / `2026-10` / `2026-10-10T14` / `all` |
| `sent` | INTEGER | 累计上传字节数 |
| `recv` | INTEGER | 累计下载字节数 |

你可以用任何 SQLite 客户端直接打开 `traffic_stats.db` 查看或导出数据：

```sql
-- 查看今日用量
SELECT * FROM stats WHERE record_type = 'daily' AND record_key = date('now');

-- 查看本月汇总
SELECT SUM(sent), SUM(recv) FROM stats
WHERE record_type = 'daily' AND record_key LIKE '2026-10%';
```

默认保留最近 90 天的历史记录（`total` 和 `monthly` 类型不受影响）。

## 后台运行

### Windows

将脚本加入任务计划程序，开机自启后台监控：

1. 打开"任务计划程序"
2. 创建基本任务 → 触发器设为"计算机启动时"
3. 操作设为启动程序：`pythonw.exe`（无声窗口）
4. 参数：`C:\path\to\network_monitor.py --monitor`

或者直接最小化运行：

```powershell
Start-Process pythonw.exe -ArgumentList "network_monitor.py --monitor" -WindowStyle Hidden
```

### Linux / macOS

```bash
nohup python network_monitor.py --monitor &
```

或者配置 systemd / launchd 服务实现开机自启。

## 项目结构

```
HowMuchGIUse/
├── network_monitor.py   # 主程序
├── requirements.txt     # Python 依赖
├── data/                # 统计数据目录（自动创建）
│   └── traffic_stats.db
└── README.md
```

## 许可

MIT License
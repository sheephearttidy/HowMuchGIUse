#!/usr/bin/env python3
"""
网络流量监控与统计脚本
功能：
  1. 实时监控上传/下载速度
  2. 记录每日/每月/每小时流量使用量
  3. 数据持久化存储（SQLite 数据库）
  4. 支持命令行参数查看统计报告
"""

import argparse
import os
import signal
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta

try:
    import psutil
except ImportError:
    print("错误：需要安装 psutil 库。请运行: pip install psutil")
    sys.exit(1)


# ============================================================
# 配置
# ============================================================

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
DB_FILE = os.path.join(DATA_DIR, "traffic_stats.db")
REFRESH_INTERVAL = 1  # 刷新间隔（秒）
MAX_HISTORY_DAYS = 90  # 保留最近 90 天的历史记录


# ============================================================
# 键值生成
# ============================================================

def get_daily_key(dt=None):
    if dt is None:
        dt = datetime.now()
    return dt.strftime("%Y-%m-%d")


def get_monthly_key(dt=None):
    if dt is None:
        dt = datetime.now()
    return dt.strftime("%Y-%m")


def get_hourly_key(dt=None):
    if dt is None:
        dt = datetime.now()
    return dt.strftime("%Y-%m-%dT%H")


# ============================================================
# 数据库管理
# ============================================================

def get_db_path():
    os.makedirs(DATA_DIR, exist_ok=True)
    return DB_FILE


def init_db():
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            record_type TEXT NOT NULL,
            record_key  TEXT NOT NULL,
            sent        INTEGER NOT NULL DEFAULT 0,
            recv        INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (record_type, record_key)
        )
    """)
    conn.commit()
    return conn


def db_upsert(conn, record_type, record_key, sent_delta, recv_delta):
    """向数据库写入增量数据（累加）"""
    conn.execute("""
        INSERT INTO stats (record_type, record_key, sent, recv)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(record_type, record_key) DO UPDATE SET
            sent = sent + excluded.sent,
            recv = recv + excluded.recv
    """, (record_type, record_key, sent_delta, recv_delta))


def db_query_one(conn, record_type, record_key):
    """查询单条记录，返回 (sent, recv) 或 (0, 0)"""
    row = conn.execute(
        "SELECT sent, recv FROM stats WHERE record_type = ? AND record_key = ?",
        (record_type, record_key),
    ).fetchone()
    if row:
        return row[0], row[1]
    return 0, 0


def db_query_range(conn, record_type, keys=None):
    """查询多条记录，返回 {key: (sent, recv)} 字典"""
    if keys is None:
        rows = conn.execute(
            "SELECT record_key, sent, recv FROM stats WHERE record_type = ? ORDER BY record_key",
            (record_type,),
        ).fetchall()
    else:
        placeholders = ",".join("?" * len(keys))
        rows = conn.execute(
            f"SELECT record_key, sent, recv FROM stats WHERE record_type = ? AND record_key IN ({placeholders}) ORDER BY record_key",
            (record_type, *keys),
        ).fetchall()
    return {row[0]: (row[1], row[2]) for row in rows}


def db_cleanup(conn):
    """清理过期记录"""
    cutoff = get_daily_key(datetime.now() - timedelta(days=MAX_HISTORY_DAYS))
    conn.execute(
        "DELETE FROM stats WHERE record_type IN ('daily', 'hourly') AND record_key < ?",
        (cutoff,),
    )


def db_reset(conn):
    """清空所有记录"""
    conn.execute("DELETE FROM stats")


# ============================================================
# 网络流量获取
# ============================================================

def get_network_io():
    counters = psutil.net_io_counters()
    return counters.bytes_sent, counters.bytes_recv


def get_all_interfaces_io():
    result = {}
    io_counters = psutil.net_io_counters(pernic=True)
    for name, counters in io_counters.items():
        result[name] = {
            "bytes_sent": counters.bytes_sent,
            "bytes_recv": counters.bytes_recv,
            "packets_sent": counters.packets_sent,
            "packets_recv": counters.packets_recv,
        }
    return result


# ============================================================
# 格式化工具
# ============================================================

def format_bytes(bytes_value):
    if bytes_value < 0:
        bytes_value = 0
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_value < 1024:
            return f"{bytes_value:.2f} {unit}"
        bytes_value /= 1024
    return f"{bytes_value:.2f} PB"


def format_speed(bytes_per_sec):
    return f"{format_bytes(bytes_per_sec)}/s"


# ============================================================
# 实时监控模式
# ============================================================

class NetworkMonitor:
    """网络流量实时监控器（数据直写 SQLite）"""

    def __init__(self, refresh_interval=REFRESH_INTERVAL):
        self.running = True
        self.interval = refresh_interval
        self.conn = init_db()
        self.prev_sent, self.prev_recv = get_network_io()

        signal.signal(signal.SIGINT, self._signal_handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        print("\n正在停止监控...")
        self.running = False

    def _update_records(self, sent_delta, recv_delta):
        now = datetime.now()
        db_upsert(self.conn, "daily", get_daily_key(now), sent_delta, recv_delta)
        db_upsert(self.conn, "monthly", get_monthly_key(now), sent_delta, recv_delta)
        db_upsert(self.conn, "hourly", get_hourly_key(now), sent_delta, recv_delta)
        db_upsert(self.conn, "total", "all", sent_delta, recv_delta)

    def _get_today_stats(self):
        today_key = get_daily_key()
        sent, recv = db_query_one(self.conn, "daily", today_key)
        return {"sent": sent, "recv": recv}

    def run(self):
        print("=" * 60)
        print("         网络流量监控器 (按 Ctrl+C 退出)")
        print("=" * 60)
        print(f"{'时间':<12} {'下载速度':>14} {'上传速度':>14} {'今日下载':>14} {'今日上传':>14}")
        print("-" * 60)

        save_counter = 0

        while self.running:
            try:
                time.sleep(self.interval)

                current_sent, current_recv = get_network_io()

                sent_delta = current_sent - self.prev_sent
                recv_delta = current_recv - self.prev_recv
                if sent_delta < 0:
                    sent_delta = 0
                if recv_delta < 0:
                    recv_delta = 0

                self._update_records(sent_delta, recv_delta)

                download_speed = recv_delta / self.interval
                upload_speed = sent_delta / self.interval

                today_stats = self._get_today_stats()

                now_str = datetime.now().strftime("%H:%M:%S")
                print(
                    f"\r{now_str:<12} "
                    f"{format_speed(download_speed):>14} "
                    f"{format_speed(upload_speed):>14} "
                    f"{format_bytes(today_stats['recv']):>14} "
                    f"{format_bytes(today_stats['sent']):>14}",
                    end="",
                    flush=True,
                )

                self.prev_sent = current_sent
                self.prev_recv = current_recv

                save_counter += 1
                if save_counter >= 30:
                    self.conn.commit()
                    db_cleanup(self.conn)
                    self.conn.commit()
                    save_counter = 0

            except Exception as e:
                print(f"\n监控出错: {e}")
                time.sleep(5)

        self.conn.commit()
        db_cleanup(self.conn)
        self.conn.commit()
        self.conn.close()
        print("\n数据已保存。监控已停止。")


# ============================================================
# 统计报告模式
# ============================================================

def db_has_data(conn):
    row = conn.execute("SELECT COUNT(*) FROM stats").fetchone()
    return row[0] > 0


def show_dashboard():
    conn = init_db()

    if not db_has_data(conn):
        print("暂无统计数据。请先运行监控模式：python network_monitor.py --monitor")
        conn.close()
        return

    print("=" * 60)
    print("                    流量使用统计面板")
    print("=" * 60)

    # 总计
    total_sent, total_recv = db_query_one(conn, "total", "all")
    total_all = total_sent + total_recv
    print(f"\n  总计使用量:")
    print(f"    总下载: {format_bytes(total_recv)}")
    print(f"    总上传: {format_bytes(total_sent)}")
    print(f"    总流量: {format_bytes(total_all)}")

    # 今日统计
    today_key = get_daily_key()
    today_sent, today_recv = db_query_one(conn, "daily", today_key)
    print(f"\n  今日 ({today_key}):")
    print(f"    下载: {format_bytes(today_recv)}")
    print(f"    上传: {format_bytes(today_sent)}")
    print(f"    合计: {format_bytes(today_sent + today_recv)}")

    # 本月统计
    month_key = get_monthly_key()
    month_sent, month_recv = db_query_one(conn, "monthly", month_key)
    print(f"\n  本月 ({month_key}):")
    print(f"    下载: {format_bytes(month_recv)}")
    print(f"    上传: {format_bytes(month_sent)}")
    print(f"    合计: {format_bytes(month_sent + month_recv)}")

    # 每日统计（最近 7 天）
    daily_all = db_query_range(conn, "daily")
    sorted_days = sorted(daily_all.keys(), reverse=True)[:7]
    print(f"\n  最近 7 天每日统计:")
    print(f"    {'日期':<12} {'下载':>14} {'上传':>14} {'合计':>14}")
    print(f"    {'-' * 54}")
    for day in sorted_days:
        s, r = daily_all[day]
        print(
            f"    {day:<12} "
            f"{format_bytes(r):>14} "
            f"{format_bytes(s):>14} "
            f"{format_bytes(s + r):>14}"
        )

    # 月度统计
    monthly_agg = defaultdict(lambda: {"sent": 0, "recv": 0})
    for day_key, (s, r) in daily_all.items():
        m_key = day_key[:7]
        monthly_agg[m_key]["sent"] += s
        monthly_agg[m_key]["recv"] += r
    print(f"\n  月度统计:")
    print(f"    {'月份':<10} {'下载':>14} {'上传':>14} {'合计':>14}")
    print(f"    {'-' * 52}")
    for m in sorted(monthly_agg.keys(), reverse=True):
        md = monthly_agg[m]
        print(
            f"    {m:<10} "
            f"{format_bytes(md['recv']):>14} "
            f"{format_bytes(md['sent']):>14} "
            f"{format_bytes(md['sent'] + md['recv']):>14}"
        )

    print("\n" + "=" * 60)
    conn.close()


def show_interfaces():
    print("=" * 60)
    print("                    网络接口信息")
    print("=" * 60)

    interfaces = get_all_interfaces_io()
    print(f"\n  {'接口名称':<20} {'发送':>14} {'接收':>14} {'状态':>10}")
    print(f"  {'-' * 60}")

    net_stats = psutil.net_if_stats()
    for name, io_data in sorted(interfaces.items()):
        iface_stat = net_stats.get(name)
        status = "启用" if (iface_stat and iface_stat.isup) else "禁用"
        print(
            f"  {name:<20} "
            f"{format_bytes(io_data['bytes_sent']):>14} "
            f"{format_bytes(io_data['bytes_recv']):>14} "
            f"{status:>10}"
        )

    print("\n" + "=" * 60)


# ============================================================
# 命令行入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="网络流量监控与统计工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python network_monitor.py                 显示统计面板
  python network_monitor.py --monitor       启动实时监控
  python network_monitor.py --interfaces    查看网络接口信息
  python network_monitor.py --reset         重置统计数据
        """,
    )
    parser.add_argument(
        "-m", "--monitor",
        action="store_true",
        help="启动实时流量监控模式",
    )
    parser.add_argument(
        "-i", "--interfaces",
        action="store_true",
        help="显示所有网络接口信息",
    )
    parser.add_argument(
        "-r", "--reset",
        action="store_true",
        help="重置所有统计数据",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=REFRESH_INTERVAL,
        help=f"监控刷新间隔（秒），默认 {REFRESH_INTERVAL}",
    )

    args = parser.parse_args()

    if args.reset:
        confirm = input("确认要重置所有统计数据吗？(y/N): ")
        if confirm.lower() == "y":
            conn = init_db()
            db_reset(conn)
            conn.commit()
            conn.close()
            print("统计数据已重置。")
        else:
            print("操作已取消。")
        return

    if args.monitor:
        monitor = NetworkMonitor(refresh_interval=args.interval)
        monitor.run()
    elif args.interfaces:
        show_interfaces()
    else:
        show_dashboard()


if __name__ == "__main__":
    main()
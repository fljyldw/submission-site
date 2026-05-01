import os
import csv
import json
import uuid
import math
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

REQUIRE_DURATION_HOURS = 5  # 所有有效时段总时长需达到（小时）
GAP_THRESHOLD_MINUTES = 60  # 相邻点间隔超过此值视为中断，划分出新时段（分钟）

def analyze_csv(csv_path):
    """
    解析上传的CSV文件，分析连续录制时长。
    返回 dict: {
        "passed": bool,
        "max_duration_hours": float,
        "max_duration_str": str,
        "total_records": int,
        "total_duration_hours": float,
        "total_duration_str": str,
        "segments": [{"start": str, "end": str, "duration_hours": float}, ...],
        "detail": str
    }
    """
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        return {"error": f"CSV 文件解析失败：{str(e)}"}

    if not rows:
        return {"error": "CSV 文件为空"}

    if "geoTime" not in rows[0]:
        return {"error": "CSV 文件缺少 geoTime 字段"}

    # 提取并排序时间戳（毫秒）
    timestamps = []
    for row in rows:
        try:
            ts = int(row["geoTime"]) / 1000.0  # 转为秒
            # 转换为本地时间（自动处理时区）
            real_time = datetime.fromtimestamp(ts)
            timestamps.append(ts)
        except (ValueError, TypeError):
            continue

    if len(timestamps) < 2:
        return {"error": f"有效定位记录不足（仅 {len(timestamps)} 条），无法计算时长"}

    # timestamps.sort()

    # 划分连续时段：相邻点间隔超过 GAP_THRESHOLD_MINUTES 则断开
    gap_seconds = GAP_THRESHOLD_MINUTES * 60
    segments = []
    seg_start = timestamps[0]

    for i in range(1, len(timestamps)):
        if timestamps[i] - timestamps[i - 1] > gap_seconds:
            # 断开了，保存上一个时段
            segments.append({
                "start": seg_start,
                "end": timestamps[i - 1],
            })
            seg_start = timestamps[i]

    # 添加最后一个时段
    segments.append({
        "start": seg_start,
        "end": timestamps[-1],
    })

    # 计算每个时段时长
    for seg in segments:
        seg["duration_seconds"] = seg["end"] - seg["start"]

    # 找出最长连续时段
    longest = max(segments, key=lambda s: s["duration_seconds"])

    # 总时长
    total_seconds = timestamps[-1] - timestamps[0]

    def fmt_time(ts):
        """秒数转为 X小时Y分钟 格式"""
        h = int(ts // 3600)
        m = int((ts % 3600) // 60)
        if h > 0:
            return f"{h}小时{m}分钟"
        return f"{m}分钟"

    def fmt_datetime(ts):
        return datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=8))).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    # 总有效时长 = 所有连续时段之和
    total_effective_seconds = sum(seg["duration_seconds"] for seg in segments)

    max_hours = round(longest["duration_seconds"] / 3600, 2)
    total_hours = round(total_effective_seconds / 3600, 2)
    passed = total_hours >= REQUIRE_DURATION_HOURS

    detail = (
        f"共 {len(timestamps)} 条定位记录，"
        f"分为 {len(segments)} 个连续时段。"
        f"最长连续录制 {fmt_time(longest['duration_seconds'])}，"
        f"各时段合计 {fmt_time(total_effective_seconds)}。"
    )
    print(passed)
    if passed:
        detail += f" 合计已达到 {REQUIRE_DURATION_HOURS} 小时要求，审核通过！"
    else:
        detail += f" 合计未达到 {REQUIRE_DURATION_HOURS} 小时要求（还差 {fmt_time(REQUIRE_DURATION_HOURS - total_hours)}），审核不通过。"


if __name__ == "__main__":
    csv_path = "uploads/20260428_181632_1_1_3A607CA2.csv"

    analyze_csv(csv_path)
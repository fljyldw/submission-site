import os
import csv
import uuid
import math
from urllib.parse import quote_plus
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from flask import Flask, request, jsonify, send_from_directory, Response, session, redirect
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_

load_dotenv()

app = Flask(__name__, static_folder="static")
CORS(app)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key-change-me")


def build_database_uri():
    """优先使用 DATABASE_URL，否则拼接 MySQL 连接串。"""
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        if database_url.startswith("sqlite:"):
            raise RuntimeError("已移除 SQLite 支持，请改用 MySQL 连接串")
        return database_url

    mysql_user = os.environ.get("MYSQL_USER", "root")
    mysql_password = os.environ.get("MYSQL_PASSWORD", "")
    mysql_host = os.environ.get("MYSQL_HOST", "127.0.0.1")
    mysql_port = os.environ.get("MYSQL_PORT", "3306")
    mysql_database = os.environ.get("MYSQL_DATABASE", "submission_site")

    if not mysql_password:
        raise RuntimeError("MYSQL_PASSWORD 未配置，请在 .env 或环境变量中设置")

    encoded_password = quote_plus(mysql_password)
    return (
        f"mysql+pymysql://{mysql_user}:{encoded_password}"
        f"@{mysql_host}:{mysql_port}/{mysql_database}?charset=utf8mb4"
    )


app.config['SQLALCHEMY_DATABASE_URI'] = build_database_uri()
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "123456")


def verify_student(name, student_id):
    """
    学生身份校验（预留：后续可对接真实姓名-学号映射表）。
    当前需求为“暂定全部正确”，故仅做非空校验并返回通过。
    """
    if not name or not student_id:
        return False, "姓名或学号不能为空"
    return True, "校验通过"


def is_admin_authed():
    return session.get("admin_authed", False)


def is_student_authed():
    return bool(session.get("student_name") and session.get("student_id"))

# 上传文件保存目录
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", os.path.join(os.path.dirname(__file__), "uploads"))
os.makedirs(UPLOAD_DIR, exist_ok=True)

class Submission(db.Model):
    __tablename__ = "submissions"

    id = db.Column(db.Integer, primary_key=True)
    submission_id = db.Column(db.String(16), unique=True, nullable=False)

    name = db.Column(db.String(50), nullable=False)
    student_id = db.Column(db.String(50), nullable=False)

    filename = db.Column(db.String(200))
    submitted_at = db.Column(db.DateTime)

    status = db.Column(db.String(20))  # 审核通过 / 未通过

    max_duration_str = db.Column(db.String(50))
    max_segment_start = db.Column(db.String(50))
    max_segment_end = db.Column(db.String(50))

def submission_to_dict(submission):
    return {
        "submission_id": submission.submission_id,
        "name": submission.name,
        "student_id": submission.student_id,
        "filename": submission.filename,
        "submitted_at": submission.submitted_at.isoformat() if submission.submitted_at else "",
        "status": submission.status,
        "max_duration_str": submission.max_duration_str,
        "max_segment_start": submission.max_segment_start,
        "max_segment_end": submission.max_segment_end,
    }


REQUIRE_DURATION_HOURS = 5  # 所有有效时段总时长需达到（小时）
GAP_THRESHOLD_MINUTES = 60  # 相邻点间隔超过此值视为中断，划分出新时段（分钟）


# ===== WGS-84 → GCJ-02 坐标转换（火星坐标系） =====
_PI = 3.1415926535897932384626
_A = 6378245.0  # 长半轴
_EE = 0.00669342162296594323  # 偏心率平方
LAT_CANDIDATES = ["latitude", "lat", "纬度", "Latitude"]
LON_CANDIDATES = ["longitude", "lng", "lon", "经度", "Longitude"]


def _out_of_china(lng, lat):
    """判断是否在中国境外"""
    return not (72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271)


def _transform_lat(lng, lat):
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + \
          0.1 * lng * lat + 0.2 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * _PI) + 20.0 *
            math.sin(2.0 * lng * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * _PI) + 40.0 *
            math.sin(lat / 3.0 * _PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * _PI) + 320.0 *
            math.sin(lat * _PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(lng, lat):
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + \
          0.1 * lng * lat + 0.1 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * _PI) + 20.0 *
            math.sin(2.0 * lng * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * _PI) + 40.0 *
            math.sin(lng / 3.0 * _PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * _PI) + 300.0 *
            math.sin(lng / 30.0 * _PI)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lng, lat):
    """将 WGS-84 坐标转换为 GCJ-02（火星坐标系）"""
    if _out_of_china(lng, lat):
        return lng, lat
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * _PI
    magic = math.sin(radlat)
    magic = 1 - _EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrtmagic) * _PI)
    dlng = (dlng * 180.0) / (_A / sqrtmagic * math.cos(radlat) * _PI)
    return lng + dlng, lat + dlat


def convert_csv_wgs_to_gcj(csv_path):
    """
    将上传 CSV 中的 WGS-84 经纬度就地转换为 GCJ-02。
    只在提交时执行一次，后续轨迹展示直接读取。
    """
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            rows = list(reader)
    except Exception as e:
        return {"error": f"CSV 文件读取失败：{str(e)}"}

    if not fieldnames:
        return {"error": "CSV 表头为空，无法转换坐标"}

    lat_key = next((k for k in LAT_CANDIDATES if k in fieldnames), None)
    lon_key = next((k for k in LON_CANDIDATES if k in fieldnames), None)
    if not lat_key or not lon_key:
        return {"error": f"CSV 中未找到经纬度字段（可用列：{', '.join(fieldnames)}）"}

    converted = 0
    for row in rows:
        try:
            lat = float(row.get(lat_key, ""))
            lng = float(row.get(lon_key, ""))
            if lat == 0 and lng == 0:
                continue
            gcj_lng, gcj_lat = wgs84_to_gcj02(lng, lat)
            row[lat_key] = f"{gcj_lat:.6f}"
            row[lon_key] = f"{gcj_lng:.6f}"
            converted += 1
        except (ValueError, TypeError):
            continue

    try:
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    except Exception as e:
        return {"error": f"CSV 文件写回失败：{str(e)}"}

    return {"converted_points": converted}


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

    if passed:
        detail += f" 合计已达到 {REQUIRE_DURATION_HOURS} 小时要求，审核通过！"
    else:
        detail += f" 合计未达到 {REQUIRE_DURATION_HOURS} 小时要求（还差 {fmt_time(REQUIRE_DURATION_HOURS - total_hours)}），审核不通过。"

    return {
        "passed": passed,
        "max_duration_hours": max_hours,
        "max_duration_str": fmt_time(longest["duration_seconds"]),
        "max_segment_start": fmt_datetime(longest["start"]),
        "max_segment_end": fmt_datetime(longest["end"]),
        "total_records": len(timestamps),
        "total_duration_hours": total_hours,
        "total_duration_str": fmt_time(total_effective_seconds),
        "segment_count": len(segments),
        "segments": [
            {
                "start": fmt_datetime(s["start"]),
                "end": fmt_datetime(s["end"]),
                "duration_str": fmt_time(s["duration_seconds"]),
                "duration_hours": round(s["duration_seconds"] / 3600, 2),
            }
            for s in segments
        ],
        "detail": detail,
    }


@app.route("/")
def index():
    """入口选择页"""
    return send_from_directory("static", "index.html")


@app.route("/submit")
def submit_page():
    """学生端入口：先登录，再进入提交/查询页面"""
    if not is_student_authed():
        return redirect("/?login=student")
    return send_from_directory("static", "student.html")


@app.route("/student-login")
def student_login_page():
    return send_from_directory("static", "student-login.html")


@app.route("/api/student/login", methods=["POST"])
def student_login():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    student_id = str(payload.get("student_id", "")).strip()
    valid, message = verify_student(name, student_id)
    if not valid:
        return jsonify({"success": False, "message": message}), 400

    session["student_name"] = name
    session["student_id"] = student_id
    return jsonify({"success": True, "message": "登录成功"})


@app.route("/api/student/logout", methods=["POST"])
def student_logout():
    session.pop("student_name", None)
    session.pop("student_id", None)
    return jsonify({"success": True})


@app.route("/api/validate-student", methods=["POST"])
def validate_student():
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()
    student_id = str(payload.get("student_id", "")).strip()
    valid, message = verify_student(name, student_id)
    return jsonify({"valid": valid, "message": message}), (200 if valid else 400)


@app.route("/api/submit", methods=["POST"])
def submit():
    name = request.form.get("name", "").strip() or session.get("student_name", "")
    student_id = request.form.get("student_id", "").strip() or session.get("student_id", "")
    csv_file = request.files.get("csv_file")

    # 基本校验
    if not name:
        return jsonify({"success": False, "message": "姓名不能为空"}), 400
    if not student_id:
        return jsonify({"success": False, "message": "学号不能为空"}), 400
    if not csv_file:
        return jsonify({"success": False, "message": "请上传 CSV 文件"}), 400
    if not csv_file.filename.lower().endswith(".csv"):
        return jsonify({"success": False, "message": "仅支持 .csv 格式的文件"}), 400

    valid, verify_message = verify_student(name, student_id)
    if not valid:
        return jsonify({"success": False, "message": verify_message}), 400

    # 保存 CSV 文件
    submission_id = str(uuid.uuid4())[:8].upper()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c for c in name if c.isalnum() or c in "-_")
    filename = f"{timestamp}_{safe_name}_{student_id}_{submission_id}.csv"
    save_path = os.path.join(UPLOAD_DIR, filename)
    csv_file.save(save_path)

    # 审核逻辑：分析CSV连续录制时长
    result = analyze_csv(save_path)

    if "error" in result:
        return jsonify({"success": False, "message": result["error"]}), 400

    passed = result["passed"]
    status = "审核通过" if passed else "审核未通过"
    message = result["detail"]

    submitted_at = datetime.now()

    new_record = Submission(
        submission_id=submission_id,
        name=name,
        student_id=student_id,
        filename=filename,
        submitted_at=submitted_at,
        status=status,
        max_duration_str=result["max_duration_str"],
        max_segment_start=result.get("max_segment_start", ""),
        max_segment_end=result.get("max_segment_end", ""),
    )

    db.session.add(new_record)
    db.session.commit()



    return jsonify({
        "success": True,
        "message": message,
        "submission_id": submission_id,
        "status": status,
        "passed": passed,
        "submitted_at": submitted_at.isoformat(),
        "analysis": result,
    })


@app.route("/api/records", methods=["GET"])
def get_records():
    """查看所有提交记录（管理用）"""
    records = Submission.query.order_by(Submission.submitted_at.desc()).all()
    records_data = [submission_to_dict(r) for r in records]
    return jsonify({"total": len(records_data), "records": records_data})


@app.route("/api/my-records", methods=["GET"])
def get_my_records():
    """学生端仅查询本人提交记录"""
    name = request.args.get("name", "").strip() or session.get("student_name", "")
    student_id = request.args.get("student_id", "").strip() or session.get("student_id", "")
    valid, verify_message = verify_student(name, student_id)
    if not valid:
        return jsonify({"message": verify_message, "total": 0, "records": []}), 400

    records = (
        Submission.query
        .filter_by(name=name, student_id=student_id)
        .order_by(Submission.submitted_at.desc())
        .all()
    )
    records_data = [submission_to_dict(r) for r in records]
    return jsonify({"total": len(records_data), "records": records_data})


@app.route("/admin-login")
def admin_login_page():
    return send_from_directory("static", "admin-login.html")


@app.route("/admin")
def admin_page():
    if not is_admin_authed():
        return redirect("/?login=admin")
    return send_from_directory("static", "admin.html")


@app.route("/api/admin/login", methods=["POST"])
def admin_login():
    payload = request.get_json(silent=True) or {}
    password = str(payload.get("password", ""))
    if password != ADMIN_PASSWORD:
        return jsonify({"success": False, "message": "密码错误"}), 401

    session["admin_authed"] = True
    return jsonify({"success": True, "message": "登录成功"})


@app.route("/api/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("admin_authed", None)
    return jsonify({"success": True})


@app.route("/api/admin/summary", methods=["GET"])
def admin_summary():
    """统计总览数据"""
    if not is_admin_authed():
        return jsonify({"error": "未登录或登录已过期"}), 401
    total = Submission.query.count()
    passed = Submission.query.filter_by(status="审核通过").count()
    failed = total - passed
    # 按学号去重统计提交人数
    unique_students = (
        db.session.query(Submission.student_id)
        .filter(Submission.student_id.isnot(None), Submission.student_id != "")
        .distinct()
        .count()
    )
    return jsonify({
        "total": total,
        "passed": passed,
        "failed": failed,
        "pass_rate": round(passed / total * 100, 1) if total > 0 else 0,
        "unique_students": unique_students,
    })


@app.route("/api/admin/records", methods=["GET"])
def admin_records():
    """分页 + 筛选获取提交记录"""
    if not is_admin_authed():
        return jsonify({"error": "未登录或登录已过期"}), 401
    query = Submission.query
    status_filter = request.args.get("status", "")
    keyword = request.args.get("keyword", "").strip()

    if status_filter:
        query = query.filter(Submission.status == status_filter)
    if keyword:
        kw = keyword.lower()
        query = query.filter(
            or_(
                Submission.name.ilike(f"%{kw}%"),
                Submission.student_id.ilike(f"%{kw}%")
            )
        )

    records = query.order_by(Submission.submitted_at.desc()).all()
    records_data = [submission_to_dict(r) for r in records]
    return jsonify({"total": len(records_data), "records": records_data})


@app.route("/api/admin/detail/<submission_id>", methods=["GET"])
def admin_detail(submission_id):
    """查看某条提交的详细审核信息（重新分析CSV）"""
    if not is_admin_authed():
        return jsonify({"error": "未登录或登录已过期"}), 401
    record = Submission.query.filter_by(submission_id=submission_id).first()
    if not record:
        return jsonify({"error": "未找到该提交记录"}), 404

    record_data = submission_to_dict(record)
    # 重新分析CSV文件
    csv_path = os.path.join(UPLOAD_DIR, record.filename or "")
    if not os.path.exists(csv_path):
        return jsonify({"record": record_data, "analysis": None, "error": "CSV 文件已丢失"})
    analysis = analyze_csv(csv_path)
    return jsonify({"record": record_data, "analysis": analysis})


@app.route("/api/admin/export", methods=["GET"])
def admin_export():
    """导出所有提交记录为 CSV"""
    if not is_admin_authed():
        return jsonify({"error": "未登录或登录已过期"}), 401
    query = Submission.query
    status_filter = request.args.get("status", "")
    if status_filter:
        query = query.filter(Submission.status == status_filter)
    records = query.order_by(Submission.submitted_at.desc()).all()

    csv_content = "\uFEFF"  # BOM for Excel
    csv_content += "提交编号,姓名,学号,提交时间,审核状态,最长连续录制,最长时段开始,最长时段结束,文件名\n"
    for r in records:
        csv_content += (
            f"{r.submission_id or ''},{r.name or ''},{r.student_id or ''},"
            f"{r.submitted_at.isoformat() if r.submitted_at else ''},{r.status or ''},"
            f"{r.max_duration_str or ''},{r.max_segment_start or ''},"
            f"{r.max_segment_end or ''},{r.filename or ''}\n"
        )

    return Response(
        csv_content,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=submissions_export.csv"}
    )


@app.route("/api/admin/track/<submission_id>", methods=["GET"])
def admin_track(submission_id):
    """获取某条提交的轨迹数据（经纬度 + 时间）"""
    if not is_admin_authed():
        return jsonify({"error": "未登录或登录已过期"}), 401
    record = Submission.query.filter_by(submission_id=submission_id).first()
    if not record:
        return jsonify({"error": "未找到该提交记录"}), 404

    csv_path = os.path.join(UPLOAD_DIR, record.filename or "")
    if not os.path.exists(csv_path):
        return jsonify({"error": "CSV 文件已丢失"}), 404

    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception as e:
        return jsonify({"error": f"CSV 解析失败：{str(e)}"}), 400

    if not rows:
        return jsonify({"error": "CSV 文件为空"}), 400

    # 确定经纬度列名（兼容不同CSV格式）
    lat_key = lon_key = time_key = None
    for candidate in LAT_CANDIDATES:
        if candidate in rows[0]:
            lat_key = candidate
            break
    for candidate in LON_CANDIDATES:
        if candidate in rows[0]:
            lon_key = candidate
            break
    for candidate in ["geoTime", "timestamp", "time", "时间"]:
        if candidate in rows[0]:
            time_key = candidate
            break

    if not lat_key or not lon_key:
        return jsonify({"error": f"CSV 中未找到经纬度字段（可用列：{', '.join(rows[0].keys())}）"}), 400

    # 提取轨迹点
    points = []
    for row in rows:
        try:
            lat = float(row[lat_key])
            lng = float(row[lon_key])
            if lat == 0 and lng == 0:
                continue
            # gcj_lng, gcj_lat = wgs84_to_gcj02(lng, lat)
            gcj_lng, gcj_lat = lng, lat
            pt = {"lat": round(gcj_lat, 6), "lng": round(gcj_lng, 6)}
            if time_key:
                try:
                    ts = int(row[time_key]) / 1000.0
                    pt["time"] = datetime.fromtimestamp(ts, tz=timezone(timedelta(hours=8))).strftime(
                        "%H:%M:%S"
                    )
                    pt["timestamp"] = ts
                except (ValueError, TypeError):
                    pass
            points.append(pt)
        except (ValueError, TypeError):
            continue

    # 按时间排序
    if points and "timestamp" in points[0]:
        points.sort(key=lambda p: p.get("timestamp", 0))

    return jsonify({
        "record": {
            "submission_id": record.submission_id,
            "name": record.name,
            "student_id": record.student_id,
            "status": record.status,
        },
        "total_points": len(points),
        "points": points,
    })


with app.app_context():
    db.create_all()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"服务器启动中... 访问 http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)

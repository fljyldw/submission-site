import os
import json
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder="static")
CORS(app)

# 上传文件保存目录（Render 环境变量优先，否则用本地路径）
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", os.path.join(os.path.dirname(__file__), "uploads"))
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 提交记录存储文件
RECORDS_FILE = os.environ.get("RECORDS_FILE", os.path.join(os.path.dirname(__file__), "submissions.json"))


def load_records():
    if os.path.exists(RECORDS_FILE):
        with open(RECORDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save_records(records):
    with open(RECORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/submit", methods=["POST"])
def submit():
    name = request.form.get("name", "").strip()
    student_id = request.form.get("student_id", "").strip()
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

    # 保存 CSV 文件
    submission_id = str(uuid.uuid4())[:8].upper()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c for c in name if c.isalnum() or c in "-_")
    filename = f"{timestamp}_{safe_name}_{student_id}_{submission_id}.csv"
    save_path = os.path.join(UPLOAD_DIR, filename)
    csv_file.save(save_path)

    # 记录提交信息
    record = {
        "submission_id": submission_id,
        "name": name,
        "student_id": student_id,
        "filename": filename,
        "submitted_at": datetime.now().isoformat(),
        "status": "审核通过",
    }
    records = load_records()
    records.append(record)
    save_records(records)

    return jsonify({
        "success": True,
        "message": "提交成功，审核通过！",
        "submission_id": submission_id,
        "status": "审核通过",
        "submitted_at": record["submitted_at"],
    })


@app.route("/api/records", methods=["GET"])
def get_records():
    """查看所有提交记录（管理用）"""
    records = load_records()
    return jsonify({"total": len(records), "records": records})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"服务器启动中... 访问 http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)

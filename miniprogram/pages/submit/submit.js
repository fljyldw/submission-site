function getBaseUrl() {
  const app = getApp();
  return app.globalData.baseUrl;
}

Page({
  data: {
    name: "",
    studentId: "",
    filePath: "",
    fileName: "",
    uploading: false,
    result: null,
  },

  onShow() {
    const currentStudent = getApp().globalData.currentStudent;
    if (!currentStudent || !currentStudent.name || !currentStudent.studentId) {
      wx.showToast({ title: "请先完成身份认证", icon: "none" });
      wx.redirectTo({ url: "/pages/home/home" });
      return;
    }
    this.setData({
      name: currentStudent.name,
      studentId: currentStudent.studentId,
    });
  },

  chooseCsv() {
    wx.chooseMessageFile({
      count: 1,
      type: "file",
      extension: ["csv"],
      success: (res) => {
        const file = (res.tempFiles && res.tempFiles[0]) || null;
        if (!file) {
          wx.showToast({ title: "未选择文件", icon: "none" });
          return;
        }
        this.setData({
          filePath: file.path,
          fileName: file.name || "unknown.csv",
        });
      },
      fail: () => {
        wx.showToast({ title: "选择文件失败", icon: "none" });
      },
    });
  },

  submitForm() {
    const { name, studentId, filePath, uploading } = this.data;
    if (uploading) {
      return;
    }
    if (!name) {
      wx.showToast({ title: "姓名不能为空", icon: "none" });
      return;
    }
    if (!studentId) {
      wx.showToast({ title: "学号不能为空", icon: "none" });
      return;
    }
    if (!filePath) {
      wx.showToast({ title: "请先选择CSV文件", icon: "none" });
      return;
    }

    this.setData({ uploading: true, result: null });
    this.validateAndUpload(name, studentId, filePath);
  },

  validateAndUpload(name, studentId, filePath) {
    wx.request({
      url: `${getBaseUrl()}/api/validate-student`,
      method: "POST",
      header: { "content-type": "application/json" },
      data: {
        name,
        student_id: studentId,
      },
      success: (verifyRes) => {
        const verifyData = verifyRes.data || {};
        if (verifyRes.statusCode >= 200 && verifyRes.statusCode < 300 && verifyData.valid) {
          this.uploadCsv(name, studentId, filePath);
          return;
        }
        this.setData({ uploading: false });
        wx.showToast({
          title: verifyData.message || "身份校验失败",
          icon: "none",
          duration: 2500,
        });
      },
      fail: () => {
        this.setData({ uploading: false });
        wx.showToast({ title: "身份校验网络异常", icon: "none" });
      },
    });
  },

  uploadCsv(name, studentId, filePath) {
    wx.uploadFile({
      url: `${getBaseUrl()}/api/submit`,
      filePath,
      name: "csv_file",
      formData: {
        name,
        student_id: studentId,
      },
      success: (res) => {
        let data = {};
        try {
          data = JSON.parse(res.data || "{}");
        } catch (err) {
          wx.showToast({ title: "服务器返回格式错误", icon: "none" });
          return;
        }

        if (res.statusCode >= 200 && res.statusCode < 300 && data.success) {
          this.setData({ result: data });
          getApp().globalData.currentStudent = { name, studentId };
          wx.showToast({ title: "提交成功", icon: "success" });
          return;
        }

        wx.showToast({
          title: data.message || `提交失败(${res.statusCode})`,
          icon: "none",
          duration: 2500,
        });
      },
      fail: () => {
        wx.showToast({ title: "网络异常，提交失败", icon: "none" });
      },
      complete: () => {
        this.setData({ uploading: false });
      },
    });
  },

  goToRecords() {
    wx.navigateTo({
      url: "/pages/records/records",
    });
  },
});

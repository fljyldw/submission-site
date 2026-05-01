function getBaseUrl() {
  return getApp().globalData.baseUrl;
}

Page({
  data: {
    name: "",
    studentId: "",
    authed: false,
    verifying: false,
  },

  onShow() {
    const currentStudent = getApp().globalData.currentStudent;
    if (currentStudent && currentStudent.name && currentStudent.studentId) {
      this.setData({
        name: currentStudent.name,
        studentId: currentStudent.studentId,
        authed: true,
      });
    }
  },

  onNameInput(e) {
    this.setData({ name: e.detail.value.trim() });
  },

  onStudentIdInput(e) {
    this.setData({ studentId: e.detail.value.trim() });
  },

  verifyStudent() {
    if (this.data.verifying) return;
    const { name, studentId } = this.data;
    if (!name || !studentId) {
      wx.showToast({ title: "姓名和学号不能为空", icon: "none" });
      return;
    }

    this.setData({ verifying: true });
    wx.request({
      url: `${getBaseUrl()}/api/validate-student`,
      method: "POST",
      header: { "content-type": "application/json" },
      data: { name, student_id: studentId },
      success: (res) => {
        const data = res.data || {};
        if (res.statusCode >= 200 && res.statusCode < 300 && data.valid) {
          getApp().globalData.currentStudent = { name, studentId };
          this.setData({ authed: true });
          wx.showToast({ title: "认证成功", icon: "success" });
          return;
        }
        wx.showToast({ title: data.message || "认证失败", icon: "none" });
      },
      fail: () => wx.showToast({ title: "网络异常", icon: "none" }),
      complete: () => this.setData({ verifying: false }),
    });
  },

  goSubmit() {
    wx.navigateTo({ url: "/pages/submit/submit" });
  },

  goRecords() {
    wx.navigateTo({ url: "/pages/records/records" });
  },

  resetAuth() {
    getApp().globalData.currentStudent = null;
    this.setData({ authed: false, name: "", studentId: "" });
  },
});

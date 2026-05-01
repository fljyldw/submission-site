function getBaseUrl() {
  const app = getApp();
  return app.globalData.baseUrl;
}

Page({
  data: {
    name: "",
    studentId: "",
    loading: false,
    total: 0,
    records: [],
  },

  onLoad(options) {
    const globalStudent = getApp().globalData.currentStudent || {};
    const name = decodeURIComponent((options && options.name) || globalStudent.name || "");
    const studentId = decodeURIComponent((options && options.studentId) || globalStudent.studentId || "");
    if (!name || !studentId) {
      wx.showToast({ title: "请先完成身份认证", icon: "none" });
      wx.redirectTo({ url: "/pages/home/home" });
      return;
    }
    this.setData({ name, studentId });
    this.loadRecords();
  },

  loadRecords() {
    if (this.data.loading) {
      return;
    }
    const { name, studentId } = this.data;
    if (!name || !studentId) return;

    this.setData({ loading: true });
    wx.request({
      url: `${getBaseUrl()}/api/my-records?name=${encodeURIComponent(name)}&student_id=${encodeURIComponent(studentId)}`,
      method: "GET",
      success: (res) => {
        const data = res.data || {};
        if (res.statusCode >= 200 && res.statusCode < 300) {
          this.setData({
            total: data.total || 0,
            records: data.records || [],
          });
          return;
        }
        wx.showToast({ title: "获取记录失败", icon: "none" });
      },
      fail: () => {
        wx.showToast({ title: "网络异常", icon: "none" });
      },
      complete: () => {
        this.setData({ loading: false });
      },
    });
  },
});

const SZI = {
  async request(path, options = {}) {
    const headers = { ...(options.headers || {}) };
    const isForm = options.body instanceof FormData;
    if (options.body && !isForm && !headers["Content-Type"]) {
      headers["Content-Type"] = "application/json";
    }
    const res = await fetch(path, { credentials: "include", ...options, headers });
    const text = await res.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = text;
      }
    }
    if (!res.ok) {
      const err = new Error((data && data.detail) || res.statusText || "Ошибка запроса");
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  },

  login(login, password) {
    return this.request("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ login, password }),
    });
  },

  me() {
    return this.request("/api/auth/me");
  },

  logout() {
    return this.request("/api/auth/logout", { method: "POST" });
  },

  async requireAdmin() {
    try {
      const user = await this.me();
      if (user.role !== "admin") {
        window.location.replace("/denied");
        return null;
      }
      return user;
    } catch (err) {
      window.location.replace("/");
      return null;
    }
  },
};

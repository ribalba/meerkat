/* Thin fetch wrapper. Exposed as window.API. Throws {status, detail} on error. */
(function () {
  async function request(method, path, body, isForm) {
    const opts = { method, headers: {}, credentials: "same-origin" };
    if (body !== undefined) {
      if (isForm) {
        opts.body = body; // FormData; let the browser set the content-type
      } else {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
      }
    }
    const resp = await fetch(path, opts);
    if (resp.status === 204) return null;
    let data = null;
    const ct = resp.headers.get("content-type") || "";
    if (ct.includes("application/json")) data = await resp.json();
    if (!resp.ok) {
      const detail = (data && data.detail) || resp.statusText;
      throw { status: resp.status, detail };
    }
    return data;
  }

  window.API = {
    get: (p) => request("GET", p),
    post: (p, b) => request("POST", p, b),
    patch: (p, b) => request("PATCH", p, b),
    del: (p) => request("DELETE", p),
    upload: (p, formData) => request("POST", p, formData, true),
  };
})();

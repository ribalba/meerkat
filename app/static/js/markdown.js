/* Markdown rendering with light sanitisation. Exposed as window.MD.render(text). */
(function () {
  function stripDangerous(html) {
    const doc = new DOMParser().parseFromString(html, "text/html");
    doc.querySelectorAll("script, iframe, object, embed, style").forEach((el) => el.remove());
    doc.querySelectorAll("*").forEach((el) => {
      for (const attr of [...el.attributes]) {
        const name = attr.name.toLowerCase();
        const val = attr.value.trim().toLowerCase();
        if (name.startsWith("on")) el.removeAttribute(attr.name);
        if ((name === "href" || name === "src") && val.startsWith("javascript:")) {
          el.removeAttribute(attr.name);
        }
      }
    });
    return doc.body.innerHTML;
  }

  window.MD = {
    render(text) {
      if (!text) return "";
      try {
        const raw = window.marked ? window.marked.parse(text, { breaks: true }) : escapeHtml(text);
        return stripDangerous(raw);
      } catch (e) {
        return escapeHtml(text);
      }
    },
  };

  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
  }
})();

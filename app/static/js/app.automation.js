/* Automation: recurring-task templates. Owner-only, managed online (not part of
 * offline sync); the server's scheduler turns each into a real todo on its cadence.
 * Rendered into the main pane via enterMainPanel("automation"). */
(function () {
  "use strict";

  const App = window.App;
  const {
    $, esc, toast, errText, STATUS, statusOf,
    liveBuckets, bucketName, labelOf, fmtDate, isValidEmail, initEmailSearch,
  } = App;

  const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]; // 0..6
  const MONTHS = ["January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"]; // 1..12

  let recCache = [];      // last list fetched from the server
  let recEditingId = null; // id being edited, or null when adding

  const ordinal = (n) => {
    const s = ["th", "st", "nd", "rd"], v = n % 100;
    return n + (s[(v - 20) % 10] || s[v] || s[0]);
  };

  // Human description of a recurring task's cadence for the list.
  function recScheduleText(r) {
    if (r.frequency === "weekly") return "Every " + (WEEKDAYS[r.day_of_week] || "?");
    if (r.frequency === "monthly") return "Monthly on the " + ordinal(r.day_of_month || 1);
    if (r.frequency === "yearly")
      return "Yearly on " + (MONTHS[(r.month_of_year || 1) - 1] || "?") + " " + ordinal(r.day_of_month || 1);
    return "Every day";
  }

  // Render the conditional "when" controls for the chosen frequency.
  function renderRecWhen(freq, vals) {
    vals = vals || {};
    const field = $("#rec-when-field");
    const el = $("#rec-when-controls");
    const days = Array.from({ length: 31 }, (_, i) => i + 1);
    if (freq === "daily") {
      field.hide();
      el.html("");
      return;
    }
    field.show();
    if (freq === "weekly") {
      const cur = vals.day_of_week != null ? vals.day_of_week : 0;
      el.html(`<select id="rec-dow" class="ui dropdown">${WEEKDAYS
        .map((d, i) => `<option value="${i}" ${i === cur ? "selected" : ""}>${d}</option>`)
        .join("")}</select>`);
    } else if (freq === "monthly") {
      const cur = vals.day_of_month || 1;
      el.html(`<select id="rec-dom" class="ui dropdown">${days
        .map((d) => `<option value="${d}" ${d === cur ? "selected" : ""}>Day ${d}</option>`)
        .join("")}</select>
        <div style="color:#888;font-size:.85em;margin-top:.3rem">Shorter months fire on their last day.</div>`);
    } else if (freq === "yearly") {
      const curM = vals.month_of_year || 1;
      const curD = vals.day_of_month || 1;
      el.html(`<div style="display:flex;gap:.5rem">
        <select id="rec-moy" class="ui dropdown">${MONTHS
          .map((m, i) => `<option value="${i + 1}" ${i + 1 === curM ? "selected" : ""}>${m}</option>`)
          .join("")}</select>
        <select id="rec-dom" class="ui dropdown">${days
          .map((d) => `<option value="${d}" ${d === curD ? "selected" : ""}>Day ${d}</option>`)
          .join("")}</select>
      </div>`);
    }
  }

  async function renderRecFormOptions() {
    const buckets = (await liveBuckets()).filter((b) => !b.archived);
    $("#rec-status").html(STATUS.map((s) => `<option value="${s.value}">${labelOf(s.value)}</option>`).join(""));
    $("#rec-bucket").html(
      buckets.map((b) => `<option value="${b.id}">${esc(b.name)}</option>`).join("") ||
      `<option value="">(create a bucket first)</option>`
    );
  }

  function resetRecForm() {
    recEditingId = null;
    $("#rec-title").val("");
    $("#rec-text").val("");
    $("#rec-status").val("open");
    $("#rec-watcher").val("");
    $("#rec-frequency").val("daily");
    $("#rec-active").prop("checked", true);
    renderRecWhen("daily", {});
    $("#rec-form-title").text("Add recurring task");
    $("#rec-save-label").text("Add recurring task");
    $("#rec-cancel").hide();
  }

  async function showAutomation() {
    App.enterMainPanel("automation");
    await renderRecFormOptions();
    resetRecForm();
    initEmailSearch("#rec-watcher");
    await loadRecList();
  }

  function recCardHtml(r, buckets) {
    const s = statusOf(r.status);
    const bName = bucketName(buckets, r.bucket_id);
    return `<div class="ui fluid card rec-card ${r.active ? "" : "rec-paused"}">
      <div class="content">
        <div class="right floated">
          <button class="ui icon mini button rec-edit" data-id="${r.id}" title="Edit"><i class="edit icon"></i></button>
          <button class="ui icon mini red basic button rec-delete" data-id="${r.id}" title="Delete"><i class="trash icon"></i></button>
        </div>
        <div class="header">${esc(r.title)}${r.active ? "" : " <span class='ui mini grey label'>Paused</span>"}</div>
        <div class="meta" style="margin-top:.5rem">
          <span class="ui ${s.color} label"><i class="${s.icon} icon"></i>${labelOf(r.status)}</span>
          <span class="ui basic label"><i class="folder outline icon"></i>${esc(bName)}</span>
          <span class="ui basic label"><i class="redo icon"></i>${esc(recScheduleText(r))}</span>
          ${r.watcher_email ? `<span class="ui basic label"><i class="eye icon"></i>${esc(r.watcher_email)}</span>` : ""}
        </div>
        ${r.text ? `<div class="description" style="margin-top:.6rem">${esc(r.text)}</div>` : ""}
        <div class="extra" style="color:#888;font-size:.85em">
          ${r.active ? `Next run: ${fmtDate(r.next_run)}` : "Paused — not scheduled"}
        </div>
      </div>
    </div>`;
  }

  async function loadRecList() {
    const el = $("#rec-list");
    if (!navigator.onLine) {
      el.html("<div style='color:#999'>Connect to view and manage recurring tasks.</div>");
      return;
    }
    try {
      recCache = await API.get("/api/recurring");
      const buckets = await liveBuckets();
      if (!recCache.length) {
        el.html("<div class='ui placeholder segment'><div class='ui icon header'>" +
          "<i class='robot icon'></i> No recurring tasks yet.</div></div>");
        return;
      }
      el.html(recCache.map((r) => recCardHtml(r, buckets)).join(""));
      $("#rec-list .rec-edit").on("click", function () { editRec($(this).data("id")); });
      $("#rec-list .rec-delete").on("click", function () { deleteRec($(this).data("id")); });
    } catch (e) {
      el.html("<div style='color:#db2828'>Couldn't load recurring tasks.</div>");
    }
  }

  function editRec(id) {
    const r = recCache.find((x) => x.id === id);
    if (!r) return;
    recEditingId = id;
    $("#rec-title").val(r.title);
    $("#rec-text").val(r.text || "");
    $("#rec-status").val(r.status);
    $("#rec-bucket").val(r.bucket_id);
    $("#rec-watcher").val(r.watcher_email || "");
    $("#rec-frequency").val(r.frequency);
    $("#rec-active").prop("checked", r.active);
    renderRecWhen(r.frequency, r);
    $("#rec-form-title").text("Edit recurring task");
    $("#rec-save-label").text("Save changes");
    $("#rec-cancel").show();
    document.getElementById("rec-form-segment").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function saveRec(e) {
    e.preventDefault();
    const title = $("#rec-title").val().trim();
    if (!title) return toast("Add a title", "warning");
    const bucket_id = $("#rec-bucket").val();
    if (!bucket_id) return toast("Create a bucket first", "warning");
    const watcher = $("#rec-watcher").val().trim();
    if (watcher && !isValidEmail(watcher)) return toast("That watcher email looks invalid", "warning");
    if (!navigator.onLine) return toast("Connect to manage automations", "warning");

    const frequency = $("#rec-frequency").val();
    const payload = {
      title,
      text: $("#rec-text").val(),
      status: $("#rec-status").val(),
      bucket_id,
      watcher_email: watcher || null,
      frequency,
      active: $("#rec-active").prop("checked"),
      day_of_week: frequency === "weekly" ? parseInt($("#rec-dow").val(), 10) : null,
      day_of_month:
        frequency === "monthly" || frequency === "yearly" ? parseInt($("#rec-dom").val(), 10) : null,
      month_of_year: frequency === "yearly" ? parseInt($("#rec-moy").val(), 10) : null,
    };
    try {
      if (recEditingId) {
        await API.patch(`/api/recurring/${recEditingId}`, payload);
        toast("Recurring task updated");
      } else {
        await API.post("/api/recurring", payload);
        toast("Recurring task added");
      }
      resetRecForm();
      await loadRecList();
    } catch (err) {
      toast(errText(err), "error");
    }
  }

  async function deleteRec(id) {
    if (!navigator.onLine) return toast("Connect to manage automations", "warning");
    if (!confirm("Delete this recurring task? Tasks it already created are kept.")) return;
    try {
      await API.del(`/api/recurring/${id}`);
      if (recEditingId === id) resetRecForm();
      await loadRecList();
      toast("Recurring task deleted");
    } catch (e) {
      toast(errText(e), "error");
    }
  }

  Object.assign(App, { showAutomation, renderRecWhen, saveRec, resetRecForm });
})();

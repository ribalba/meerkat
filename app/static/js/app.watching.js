/* Watching: tasks shared with me (owned by other people, fetched online rather
 * than synced). Rendered into the main pane like normal tasks, with a read-only
 * detail view that still allows commenting and attaching files. */
(function () {
  "use strict";

  const App = window.App;
  const { $, esc, state, toast, errText, statusOf, labelOf } = App;

  async function renderWatchingList() {
    const list = $("#todo-list");
    const empty = (icon, msg) => {
      list.empty();
      $("#empty-state .ui.icon.header").html(`<i class="${icon} icon"></i> ${msg}`);
      $("#empty-state").show();
    };

    if (!navigator.onLine) return empty("wifi", "Connect to see tasks shared with you.");

    $("#empty-state").hide();
    list.html("<div class='ui active centered inline loader' style='margin-top:2rem'></div>");
    let items;
    try {
      items = await API.get("/api/watching");
    } catch (e) {
      return empty("exclamation triangle", esc(errText(e)));
    }
    if (!items.length) return empty("eye", "No one has shared a task with you yet.");

    $("#empty-state").hide();
    list.html(items.map(watchNodeHtml).join(""));
    list.find(".todo-card").on("click", function () {
      openWatchedDetail($(this).data("token"), String($(this).data("id")));
    });
    if (state.currentTodoId) {
      list.find(`.todo-card[data-id="${state.currentTodoId}"]`).addClass("selected");
    }
  }

  function watchNodeHtml(t) {
    const s = statusOf(t.status);
    const done = t.status === "done";
    return `
      <div class="todo-node">
        <div class="ui fluid card todo-card watch-card" data-id="${t.id}" data-token="${esc(t.public_token)}" style="${done ? "opacity:.65" : ""}">
          <div class="content">
            <div class="todo-row">
              <div class="todo-main">
                <div class="header" style="${done ? "text-decoration:line-through" : ""}">${esc(t.title)}</div>
                <div class="watch-sub"><i class="user outline icon"></i>${esc(t.owner_name)} · <i class="folder outline icon"></i>${esc(t.bucket_name)}</div>
              </div>
              <div class="todo-pills"><span class="ui ${s.color} label status-pill"><i class="${s.icon} icon"></i>${labelOf(t.status)}</span></div>
            </div>
          </div>
        </div>
      </div>`;
  }

  // Read-only detail for a watched task, shown in the normal detail pane.
  async function openWatchedDetail(token, id) {
    state.currentWatchToken = token;
    $("body").addClass("detail-open");
    App.applyDetailWidth();
    $("#detail-body").html("<div class='ui active centered inline loader' style='margin-top:2rem'></div>");
    let data;
    try {
      data = await API.get(`/api/public/${encodeURIComponent(token)}`);
    } catch (e) {
      $("#detail-body").html(`<div style="color:#999;padding:1rem">${esc(errText(e))}</div>`);
      return;
    }
    // When opened by token alone (e.g. the share-page deep link) the id isn't
    // known up front; take it from the fetched task so the list card highlights.
    id = id || data.todo.id;
    state.currentTodoId = id;
    $("#todo-list .todo-card").removeClass("selected");
    $(`#todo-list .todo-card[data-id="${id}"]`).addClass("selected");
    $("#detail-body").html(watchedDetailHtml(data, token));
    wireWatchedDetail(token);
  }

  // Open the Watching tab and select a shared task by its public token. Used by
  // the public share page's "Go to task in dashboard" link.
  async function openWatchingTask(token) {
    App.enterWatching();
    await openWatchedDetail(token);
  }

  function watchedDetailHtml(data, token) {
    const t = data.todo;
    const s = statusOf(t.status);
    const subs = data.subtodos || [];
    const events = data.timeline || [];
    const att = t.attachments || [];
    const fileChip = (a) =>
      `<a class="ui label" target="_blank" href="/api/attachments/${a.id}?token=${encodeURIComponent(token)}"><i class="file icon"></i>${esc(a.filename)}</a>`;
    return `
      <div class="detail-top">
        <div class="detail-controls">
          <span class="ui ${s.color} label" style="margin-right:auto"><i class="${s.icon} icon"></i>${labelOf(t.status)}</span>
          <button class="ui icon button" id="wd-file-btn" title="Attach a file"><i class="upload icon"></i></button>
        </div>
        <input type="file" id="wd-file" multiple style="display:none" />
        <h2 class="ui header" style="margin:.6rem 0 0">${esc(t.title)}</h2>
        <div style="color:#888;font-size:.9em">Shared with you</div>
      </div>

      <h4 class="ui horizontal divider header"><i class="align left icon"></i> Description</h4>
      <div class="markdown">${t.text ? MD.render(t.text) : "<span style='color:#aaa'>No description.</span>"}</div>

      ${att.length ? `<h4 class="ui horizontal divider header"><i class="paperclip icon"></i> Files</h4>
        <div>${att.map(fileChip).join(" ")}</div>` : ""}

      ${subs.length ? `<h4 class="ui horizontal divider header"><i class="sitemap icon"></i> Subtasks</h4>
        <div class="ui list">${subs.map((st) => `<div class="item"><i class="angle right icon"></i>
          <div class="content"><a class="wd-sub" data-token="${esc(st.public_token)}" data-id="${st.id}" style="cursor:pointer;${st.status === "done" ? "text-decoration:line-through" : ""}">${esc(st.title)}</a></div></div>`).join("")}</div>` : ""}

      <h4 class="ui horizontal divider header"><i class="comments icon"></i> Activity</h4>
      <div class="ui feed" id="wd-feed">${events.map(App.eventHtml).join("") || "<div class='wd-empty' style='color:#aaa'>No activity yet.</div>"}</div>

      <div class="ui form" style="margin-top:1rem">
        <div class="field">
          <textarea id="wd-comment" rows="2" placeholder="Add a comment (markdown)…"></textarea>
        </div>
        <input type="file" id="wd-comment-file" style="display:none" />
        <button class="ui icon button" id="wd-comment-file-btn" title="Attach a file"><i class="upload icon"></i></button>
        <button class="ui primary button" id="wd-add-comment">Comment</button>
        <span id="wd-comment-file-name" style="color:#888;font-size:.85em;margin-left:.4rem"></span>
      </div>`;
  }

  function wireWatchedDetail(token) {
    // Subtasks open their own read-only view in-app.
    $("#detail-body .wd-sub").on("click", function () {
      openWatchedDetail($(this).data("token"), String($(this).data("id")));
    });
    // Attach a file directly to the task (allowed for watchers).
    $("#wd-file-btn").on("click", () => document.getElementById("wd-file").click());
    $("#wd-file").on("change", function () {
      const files = this.files;
      this.value = "";
      App.uploadFilesToTodo(state.currentTodoId, files);
    });
    $("#wd-comment-file-btn").on("click", () => document.getElementById("wd-comment-file").click());
    $("#wd-comment-file").on("change", function () {
      $("#wd-comment-file-name").text(this.files[0] ? this.files[0].name : "");
    });
    $("#wd-add-comment").on("click", () => submitWatchedComment(token));
  }

  // Comment on a watched task (attributed to my account) and append it to the feed.
  async function submitWatchedComment(token) {
    const $body = $("#wd-comment");
    const body = ($body.val() || "").trim();
    if (!body) return;
    const $btn = $("#wd-add-comment").addClass("loading disabled");
    try {
      const event = await API.post(`/api/watching/${encodeURIComponent(token)}/comments`, { body });
      const fileInput = document.getElementById("wd-comment-file");
      const file = fileInput && fileInput.files[0];
      if (file) {
        const fd = new FormData();
        fd.append("file", file);
        try {
          const up = await API.upload(
            `/api/public/${encodeURIComponent(token)}/attachments?owner_type=event&owner_id=${encodeURIComponent(event.id)}`,
            fd
          );
          event.attachments = [up];
        } catch (e) { toast("Comment added, but the file didn't upload", "warning"); }
      }
      const $feed = $("#wd-feed");
      $feed.find(".wd-empty").remove();
      $feed.append(App.eventHtml(event));
      $body.val("");
      if (fileInput) fileInput.value = "";
      $("#wd-comment-file-name").text("");
    } catch (e) {
      toast(errText(e), "error");
    } finally {
      $btn.removeClass("loading disabled");
    }
  }

  // Open a task reached by a deep link (/?todo=id). If it isn't one of the user's
  // own (synced) tasks, it's a task shared with them: switch to the Watching view
  // and open it read-only.
  async function openTaskOrWatched(id) {
    const local = await DB.get("todos", id);
    if (local && !local.deleted) {
      App.openTodo(id);
      return;
    }
    App.enterWatching();
    try {
      const items = await API.get("/api/watching");
      const match = items.find((t) => t.id === id);
      if (match) await openWatchedDetail(match.public_token, id);
    } catch (e) { /* stay on the Watching list */ }
  }

  Object.assign(App, { renderWatchingList, openWatchedDetail, openWatchingTask, openTaskOrWatched });
})();

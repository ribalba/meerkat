/* Local-first sync engine. Exposed as window.Sync.
 *
 * Every change goes through Sync.mutate(): it (1) writes optimistically to
 * IndexedDB, (2) appends a mutation to the queue, (3) best-effort flushes to the
 * server. flush() pushes the queue then pulls server deltas. Conflicts resolve
 * last-write-wins on updated_at (enforced server-side). */
(function () {
  const listeners = new Set();
  let flushing = false;

  function uuid() {
    if (crypto.randomUUID) return crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
      const r = (Math.random() * 16) | 0;
      return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
    });
  }

  const STORE_FOR = { bucket: "buckets", todo: "todos", comment: "events" };

  function emit() {
    listeners.forEach((fn) => {
      try { fn(); } catch (e) { console.error(e); }
    });
  }

  async function localApply(entity, action, id, data) {
    const store = STORE_FOR[entity];
    if (action === "delete") {
      const existing = await DB.get(store, id);
      if (existing) await DB.put(store, { ...existing, deleted: true });
      return;
    }
    const existing = (await DB.get(store, id)) || { id };
    await DB.put(store, { ...existing, ...data, id });
  }

  /* Make a change locally + queue it for the server. Returns the entity id. */
  async function mutate(entity, action, id, data) {
    id = id || uuid();
    const updated_at = new Date().toISOString();
    await localApply(entity, action, id, { ...data, updated_at });
    await DB.enqueue({
      op_id: uuid(),
      entity,
      action,
      id,
      updated_at,
      data: data || {},
    });
    emit();
    flush(); // fire and forget
    return id;
  }

  async function flush() {
    if (flushing || !navigator.onLine) return;
    flushing = true;
    try {
      const queue = await DB.queued();
      if (queue.length) {
        const mutations = queue.map(({ op_id, entity, action, id, updated_at, data }) => ({
          op_id, entity, action, id, updated_at, data,
        }));
        const resp = await API.post("/api/sync/push", { mutations });
        for (const r of resp.results) {
          if (r.status !== "error") await DB.dequeue(r.op_id);
        }
      }
      await pull();
      emit();
    } catch (e) {
      // Offline or server error: leave the queue intact and try again later.
      console.debug("flush deferred:", e);
    } finally {
      flushing = false;
    }
  }

  async function pull() {
    const since = await DB.getMeta("last_sync", null);
    const qs = since ? `?since=${encodeURIComponent(since)}` : "";
    const data = await API.get(`/api/sync/pull${qs}`);
    const changed = data.buckets.length || data.todos.length || data.events.length;
    if (data.buckets.length) await DB.bulkPut("buckets", data.buckets);
    if (data.todos.length) await DB.bulkPut("todos", data.todos);
    if (data.events.length) await DB.bulkPut("events", data.events);
    await DB.setMeta("last_sync", data.server_time);
    // Notify the UI so views re-render after a standalone pull (e.g. adding a
    // watcher or uploading a file, which bypass the local mutation queue).
    if (changed) emit();
  }

  async function fullResync() {
    await DB.setMeta("last_sync", null);
    await DB.clear("buckets");
    await DB.clear("todos");
    await DB.clear("events");
    await flush();
  }

  const Sync = {
    uuid,
    mutate,
    flush,
    pull,
    fullResync,
    onChange: (fn) => { listeners.add(fn); return () => listeners.delete(fn); },
    pendingCount: async () => (await DB.queued()).length,
    start() {
      window.addEventListener("online", () => { emit(); flush(); });
      window.addEventListener("offline", emit);
      setInterval(() => flush(), 30000); // periodic catch-up
    },
  };

  window.Sync = Sync;
})();

/* Minimal IndexedDB wrapper used as the local-first mirror of the server data.
 * Stores: buckets, todos, events (timeline/comments), queue (pending mutations),
 * meta (key/value e.g. last_sync). Exposed as window.DB. */
(function () {
  const DB_NAME = "todo-app";
  const DB_VERSION = 1;
  let dbp = null;

  function open() {
    if (dbp) return dbp;
    dbp = new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        for (const name of ["buckets", "todos", "events"]) {
          if (!db.objectStoreNames.contains(name)) {
            db.createObjectStore(name, { keyPath: "id" });
          }
        }
        if (!db.objectStoreNames.contains("queue")) {
          db.createObjectStore("queue", { keyPath: "op_id" });
        }
        if (!db.objectStoreNames.contains("meta")) {
          db.createObjectStore("meta", { keyPath: "key" });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    return dbp;
  }

  function tx(store, mode, fn) {
    return open().then(
      (db) =>
        new Promise((resolve, reject) => {
          const t = db.transaction(store, mode);
          const os = t.objectStore(store);
          const result = fn(os);
          t.oncomplete = () => resolve(result && result.__val !== undefined ? result.__val : result);
          t.onerror = () => reject(t.error);
          t.onabort = () => reject(t.error);
        })
    );
  }

  function reqValue(request) {
    const box = { __val: undefined };
    request.onsuccess = () => (box.__val = request.result);
    return box;
  }

  const DB = {
    put: (store, value) => tx(store, "readwrite", (os) => os.put(value)),
    bulkPut: (store, values) =>
      tx(store, "readwrite", (os) => values.forEach((v) => os.put(v))),
    get: (store, id) => tx(store, "readonly", (os) => reqValue(os.get(id))),
    getAll: (store) => tx(store, "readonly", (os) => reqValue(os.getAll())),
    delete: (store, id) => tx(store, "readwrite", (os) => os.delete(id)),
    clear: (store) => tx(store, "readwrite", (os) => os.clear()),

    // meta helpers
    async getMeta(key, dflt) {
      const row = await DB.get("meta", key);
      return row ? row.value : dflt;
    },
    setMeta: (key, value) => DB.put("meta", { key, value }),

    // queue helpers
    enqueue: (mutation) => DB.put("queue", mutation),
    queued: () => DB.getAll("queue"),
    dequeue: (op_id) => DB.delete("queue", op_id),
  };

  window.DB = DB;
})();

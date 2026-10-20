// Every mounted workspace owns its listeners, observers, timers, and requests.
export function createScope() {
  const controller = new AbortController();
  const cleanups = new Set();
  const timeouts = new Set();
  const intervals = new Set();
  const frames = new Set();
  let disposed = false;

  return {
    onDispose(cleanup) {
      cleanups.add(cleanup);
    },
    listen(target, event, listener, options) {
      if (!target || disposed) return;
      target.addEventListener(event, listener, options);
      const cleanup = () => {
        target.removeEventListener(event, listener, options);
        cleanups.delete(cleanup);
      };
      cleanups.add(cleanup);
      return cleanup;
    },
    observe(observer) {
      cleanups.add(() => observer.disconnect());
      return observer;
    },
    setTimeout(callback, delay, ...args) {
      if (disposed) return;
      const id = window.setTimeout(() => {
        timeouts.delete(id);
        if (!disposed) callback(...args);
      }, delay);
      timeouts.add(id);
      return id;
    },
    clearTimeout(id) {
      window.clearTimeout(id);
      timeouts.delete(id);
    },
    setInterval(callback, delay, ...args) {
      if (disposed) return;
      const id = window.setInterval(() => {
        if (!disposed) callback(...args);
      }, delay);
      intervals.add(id);
      return id;
    },
    clearInterval(id) {
      window.clearInterval(id);
      intervals.delete(id);
    },
    requestAnimationFrame(callback) {
      if (disposed) return;
      const id = window.requestAnimationFrame((time) => {
        frames.delete(id);
        if (!disposed) callback(time);
      });
      frames.add(id);
      return id;
    },
    cancelAnimationFrame(id) {
      window.cancelAnimationFrame(id);
      frames.delete(id);
    },
    async fetch(path, options = {}) {
      const signal = options.signal
        ? AbortSignal.any([controller.signal, options.signal])
        : controller.signal;
      return fetch(path, { ...options, signal });
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      controller.abort();
      for (const id of timeouts) window.clearTimeout(id);
      for (const id of intervals) window.clearInterval(id);
      for (const id of frames) window.cancelAnimationFrame(id);
      for (const cleanup of [...cleanups].reverse()) cleanup();
      cleanups.clear();
      timeouts.clear();
      intervals.clear();
      frames.clear();
    },
  };
}

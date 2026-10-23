import { useLayoutEffect } from "react";

export function useVisualViewport() {
  useLayoutEffect(() => {
    const root = document.documentElement;
    const viewport = window.visualViewport;
    let frame = 0;
    const fit = () => {
      frame = 0;
      // Leave native pinch zoom and panning in control while the page is magnified.
      if (viewport && viewport.scale !== 1) return;
      const height = viewport?.height ?? window.innerHeight;
      // Ignore incomplete viewport measurements during keyboard transitions.
      if (!Number.isFinite(height) || height <= 0) return;
      // Safari can retain its keyboard offset briefly after restoring the full height.
      const top = Math.max(
        0,
        Math.min(viewport?.offsetTop ?? 0, window.innerHeight - height),
      );
      root.style.setProperty("--viewport-height", `${height}px`);
      root.style.setProperty("--viewport-top", `${top}px`);
      root.classList.toggle("keyboard-open", window.innerHeight - height > 120);
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(fit);
    };
    // Keyboard focus can pan Safari without another viewport resize.
    viewport?.addEventListener("resize", schedule);
    viewport?.addEventListener("scroll", schedule);
    window.addEventListener("resize", schedule);
    window.addEventListener("pageshow", schedule);
    document.addEventListener("focusin", schedule);
    document.addEventListener("focusout", schedule);
    fit();
    return () => {
      cancelAnimationFrame(frame);
      viewport?.removeEventListener("resize", schedule);
      viewport?.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      window.removeEventListener("pageshow", schedule);
      document.removeEventListener("focusin", schedule);
      document.removeEventListener("focusout", schedule);
      root.classList.remove("keyboard-open");
      root.style.removeProperty("--viewport-height");
      root.style.removeProperty("--viewport-top");
    };
  }, []);
}

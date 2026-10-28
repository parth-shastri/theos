import { useEffect, useRef, useState } from "react";
import { composerPrompts, mobileComposerPrompts } from "../state/config";

export function composerPlaceholder({ mobile, focused, activity, index }) {
  return (
    activity ||
    (focused
      ? "Start Typing..."
      : (mobile ? mobileComposerPrompts : composerPrompts)[index])
  );
}
export function appendTranscript(draft, text) {
  const next = [draft.trim(), text.trim()].filter(Boolean).join("\n");
  if (next.length > 32000)
    throw new Error(
      "The transcription exceeds the message limit. Shorten the recording.",
    );
  return next;
}
export function useComposerPrompt({
  active,
  draft,
  focused,
  mobile,
  activity,
}) {
  const [index, setIndex] = useState(0);
  const current = useRef({});
  current.current = { active, draft, focused, activity };
  useEffect(() => {
    let timer;
    const start = () => {
      clearInterval(timer);
      timer = setInterval(() => {
        const value = current.current;
        if (
          !document.hidden &&
          value.active &&
          !value.draft &&
          !value.focused &&
          !value.activity
        )
          setIndex((index) => (index + 1) % composerPrompts.length);
      }, 8000);
    };
    const stop = () => clearInterval(timer);
    const restore = (event) => {
      if (event.persisted) start();
    };
    start();
    window.addEventListener("pagehide", stop);
    window.addEventListener("pageshow", restore);
    return () => {
      stop();
      window.removeEventListener("pagehide", stop);
      window.removeEventListener("pageshow", restore);
    };
  }, []);
  return composerPlaceholder({ mobile, focused, activity, index });
}

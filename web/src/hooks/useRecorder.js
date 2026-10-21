"use client";
import { useEffect, useRef, useState } from "react";
import { useWorkspace } from "../state/WorkspaceContext";

export function useRecorder(appendDraft) {
  const { me, busy, setWorking, json, showError, status } = useWorkspace();
  const [activity, setActivity] = useState("");
  const [recording, setRecording] = useState(false);
  const [supported, setSupported] = useState(false);
  const state = useRef({ mounted: false });
  const append = useRef(appendDraft);
  append.current = appendDraft;
  const stopMeter = () => {
    const meter = state.current.meter;
    if (meter) {
      cancelAnimationFrame(meter.frame);
      meter.source?.disconnect();
      meter.analyser?.disconnect();
      meter.motion.removeEventListener("change", meter.changed);
      meter.context.close().catch(() => {});
      state.current.meter = null;
    }
    document.getElementById("composer")?.style.removeProperty("--voice-level");
    document
      .getElementById("voice-ambience")
      ?.style.removeProperty("--voice-level");
  };
  const release = () => {
    clearTimeout(state.current.timer);
    stopMeter();
    state.current.stream?.getTracks().forEach((track) => track.stop());
    state.current.stream = null;
    if (state.current.mounted) {
      setRecording(false);
      setActivity("");
    }
  };
  const stop = (cancelled = false) => {
    state.current.cancelled = cancelled;
    if (state.current.recorder?.state === "recording")
      state.current.recorder.stop();
    release();
  };
  const startMeter = async (stream) => {
    const Context = window.AudioContext || window.webkitAudioContext;
    const motion = matchMedia("(prefers-reduced-motion: reduce)");
    if (!Context || motion.matches) return;
    const meter = {
      context: new Context(),
      motion,
      changed: () => {
        if (motion.matches) stopMeter();
      },
    };
    state.current.meter = meter;
    try {
      motion.addEventListener("change", meter.changed);
      await meter.context.resume();
      if (state.current.meter !== meter) return;
      meter.source = meter.context.createMediaStreamSource(stream);
      meter.analyser = meter.context.createAnalyser();
      meter.analyser.fftSize = 1024;
      meter.source.connect(meter.analyser);
      const samples = new Float32Array(1024);
      let level = 0;
      const measure = () => {
        if (state.current.meter !== meter) return;
        meter.analyser.getFloatTimeDomainData(samples);
        const rms = Math.sqrt(
          samples.reduce((sum, value) => sum + value * value, 0) /
            samples.length,
        );
        const target = Math.min(1, Math.max(0, (rms - 0.008) * 8));
        level += (target - level) * (target > level ? 0.35 : 0.12);
        document
          .getElementById("composer")
          ?.style.setProperty("--voice-level", level.toFixed(3));
        document
          .getElementById("voice-ambience")
          ?.style.setProperty("--voice-level", level.toFixed(3));
        meter.frame = requestAnimationFrame(measure);
      };
      measure();
    } catch {
      if (state.current.meter === meter) stopMeter();
    }
  };
  useEffect(() => {
    state.current.mounted = true;
    setSupported(
      window.isSecureContext &&
        !!navigator.mediaDevices?.getUserMedia &&
        typeof MediaRecorder !== "undefined",
    );
    const hide = () => stop(true);
    window.addEventListener("pagehide", hide);
    return () => {
      state.current.mounted = false;
      stop(true);
      state.current.request?.abort();
      window.removeEventListener("pagehide", hide);
      document.body.classList.remove("is-recording");
    };
  }, []);
  useEffect(() => {
    document.body.classList.toggle("is-recording", recording);
    return () => document.body.classList.remove("is-recording");
  }, [recording]);
  useEffect(() => {
    if (!me) {
      state.current.request?.abort();
      stop(true);
      setWorking(false);
    }
  }, [me]);
  const toggle = async () => {
    if (state.current.recorder?.state === "recording") return stop();
    if (busy) return;
    status("");
    setWorking(true);
    setActivity("Opening microphone...");
    const request = new AbortController();
    state.current.request = request;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!state.current.mounted || request.signal.aborted) {
        stream.getTracks().forEach((track) => track.stop());
        if (state.current.mounted) setWorking(false);
        return;
      }
      state.current.stream = stream;
      const mimeType = [
        "audio/webm;codecs=opus",
        "audio/mp4",
        "audio/ogg;codecs=opus",
      ].find((type) => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});
      state.current.recorder = recorder;
      state.current.cancelled = false;
      const chunks = [];
      let size = 0;
      recorder.ondataavailable = (event) => {
        size += event.data.size;
        chunks.push(event.data);
        if (size > me.voice.max_upload_bytes) {
          stop(true);
          showError(
            new Error(
              "The recording exceeds the upload limit. Record a shorter message.",
            ),
          );
        }
      };
      recorder.onerror = () => {
        stop(true);
        showError(new Error("Microphone recording failed. Try again."));
        setWorking(false);
      };
      recorder.onstop = async () => {
        release();
        if (state.current.cancelled || !state.current.mounted) {
          if (state.current.mounted) setWorking(false);
          return;
        }
        setActivity("Transcribing...");
        try {
          const type = recorder.mimeType || "audio/webm";
          const extension = type.includes("mp4")
            ? "m4a"
            : type.includes("ogg")
              ? "ogg"
              : "webm";
          const form = new FormData();
          form.append(
            "file",
            new Blob(chunks, { type }),
            "recording." + extension,
          );
          const file = await json("/api/files", {
            method: "POST",
            body: form,
            signal: request.signal,
          });
          const result = await json("/api/audio/transcribe", {
            method: "POST",
            body: { file_id: file.id },
            signal: request.signal,
          });
          if (state.current.mounted && !request.signal.aborted)
            append.current(result.text.trim());
        } catch (error) {
          if (state.current.mounted) showError(error);
        } finally {
          if (state.current.mounted) {
            setActivity("");
            setWorking(false);
          }
        }
      };
      recorder.start(1000);
      setRecording(true);
      setActivity("Listening...");
      startMeter(stream).catch(stopMeter);
      state.current.timer = setTimeout(() => stop(), 120000);
    } catch (error) {
      stop(true);
      setWorking(false);
      showError(
        new Error(
          error.name === "NotAllowedError"
            ? "Allow microphone access in your browser to record a voice message."
            : "Microphone access failed. Check your device and browser settings.",
        ),
      );
    }
  };
  return {
    activity,
    recording,
    supported,
    toggle,
    cancel: () => stop(true),
    canRecord: !!me?.voice.transcription && supported,
  };
}

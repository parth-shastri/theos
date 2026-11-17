"use client";
import { useEffect, useRef, useState } from "react";
import { useWorkspace } from "../state/WorkspaceContext";

const waveformSpacing = 6;
const waveformSamples = 192;

function drawWaveform(canvas, history) {
  const width = canvas?.clientWidth;
  if (!width) return;
  const height = canvas.clientHeight;
  const density = window.devicePixelRatio || 1;
  const pixelWidth = Math.round(width * density);
  const pixelHeight = Math.round(height * density);
  if (canvas.width !== pixelWidth) canvas.width = pixelWidth;
  if (canvas.height !== pixelHeight) canvas.height = pixelHeight;
  const drawing = canvas.getContext("2d");
  if (!drawing) return;
  drawing.setTransform(density, 0, 0, density, 0, 0);
  drawing.clearRect(0, 0, width, height);
  drawing.strokeStyle = getComputedStyle(canvas).color;
  drawing.lineWidth = 2;
  drawing.lineCap = "round";
  const count = Math.min(history.length, Math.floor(width / waveformSpacing));
  const first = history.length - count;
  drawing.beginPath();
  for (let index = 0; index < count; index++) {
    const amplitude = history[first + index];
    if (amplitude < 0.045) continue;
    const x = (index + 0.5) * waveformSpacing;
    const radius = Math.max(1, amplitude * (height / 2 - 3));
    drawing.moveTo(x, height / 2 - radius);
    drawing.lineTo(x, height / 2 + radius);
  }
  drawing.stroke();
}

export function useRecorder(appendDraft) {
  const { me, chat, busy, setWorking, json, showError, status } =
    useWorkspace();
  const [activity, setActivity] = useState("");
  const [recording, setRecording] = useState(false);
  const [supported, setSupported] = useState(false);
  const state = useRef({ mounted: false });
  const waveform = useRef(null);
  const conversation = useRef(chat.id);
  conversation.current = chat.id;
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
  const release = (nextActivity = "") => {
    clearTimeout(state.current.timer);
    stopMeter();
    state.current.stream?.getTracks().forEach((track) => track.stop());
    state.current.stream = null;
    if (state.current.mounted) {
      setRecording(false);
      setActivity(nextActivity);
    }
  };
  const stop = (cancelled = false) => {
    state.current.cancelled = cancelled;
    const active = state.current.recorder?.state === "recording";
    if (active) state.current.recorder.stop();
    release(active && !cancelled ? "Transcribing..." : "");
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
      const history = new Float32Array(waveformSamples);
      let level = 0;
      let lastBar = -Infinity;
      const measure = (now) => {
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
        if (now - lastBar >= 48) {
          history.copyWithin(0, 1);
          history[history.length - 1] = Math.max(target, level);
          drawWaveform(waveform.current, history);
          lastBar = now;
        }
        meter.frame = requestAnimationFrame(measure);
      };
      meter.frame = requestAnimationFrame(measure);
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
    const hide = () => {
      state.current.request?.abort();
      stop(true);
      setWorking(false);
    };
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
  useEffect(() => {
    if (state.current.sessionId && state.current.sessionId !== chat.id) {
      state.current.request?.abort();
      state.current.sessionId = null;
      stop(true);
      setWorking(false);
    }
  }, [chat.id]);
  const toggle = async () => {
    if (state.current.recorder?.state === "recording") return stop();
    if (busy) return;
    status("");
    setWorking(true);
    setActivity("Opening microphone...");
    const request = new AbortController();
    state.current.request = request;
    const sessionId = chat.id;
    state.current.sessionId = sessionId;
    const finish = () => {
      if (!state.current.mounted || state.current.request !== request) return;
      state.current.request = null;
      state.current.sessionId = null;
      setActivity("");
      setWorking(false);
    };
    const canvas = waveform.current;
    canvas?.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (
        !state.current.mounted ||
        request.signal.aborted ||
        conversation.current !== sessionId
      ) {
        stream.getTracks().forEach((track) => track.stop());
        finish();
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
        if (state.current.request !== request || request.signal.aborted) return;
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
        if (state.current.request !== request || request.signal.aborted) return;
        stop(true);
        showError(new Error("Microphone recording failed. Try again."));
        finish();
      };
      recorder.onstop = async () => {
        if (state.current.request !== request) return;
        const cancelled =
          state.current.cancelled ||
          request.signal.aborted ||
          conversation.current !== sessionId;
        release(cancelled ? "" : "Transcribing...");
        if (cancelled || !state.current.mounted) {
          finish();
          return;
        }
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
          if (
            state.current.mounted &&
            !request.signal.aborted &&
            conversation.current === sessionId
          )
            append.current(result.text.trim());
        } catch (error) {
          if (state.current.mounted && state.current.request === request)
            showError(error);
        } finally {
          finish();
        }
      };
      recorder.start(1000);
      setRecording(true);
      setActivity("Listening...");
      startMeter(stream).catch(stopMeter);
      state.current.timer = setTimeout(() => stop(), 120000);
    } catch (error) {
      if (state.current.request !== request) return;
      stop(true);
      finish();
      if (request.signal.aborted) return;
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
    waveform,
    supported,
    toggle,
    cancel: () => stop(true),
    canRecord: !!me?.voice.transcription && supported,
  };
}

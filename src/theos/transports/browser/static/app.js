"use strict";
const $ = (id) => document.getElementById(id);
const agentName = $("agent-name").textContent;
let token = sessionStorage.getItem("theos-token") || "";
let selected = null;
let me = null;
let busy = false;
let files = [];
let notificationTimer;
let connectionTimer;
let connectionBusy = false;
let connectionSnapshot = "";
const authorizationLinks = new Map();
let toolCatalog = [];
let commandMatches = [];
let commandIndex = 0;
let mentionRange = null;
let mentionCatalog = [];
let mentionCatalogUpdated = 0;
let mentionRequest = null;
let mentionsDismissed = false;
const providerIcons = {
  gmail: "/static/providers/gmail.svg",
  health: "/static/providers/health.png",
  zepto: "/static/providers/zepto.png",
};
let generation = {};
let savedModel = "";
let savedReasoning = "default";
let settingsSaving = false;
let usageRequest = 0;
let recorder = null;
let recordingStream = null;
let recordingTimer;
let recordingCancelled = false;
let recordingMeter = null;
const audioUrls = new Set();
const speechControls = new Set();
let activeSpeech = null;
let followChat = true;
const messageTimers = new Set();
const generationFields = {
  max_output_tokens: {
    label: "Output token limit",
    min: 1,
    step: 1,
    description: "Maximum generated tokens, including reasoning tokens.",
  },
  temperature: {
    label: "Temperature",
    min: 0,
    max: 2,
    step: 0.01,
    description: "Lower values make output more predictable.",
  },
  top_p: {
    label: "Top P",
    min: 0,
    max: 1,
    step: 0.01,
    description: "Limit sampling to a share of the probability mass.",
  },
  top_k: {
    label: "Top K",
    min: 1,
    max: 1000,
    step: 1,
    description: "Limit sampling to the highest-ranked tokens.",
  },
  seed: {
    label: "Seed",
    min: 0,
    max: 2147483647,
    step: 1,
    description: "Request repeatable sampling when the provider supports it.",
  },
  frequency_penalty: {
    label: "Frequency penalty",
    min: -2,
    max: 2,
    step: 0.01,
    description: "Positive values reduce repeated tokens.",
  },
  presence_penalty: {
    label: "Presence penalty",
    min: -2,
    max: 2,
    step: 0.01,
    description: "Positive values encourage new topics.",
  },
};
const commands = [
  { name: "help", description: "Show commands and keyboard shortcuts" },
  { name: "new", description: "Start a new conversation" },
  { name: "reset", description: "Reset this conversation after confirmation" },
  { name: "resume", description: "Continue saved work" },
  {
    name: "model",
    argument: "NAME",
    description: "Show or choose an available model",
  },
  {
    name: "reasoning",
    argument: "EFFORT",
    description: "Show or choose reasoning effort",
  },
  {
    name: "settings",
    description: "Edit model, reasoning, generation, and voice",
  },
  { name: "tools", description: "Open the conversation tools view" },
  {
    name: "connections",
    description: "Connect accounts and inspect workspace services",
  },
  { name: "usage", description: "Show your total and conversation costs" },
  { name: "voice", description: "Show microphone and speech settings" },
];

function reasoningChoices() {
  return me.generation_capabilities[$("model").value]?.reasoning || ["default"];
}
function renderReasoning(value) {
  const choices = reasoningChoices();
  $("reasoning").replaceChildren(
    ...choices.map((choice) => {
      const option = node("option", choice === "default" ? "Default" : choice);
      option.value = choice;
      return option;
    }),
  );
  $("reasoning").value = choices.includes(value) ? value : "default";
}

function generationValues() {
  const values = {};
  for (const input of $("generation-fields").querySelectorAll("input"))
    if (input.value !== "") values[input.name] = Number(input.value);
  return values;
}
function renderGeneration(values = generation) {
  const capabilities = me.generation_capabilities[$("model").value];
  $("generation-model").textContent = `Model: ${$("model").value}`;
  $("generation-fields").replaceChildren();
  for (const key of capabilities.parameters) {
    const spec = generationFields[key];
    const row = node("div", "", "generation-field");
    const label = node("label", spec.label);
    label.htmlFor = `generation-${key}`;
    const input = node("input", "");
    input.id = label.htmlFor;
    input.name = key;
    input.type = "number";
    input.min = spec.min;
    input.max =
      key === "max_output_tokens" ? capabilities.max_output_tokens : spec.max;
    input.step = spec.step;
    input.placeholder = "Model default";
    input.value =
      key === "max_output_tokens" && values[key] != null
        ? Math.min(values[key], capabilities.max_output_tokens)
        : (values[key] ?? "");
    const hint = node("small", spec.description);
    hint.id = `${input.id}-hint`;
    input.setAttribute("aria-describedby", hint.id);
    row.append(label, input, hint);
    $("generation-fields").append(row);
  }
  if (!capabilities.parameters.length)
    $("generation-fields").append(
      node("p", "This model uses its default generation parameters."),
    );
  $("generation-error").textContent = "";
}
function openSettings(section = "") {
  if (busy || settingsSaving || !selected) return;
  if (sidebarMedia.matches) setSidebar(false);
  $("model").value = savedModel;
  renderReasoning(savedReasoning);
  renderGeneration();
  $("settings-conversation").textContent = $("session-title").textContent;
  $("generation-options").open = false;
  $("voice-services").textContent =
    `Microphone transcription: ${me.voice.transcription ? "configured" : "unavailable"}. TTS playback: ${me.voice.tts ? "configured" : "unavailable"}.`;
  $("auto-speech").disabled = !me.voice.tts;
  $("auto-speech").checked =
    me.voice.tts && sessionStorage.getItem(`theos-tts-${me.id}`) === "true";
  $("generation-dialog").showModal();
  if (section === "model" || section === "reasoning") $(section).focus();
  if (section === "voice") $("auto-speech").focus();
}
$("generation-button").onclick = () => openSettings();
$("generation-close").onclick = () => $("generation-dialog").close();
$("generation-cancel").onclick = () => $("generation-dialog").close();
$("generation-dialog").addEventListener("cancel", (event) => {
  if (settingsSaving) event.preventDefault();
});
$("generation-dialog").addEventListener("close", () => {
  $("model").value = savedModel;
  renderReasoning(savedReasoning);
});
$("generation-defaults").onclick = () => {
  for (const input of $("generation-fields").querySelectorAll("input"))
    input.value = "";
};
$("generation-form").addEventListener(
  "invalid",
  (event) => {
    if ($("generation-fields").contains(event.target))
      $("generation-options").open = true;
  },
  true,
);
$("generation-form").onsubmit = async (event) => {
  event.preventDefault();
  if (settingsSaving || busy) return;
  const values = generationValues();
  const model = $("model").value;
  const reasoning = $("reasoning").value;
  settingsSaving = true;
  const controls = Array.from($("generation-form").elements);
  const disabled = controls.map((control) => control.disabled);
  controls.forEach((control) => {
    control.disabled = true;
  });
  try {
    const result = await json(`/api/sessions/${selected}`, {
      method: "PATCH",
      body: JSON.stringify({
        model,
        reasoning,
        generation: values,
      }),
    });
    generation = result.generation;
    savedModel = model;
    savedReasoning = reasoning;
    sessionStorage.setItem(
      `theos-tts-${me.id}`,
      String($("auto-speech").checked),
    );
    $("generation-dialog").close();
    $("status").textContent = "Settings saved.";
    $("status").className = "";
  } catch (error) {
    $("generation-error").textContent = error.message;
  } finally {
    settingsSaving = false;
    controls.forEach((control, index) => {
      control.disabled = disabled[index];
    });
  }
};
// Small SVG controls keep voice actions consistent without an icon dependency.
function controlIcon(name) {
  const paths = {
    sidebar: ["M3 4h18v16H3Z", "M9 4v16"],
    settings: ["M4 7h16M4 17h16", "M8 4v6M16 14v6"],
    sun: [
      "M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z",
      "M12 2v2M12 20v2M2 12h2M20 12h2m-3-7 1.5-1.5M5 19l1.5-1.5M5 5l1.5 1.5M17.5 17.5 19 19",
    ],
    moon: ["M20.9 13a9 9 0 1 1-9.9-9.9A7 7 0 0 0 20.9 13Z"],
    attach: [
      "m20 11-8 8a5 5 0 0 1-7-7l9-9a3 3 0 0 1 4 4l-9 9a1 1 0 0 1-2-2l8-8",
    ],
    command: ["m15 4-6 16"],
    send: ["M12 19V5m-6 6 6-6 6 6"],
    microphone: [
      "M12 15a3 3 0 0 0 3-3V5a3 3 0 0 0-6 0v7a3 3 0 0 0 3 3Z",
      "M5 10v2a7 7 0 0 0 14 0v-2",
      "M12 19v3",
      "M8 22h8",
    ],
    speaker: [
      "M11 5 6 9H3v6h3l5 4V5Z",
      "M15 8a6 6 0 0 1 0 8",
      "M18 5a10 10 0 0 1 0 14",
    ],
    sandbox: ["M4 4h16v16H4Z", "m7 8 3 3-3 3", "M13 15h4"],
    memory: [
      "M12 4a3 3 0 0 0-5-1 4 4 0 0 0-3 6 4 4 0 0 0 0 6 4 4 0 0 0 3 6 3 3 0 0 0 5-1V4Z",
      "M12 4a3 3 0 0 1 5-1 4 4 0 0 1 3 6 4 4 0 0 1 0 6 4 4 0 0 1-3 6 3 3 0 0 1-5-1",
      "M7 7v3l-3 1M17 7v3l3 1M7 17l2-2M17 17l-2-2",
    ],
    search: ["M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z", "m15 15 6 6"],
    storage: [
      "M7 18H6a4 4 0 0 1-1-8 7 7 0 0 1 13-2 5 5 0 0 1 0 10h-1",
      "M12 21V12m-3 3 3-3 3 3",
    ],
    transcription: ["M3 9v6M6 5v14M9 8v8", "M13 7h8M13 12h8M13 17h5"],
    weather: [
      "M12 7a4 4 0 1 0-7 3",
      "M8 1v2M1 8h2M3 3l1.5 1.5M13 3l-1.5 1.5",
      "M7 21a4 4 0 0 1-1-8 6 6 0 0 1 11-2 5 5 0 0 1 1 10H7Z",
    ],
    skills: [
      "M12 5c-3-2-6-2-9-1v15c3-1 6-1 9 1 3-2 6-2 9-1V4c-3-1-6-1-9 1Z",
      "M12 5v15",
    ],
    connection: [
      "m10 13 4-4",
      "M8 16l-1 1a4 4 0 0 1-6-6l4-4a4 4 0 0 1 6 0",
      "M16 8l1-1a4 4 0 0 1 6 6l-4 4a4 4 0 0 1-6 0",
    ],
    stop: ["M7 7h10v10H7Z"],
    cancel: ["m6 6 12 12", "M6 18 18 6"],
    loading: ["M20 12a8 8 0 1 1-8-8"],
  };
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  svg.setAttribute("fill", name === "stop" ? "currentColor" : "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.8");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  if (name === "loading") svg.classList.add("voice-spinner");
  for (const d of paths[name]) {
    const path = document.createElementNS(svg.namespaceURI, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}
function setIconButton(button, icon, label) {
  button.replaceChildren(controlIcon(icon));
  button.setAttribute("aria-label", label);
  button.title = label;
}
setIconButton($("microphone"), "microphone", "Record a voice message");
setIconButton($("cancel-recording"), "cancel", "Cancel recording");
setIconButton($("attach-files"), "attach", "Attach files");
setIconButton($("command-help"), "command", "Show command and connection help");
setIconButton($("send"), "send", "Send message");
setIconButton($("toggle-sidebar"), "sidebar", "Toggle conversation sidebar");
$("generation-button").prepend(controlIcon("settings"));
setIconButton($("generation-close"), "cancel", "Close settings");
setIconButton($("usage-close"), "cancel", "Close usage");
setIconButton($("help-close"), "cancel", "Close command help");
function releaseAudio() {
  for (const control of speechControls) control.dispose();
  speechControls.clear();
  for (const url of audioUrls) URL.revokeObjectURL(url);
  audioUrls.clear();
  activeSpeech = null;
}
function speechControl(body) {
  const speechText = TheosMarkdown.text(body);
  if (
    !me?.voice.tts ||
    !speechText ||
    body.parentElement.querySelector(".speech-control")
  )
    return null;
  const box = node("div", "", "speech-control");
  const button = node("button", "", "icon-button speech-button");
  button.type = "button";
  const tooLong = speechText.length > 12000;
  let audio = null;
  let url = null;
  let disposed = false;
  let playing = false;
  const request = new AbortController();
  const ready = () => {
    playing = false;
    button.disabled = tooLong;
    button.removeAttribute("aria-busy");
    button.classList.remove("is-playing");
    setIconButton(
      button,
      "speaker",
      tooLong
        ? "Speech supports replies up to 12,000 characters."
        : "Read aloud",
    );
  };
  const control = {
    stop() {
      if (activeSpeech === control) activeSpeech = null;
      if (audio) {
        audio.pause();
        audio.currentTime = 0;
      }
      ready();
    },
    dispose() {
      disposed = true;
      request.abort();
      control.stop();
      if (audio) {
        audio.onended = audio.onpause = audio.onerror = null;
        audio.removeAttribute("src");
        audio.load();
      }
      if (url) {
        URL.revokeObjectURL(url);
        audioUrls.delete(url);
      }
    },
  };
  speechControls.add(control);
  ready();
  button.onclick = async () => {
    if (playing) return control.stop();
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    setIconButton(button, "loading", "Preparing audio");
    try {
      if (!audio) {
        const result = await json("/api/audio/speech", {
          method: "POST",
          body: JSON.stringify({ text: speechText }),
          signal: request.signal,
        });
        const response = await api(`/api/files/${result.file_id}`, {
          signal: request.signal,
        });
        const blob = await response.blob();
        if (disposed || !body.isConnected) return;
        url = URL.createObjectURL(blob);
        audioUrls.add(url);
        // Keep the media player off the page. The same button starts and stops it.
        audio = new Audio(url);
        audio.onended = audio.onpause = () => {
          if (!audio.paused && !audio.ended) return;
          if (activeSpeech === control) activeSpeech = null;
          ready();
        };
        audio.onerror = () => {
          control.stop();
          audio.removeAttribute("src");
          audio.load();
          audio = null;
          URL.revokeObjectURL(url);
          audioUrls.delete(url);
          url = null;
          if (!disposed)
            showError(
              new Error(
                "Audio playback failed. Select Read aloud to try again.",
              ),
            );
        };
      }
      if (disposed || !body.isConnected) return;
      activeSpeech?.stop();
      activeSpeech = control;
      playing = true;
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.classList.add("is-playing");
      setIconButton(button, "stop", "Stop playback");
      await audio.play();
      // A later click or conversation change can supersede a pending play request.
      if (disposed || activeSpeech !== control) control.stop();
    } catch (error) {
      control.stop();
      if (disposed || !body.isConnected) return;
      if (error.name === "NotAllowedError")
        $("status").textContent =
          "Audio is ready. Select Read aloud to listen.";
      else if (error.name !== "AbortError") showError(error);
    }
  };
  box.append(button);
  messageFooter(body).prepend(box);
  return button;
}
function stopRecordingMeter() {
  const meter = recordingMeter;
  recordingMeter = null;
  if (meter) {
    cancelAnimationFrame(meter.frame);
    meter.source?.disconnect();
    meter.analyser?.disconnect();
    meter.motion.removeEventListener?.("change", meter.onMotionChange);
    meter.context.close().catch(() => {});
  }
  $("composer").style.removeProperty("--voice-level");
}
async function startRecordingMeter(stream) {
  stopRecordingMeter();
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  const motion = matchMedia("(prefers-reduced-motion: reduce)");
  if (!AudioContextClass || motion.matches) return;
  const meter = {
    context: null,
    frame: null,
    source: null,
    analyser: null,
    motion,
    onMotionChange: () => {
      if (motion.matches && recordingMeter === meter) stopRecordingMeter();
    },
  };
  try {
    meter.context = new AudioContextClass();
    recordingMeter = meter;
    motion.addEventListener?.("change", meter.onMotionChange);
    await meter.context.resume();
    if (recordingMeter !== meter) return;
    meter.source = meter.context.createMediaStreamSource(stream);
    meter.analyser = meter.context.createAnalyser();
    meter.analyser.fftSize = 1024;
    meter.source.connect(meter.analyser);
    const samples = new Float32Array(meter.analyser.fftSize);
    let level = 0;
    const measure = () => {
      if (recordingMeter !== meter) return;
      meter.analyser.getFloatTimeDomainData(samples);
      const rms = Math.sqrt(
        samples.reduce((sum, value) => sum + value * value, 0) / samples.length,
      );
      const target = Math.min(1, Math.max(0, (rms - 0.008) * 8));
      level += (target - level) * (target > level ? 0.35 : 0.12);
      $("composer").style.setProperty("--voice-level", level.toFixed(3));
      meter.frame = requestAnimationFrame(measure);
    };
    measure();
  } catch (_) {
    // Keep recording available if this browser cannot analyze microphone volume.
    if (recordingMeter === meter) stopRecordingMeter();
  }
}
function releaseRecording() {
  clearTimeout(recordingTimer);
  stopRecordingMeter();
  recordingStream?.getTracks().forEach((track) => track.stop());
  recordingStream = null;
  setIconButton($("microphone"), "microphone", "Record a voice message");
  $("microphone").classList.remove("is-recording");
  $("composer").classList.remove("is-recording");
  $("cancel-recording").hidden = true;
}
function stopRecording(cancelled = false) {
  recordingCancelled = cancelled;
  if (recorder?.state === "recording") recorder.stop();
  releaseRecording();
}
$("microphone").onclick = async () => {
  if (recorder?.state === "recording") return stopRecording();
  if (busy) return;
  setBusy(true);
  try {
    recordingStream = await navigator.mediaDevices.getUserMedia({
      audio: true,
    });
    const mimeType = [
      "audio/webm;codecs=opus",
      "audio/mp4",
      "audio/ogg;codecs=opus",
    ].find((type) => MediaRecorder.isTypeSupported(type));
    recorder = new MediaRecorder(recordingStream, mimeType ? { mimeType } : {});
    const chunks = [];
    let size = 0;
    recordingCancelled = false;
    recorder.ondataavailable = (event) => {
      size += event.data.size;
      chunks.push(event.data);
      if (size > me.voice.max_upload_bytes) {
        stopRecording(true);
        showError(
          new Error(
            "The recording exceeds the upload limit. Record a shorter message.",
          ),
        );
      }
    };
    recorder.onerror = () => {
      stopRecording(true);
      showError(new Error("Microphone recording failed. Try again."));
      setBusy(false);
    };
    recorder.onstop = async () => {
      releaseRecording();
      if (recordingCancelled) {
        setBusy(false);
        return;
      }
      $("microphone").disabled = true;
      $("status").textContent = "Transcribing recording…";
      try {
        const type = recorder.mimeType || "audio/webm";
        const audio = new Blob(chunks, { type });
        const form = new FormData();
        const extension = type.includes("mp4")
          ? "m4a"
          : type.includes("ogg")
            ? "ogg"
            : "webm";
        form.append("file", audio, `recording.${extension}`);
        const file = await json("/api/files", { method: "POST", body: form });
        const result = await json("/api/audio/transcribe", {
          method: "POST",
          body: JSON.stringify({ file_id: file.id }),
        });
        const draft = [$("message").value.trim(), result.text.trim()]
          .filter(Boolean)
          .join("\n");
        if (draft.length > 32000)
          throw new Error(
            "The transcription exceeds the message limit. Shorten the recording.",
          );
        $("message").value = draft;
        resizeComposer();
        $("message").focus();
        $("status").textContent =
          "Transcription ready. Review the text, then send.";
      } catch (error) {
        showError(error);
      } finally {
        setBusy(false);
        $("microphone").disabled = false;
      }
    };
    recorder.start(1000);
    setIconButton($("microphone"), "stop", "Stop voice recording");
    $("microphone").classList.add("is-recording");
    $("composer").classList.add("is-recording");
    startRecordingMeter(recordingStream);
    $("microphone").disabled = false;
    $("cancel-recording").hidden = false;
    $("status").className = "recording-status";
    $("status").textContent =
      "Recording… Stop to transcribe, or cancel. Maximum two minutes.";
    recordingTimer = setTimeout(() => stopRecording(), 120000);
  } catch (error) {
    stopRecording(true);
    setBusy(false);
    showError(
      new Error(
        error.name === "NotAllowedError"
          ? "Allow microphone access in your browser to record a voice message."
          : "Microphone access failed. Check your device and browser settings.",
      ),
    );
  }
};
$("cancel-recording").onclick = () => {
  stopRecording(true);
  $("status").textContent = "Recording cancelled.";
};
window.addEventListener("pagehide", () => {
  stopRecording(true);
  releaseAudio();
  for (const timer of messageTimers) clearInterval(timer);
  messageTimers.clear();
});

function hideCommands() {
  $("command-suggestions").hidden = true;
  $("message").setAttribute("aria-expanded", "false");
  $("message").removeAttribute("aria-activedescendant");
  mentionRange = null;
}
function providerIcon(id) {
  if (!providerIcons[id]) return null;
  const icon = document.createElement("img");
  icon.src = providerIcons[id];
  icon.alt = "";
  icon.className = "provider-icon";
  icon.width = 32;
  icon.height = 32;
  return icon;
}
function connectionIcon(id) {
  const provider = providerIcon(id);
  if (provider) return provider;
  const names = {
    sandbox: "sandbox",
    memory: "memory",
    search: "search",
    storage: "storage",
    transcription: "transcription",
    tts: "speaker",
    weather: "weather",
    skills: "skills",
  };
  const icon = node("span", "", "service-icon");
  icon.setAttribute("aria-hidden", "true");
  icon.append(controlIcon(names[id] || "connection"));
  return icon;
}
function rememberConnections(data) {
  mentionCatalog = [
    ...data.accounts.map((account) => ({
      id: account.id,
      name: account.name,
      status: !account.configured
        ? "Not configured"
        : account.connected
          ? "Connected"
          : "Sign-in required",
    })),
    ...data.services
      .filter((service) => service.configured)
      .map((service) => ({ ...service, status: "Configured" })),
  ];
  mentionCatalogUpdated = Date.now();
}
function refreshMentionConnections() {
  if (mentionRequest || Date.now() - mentionCatalogUpdated < 15000) return;
  mentionRequest = json("/api/connections")
    .then((data) => {
      rememberConnections(data);
      if (
        !mentionsDismissed &&
        document.activeElement === $("message") &&
        mentionContext()
      )
        suggestCommands();
    })
    .catch(() => {})
    .finally(() => {
      mentionRequest = null;
    });
}
function mentionContext() {
  const message = $("message");
  if (message.selectionStart !== message.selectionEnd) return null;
  const caret = message.selectionStart;
  const match = message.value.slice(0, caret).match(/(?:^|\s)@([a-z0-9_-]*)$/i);
  if (!match) return null;
  return {
    query: match[1].toLowerCase(),
    start: caret - match[1].length - 1,
    end:
      caret +
      (message.value.slice(caret).match(/^[a-z0-9_-]*/i)?.[0].length || 0),
  };
}
function suggestCommands() {
  const text = $("message").value;
  if (busy) return hideCommands();
  const mention = mentionContext();
  if (mention) {
    refreshMentionConnections();
    mentionRange = mention;
    commandMatches = mentionCatalog
      .filter(
        (connection) =>
          connection.id.startsWith(mention.query) ||
          connection.name.toLowerCase().startsWith(mention.query),
      )
      .map((connection) => ({
        value: `@${connection.id}`,
        description: connection.status,
        connection,
      }));
    commandIndex = 0;
    drawCommands();
    return;
  }
  mentionRange = null;
  if (!/^\/[^\n]*$/.test(text)) return hideCommands();
  const query = text.slice(1).toLowerCase();
  let [name, ...args] = query.split(/\s+/);
  if (name === "thinking") name = "reasoning";
  if (args.length) {
    const values =
      name === "model"
        ? me.models
        : name === "reasoning"
          ? reasoningChoices()
          : [];
    commandMatches = values
      .filter((value) => value.toLowerCase().startsWith(args.join(" ")))
      .map((value) => ({
        value: `/${name} ${value}`,
        description:
          value === $(name === "model" ? "model" : "reasoning").value
            ? "Current selection"
            : name === "model"
              ? "Choose model"
              : "Set reasoning effort",
      }));
  } else {
    commandMatches = commands
      .filter((command) => command.name.startsWith(name))
      .map((command) => ({
        value: `/${command.name}`,
        argument: command.argument,
        description: command.description,
      }));
  }
  commandIndex = 0;
  drawCommands();
}
function drawCommands() {
  const list = $("command-suggestions");
  list.replaceChildren();
  if (!commandMatches.length) return hideCommands();
  list.setAttribute(
    "aria-label",
    mentionRange ? "Connections" : "Slash commands",
  );
  commandMatches.forEach((match, index) => {
    const option = node("button", "", "command-option");
    option.type = "button";
    option.id = `command-option-${index}`;
    option.setAttribute("role", "option");
    option.setAttribute("aria-selected", String(index === commandIndex));
    const label = node(
      "strong",
      `${match.value}${match.argument ? ` ${match.argument}` : ""}`,
    );
    if (match.connection) {
      option.classList.add("connection-option");
      const identity = node("div", "", "mention-identity");
      identity.append(connectionIcon(match.connection.id), label);
      option.append(identity, node("span", match.description));
    } else option.append(label, node("span", match.description));
    option.onmousedown = (event) => event.preventDefault();
    option.onclick = () => chooseCommand(index);
    list.append(option);
  });
  list.hidden = false;
  $("message").setAttribute("aria-expanded", "true");
  $("message").setAttribute(
    "aria-activedescendant",
    `command-option-${commandIndex}`,
  );
  list.children[commandIndex].scrollIntoView({ block: "nearest" });
}
function chooseCommand(index) {
  const command = commandMatches[index];
  if (command.connection && mentionRange) {
    const message = $("message");
    const after = message.value.slice(mentionRange.end);
    const hasSeparator = /^\s/.test(after);
    const separator = hasSeparator ? after[0] : " ";
    message.setRangeText(
      command.value + separator,
      mentionRange.start,
      mentionRange.end + (hasSeparator ? 1 : 0),
      "end",
    );
    resizeComposer();
    message.focus();
    hideCommands();
    return;
  }
  $("message").value = command.value + (command.argument ? " " : "");
  resizeComposer();
  $("message").focus();
  if (command.argument) suggestCommands();
  else hideCommands();
}
function commandHelp() {
  if (busy || !selected) return;
  if (sidebarMedia.matches) setSidebar(false);
  $("help-commands").replaceChildren(
    ...commands.map((command) => {
      const button = node("button", "", "help-command");
      button.type = "button";
      button.append(
        node("strong", `/${command.name}`),
        node("span", command.description),
      );
      if (command.argument) button.append(node("small", "Choose an option →"));
      button.onclick = () => {
        $("help-dialog").close();
        if (command.argument) return selectCommandOptions(command.name);
        runCommand(`/${command.name}`).catch(showError);
      };
      return button;
    }),
  );
  $("help-dialog").showModal();
}
function selectCommandOptions(name) {
  showView("chat-view");
  $("message").value = `/${name} `;
  resizeComposer();
  $("message").focus();
  suggestCommands();
}
$("help-close").onclick = () => $("help-dialog").close();

async function showUsage() {
  if (!selected) return;
  if (sidebarMedia.matches) setSidebar(false);
  const request = ++usageRequest;
  const sessionId = selected;
  $("usage-content").replaceChildren();
  $("usage-status").textContent = "Loading usage…";
  $("usage-status").className = "";
  $("usage-refresh").disabled = true;
  if (!$("usage-dialog").open) $("usage-dialog").showModal();
  try {
    const [session, usage] = await Promise.all([
      json(`/api/sessions/${sessionId}`),
      json("/api/usage"),
    ]);
    if (request !== usageRequest || sessionId !== selected) return;
    for (const [title, summary, subtitle] of [
      ["This conversation", session.usage, session.title],
      ["Your total", usage, "All your conversations and transports"],
    ]) {
      const card = node("section", "", "usage-card");
      card.append(
        node("h3", title),
        node("p", subtitle, "usage-subtitle"),
        node("strong", formatCost(summary), "usage-cost"),
      );
      const metrics = node("dl", "", "usage-metrics");
      for (const [label, value] of [
        ["Requests", summary.requests],
        ["Input tokens", summary.input_tokens],
        ["Output tokens", summary.output_tokens],
        ["Unpriced requests", summary.unpriced_requests],
      ])
        metrics.append(
          node("dt", label),
          node("dd", new Intl.NumberFormat().format(value)),
        );
      card.append(metrics);
      if (summary.unpriced_requests)
        card.append(
          node(
            "p",
            "Some requests have no recorded price. The cost is incomplete.",
            "usage-warning",
          ),
        );
      $("usage-content").append(card);
    }
    $("usage-status").textContent = "Recorded usage · USD";
    $("conversation-cost").textContent =
      `Conversation cost: ${formatCost(session.usage)}`;
    $("user-cost").textContent = `Your total cost: ${formatCost(usage)}`;
  } catch (error) {
    if (request !== usageRequest) return;
    $("usage-status").textContent = error.message;
    $("usage-status").className = "error";
  } finally {
    if (request === usageRequest) $("usage-refresh").disabled = false;
  }
}
$("usage-refresh").onclick = showUsage;
$("usage-close").onclick = () => $("usage-dialog").close();
$("usage-dialog").addEventListener("close", () => {
  usageRequest++;
});
async function runCommand(text) {
  const [command, ...parts] = text.slice(1).split(/\s+/);
  const argument = parts.join(" ").trim();
  const name =
    command.toLowerCase() === "thinking" ? "reasoning" : command.toLowerCase();
  const spec = commands.find((item) => item.name === name);
  if (!spec)
    throw new Error(
      `Unknown command /${command}. Use /help to see available commands.`,
    );
  if (!spec.argument && argument)
    throw new Error(
      `/${spec.name} takes no arguments. Use /help for command syntax.`,
    );
  if (spec.name === "help") return commandHelp();
  if (spec.name === "new") return newSession();
  if (spec.name === "reset") return $("reset").onclick();
  if (spec.name === "resume") return stream(`/api/sessions/${selected}/resume`);
  if (spec.name === "tools") return $("tools-button").onclick();
  if (spec.name === "connections") return $("connections-button").onclick();
  if (spec.name === "voice") return openSettings("voice");
  if (spec.name === "usage") return showUsage();
  if (spec.name === "settings") return openSettings();
  const field = spec.name === "model" ? "model" : "reasoning";
  const values = field === "model" ? me.models : reasoningChoices();
  if (!argument) return selectCommandOptions(spec.name);
  if (!values.includes(argument))
    throw new Error(`Choose one of: ${values.join(", ")}`);
  const previous = $(field).value;
  $(field).value = argument;
  if (field === "model") renderReasoning($("reasoning").value);
  try {
    await saveSettings();
    $("status").textContent =
      `${field === "model" ? "Model" : "Reasoning effort"} saved: ${argument}`;
  } catch (error) {
    $(field).value = previous;
    throw error;
  }
}

function showView(id) {
  clearInterval(connectionTimer);
  $("conversation-toolbar").hidden = ["dashboard", "connections-view"].includes(
    id,
  );
  if (matchMedia("(max-width: 700px)").matches) setSidebar(false);
  for (const view of [
    "chat-view",
    "dashboard",
    "tools-view",
    "connections-view",
  ])
    $(view).hidden = view !== id;
  $("resume").hidden = id !== "chat-view";
  $("reset").hidden = id !== "chat-view";
}
function formatCost(usage) {
  if (!usage.requests) return "$0.00";
  if (usage.cost === null) return "Unavailable";
  const cost = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 6,
  }).format(usage.cost);
  return usage.unpriced_requests ? `${cost} (partial)` : cost;
}
async function refreshCosts(session) {
  $("conversation-cost").textContent =
    `Conversation cost: ${formatCost(session.usage)}`;
  const usage = await json("/api/usage");
  $("user-cost").textContent = `Your total cost: ${formatCost(usage)}`;
}
function thinking(body, text, active = false) {
  const wrapper = body.parentElement;
  let details = wrapper.querySelector(".thinking");
  if (!details) {
    details = node("details", "", "thinking");
    const summary = node("summary", "");
    const orb = node("span", "", "thinking-orb");
    orb.setAttribute("aria-hidden", "true");
    summary.append(orb, node("span", "Thinking", "thinking-label"));
    details.append(summary, node("div", "", "thinking-body"));
    wrapper.insertBefore(details, body);
  }
  TheosMarkdown.render(details.querySelector(".thinking-body"), text, active);
  details.querySelector(".thinking-body").hidden = !text;
  details.querySelector(".thinking-label").textContent = active
    ? "Thinking…"
    : "Thinking";
  details.classList.toggle("is-thinking", active);
  return details;
}
function finishThinking(details) {
  if (!details) return;
  const content = details.querySelector(".thinking-body");
  if (!TheosMarkdown.source(content)) return details.remove();
  TheosMarkdown.render(content, TheosMarkdown.source(content));
  details.classList.remove("is-thinking");
  details.querySelector(".thinking-label").textContent = "Thinking";
}
function toolActivity(call, status, content = null, argumentsValue = null) {
  const callId = call.call_id ?? call.id;
  const existing = [...$("messages").querySelectorAll(".tool-activity")].find(
    (item) => callId && item.dataset.callId === callId,
  );
  const details = existing || node("details", "", "tool-activity");
  if (callId) details.dataset.callId = callId;
  if (!existing) details.append(node("summary", ""));
  details.querySelector("summary").textContent =
    `${call.name} · ${status.replaceAll("_", " ")}`;
  if (argumentsValue !== null && !details.querySelector(".tool-inputs")) {
    details.append(
      node("strong", "Inputs"),
      node("pre", JSON.stringify(argumentsValue, null, 2), "tool-inputs"),
    );
  }
  if (content !== null) {
    const result = details.querySelector(".tool-result");
    if (result) result.textContent = content;
    else
      details.append(
        node("strong", "Result"),
        node("pre", content, "tool-result"),
      );
  }
  if (!existing) $("messages").append(details);
  return details;
}

async function api(path, options = {}) {
  const headers = { "X-Theos-Request": "1", ...options.headers };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (options.body && !(options.body instanceof FormData))
    headers["Content-Type"] = "application/json";
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    let detail = "The request failed. Please try again.";
    try {
      const value = await response.json();
      if (typeof value.detail === "string") detail = value.detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return response;
}
async function json(path, options = {}) {
  return (await api(path, options)).json();
}
function showError(error) {
  $("status").textContent = error.message;
  $("status").className = "error";
}
function node(tag, text, className = "") {
  const element = document.createElement(tag);
  element.textContent = text;
  element.className = className;
  return element;
}
function setBusy(value) {
  busy = value;
  for (const id of [
    "send",
    "new-session",
    "resume",
    "reset",
    "model",
    "reasoning",
    "upload",
    "generation-button",
    "command-help",
    "new-session",
    "attach-files",
    "tools-button",
    "connections-button",
    "activity-button",
    "dashboard-button",
  ])
    $(id).disabled = value;
  for (const button of $("sessions").querySelectorAll("button"))
    button.disabled = value;
  for (const button of $("approvals").querySelectorAll("button"))
    button.disabled = value;
  $("microphone").disabled =
    (value && recorder?.state !== "recording") ||
    !me?.voice.transcription ||
    !window.isSecureContext ||
    !navigator.mediaDevices?.getUserMedia ||
    typeof MediaRecorder === "undefined";
  if (value || !$("status").classList.contains("error"))
    $("status").className = "";
  if (value) hideCommands();
}
$("messages").addEventListener("scroll", () => {
  const messages = $("messages");
  followChat =
    messages.scrollHeight - messages.scrollTop - messages.clientHeight < 80;
});
$("messages").addEventListener("markdown-rendered", () => scrollChat());
function scrollChat(force = false) {
  if (force) followChat = true;
  if (followChat) $("messages").scrollTop = $("messages").scrollHeight;
}
function bubble(role, text) {
  const wrapper = node(
    "article",
    "",
    `message ${role === "workspace" ? "system" : role}`,
  );
  wrapper.append(
    node(
      "div",
      role === "assistant"
        ? agentName
        : role === "workspace"
          ? "Workspace"
          : "You",
      "role",
    ),
  );
  const body = node("div", text, "body");
  wrapper.append(body);
  if (role === "assistant") TheosMarkdown.render(body, text);
  $("messages").append(wrapper);
  scrollChat();
  return body;
}
function messageFooter(body) {
  let footer = body.parentElement.querySelector(".message-footer");
  if (!footer) {
    footer = node("div", "", "message-footer");
    body.parentElement.append(footer);
  }
  return footer;
}
function messageMetadata(body, display = {}, usage = {}, estimate = null) {
  const footer = messageFooter(body);
  let meta = footer.querySelector(".message-meta");
  if (!meta) {
    meta = node("div", "", "message-meta");
    footer.append(meta);
  }
  const parts = [];
  const tokens = usage.output_tokens;
  const hasUsage =
    tokens > 0 || usage.input_tokens > 0 || usage.total_tokens > 0;
  if (hasUsage && Number.isInteger(tokens) && tokens >= 0) {
    const count = node(
      "span",
      `${tokens.toLocaleString()} tokens`,
      "token-count",
    );
    count.title =
      "Output tokens reported by the provider, including reasoning when applicable.";
    parts.push(count);
  } else if (estimate !== null) {
    const count = node(
      "span",
      `~${estimate.toLocaleString()} tokens`,
      "token-count",
    );
    count.title =
      "Estimated from streamed text and reasoning. Provider usage may include additional tokens.";
    parts.push(count);
  }
  if (Number.isFinite(display.duration_ms)) {
    const ms = Math.max(0, display.duration_ms);
    const duration =
      ms < 60000
        ? `${(ms / 1000).toFixed(1)}s`
        : `${Math.floor(ms / 60000)}m ${String(Math.floor((ms % 60000) / 1000)).padStart(2, "0")}s`;
    const timing = node("span", duration, "generation-time");
    timing.title = "Time spent generating this message.";
    parts.push(timing);
  }
  if (Number.isFinite(display.created_at)) {
    const date = new Date(display.created_at * 1000);
    const values = Object.fromEntries(
      new Intl.DateTimeFormat(undefined, {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      })
        .formatToParts(date)
        .map((part) => [part.type, part.value]),
    );
    const timestamp = node(
      "time",
      `${values.day} ${values.month} ${values.hour}:${values.minute}`,
    );
    timestamp.dateTime = date.toISOString();
    timestamp.title = date.toLocaleString(undefined, {
      dateStyle: "full",
      timeStyle: "long",
    });
    parts.push(timestamp);
  }
  meta.replaceChildren();
  parts.forEach((part, index) => {
    if (index) {
      const separator = node("span", "·", "meta-separator");
      separator.setAttribute("aria-hidden", "true");
      meta.append(separator);
    }
    meta.append(part);
  });
  meta.hidden = !parts.length;
}
function streamingMetadata(body) {
  let started = performance.now();
  let display = { created_at: Date.now() / 1000 };
  let estimate = 0;
  const draw = () =>
    messageMetadata(
      body,
      {
        ...display,
        duration_ms: performance.now() - started,
      },
      {},
      estimate,
    );
  const stop = () => {
    clearInterval(timer);
    messageTimers.delete(timer);
  };
  const timer = setInterval(() => {
    if (!body.isConnected) return stop();
    draw();
  }, 200);
  messageTimers.add(timer);
  draw();
  return {
    start(value = {}) {
      started = performance.now();
      display = { ...display, ...value };
      draw();
    },
    update(text, reasoning) {
      estimate = Math.ceil((text.length + reasoning.length) / 4);
      draw();
    },
    finish(value = {}, usage = {}) {
      stop();
      messageMetadata(
        body,
        {
          ...display,
          duration_ms: performance.now() - started,
          ...value,
        },
        usage,
        estimate,
      );
    },
  };
}
function empty() {
  releaseAudio();
  $("messages").replaceChildren();
  followChat = true;
  const box = node("div", "", "empty");
  const mark = node("img", "", "mark");
  mark.src = brandSource();
  mark.alt = "";
  mark.setAttribute("data-brand", "");
  box.append(
    mark,
    node("h1", "Start a conversation"),
    node(
      "p",
      "Choose a model, then ask a question or describe a task. Attach files when you need more context.",
    ),
  );
  $("messages").append(box);
}
async function listSessions() {
  const sessions = await json("/api/sessions");
  $("sessions").replaceChildren();
  for (const session of sessions) {
    const button = node(
      "button",
      session.title,
      session.id === selected ? "active" : "",
    );
    button.title = session.title;
    button.disabled = busy;
    if (session.id === selected) button.setAttribute("aria-current", "page");
    button.onclick = () => {
      if (!busy) openSession(session.id).catch(showError);
    };
    $("sessions").append(button);
  }
}
async function openSession(id) {
  showView("chat-view");
  const session = await json(`/api/sessions/${id}`);
  selected = id;
  $("session-title").textContent = session.title;
  $("model").value = session.model;
  savedModel = session.model;
  savedReasoning = session.reasoning;
  renderReasoning(session.reasoning);
  generation = session.generation;
  releaseAudio();
  followChat = true;
  $("messages").replaceChildren();
  if (!session.history.length) empty();
  const calls = new Map();
  for (const message of session.history) {
    if (message.display?.superseded) continue;
    if (message.type === "user") {
      const body = bubble("user", message.content);
      messageMetadata(body, message.display);
      for (const image of message.images || []) {
        if (!image.url.startsWith("data:image/")) continue;
        const img = document.createElement("img");
        img.src = image.url;
        img.alt = image.filename || "Attached image";
        body.append(img);
      }
    }
    if (message.type === "assistant") {
      if (message.text || message.reasoning) {
        const body = bubble("assistant", message.text || "");
        if (message.reasoning) thinking(body, message.reasoning);
        messageMetadata(
          body,
          message.display,
          message.usage,
          Math.ceil(
            ((message.text || "").length + (message.reasoning || "").length) /
              4,
          ),
        );
        speechControl(body);
      }
      for (const call of message.tool_calls || []) calls.set(call.id, call);
    }
    if (message.type === "tool_result") {
      const call = calls.get(message.call_id);
      toolActivity(
        message,
        message.status,
        message.content,
        call?.arguments ?? null,
      );
      calls.delete(message.call_id);
    }
    if (message.type === "tool_result" && message.status === "completed") {
      try {
        const result = JSON.parse(message.content);
        if (result.file_id) addFileLink(result);
      } catch (_) {}
    }
  }
  const pendingCalls = new Set(session.approvals.map((item) => item.call_id));
  for (const call of calls.values())
    toolActivity(
      call,
      pendingCalls.has(call.id) ? "waiting_for_approval" : "unresolved",
      null,
      call.arguments,
    );
  approvals(session.approvals);
  $("status").textContent =
    session.status === "running"
      ? "This turn is still running. Reopen the conversation to load its result."
      : "Ready when you are.";
  $("status").className = "";
  scrollChat(true);
  await listSessions();
  await refreshCosts(session);
}
function approvals(items) {
  $("approvals").replaceChildren();
  for (const item of items) {
    const card = node("article", "");
    card.append(node("strong", `Review ${item.tool}`));
    card.append(node("pre", JSON.stringify(JSON.parse(item.preview), null, 2)));
    for (const [label, approved] of [
      ["Approve", true],
      ["Deny", false],
    ]) {
      const button = node("button", label, approved ? "primary" : "");
      button.disabled = busy;
      button.onclick = () => {
        if (busy) return;
        stream(
          `/api/sessions/${selected}/approvals/${item.id}`,
          { approved },
          () => {
            card.remove();
            toolActivity(
              { call_id: item.call_id, name: item.tool },
              approved ? "approved" : "denied",
            );
          },
        ).catch(showError);
      };
      card.append(button);
    }
    $("approvals").append(card);
  }
}
function addFileLink(result) {
  const link = node("button", `↓ ${result.name || "Download file"}`);
  link.onclick = async () => {
    try {
      const response = await api(`/api/files/${result.file_id}`);
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = result.name || "file";
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      showError(error);
    }
  };
  $("messages").append(link);
}
async function stream(path, payload, onAccepted = null) {
  const sessionId = selected;
  setBusy(true);
  $("status").textContent = "Thinking…";
  $("status").className = "thinking-status";
  let body = bubble("assistant", "");
  let metrics = streamingMetadata(body);
  thinking(body, "", true);
  scrollChat(true);
  let finalReply = null;
  let lastAnswerBody = null;
  let answerBodies = [];
  let reasoning = "";
  let responseText = "";
  let buffer = "";
  let finished = false;
  let approvalsSynced = false;
  try {
    const response = await api(path, {
      method: "POST",
      body: payload ? JSON.stringify(payload) : undefined,
    });
    onAccepted?.();
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      let index;
      while ((index = buffer.indexOf("\n\n")) >= 0) {
        const line = buffer.slice(0, index);
        buffer = buffer.slice(index + 2);
        if (!line.startsWith("data: ")) continue;
        const event = JSON.parse(line.slice(6));
        if (event.type === "title") {
          $("session-title").textContent = event.title;
        }
        if (event.type === "thinking") {
          if (!body) {
            body = bubble("assistant", "");
            metrics = streamingMetadata(body);
          }
          metrics.start(event.display);
          thinking(body, reasoning, true);
          $("status").textContent = "Thinking…";
          $("status").className = "thinking-status";
        }
        if (event.type === "text") {
          if (!body) {
            body = bubble("assistant", "");
            metrics = streamingMetadata(body);
          }
          responseText += event.text;
          TheosMarkdown.render(body, responseText, true);
          metrics.update(responseText, reasoning);
          scrollChat();
        }
        if (event.type === "reasoning") {
          if (!body) {
            body = bubble("assistant", "");
            metrics = streamingMetadata(body);
          }
          reasoning += event.text;
          metrics.update(responseText, reasoning);
          thinking(body, reasoning, true);
        }
        if (event.type === "answer_replace") {
          if (finalReply) {
            finalReply.dispose();
            speechControls.delete(finalReply);
            lastAnswerBody?.parentElement.querySelector(".speech-control")?.remove();
            finalReply = null;
          }
          if (!body && lastAnswerBody) {
            body = lastAnswerBody;
            metrics = streamingMetadata(body);
          }
          for (const previous of answerBodies) {
            if (previous !== body) previous.parentElement.remove();
          }
          answerBodies = [];
        }
        if (event.type === "assistant_complete" || event.type === "answer_replace") {
          if (event.text || event.reasoning || body) {
            if (!body) {
              body = bubble("assistant", "");
              metrics = streamingMetadata(body);
            }
            responseText = event.text || "";
            TheosMarkdown.render(body, responseText);
            metrics.update(responseText, event.reasoning || "");
            metrics.finish(event.display, event.usage);
            if (event.reasoning) thinking(body, event.reasoning);
            finishThinking(body.parentElement.querySelector(".thinking"));
            if (!event.text && !event.reasoning) {
              body.parentElement.remove();
              finalReply = null;
            } else finalReply = speechControl(body);
          }
          if (body && !event.requested_tools?.length) {
            lastAnswerBody = body;
            answerBodies.push(body);
          }
          body = null;
          metrics = null;
          reasoning = "";
          responseText = "";
          $("status").classList.remove("thinking-status");
        }
        if (event.type === "tool") {
          $("status").classList.remove("thinking-status");
          $("status").textContent = `${event.name}: ${event.status}`;
          toolActivity(
            event,
            event.status,
            event.content ?? null,
            event.arguments ?? null,
          );
        }
        if (event.type === "file") addFileLink(event);
        if (event.type === "approvals") approvals(event.items);
        if (event.type === "error") showError(new Error(event.message));
        if (event.type === "done") {
          finished = true;
          $("status").textContent = event.status.replaceAll("_", " ");
        }
      }
      if (done) break;
    }
    if (!finished)
      throw new Error(
        "The connection ended. Reopen the conversation to inspect its saved result before you retry.",
      );
    const session = await json(`/api/sessions/${sessionId}`);
    approvals(session.approvals);
    approvalsSynced = true;
    $("session-title").textContent = session.title;
    await listSessions();
    await refreshCosts(session);
    if (
      session.status === "completed" &&
      sessionStorage.getItem(`theos-tts-${me.id}`) === "true" &&
      finalReply &&
      !finalReply.disabled
    )
      finalReply.click();
  } finally {
    if (!approvalsSynced && selected === sessionId) {
      try {
        const session = await json(`/api/sessions/${sessionId}`);
        approvals(session.approvals);
      } catch (_) {
        // Keep the last known controls if the server cannot confirm their state.
      }
    }
    if (body) TheosMarkdown.render(body, responseText);
    metrics?.finish();
    for (const details of $("messages").querySelectorAll(".is-thinking"))
      finishThinking(details);
    if (body && !body.textContent && !reasoning) body.parentElement.remove();
    setBusy(false);
  }
}
async function newSession() {
  const session = await json("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ title: "New conversation" }),
  });
  await openSession(session.id);
  $("message").focus();
}
async function login() {
  me = await json("/api/me");
  const canRecord =
    me.voice.transcription &&
    window.isSecureContext &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof MediaRecorder !== "undefined";
  $("microphone").disabled = !canRecord;
  $("microphone").title = canRecord
    ? "Record, transcribe, and review a voice message"
    : !me.voice.transcription
      ? "Transcription service is not configured"
      : "Microphone recording requires HTTPS or localhost and a supported browser";
  if (token) sessionStorage.setItem("theos-token", token);
  $("login").hidden = true;
  $("workspace").hidden = false;
  $("identity").textContent = me.display_name || me.id;
  $("identity").title = me.id;
  $("dashboard-button").hidden = !me.admin;
  $("model").replaceChildren();
  for (const model of me.models) {
    const option = node("option", model);
    option.value = model;
    $("model").append(option);
  }
  const sessions = await json("/api/sessions");
  if (sessions.length) await openSession(sessions[0].id);
  else await newSession();
  refreshMentionConnections();
  clearInterval(notificationTimer);
  notificationTimer = setInterval(async () => {
    try {
      const notifications = await json("/api/notifications");
      $("notifications").replaceChildren(
        ...notifications
          .slice(0, 3)
          .map((n) => node("p", `Reminder: ${n.text}`)),
      );
    } catch (_) {}
  }, 15000);
}
$("login-form").onsubmit = async (event) => {
  event.preventDefault();
  token = $("token").value.trim();
  try {
    await login();
  } catch (error) {
    $("login-error").textContent = error.message;
  }
};
$("sign-out").onclick = async () => {
  stopRecording(true);
  releaseAudio();
  try {
    await json("/api/auth/logout", { method: "POST" });
    sessionStorage.removeItem("theos-token");
    location.reload();
  } catch (error) {
    showError(error);
  }
};
$("new-session").onclick = () => newSession().catch(showError);
$("composer").onsubmit = async (event) => {
  event.preventDefault();
  if (busy) return;
  const text = $("message").value.trim();
  if (!text && !files.length) return;
  if (text.startsWith("/")) {
    if (files.length)
      return showError(
        new Error("Send attached files with a message before using a command."),
      );
    hideCommands();
    $("message").value = "";
    resizeComposer();
    try {
      await runCommand(text);
    } catch (error) {
      $("message").value = text;
      resizeComposer();
      showError(error);
    }
    return;
  }
  if ($("messages").querySelector(".empty")) $("messages").replaceChildren();
  messageMetadata(bubble("user", text), { created_at: Date.now() / 1000 });
  $("message").value = "";
  resizeComposer();
  const attached = files.map((f) => f.id);
  files = [];
  $("attachments").textContent = "";
  $("message").required = true;
  try {
    await stream(`/api/sessions/${selected}/turn`, { text, files: attached });
  } catch (error) {
    showError(error);
  }
};
$("message").onkeydown = (event) => {
  if (!$("command-suggestions").hidden && !event.isComposing) {
    if (["ArrowDown", "ArrowUp"].includes(event.key)) {
      event.preventDefault();
      commandIndex =
        (commandIndex +
          (event.key === "ArrowDown" ? 1 : -1) +
          commandMatches.length) %
        commandMatches.length;
      drawCommands();
      return;
    }
    if ((event.key === "Enter" && !event.shiftKey) || event.key === "Tab") {
      event.preventDefault();
      chooseCommand(commandIndex);
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      mentionsDismissed = true;
      hideCommands();
      return;
    }
  }
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    $("composer").requestSubmit();
  }
};
function resizeComposer() {
  const message = $("message");
  message.style.height = "auto";
  message.style.height = `${Math.max(28, Math.min(message.scrollHeight, 140))}px`;
}
$("message").oninput = (event) => {
  mentionsDismissed = false;
  resizeComposer();
  if (event.isComposing) hideCommands();
  else suggestCommands();
};
$("message").oncompositionend = suggestCommands;
$("message").onclick = () => {
  mentionsDismissed = false;
  suggestCommands();
};
$("message").onblur = hideCommands;
$("message").onkeyup = (event) => {
  if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
    suggestCommands();
};
$("command-help").onclick = commandHelp;
$("upload").onchange = async () => {
  try {
    for (const file of $("upload").files) {
      const form = new FormData();
      form.append("file", file);
      files.push(await json("/api/files", { method: "POST", body: form }));
    }
    $("attachments").textContent = files.map((f) => f.name).join(" · ");
    $("message").required = !files.length;
  } catch (error) {
    showError(error);
  }
  $("upload").value = "";
};
async function saveSettings() {
  setBusy(true);
  try {
    const result = await json(`/api/sessions/${selected}`, {
      method: "PATCH",
      body: JSON.stringify({
        model: $("model").value,
        reasoning: $("reasoning").value,
      }),
    });
    generation = result.generation;
    savedModel = $("model").value;
    savedReasoning = $("reasoning").value;
    $("status").textContent = "Settings saved.";
    $("status").className = "";
  } catch (error) {
    $("model").value = savedModel;
    renderReasoning(savedReasoning);
    throw error;
  } finally {
    setBusy(false);
  }
}
$("model").onchange = () => {
  renderReasoning($("reasoning").value);
  renderGeneration(generationValues());
};
$("resume").onclick = () =>
  stream(`/api/sessions/${selected}/resume`).catch(showError);
$("reset").onclick = async () => {
  if (
    !confirm(
      "Reset this conversation? Saved records and files remain available.",
    )
  )
    return;
  try {
    await json(`/api/sessions/${selected}/reset`, { method: "POST" });
    await openSession(selected);
  } catch (error) {
    showError(error);
  }
};
function table(title, rows, keys) {
  const section = node("section", "");
  section.append(node("h2", title));
  if (!rows.length) {
    section.append(node("p", "No records yet."));
    return section;
  }
  const scroll = node("div", "", "table-scroll");
  const table = node("table", "");
  const head = node("tr", "");
  for (const key of keys) head.append(node("th", key.replaceAll("_", " ")));
  table.append(head);
  for (const row of rows) {
    const tr = node("tr", "");
    for (const key of keys)
      tr.append(
        node(
          "td",
          key === "cost"
            ? formatCost(row)
            : row[key] === null
              ? "Not configured"
              : String(row[key] ?? ""),
        ),
      );
    table.append(tr);
  }
  scroll.append(table);
  section.append(scroll);
  return section;
}
let dashboardRequest = 0;
let dashboardScope = "personal";
async function loadDashboard(scope = dashboardScope) {
  dashboardScope = scope;
  const admin = scope === "admin";
  const request = ++dashboardRequest;
  showView("dashboard");
  $("dashboard-content").replaceChildren();
  $("dashboard-title").textContent = admin
    ? "Admin dashboard"
    : "Your activity & usage";
  $("dashboard-status").hidden = false;
  $("dashboard-status").textContent = "Loading activity…";
  $("dashboard-status").className = "";
  $("dashboard-range").disabled = true;
  try {
    const [data, logs] = await Promise.all([
      json(
        `/api/${admin ? "dashboard" : "activity"}?days=${$("dashboard-range").value}`,
      ),
      admin ? json("/api/logs") : Promise.resolve([]),
    ]);
    if (request !== dashboardRequest) return;
    const content = $("dashboard-content");
    content.replaceChildren();
    const stats = node("div", "", "stats");
    for (const [value, label] of [
      ...(admin ? [[data.totals.users, "Users"]] : []),
      [data.totals.conversations, "Conversations"],
      [
        (data.totals.input_tokens + data.totals.output_tokens).toLocaleString(),
        "Tokens",
      ],
      [formatCost(data.totals), "Total cost · USD"],
    ]) {
      const stat = node("div", "", "stat");
      stat.append(node("strong", value), node("span", label));
      stats.append(stat);
    }
    content.append(
      node(
        "p",
        admin ? "All-time workspace totals" : "Your all-time totals",
        "dashboard-caption",
      ),
      stats,
      node(
        "p",
        `Costs use provider-reported amounts or configured token rates. ${data.totals.unpriced_requests} requests have no recorded price.`,
        "cost-label",
      ),
      TheosCharts.activity(data.activity),
      ...(admin
        ? [
            table("Usage per user", data.cost_per_user, [
              "owner",
              "requests",
              "input_tokens",
              "output_tokens",
              "cache_tokens",
              "cost",
              "unpriced_requests",
            ]),
          ]
        : []),
      table("Cost per conversation", data.cost_per_conversation, [
        "owner",
        "id",
        "channel",
        "requests",
        "cost",
        "unpriced_requests",
      ]),
      table("Usage", data.usage, [
        "owner",
        "model",
        "requests",
        "input_tokens",
        "output_tokens",
        "cache_tokens",
        "cost",
        "unpriced_requests",
      ]),
      ...(admin
        ? [
            table("Conversations", data.sessions, [
              "owner",
              "id",
              "channel",
              "status",
            ]),
            table("Background work", data.jobs, [
              "kind",
              "owner",
              "status",
              "attempts",
            ]),
            table("Traces", data.traces, [
              "session",
              "event",
              "tool",
              "status",
            ]),
            table("Application logs", logs, ["time", "event", "error_type"]),
          ]
        : []),
    );
    $("dashboard-status").hidden = true;
  } catch (error) {
    if (request !== dashboardRequest) return;
    $("dashboard-status").textContent = error.message;
    $("dashboard-status").className = "error";
  } finally {
    if (request === dashboardRequest) $("dashboard-range").disabled = false;
  }
}
$("activity-button").onclick = () => loadDashboard("personal");
$("dashboard-button").onclick = () => loadDashboard("admin");
$("dashboard-range").onchange = () => loadDashboard();
$("back-chat").onclick = () => {
  showView("chat-view");
};
function renderTools() {
  const query = $("tool-search").value.trim().toLowerCase();
  const tools = toolCatalog.filter((tool) =>
    `${tool.name} ${tool.description}`.toLowerCase().includes(query),
  );
  $("tool-count").textContent =
    `${tools.length} of ${toolCatalog.length} tools`;
  $("tools-content").replaceChildren();
  if (!tools.length) $("tools-content").append(node("p", "No matching tools."));
  for (const tool of tools) {
    const card = node("details", "", "tool-card");
    const summary = node("summary", "");
    summary.append(
      node("strong", tool.name),
      node(
        "span",
        tool.requires_approval ? "Approval required" : "Available",
        tool.requires_approval ? "approval-badge" : "tool-badge",
      ),
    );
    card.append(
      summary,
      node("p", tool.description),
      node("strong", "Inputs"),
      node("pre", JSON.stringify(tool.parameters, null, 2)),
    );
    $("tools-content").append(card);
  }
}
$("tools-button").onclick = async () => {
  try {
    toolCatalog = await json(`/api/sessions/${selected}/tools`);
    $("tool-search").value = "";
    renderTools();
    showView("tools-view");
  } catch (error) {
    showError(error);
  }
};
$("tool-search").oninput = renderTools;
$("back-tools").onclick = () => showView("chat-view");

const accountDescriptions = {
  gmail:
    "Search messages, manage drafts and labels. Sending a draft requires approval.",
  health:
    "Import activity, sleep and health summaries. Connecting also enables meal exports to Google Health.",
  zepto:
    "Connect your shopping account. Every Zepto tool call requires approval.",
};
function signInLink(url) {
  const parsed = new URL(url);
  if (
    !["https:", "http:"].includes(parsed.protocol) ||
    parsed.username ||
    parsed.password
  )
    throw new Error("The service returned an invalid sign-in link.");
  if (
    parsed.protocol === "http:" &&
    !["localhost", "127.0.0.1"].includes(parsed.hostname)
  )
    throw new Error("The sign-in link must use HTTPS.");
  const link = node("a", "Continue sign-in ↗", "connection-link");
  link.href = parsed.href;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  return link;
}
async function connectionAction(action) {
  connectionBusy = true;
  for (const button of $("account-connections").querySelectorAll("button"))
    button.disabled = true;
  $("connections-status").className = "";
  $("connections-status").textContent = "Updating connection…";
  try {
    await action();
    connectionSnapshot = "";
    await refreshConnections();
    $("connections-status").textContent = "Connection status updated.";
  } catch (error) {
    $("connections-status").className = "error";
    $("connections-status").textContent = error.message;
    for (const button of $("account-connections").querySelectorAll("button"))
      button.disabled = false;
  } finally {
    connectionBusy = false;
  }
}
async function refreshConnections() {
  const data = await json("/api/connections");
  rememberConnections(data);
  const snapshot = JSON.stringify(data);
  // Preserve an unfinished return URL when another account's status changes.
  if (
    snapshot === connectionSnapshot ||
    ($("account-connections").contains(document.activeElement) &&
      document.activeElement.tagName === "INPUT")
  )
    return;
  $("account-connections").replaceChildren();
  for (const account of data.accounts) {
    const setup = account.setup;
    const pending = ["starting", "waiting"].includes(setup.status);
    const card = node("article", "", "connection-card");
    const header = node("div", "", "connection-heading");
    const identity = node("div", "", "connection-identity");
    identity.append(connectionIcon(account.id));
    identity.append(node("h3", account.name));
    header.append(
      identity,
      node(
        "span",
        !account.configured
          ? "Not configured"
          : pending
            ? "Awaiting sign-in"
            : account.connected
              ? "Connected"
              : "Not connected",
        account.connected ? "tool-badge" : "connection-badge",
      ),
    );
    card.append(header, node("p", accountDescriptions[account.id]));
    if (setup.message)
      card.append(
        node("p", setup.message, setup.status === "failed" ? "error" : ""),
      );
    const actions = node("div", "", "connection-actions");
    if (account.configured) {
      const connect = node(
        "button",
        pending
          ? account.id === "zepto"
            ? "Continue setup"
            : "Start again"
          : account.connected
            ? "Reconnect"
            : "Connect",
      );
      connect.disabled = setup.status === "starting";
      connect.onclick = () =>
        connectionAction(async () => {
          const result = await json(`/api/connections/${account.id}/connect`, {
            method: "POST",
          });
          if (result.url) authorizationLinks.set(account.id, result.url);
        });
      actions.append(connect);
    }
    if (account.connected || pending) {
      const disconnect = node(
        "button",
        account.connected ? "Disconnect" : "Cancel setup",
      );
      disconnect.onclick = () => {
        if (
          account.connected &&
          !confirm(`Disconnect ${account.name} from your workspace?`)
        )
          return;
        return connectionAction(async () => {
          await json(`/api/connections/${account.id}/disconnect`, {
            method: "POST",
          });
          authorizationLinks.delete(account.id);
        });
      };
      actions.append(disconnect);
    }
    const url = setup.url || authorizationLinks.get(account.id);
    if (pending && url) actions.append(signInLink(url));
    if (!pending) authorizationLinks.delete(account.id);
    card.append(actions);
    if (pending && setup.manual_return) {
      const form = node("form", "", "connection-return");
      const label = node(
        "label",
        "After sign-in, paste the full localhost return URL here.",
      );
      const input = node("input", "");
      input.id = "zepto-return-url";
      input.type = "url";
      input.required = true;
      input.maxLength = 4000;
      input.autocomplete = "off";
      input.placeholder = "http://localhost/callback?…";
      label.htmlFor = input.id;
      const finish = node("button", "Finish connection");
      finish.type = "submit";
      form.append(label, input, finish);
      form.onsubmit = (event) => {
        event.preventDefault();
        const returnURL = input.value.trim();
        // OAuth codes go only to the account endpoint, never to the chat composer.
        input.value = "";
        input.blur();
        connectionAction(() =>
          json("/api/connections/zepto/finish", {
            method: "POST",
            body: JSON.stringify({ url: returnURL }),
          }),
        );
      };
      card.append(form);
    }
    $("account-connections").append(card);
  }
  $("workspace-services").replaceChildren(
    ...data.services.map((service) => {
      const row = node("div", "", "service-row");
      const identity = node("div", "", "connection-identity");
      identity.append(connectionIcon(service.id), node("strong", service.name));
      row.append(
        identity,
        node(
          "span",
          service.configured ? "Configured" : "Not configured",
          service.configured ? "tool-badge" : "connection-badge",
        ),
      );
      return row;
    }),
  );
  connectionSnapshot = snapshot;
}
$("connections-button").onclick = async () => {
  showView("connections-view");
  connectionSnapshot = "";
  $("connections-status").textContent = "Loading connections…";
  try {
    await refreshConnections();
    if ($("connections-view").hidden) return;
    $("connections-status").textContent =
      "Account status refreshes while this view is open.";
    $("connections-status").className = "";
    connectionTimer = setInterval(() => {
      if (!connectionBusy)
        refreshConnections().catch((error) => {
          $("connections-status").textContent = error.message;
          $("connections-status").className = "error";
        });
    }, 3000);
  } catch (error) {
    $("connections-status").textContent = error.message;
    $("connections-status").className = "error";
  }
};
$("refresh-connections").onclick = () => connectionAction(async () => {});
$("back-connections").onclick = () => showView("chat-view");
let signinTimer;
function signinError(error) {
  clearTimeout(signinTimer);
  $("web-signin-status").textContent = error.message;
  $("web-signin-status").className = "error";
}
async function pollSignin() {
  const status = await json("/api/onboarding/status");
  $("web-signin-code").textContent = status.code;
  if (status.state === "approved") {
    const access = await json("/api/onboarding/complete", { method: "POST" });
    token = "";
    sessionStorage.removeItem("theos-token");
    sessionStorage.removeItem("theos-pending-signin");
    $("web-signin-title").textContent = "Your account is ready";
    $("web-signin-instructions").textContent =
      "Save your personal access token, then open your workspace.";
    $("web-signin-code").hidden = true;
    $("web-signin-status").textContent = "Telegram confirmed this browser.";
    $("web-access-token").value = access.token;
    $("web-token-save").hidden = false;
    $("cancel-web-signin").hidden = true;
  } else if (status.state === "pending") {
    signinTimer = setTimeout(() => pollSignin().catch(signinError), 2000);
  } else {
    throw new Error(
      "This sign-in was denied or already used. Send /web in Telegram for a new link.",
    );
  }
}
async function beginSignin(invite) {
  $("login-form").hidden = true;
  $("web-signin").hidden = false;
  const result = await json("/api/onboarding/start", {
    method: "POST",
    body: JSON.stringify({ invite }),
  });
  $("web-signin-code").textContent = result.code;
  sessionStorage.setItem("theos-pending-signin", "1");
  $("web-signin-status").textContent =
    `Waiting for your confirmation in Telegram. Confirm before ${new Date(result.expires * 1000).toLocaleTimeString()}.`;
  await pollSignin();
}
$("copy-web-token").onclick = async () => {
  try {
    await navigator.clipboard.writeText($("web-access-token").value);
    $("copy-web-token").textContent = "Copied";
  } catch (_) {
    $("web-access-token").type = "text";
    $("web-access-token").select();
    $("copy-web-token").textContent = "Select and copy the token";
  }
};
$("finish-web-signin").onclick = async () => {
  $("finish-web-signin").disabled = true;
  try {
    await login();
    $("web-access-token").value = "";
  } catch (error) {
    signinError(error);
    $("finish-web-signin").disabled = false;
  }
};
$("cancel-web-signin").onclick = async () => {
  clearTimeout(signinTimer);
  try {
    await json("/api/onboarding/cancel", { method: "POST" });
    sessionStorage.removeItem("theos-pending-signin");
    location.reload();
  } catch (error) {
    signinError(error);
  }
};
const signinInvite = new URLSearchParams(location.hash.slice(1)).get("onboard");
window.addEventListener("hashchange", () => {
  if (new URLSearchParams(location.hash.slice(1)).has("onboard"))
    location.reload();
});
if (signinInvite) {
  history.replaceState(null, "", location.pathname + location.search);
  beginSignin(signinInvite).catch(signinError);
} else if (sessionStorage.getItem("theos-pending-signin")) {
  $("login-form").hidden = true;
  $("web-signin").hidden = false;
  $("web-signin-status").textContent =
    "Waiting for your confirmation in Telegram.";
  pollSignin().catch(signinError);
} else {
  login().catch((error) => {
    if (token) $("login-error").textContent = error.message;
  });
}

function brandSource() {
  return document.documentElement.dataset.theme === "light"
    ? "/static/brand-light.png"
    : "/static/brand.png";
}
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  for (const image of document.querySelectorAll("[data-brand]"))
    image.src = brandSource();
  setIconButton(
    $("theme-toggle"),
    theme === "dark" ? "sun" : "moon",
    `Switch to ${theme === "dark" ? "light" : "dark"} mode`,
  );
}
const savedTheme = localStorage.getItem("theos-theme");
applyTheme(
  ["light", "dark"].includes(savedTheme)
    ? savedTheme
    : matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light",
);
$("theme-toggle").onclick = () => {
  const theme =
    document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  applyTheme(theme);
  localStorage.setItem("theos-theme", theme);
};
const sidebarMedia = matchMedia("(max-width: 700px)");
function setSidebar(open) {
  $("workspace").classList.toggle("sidebar-collapsed", !open);
  $("toggle-sidebar").setAttribute("aria-expanded", String(open));
  $("sidebar").inert = !open;
  $("sidebar-backdrop").hidden = !(sidebarMedia.matches && open);
  document.querySelector("main").inert = sidebarMedia.matches && open;
}
$("toggle-sidebar").onclick = () => {
  const open = $("workspace").classList.contains("sidebar-collapsed");
  setSidebar(open);
  if (open && sidebarMedia.matches) $("new-session").focus();
};
$("sidebar-backdrop").onclick = () => {
  setSidebar(false);
  $("toggle-sidebar").focus();
};
document.addEventListener("keydown", (event) => {
  if (
    event.key === "Escape" &&
    sidebarMedia.matches &&
    !$("sidebar-backdrop").hidden
  ) {
    setSidebar(false);
    $("toggle-sidebar").focus();
  }
});
sidebarMedia.addEventListener("change", () =>
  setSidebar(!sidebarMedia.matches),
);
setSidebar(!sidebarMedia.matches);

document
  .getElementById("attach-files")
  .addEventListener("click", () => document.getElementById("upload").click());

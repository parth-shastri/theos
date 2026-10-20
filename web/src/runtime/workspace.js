import { createScope } from "./scope";
import { createMarkdown } from "./markdown";
import { createCharts } from "./charts";
import { createSelects } from "./selects";
import { createGlass } from "./glass";
export function mountWorkspace() {
  const scope = createScope();
  const TheosMarkdown = createMarkdown(scope);
  const TheosCharts = createCharts(scope);
  const TheosSelects = createSelects(scope);
  let TheosGlass = {
    enhance() {},
  };
  const $ = (id) => document.getElementById(id);
  const agentName = $("agent-name").textContent;
  sessionStorage.removeItem("theos-token");
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
    {
      name: "research",
      argument: "question",
      description: "Start explicit deep research",
    },
    {
      name: "help",
      description: "Show commands and keyboard shortcuts",
    },
    {
      name: "new",
      description: "Start a new conversation",
    },
    {
      name: "reset",
      description: "Reset this conversation after confirmation",
    },
    {
      name: "resume",
      description: "Continue saved work",
    },
    {
      name: "model",
      argument: "name",
      description: "Show or choose an available model",
    },
    {
      name: "reasoning",
      argument: "effort",
      description: "Show or choose reasoning effort",
    },
    {
      name: "settings",
      description: "Edit model, reasoning, generation, and voice",
    },
    {
      name: "tools",
      description: "Open the conversation tools view",
    },
    {
      name: "connections",
      description: "Connect accounts and inspect workspace services",
    },
    {
      name: "usage",
      description: "Show your total and conversation costs",
    },
    {
      name: "voice",
      description: "Show microphone and speech settings",
    },
  ];
  function reasoningChoices() {
    return (
      me.generation_capabilities[$("model").value]?.reasoning || ["default"]
    );
  }
  function renderReasoning(value) {
    const choices = reasoningChoices();
    $("reasoning").replaceChildren(
      ...choices.map((choice) => {
        const option = node(
          "option",
          choice === "default" ? "Default" : choice,
        );
        option.value = choice;
        return option;
      }),
    );
    $("reasoning").value = choices.includes(value) ? value : "default";
    TheosSelects.sync("model");
    TheosSelects.sync("reasoning");
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
      input.placeholder =
        key === "max_output_tokens"
          ? String(
              Math.min(
                me.default_max_output_tokens || 8192,
                capabilities.max_output_tokens,
              ),
            )
          : "Model default";
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
    if (section === "model" || section === "reasoning")
      ($(section + "-trigger") || $(section)).focus();
    if (section === "voice") $("auto-speech").focus();
  }
  $("generation-button").onclick = () => openSettings();
  $("sidebar-settings-button").onclick = () => openSettings();
  $("generation-close").onclick = () => $("generation-dialog").close();
  $("generation-cancel").onclick = () => $("generation-dialog").close();
  scope.listen($("generation-dialog"), "cancel", (event) => {
    if (settingsSaving) event.preventDefault();
  });
  scope.listen($("generation-dialog"), "close", () => {
    TheosSelects.close();
    $("model").value = savedModel;
    renderReasoning(savedReasoning);
    if (sidebarMedia.matches) $("toggle-sidebar").focus();
  });
  $("generation-defaults").onclick = () => {
    for (const input of $("generation-fields").querySelectorAll("input"))
      input.value = "";
  };
  scope.listen(
    $("generation-form"),
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
      plus: ["M12 5v14M5 12h14"],
      chat: [
        "M21 11a8 8 0 0 1-8 8H8l-5 3V11a9 9 0 0 1 18 0Z",
        "M8 10h8M8 14h5",
      ],
      chevron: ["m8 14 4-4 4 4"],
      check: ["m5 12 4 4L19 6"],
      calendar: [
        "M5 4h14a2 2 0 0 1 2 2v14H3V6a2 2 0 0 1 2-2Z",
        "M7 2v4M17 2v4M3 10h18M7 14h2M13 14h4",
      ],
      refresh: ["M20 7a9 9 0 1 0 1 8", "M20 2v6h-6"],
      back: ["M19 12H5m6-6-6 6 6 6"],
      users: [
        "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2",
        "M13 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z",
        "M18 3a4 4 0 0 1 0 8M22 21v-2a4 4 0 0 0-3-3.9",
      ],
      activity: ["M3 12h4l3-8 4 16 3-8h4"],
      wallet: [
        "M20 7H5a2 2 0 0 1 0-4h13v4",
        "M3 5v14a2 2 0 0 0 2 2h16V7",
        "M21 12h-6v5h6M17 14.5h.01",
      ],
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
  TheosSelects.enhance($("model"), controlIcon("memory"), controlIcon("check"));
  TheosSelects.enhance(
    $("reasoning"),
    controlIcon("settings"),
    controlIcon("check"),
  );
  TheosSelects.enhance(
    $("dashboard-range"),
    controlIcon("calendar"),
    controlIcon("check"),
  );
  for (const id of ["back-chat", "back-connections"])
    $(id).prepend(controlIcon("back"));
  for (const id of ["dashboard-refresh", "refresh-connections"])
    $(id).prepend(controlIcon("refresh"));
  setIconButton($("cancel-recording"), "cancel", "Cancel recording");
  setIconButton($("attach-files"), "attach", "Attach files");
  setIconButton(
    $("command-help"),
    "command",
    "Show command and connection help",
  );
  $("attach-files").append(node("span", "Attach files"));
  $("command-help").append(node("span", "Commands & connections"));
  $("composer-settings").prepend(controlIcon("settings"));
  setIconButton($("composer-add"), "plus", "Add files and options");
  setIconButton($("send"), "send", "Send message");
  setIconButton($("toggle-sidebar"), "sidebar", "Toggle conversation sidebar");
  $("generation-button").prepend(controlIcon("settings"));
  $("sidebar-settings-button").prepend(controlIcon("settings"));
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
    const speechSession = selected;
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
            body: JSON.stringify({
              text: speechText,
              session_id: speechSession,
            }),
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
  const composerPrompts = [
    "Make me a billionaire...",
    "Initiate a worldwide peacekeeping mission...",
    "Plan my next great escape...",
    "Find me a new rabbit hole...",
    "Make Monday feel like Friday...",
  ];
  const mobileComposerPrompts = [
    "Sue the void",
    "Tax my soul",
    "Fire my ego",
    "Hire a god",
    "Fix free will",
  ];
  const composerPromptMedia = matchMedia("(max-width: 700px)");
  let composerPromptIndex = 0;
  let composerPromptTimer;
  let composerVoiceActivity = "";
  function syncComposerPlaceholder() {
    const message = $("message");
    const prompts = composerPromptMedia.matches
      ? mobileComposerPrompts
      : composerPrompts;
    message.placeholder =
      composerVoiceActivity ||
      (document.activeElement === message
        ? "Start Typing..."
        : prompts[composerPromptIndex]);
    $("status").classList.toggle(
      "placeholder-status",
      !!composerVoiceActivity &&
        !message.value &&
        $("status").classList.contains("voice-status"),
    );
  }
  function setComposerVoiceActivity(activity) {
    composerVoiceActivity = activity;
    const status = $("status");
    if (activity) {
      status.textContent = activity;
      status.className = "voice-status";
    } else if (status.classList.contains("voice-status")) {
      status.textContent = "";
      status.className = "";
    }
    if (activity === "Transcribing...")
      $("message").setAttribute("aria-busy", "true");
    else $("message").removeAttribute("aria-busy");
    syncComposerPlaceholder();
  }
  function rotateComposerPrompt() {
    if (
      document.hidden ||
      $("workspace").hidden ||
      $("message").value ||
      document.activeElement === $("message") ||
      composerVoiceActivity
    )
      return;
    composerPromptIndex = (composerPromptIndex + 1) % composerPrompts.length;
    syncComposerPlaceholder();
  }
  function startComposerPrompts() {
    scope.clearInterval(composerPromptTimer);
    syncComposerPlaceholder();
    composerPromptTimer = scope.setInterval(rotateComposerPrompt, 8000);
  }
  scope.listen(composerPromptMedia, "change", syncComposerPlaceholder);
  function stopRecordingMeter() {
    const meter = recordingMeter;
    recordingMeter = null;
    if (meter) {
      scope.cancelAnimationFrame(meter.frame);
      meter.source?.disconnect();
      meter.analyser?.disconnect();
      meter.motion.removeEventListener?.("change", meter.onMotionChange);
      meter.context.close().catch(() => {});
    }
    $("composer").style.removeProperty("--voice-level");
    $("voice-ambience").style.removeProperty("--voice-level");
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
      scope.listen(motion, "change", meter.onMotionChange);
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
          samples.reduce((sum, value) => sum + value * value, 0) /
            samples.length,
        );
        const target = Math.min(1, Math.max(0, (rms - 0.008) * 8));
        level += (target - level) * (target > level ? 0.35 : 0.12);
        $("composer").style.setProperty("--voice-level", level.toFixed(3));
        $("voice-ambience").style.setProperty(
          "--voice-level",
          level.toFixed(3),
        );
        meter.frame = scope.requestAnimationFrame(measure);
      };
      measure();
    } catch (_) {
      // Keep recording available if this browser cannot analyze microphone volume.
      if (recordingMeter === meter) stopRecordingMeter();
    }
  }
  function releaseRecording() {
    scope.clearTimeout(recordingTimer);
    stopRecordingMeter();
    recordingStream?.getTracks().forEach((track) => track.stop());
    recordingStream = null;
    setIconButton($("microphone"), "microphone", "Record a voice message");
    $("microphone").classList.remove("is-recording");
    $("composer").classList.remove("is-recording");
    document.body.classList.remove("is-recording");
    $("cancel-recording").hidden = true;
    setComposerVoiceActivity("");
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
    setComposerVoiceActivity("Opening microphone...");
    try {
      recordingStream = await navigator.mediaDevices.getUserMedia({
        audio: true,
      });
      const mimeType = [
        "audio/webm;codecs=opus",
        "audio/mp4",
        "audio/ogg;codecs=opus",
      ].find((type) => MediaRecorder.isTypeSupported(type));
      recorder = new MediaRecorder(
        recordingStream,
        mimeType
          ? {
              mimeType,
            }
          : {},
      );
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
        setComposerVoiceActivity("Transcribing...");
        try {
          const type = recorder.mimeType || "audio/webm";
          const audio = new Blob(chunks, {
            type,
          });
          const form = new FormData();
          const extension = type.includes("mp4")
            ? "m4a"
            : type.includes("ogg")
              ? "ogg"
              : "webm";
          form.append("file", audio, `recording.${extension}`);
          const file = await json("/api/files", {
            method: "POST",
            body: form,
          });
          const result = await json("/api/audio/transcribe", {
            method: "POST",
            body: JSON.stringify({
              file_id: file.id,
            }),
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
        } catch (error) {
          showError(error);
        } finally {
          setComposerVoiceActivity("");
          setBusy(false);
          $("microphone").disabled = false;
        }
      };
      recorder.start(1000);
      setIconButton($("microphone"), "stop", "Stop voice recording");
      $("microphone").classList.add("is-recording");
      $("composer").classList.add("is-recording");
      document.body.classList.add("is-recording");
      startRecordingMeter(recordingStream);
      $("microphone").disabled = false;
      $("cancel-recording").hidden = false;
      setComposerVoiceActivity("Listening...");
      recordingTimer = scope.setTimeout(() => stopRecording(), 120000);
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
  };
  scope.listen(window, "pagehide", () => {
    scope.clearInterval(composerPromptTimer);
    stopRecording(true);
    releaseAudio();
    for (const timer of messageTimers) scope.clearInterval(timer);
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
        .map((service) => ({
          ...service,
          status: "Configured",
        })),
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
    const match = message.value
      .slice(0, caret)
      .match(/(?:^|\s)@([a-z0-9_-]*)$/i);
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
    list.children[commandIndex].scrollIntoView({
      block: "nearest",
    });
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
        if (command.argument)
          button.append(node("small", "Choose an option →"));
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
      renderConversationCost(session.usage);
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
  scope.listen($("usage-dialog"), "close", () => {
    usageRequest++;
  });
  async function runCommand(text) {
    const [command, ...parts] = text.slice(1).split(/\s+/);
    const argument = parts.join(" ").trim();
    const name =
      command.toLowerCase() === "thinking"
        ? "reasoning"
        : command.toLowerCase();
    const spec = commands.find((item) => item.name === name);
    if (!spec)
      throw new Error(
        `Unknown command /${command}. Use /help to see available commands.`,
      );
    if (!spec.argument && argument)
      throw new Error(
        `/${spec.name} takes no arguments. Use /help for command syntax.`,
      );
    if (spec.name === "research") {
      if (!argument)
        throw new Error("Use /research followed by your question.");
      messageMetadata(bubble("user", argument), {
        created_at: Date.now() / 1000,
      });
      $("research-mode").value = "normal";
      return stream(`/api/sessions/${selected}/turn`, {
        text: argument,
        mode: "deep_research",
      });
    }
    if (spec.name === "help") return commandHelp();
    if (spec.name === "new") return newSession();
    if (spec.name === "reset") return $("reset").onclick();
    if (spec.name === "resume")
      return stream(`/api/sessions/${selected}/resume`);
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
    TheosSelects.close();
    scope.clearInterval(connectionTimer);
    $("mobile-conversation-heading").hidden = id !== "chat-view";
    $("conversation-toolbar").hidden = [
      "dashboard",
      "connections-view",
    ].includes(id);
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
  function renderConversationTitle(title) {
    $("session-title").textContent = title;
    $("mobile-session-title").textContent = title;
    $("mobile-session-title").title = title;
  }
  function renderConversationCost(usage) {
    const text = `Conversation cost: ${formatCost(usage)}`;
    $("conversation-cost").textContent = text;
    $("mobile-conversation-cost").textContent = text;
  }
  async function refreshCosts(session) {
    renderConversationCost(session.usage);
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
    const headers = {
      "X-Theos-Request": "1",
      ...options.headers,
    };
    if (options.body && !(options.body instanceof FormData))
      headers["Content-Type"] = "application/json";
    const response = await scope.fetch(path, {
      ...options,
      headers,
    });
    if (!response.ok) {
      let detail = "The request failed. Please try again.";
      try {
        const value = await response.json();
        if (typeof value.detail === "string") detail = value.detail;
      } catch (_) {}
      const error = new Error(detail);
      error.status = response.status;
      if (response.status === 401 && me) {
        clearInterval(notificationTimer);
        clearInterval(connectionTimer);
        stopRecording(true);
        releaseAudio();
        me = null;
        $("workspace").hidden = true;
        $("login").hidden = false;
        $("login-error").textContent = "Your session expired. Sign in again.";
      }
      throw error;
    }
    return response;
  }
  async function json(path, options = {}) {
    return (await api(path, options)).json();
  }
  function showError(error) {
    if (error.name === "AbortError") return;
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
      "sidebar-settings-button",
      "research-mode",
      "mode-trigger",
      "command-help",
      "new-session",
      "attach-files",
      "composer-add",
      "composer-settings",
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
    if (value) {
      hideCommands();
      closeComposerOptions();
      closeModeMenu();
    }
  }
  scope.listen($("messages"), "scroll", () => {
    const messages = $("messages");
    followChat =
      messages.scrollHeight - messages.scrollTop - messages.clientHeight < 80;
  });
  scope.listen($("messages"), "markdown-rendered", () => scrollChat());
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
          year: "numeric",
          hour: "2-digit",
          minute: "2-digit",
          hourCycle: "h23",
        })
          .formatToParts(date)
          .map((part) => [part.type, part.value]),
      );
      const timestamp = node(
        "time",
        `${values.day} ${values.month} ${values.year} ${values.hour}:${values.minute}`,
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
    let display = {
      created_at: Date.now() / 1000,
    };
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
      scope.clearInterval(timer);
      messageTimers.delete(timer);
    };
    const timer = scope.setInterval(() => {
      if (!body.isConnected) return stop();
      draw();
    }, 200);
    messageTimers.add(timer);
    draw();
    return {
      start(value = {}) {
        started = performance.now();
        display = {
          ...display,
          ...value,
        };
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
      node("span", "A little space to think", "eyebrow"),
      node("h1", "What’s on your mind?"),
      node(
        "p",
        "Ask a question, make a plan, or work through an idea. Your next step starts here.",
      ),
    );
    const starters = node("div", "", "conversation-starters");
    for (const [icon, label, draft] of [
      ["skills", "Make a plan", "Help me make a plan for "],
      ["search", "Explore a topic", "Help me understand "],
      ["attach", "Work with a file", "Help me with the file I attach. "],
    ]) {
      const button = node("button", label);
      button.type = "button";
      button.prepend(controlIcon(icon));
      button.onclick = () => {
        $("message").value = draft;
        resizeComposer();
        $("message").focus();
      };
      starters.append(button);
    }
    box.append(starters);
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
    $("research-mode").value = "normal";
    resizeComposer();
    renderConversationTitle(session.title);
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
        : "";
    $("status").className = "";
    scrollChat(true);
    await listSessions();
    await refreshCosts(session);
  }
  function compactionActivity(event, rows) {
    const key = event.compaction_id || event.parent_call_id || "parent";
    let row = rows.get(key);
    if (!row || event.status === "started") {
      row = node("div", "", "context-activity");
      row.setAttribute("role", "status");
      row.setAttribute("aria-live", "polite");
      $("messages").append(row);
      rows.set(key, row);
    }
    const active = ["started", "progress"].includes(event.status);
    row.className = "context-activity" + (active ? " is-organizing" : "");
    row.textContent = active
      ? event.parent_call_id
        ? "Organizing research context…"
        : "Organizing earlier conversation…"
      : event.status === "completed"
        ? "Context ready. Continuing."
        : "Context preparation stopped. Your conversation is saved.";
    scrollChat();
  }
  function approvals(items) {
    $("approvals").replaceChildren();
    for (const item of items) {
      const card = node("article", "");
      card.append(node("strong", "Approval needed"));
      card.append(
        node(
          "p",
          item.label || item.tool.replaceAll("_", " "),
          "approval-action",
        ),
      );
      let fields = null;
      let group = null;
      const technical = node("details", "", "approval-technical");
      technical.append(node("summary", "Exact request details"));
      const technicalFields = node("dl", "", "approval-fields");
      let technicalGroup = null;
      for (const field of item.review || []) {
        if (field.technical && field.group && field.group !== technicalGroup) {
          technicalGroup = field.group;
          technicalFields.append(node("dt", technicalGroup, "approval-group"));
        }
        if (!field.technical && (!fields || group !== field.group)) {
          group = field.group;
          if (group) card.append(node("h3", group, "approval-group"));
          fields = node("dl", "", "approval-fields");
          card.append(fields);
        }
        const destination = field.technical ? technicalFields : fields;
        const label = node("dt", field.label);
        destination.append(label);
        const value = node("dd", "");
        if (field.kind === "markdown") {
          const content = node("div", "", "markdown");
          TheosMarkdown.render(content, field.text);
          value.append(content);
        } else {
          value.append(
            node(
              field.kind === "code" ? "pre" : "div",
              field.text,
              "approval-value",
            ),
          );
        }
        destination.append(value);
        if (field.kind !== "text" || field.text.includes("\n")) {
          label.classList.add("approval-wide");
          value.classList.add("approval-wide");
        }
        if (field.hint)
          value.append(node("small", field.hint, "approval-hint"));
      }
      if (technicalFields.childElementCount) {
        technical.append(technicalFields);
        card.append(technical);
      }
      const exact = node("details", "");
      exact.append(node("summary", "Exact tool arguments"));
      exact.append(
        node("pre", JSON.stringify(JSON.parse(item.arguments), null, 2)),
      );
      card.append(exact);
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
            {
              approved,
            },
            () => {
              card.remove();
              toolActivity(
                {
                  call_id: item.call_id,
                  name: item.tool,
                },
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
        scope.setTimeout(() => URL.revokeObjectURL(url), 1000);
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
    const compactionRows = new Map();
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
        buffer += decoder.decode(value || new Uint8Array(), {
          stream: !done,
        });
        let index;
        while ((index = buffer.indexOf("\n\n")) >= 0) {
          const line = buffer.slice(0, index);
          buffer = buffer.slice(index + 2);
          if (!line.startsWith("data: ")) continue;
          const event = JSON.parse(line.slice(6));
          if (event.type === "compaction") {
            compactionActivity(event, compactionRows);
            $("status").textContent = ["started", "progress"].includes(
              event.status,
            )
              ? "Organizing context…"
              : "Continuing…";
            $("status").classList.remove("thinking-status");
          }
          if (event.type === "title") {
            renderConversationTitle(event.title);
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
              lastAnswerBody?.parentElement
                .querySelector(".speech-control")
                ?.remove();
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
          if (
            event.type === "assistant_complete" ||
            event.type === "answer_replace"
          ) {
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
      renderConversationTitle(session.title);
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
      for (const row of compactionRows.values()) {
        if (row.classList.contains("is-organizing")) {
          row.className = "context-activity";
          row.textContent =
            "Context preparation stopped. Your conversation is saved.";
        }
      }
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
      body: JSON.stringify({
        title: "New conversation",
      }),
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
    scope.clearInterval(notificationTimer);
    notificationTimer = scope.setInterval(async () => {
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
    const button = $("login-form").querySelector("button[type=submit]");
    button.disabled = true;
    $("login-error").textContent = "";
    try {
      await json("/api/auth/login", {
        method: "POST",
        body: JSON.stringify({ token: $("token").value.trim() }),
      });
      $("token").value = "";
      await login();
    } catch (error) {
      $("login-error").textContent = error.message;
    } finally {
      button.disabled = false;
    }
  };
  $("sign-out").onclick = async () => {
    stopRecording(true);
    releaseAudio();
    try {
      await json("/api/auth/logout", {
        method: "POST",
      });
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
          new Error(
            "Send attached files with a message before using a command.",
          ),
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
    messageMetadata(bubble("user", text), {
      created_at: Date.now() / 1000,
    });
    $("message").value = "";
    const attached = files.map((f) => f.id);
    files = [];
    $("attachments").textContent = "";
    $("message").required = true;
    try {
      const mode = $("research-mode").value;
      $("research-mode").value = "normal";
      resizeComposer();
      await stream(`/api/sessions/${selected}/turn`, {
        text,
        files: attached,
        mode,
      });
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
    syncModePicker();
    syncComposerPlaceholder();
    const message = $("message");
    $("composer").classList.toggle(
      "has-draft",
      !!message.value ||
        !!files.length ||
        $("research-mode").value !== "normal",
    );
    message.style.height = "auto";
    if (!message.value) return;
    message.style.height = `${Math.max(44, Math.min(message.scrollHeight, 140))}px`;
  }
  $("message").oninput = (event) => {
    closeComposerOptions();
    closeModeMenu();
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
  $("message").onblur = () => {
    hideCommands();
    syncComposerPlaceholder();
  };
  $("message").onkeyup = (event) => {
    if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key))
      suggestCommands();
  };
  $("command-help").onclick = commandHelp;
  function closeComposerOptions(restoreFocus = false) {
    if ($("composer-options").hidden) return;
    $("composer-options").hidden = true;
    $("composer-add").setAttribute("aria-expanded", "false");
    if (restoreFocus) $("composer-add").focus();
  }
  $("composer-add").onclick = () => {
    closeModeMenu();
    const open = $("composer-options").hidden;
    hideCommands();
    $("composer-options").hidden = !open;
    $("composer-add").setAttribute("aria-expanded", String(open));
    if (open)
      $("composer-options").querySelector("button:not(:disabled)").focus();
  };
  scope.listen($("composer-options"), "click", (event) => {
    if (event.target.closest("button")) closeComposerOptions();
  });
  $("composer-settings").onclick = () => openSettings();
  scope.listen(document, "click", (event) => {
    if (!event.target.closest("#composer-options, #composer-add"))
      closeComposerOptions();
  });
  scope.listen($("composer"), "focusout", () => {
    scope.requestAnimationFrame(() => {
      if (!$("composer").contains(document.activeElement)) {
        closeComposerOptions();
        closeModeMenu();
      }
      resizeComposer();
    });
  });
  scope.listen($("message"), "focus", resizeComposer);
  startComposerPrompts();
  scope.listen(window, "pageshow", (event) => {
    if (event.persisted) startComposerPrompts();
  });
  const messageModes = {
    normal: {
      label: "Normal",
      icon: "chat",
      detail: "Everyday conversations",
    },
    deep_research: {
      label: "Deep research",
      icon: "search",
      detail: "Explore sources in depth",
    },
  };
  const modeOptions = [...$("mode-menu").querySelectorAll("[data-mode]")];
  for (const option of modeOptions) {
    const mode = messageModes[option.dataset.mode];
    const copy = node("span", "", "mode-copy");
    copy.append(node("strong", mode.label), node("small", mode.detail));
    const check = controlIcon("check");
    check.classList.add("mode-check");
    option.append(controlIcon(mode.icon), copy, check);
    option.onclick = () => {
      $("research-mode").value = option.dataset.mode;
      closeModeMenu(true);
      resizeComposer();
    };
  }
  function syncModePicker() {
    const mode = messageModes[$("research-mode").value];
    const trigger = $("mode-trigger");
    if (trigger.dataset.mode === $("research-mode").value) return;
    trigger.dataset.mode = $("research-mode").value;
    trigger.replaceChildren(
      controlIcon(mode.icon),
      node("span", mode.label),
      controlIcon("chevron"),
    );
    trigger.setAttribute("aria-label", `Message mode: ${mode.label}`);
    for (const option of modeOptions)
      option.setAttribute(
        "aria-selected",
        String(option.dataset.mode === trigger.dataset.mode),
      );
  }
  function closeModeMenu(restoreFocus = false) {
    if ($("mode-menu").hidden) return;
    $("mode-menu").hidden = true;
    $("mode-trigger").setAttribute("aria-expanded", "false");
    if (restoreFocus) $("mode-trigger").focus();
  }
  function openModeMenu() {
    if (busy) return;
    closeComposerOptions();
    hideCommands();
    $("mode-menu").hidden = false;
    $("mode-trigger").setAttribute("aria-expanded", "true");
    modeOptions
      .find((option) => option.dataset.mode === $("research-mode").value)
      .focus();
  }
  $("mode-trigger").onclick = () =>
    $("mode-menu").hidden ? openModeMenu() : closeModeMenu();
  $("mode-trigger").onkeydown = (event) => {
    if (["ArrowUp", "ArrowDown"].includes(event.key)) {
      event.preventDefault();
      openModeMenu();
    }
  };
  $("mode-menu").onkeydown = (event) => {
    const index = modeOptions.indexOf(document.activeElement);
    if (["ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      const next =
        event.key === "Home"
          ? 0
          : event.key === "End"
            ? modeOptions.length - 1
            : (index +
                (event.key === "ArrowDown" ? 1 : -1) +
                modeOptions.length) %
              modeOptions.length;
      modeOptions[next].focus();
    } else if (event.key === "Escape") {
      event.preventDefault();
      closeModeMenu(true);
    } else if (event.key === "Tab") closeModeMenu(true);
  };
  scope.listen(document, "click", (event) => {
    if (!event.target.closest("#mode-menu, #mode-trigger")) closeModeMenu();
  });
  syncModePicker();
  $("upload").onchange = async () => {
    try {
      for (const file of $("upload").files) {
        const form = new FormData();
        form.append("file", file);
        files.push(
          await json("/api/files", {
            method: "POST",
            body: form,
          }),
        );
      }
      $("attachments").textContent = files.map((f) => f.name).join(" · ");
      $("message").required = !files.length;
      resizeComposer();
      if (files.length) $("message").focus();
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
  $("resume").onclick = () => {
    if (sidebarMedia.matches) setSidebar(false);
    return stream(`/api/sessions/${selected}/resume`).catch(showError);
  };
  $("reset").onclick = async () => {
    if (
      !confirm(
        "Reset this conversation? Saved records and files remain available.",
      )
    )
      return;
    try {
      await json(`/api/sessions/${selected}/reset`, {
        method: "POST",
      });
      await openSession(selected);
    } catch (error) {
      showError(error);
    }
  };
  function table(title, rows, keys) {
    const section = node("details", "", "data-panel liquid-panel");
    const summary = node("summary", "", "data-panel-heading");
    const label = node("span", "", "data-panel-title");
    label.append(
      node("strong", title),
      node(
        "small",
        `${rows.length.toLocaleString()} ${rows.length === 1 ? "record" : "records"} · all time`,
      ),
    );
    summary.append(label, controlIcon("chevron"));
    section.append(summary);
    if (!rows.length) {
      section.append(node("p", "No records yet.", "table-empty"));
      return section;
    }
    const labels = {
      owner: "User",
      id: "Conversation",
      input_tokens: "Input tokens",
      output_tokens: "Output tokens",
      cache_tokens: "Cached tokens",
      cost: "Recorded USD",
      unpriced_requests: "Unpriced",
      error_type: "Error type",
    };
    const scroll = node("div", "", "table-scroll");
    scroll.tabIndex = 0;
    scroll.setAttribute("role", "region");
    scroll.setAttribute(
      "aria-label",
      `${title} table. Scroll horizontally for more columns.`,
    );
    const data = node("table");
    const caption = node("caption", `${title} · all-time records`, "sr-only");
    const head = node("tr");
    const thead = node("thead");
    const numeric = new Set([
      "requests",
      "input_tokens",
      "output_tokens",
      "cache_tokens",
      "cost",
      "unpriced_requests",
      "attempts",
    ]);
    for (const key of keys) {
      const cell = node(
        "th",
        labels[key] || key.replaceAll("_", " "),
        numeric.has(key) ? "numeric" : "",
      );
      cell.scope = "col";
      head.append(cell);
    }
    thead.append(head);
    const body = node("tbody");
    for (const row of rows) {
      const tr = node("tr");
      for (const key of keys) {
        const cell = node(
          "td",
          key === "cost"
            ? formatCost(row)
            : row[key] == null
              ? "Unavailable"
              : typeof row[key] === "number"
                ? row[key].toLocaleString()
                : String(row[key]),
          numeric.has(key) ? "numeric" : "",
        );
        if (["id", "session"].includes(key)) cell.classList.add("record-id");
        tr.append(cell);
      }
      body.append(tr);
    }
    data.append(caption, thead, body);
    scroll.append(data);
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
    const content = $("dashboard-content");
    content.replaceChildren();
    content.setAttribute("aria-busy", "true");
    $("dashboard-title").textContent = admin
      ? "Admin dashboard"
      : "Activity & usage";
    $("dashboard-eyebrow").textContent = admin
      ? "Workspace insights"
      : "Personal insights";
    $("dashboard-description").textContent = admin
      ? "A clear view of usage across all users and transports."
      : "Your conversations, model usage, and recorded costs in one place.";
    $("dashboard-status").hidden = false;
    $("dashboard-status").textContent = "Loading activity…";
    $("dashboard-status").className = "panel-status";
    $("dashboard-range").disabled = true;
    $("dashboard-refresh").disabled = true;
    $("dashboard-refresh").setAttribute("aria-busy", "true");
    try {
      const [data, logs] = await Promise.all([
        json(
          `/api/${admin ? "dashboard" : "activity"}?days=${$("dashboard-range").value}`,
        ),
        admin ? json("/api/logs") : Promise.resolve([]),
      ]);
      if (request !== dashboardRequest) return;
      const overview = node("section", "", "dashboard-overview liquid-panel");
      overview.append(
        node("h2", "Lifetime overview"),
        node(
          "p",
          admin ? "All users · all time" : "Your account · all time",
          "dashboard-caption",
        ),
      );
      const stats = node("div", "", "stats");
      for (const [value, label, icon] of [
        ...(admin
          ? [[data.totals.users.toLocaleString(), "Users", "users"]]
          : []),
        [data.totals.conversations.toLocaleString(), "Conversations", "chat"],
        [
          (
            data.totals.input_tokens + data.totals.output_tokens
          ).toLocaleString(),
          "Tokens processed",
          "activity",
        ],
        [formatCost(data.totals), "Recorded cost · USD", "wallet"],
      ]) {
        const stat = node("div", "", "stat");
        const title = node("span", "", "stat-label");
        title.append(controlIcon(icon), node("span", label));
        stat.append(title, node("strong", value));
        stats.append(stat);
      }
      overview.append(
        stats,
        node(
          "p",
          data.totals.unpriced_requests
            ? `${data.totals.unpriced_requests.toLocaleString()} requests have no recorded price. Cost totals include priced requests only.`
            : "Costs use provider-reported amounts or configured token rates.",
          "cost-label",
        ),
      );
      const chartHeading = node(
        "div",
        "",
        "section-title chart-section-heading",
      );
      chartHeading.append(
        node("h2", "Activity at a glance"),
        node("span", `Last ${data.activity.days} days · UTC`),
      );
      content.append(
        overview,
        chartHeading,
        TheosCharts.activity(data.activity),
      );
      const records = node("section", "", "dashboard-records");
      const recordHeading = node("div", "", "section-title");
      recordHeading.append(
        node("h2", "Explore the details"),
        node("span", "All-time records"),
      );
      records.append(recordHeading);
      if (admin)
        records.append(
          table("Usage per user", data.cost_per_user, [
            "owner",
            "requests",
            "input_tokens",
            "output_tokens",
            "cache_tokens",
            "cost",
            "unpriced_requests",
          ]),
        );
      records.append(
        table("Cost per conversation", data.cost_per_conversation, [
          ...(admin ? ["owner"] : []),
          "id",
          "channel",
          "requests",
          "cost",
          "unpriced_requests",
        ]),
        table("Usage by model", data.usage, [
          ...(admin ? ["owner"] : []),
          "model",
          "requests",
          "input_tokens",
          "output_tokens",
          "cache_tokens",
          "cost",
          "unpriced_requests",
        ]),
      );
      if (admin)
        records.append(
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
          table("Traces", data.traces, ["session", "event", "tool", "status"]),
          table("Application logs", logs, ["time", "event", "error_type"]),
        );
      content.append(records);
      TheosGlass.enhance(content);
      $("dashboard-status").hidden = true;
    } catch (error) {
      if (request !== dashboardRequest) return;
      $("dashboard-status").textContent = error.message;
      $("dashboard-status").className = "panel-status error";
    } finally {
      if (request === dashboardRequest) {
        content.removeAttribute("aria-busy");
        $("dashboard-range").disabled = false;
        $("dashboard-refresh").disabled = false;
        $("dashboard-refresh").removeAttribute("aria-busy");
      }
    }
  }
  $("activity-button").onclick = () => loadDashboard("personal");
  $("dashboard-button").onclick = () => loadDashboard("admin");
  $("dashboard-range").onchange = () => loadDashboard();
  $("dashboard-refresh").onclick = () => loadDashboard();
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
    if (!tools.length)
      $("tools-content").append(node("p", "No matching tools."));
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
    $("refresh-connections").disabled = true;
    $("refresh-connections").setAttribute("aria-busy", "true");
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
      $("refresh-connections").disabled = false;
      $("refresh-connections").removeAttribute("aria-busy");
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
    $("connection-summary").textContent =
      `${data.accounts.filter((account) => account.connected).length} connected · ${data.accounts.length} accounts`;
    for (const account of data.accounts) {
      const setup = account.setup;
      const pending = ["starting", "waiting"].includes(setup.status);
      const card = node("article", "", "connection-card liquid-panel");
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
          `status-pill ${account.connected ? "is-connected" : pending ? "is-pending" : "is-unavailable"}`,
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
          account.connected ? "soft-button" : "primary",
        );
        connect.disabled = setup.status === "starting";
        connect.onclick = () =>
          connectionAction(async () => {
            const result = await json(
              `/api/connections/${account.id}/connect`,
              {
                method: "POST",
              },
            );
            if (result.url) authorizationLinks.set(account.id, result.url);
          });
        actions.append(connect);
      }
      if (account.connected || pending) {
        const disconnect = node(
          "button",
          account.connected ? "Disconnect" : "Cancel setup",
          "soft-button",
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
              body: JSON.stringify({
                url: returnURL,
              }),
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
        identity.append(
          connectionIcon(service.id),
          node("strong", service.name),
        );
        row.append(
          identity,
          node(
            "span",
            service.configured ? "Configured" : "Not configured",
            `status-pill ${service.configured ? "is-connected" : "is-unavailable"}`,
          ),
        );
        return row;
      }),
    );
    connectionSnapshot = snapshot;
    TheosGlass.enhance($("connections-view"));
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
      connectionTimer = scope.setInterval(() => {
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
    if (error.name === "AbortError") return;
    scope.clearTimeout(signinTimer);
    $("web-signin-status").textContent = error.message;
    $("web-signin-status").className = "error";
  }
  async function pollSignin() {
    const status = await json("/api/onboarding/status");
    $("web-signin-code").textContent = status.code;
    if (status.state === "approved") {
      const access = await json("/api/onboarding/complete", {
        method: "POST",
      });
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
      signinTimer = scope.setTimeout(
        () => pollSignin().catch(signinError),
        2000,
      );
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
      body: JSON.stringify({
        invite,
      }),
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
    scope.clearTimeout(signinTimer);
    try {
      await json("/api/onboarding/cancel", {
        method: "POST",
      });
      sessionStorage.removeItem("theos-pending-signin");
      location.reload();
    } catch (error) {
      signinError(error);
    }
  };
  const signinInvite = new URLSearchParams(location.hash.slice(1)).get(
    "onboard",
  );
  scope.listen(window, "hashchange", () => {
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
      if (error.name !== "AbortError" && error.status !== 401)
        $("login-error").textContent = error.message;
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
    for (const id of ["theme-toggle", "sidebar-theme-toggle"])
      setIconButton(
        $(id),
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
  function toggleTheme() {
    const theme =
      document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    applyTheme(theme);
    localStorage.setItem("theos-theme", theme);
  }
  $("theme-toggle").onclick = toggleTheme;
  $("sidebar-theme-toggle").onclick = toggleTheme;
  const sidebarMedia = matchMedia("(max-width: 700px)");
  const conversationActions = $("conversation-actions");
  const desktopConversationControls = conversationActions.parentElement;
  function closeConversationActions(restoreFocus = false) {
    if (!conversationActions.open) return;
    conversationActions.open = false;
    if (restoreFocus) conversationActions.querySelector("summary").focus();
  }
  scope.listen(conversationActions, "click", (event) => {
    if (event.target.closest("button")) closeConversationActions();
  });
  scope.listen(document, "click", (event) => {
    if (!conversationActions.contains(event.target)) closeConversationActions();
  });
  function setSidebar(open) {
    closeConversationActions();
    $("workspace").classList.toggle("sidebar-collapsed", !open);
    $("toggle-sidebar").setAttribute("aria-expanded", String(open));
    $("sidebar").inert = !open;
    $("sidebar-backdrop").hidden = !(sidebarMedia.matches && open);
    document.querySelector("main").inert = sidebarMedia.matches && open;
    document.querySelector(".app-header .header-actions").inert =
      sidebarMedia.matches && open;
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
  scope.listen(document, "keydown", (event) => {
    if (event.key === "Escape") closeComposerOptions(true);
    if (event.key === "Escape") closeModeMenu(true);
    if (event.key === "Escape") closeConversationActions(true);
    if (
      event.key === "Tab" &&
      sidebarMedia.matches &&
      !$("sidebar-backdrop").hidden
    ) {
      const controls = [
        $("toggle-sidebar"),
        ...$("sidebar").querySelectorAll("button:not(:disabled):not([hidden])"),
      ].filter((control) => control.getClientRects().length);
      const first = controls[0],
        last = controls.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    if (
      event.key === "Escape" &&
      sidebarMedia.matches &&
      !$("sidebar-backdrop").hidden
    ) {
      setSidebar(false);
      $("toggle-sidebar").focus();
    }
  });
  function placeConversationControls() {
    const parent = sidebarMedia.matches
      ? $("mobile-conversation-controls")
      : desktopConversationControls;
    parent.append(conversationActions);
  }
  scope.listen(sidebarMedia, "change", () => {
    placeConversationControls();
    setSidebar(!sidebarMedia.matches);
  });
  placeConversationControls();
  setSidebar(!sidebarMedia.matches);

  // Mobile keyboards resize the visual viewport without always resizing CSS vh.
  function fitViewport() {
    const viewport = window.visualViewport;
    if (!viewport || viewport.scale !== 1) return;
    const keyboardOpen = window.innerHeight - viewport.height > 120;
    document.documentElement.style.setProperty(
      "--viewport-height",
      `${Math.round(viewport.height)}px`,
    );
    document.documentElement.classList.toggle("keyboard-open", keyboardOpen);
    if (followChat) scrollChat();
  }
  scope.listen(window.visualViewport, "resize", fitViewport);
  fitViewport();

  // Leave scroll space for the floating composer, including approval cards.
  const composerSize = scope.observe(
    new ResizeObserver(() => {
      const height = document
        .querySelector(".composer-wrap")
        .getBoundingClientRect().height;
      if (!height) return;
      $("chat-view").style.setProperty(
        "--composer-space",
        `${Math.ceil(height)}px`,
      );
      const menuSpace =
        $("composer").getBoundingClientRect().top -
        document.querySelector("main").getBoundingClientRect().top -
        12;
      $("composer").style.setProperty(
        "--composer-menu-space",
        `${Math.max(44, Math.floor(menuSpace))}px`,
      );
      scrollChat();
    }),
  );
  composerSize.observe(document.querySelector(".composer-wrap"));
  composerSize.observe($("chat-view"));
  scope.listen(document.getElementById("attach-files"), "click", () =>
    document.getElementById("upload").click(),
  );

  // A selected mode applies to one message. Ordinary follow-ups never inherit it.
  let researchRequest = 0;
  async function showResearch() {
    if (!selected) return;
    if (sidebarMedia.matches) setSidebar(false);
    const sessionId = selected,
      request = ++researchRequest;
    $("research-dialog").showModal();
    $("research-status").textContent = "Loading saved research…";
    $("research-detail").replaceChildren();
    try {
      const runs = await json(`/api/sessions/${sessionId}/research`);
      if (request !== researchRequest || selected !== sessionId) return;
      $("research-runs").replaceChildren();
      $("research-status").textContent = runs.length
        ? "Select a researcher to inspect findings and sources."
        : "No saved deep research in this conversation.";
      for (const run of runs) {
        const button = node("button", `${run.name} · ${run.status}`);
        button.onclick = async () => {
          const detailRequest = ++researchRequest;
          try {
            const detail = await json(
              `/api/sessions/${sessionId}/research/${run.id}`,
            );
            if (detailRequest !== researchRequest || selected !== sessionId)
              return;
            button.textContent = `${detail.name} · ${detail.status}`;
            drawResearch(detail);
          } catch (error) {
            $("research-status").textContent = error.message;
          }
        };
        $("research-runs").append(button);
      }
    } catch (error) {
      $("research-status").textContent = error.message;
    }
  }
  function drawResearch(run) {
    const content = $("research-detail");
    content.replaceChildren(
      node("h3", run.name),
      node("p", run.task),
      node("p", run.reason || run.status),
    );
    if (run.answer) {
      content.append(node("h3", "Report"));
      const report = node("div", "", "markdown-body");
      TheosMarkdown.render(report, run.answer);
      content.append(report);
    }
    if (run.scratchpad.length)
      content.append(node("h3", "Evidence scratchpad"));
    for (const item of run.scratchpad) {
      const details = node("details"),
        value = item.content;
      details.append(
        node("summary", `${item.kind}: ${value.title || value.url || item.id}`),
      );
      if (value.url) {
        try {
          const url = new URL(value.url);
          if (["https:", "http:"].includes(url.protocol)) {
            const link = node("a", value.url);
            link.href = url.href;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            details.append(link);
          }
        } catch (_) {
          /* Keep invalid source URLs as plain saved data. */
        }
      }
      details.append(node("pre", JSON.stringify(value, null, 2)));
      content.append(details);
    }
    const transcript = node("details");
    transcript.append(
      node("summary", "Original research transcript"),
      node("pre", JSON.stringify(run.history, null, 2)),
    );
    content.append(transcript);
    const summaries = node("details");
    summaries.append(
      node("summary", "Saved summary checkpoints"),
      node("pre", JSON.stringify(run.checkpoints, null, 2)),
    );
    content.append(summaries);
  }
  $("research-button").onclick = () => showResearch();
  $("research-refresh").onclick = () => showResearch();
  $("research-close").onclick = () => {
    researchRequest++;
    $("research-dialog").close();
  };
  scope.listen($("research-dialog"), "close", () => {
    if (sidebarMedia.matches) $("toggle-sidebar").focus();
  });
  TheosGlass = createGlass(scope);
  scope.onDispose(() => {
    stopRecording(true);
    releaseAudio();
    if (conversationActions.parentElement !== desktopConversationControls)
      desktopConversationControls.append(conversationActions);
    document.documentElement.classList.remove("keyboard-open");
    document.documentElement.style.removeProperty("--viewport-height");
  });
  return () => scope.dispose();
}

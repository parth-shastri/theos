export const generationFields = {
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

export const commands = [
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

export const composerPrompts = [
  "Make me a billionaire...",
  "Initiate a worldwide peacekeeping mission...",
  "Plan my next great escape...",
  "Find me a new rabbit hole...",
  "Make Monday feel like Friday...",
];

export const mobileComposerPrompts = [
  "Sue the void",
  "Tax my soul",
  "Fire my ego",
  "Hire a god",
  "Fix free will",
];

export const messageModes = {
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

export const accountDescriptions = {
  github:
    "Search and read repositories, issues, pull requests, and Actions through the official GitHub MCP server.",
  slack:
    "Search and read Slack conversations through the official Slack MCP server. Available tools depend on your granted scopes.",
  gmail:
    "Search messages, manage drafts and labels. Sending a draft requires approval.",
  health:
    "Import activity, sleep, HRV and vitals from your linked Google Health profile. Connecting also enables meal exports.",
  zepto:
    "Shop for groceries and essentials. Choose a delivery address after connecting. Checkout, orders and payments require approval.",
};

export const providerIcons = {
  github: "/static/providers/github.svg",
  slack: "/static/providers/slack.svg",
  gmail: "/static/providers/gmail.svg",
  health: "/static/providers/health.png",
  zepto: "/static/providers/zepto.png",
};

export const iconPaths = {
  sidebar: ["M3 4h18v16H3Z", "M9 4v16"],
  settings: ["M4 7h16M4 17h16", "M8 4v6M16 14v6"],
  sun: [
    "M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z",
    "M12 2v2M12 20v2M2 12h2M20 12h2m-3-7 1.5-1.5M5 19l1.5-1.5M5 5l1.5 1.5M17.5 17.5 19 19",
  ],
  moon: ["M20.9 13a9 9 0 1 1-9.9-9.9A7 7 0 0 0 20.9 13Z"],
  attach: ["m20 11-8 8a5 5 0 0 1-7-7l9-9a3 3 0 0 1 4 4l-9 9a1 1 0 0 1-2-2l8-8"],
  command: ["m15 4-6 16"],
  send: ["M12 19V5m-6 6 6-6 6 6"],
  arrowUpRight: ["M5 19 19 5M5 5h14v14"],
  plus: ["M12 5v14M5 12h14"],
  chat: ["M21 11a8 8 0 0 1-8 8H8l-5 3V11a9 9 0 0 1 18 0Z", "M8 10h8M8 14h5"],
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

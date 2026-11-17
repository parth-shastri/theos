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
  calendar:
    "Find events, check availability, and create, reschedule, or delete single events in Google Calendar.",
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
  calendar: "/static/providers/calendar.svg",
  github: "/static/providers/github.svg",
  slack: "/static/providers/slack.svg",
  gmail: "/static/providers/gmail.svg",
  health: "/static/providers/health.png",
  zepto: "/static/providers/zepto.png",
};

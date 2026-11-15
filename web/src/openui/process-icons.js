export const cardIcons = [
  "activity",
  "timer",
  "calendar",
  "branch",
  "wallet",
  "weather",
  "skills",
  "globe",
  "lock",
  "window",
  "scale",
  "connection",
  "certificate",
  "key",
  "signature",
  "verify",
  "storage",
  "sandbox",
  "check",
  "alert",
  "chat",
  "users",
  "search",
];

export function processStepIcon(step) {
  if (cardIcons.includes(step.icon) && step.icon !== "connection")
    return step.icon;
  const label = step.label || "";
  const description = step.description || "";
  const meanings = [
    [/\b(check|verify|validate|confirm)\b/i, "verify"],
    [/\b(sign|signing|signature)\b/i, "signature"],
    [/\b(certificate|certifying|identity|trust)\b/i, "certificate"],
    [/\bkey\b/i, "key"],
  ];
  for (const text of [label, description]) {
    const match = meanings.find(([pattern]) => pattern.test(text));
    if (match) return match[1];
  }
  return step.icon === "connection" ? "connection" : null;
}

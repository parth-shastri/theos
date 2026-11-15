export function reasoningForDisplay(summary) {
  return summary.replace(/\bOpenUI(?:[ -]+Lang)?(?![\w-])/gi, "intelligent UI");
}

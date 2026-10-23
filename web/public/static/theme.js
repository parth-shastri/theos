// Set the page backdrop before Safari samples it for its native bars.
(() => {
  let preference;
  try {
    preference = localStorage.getItem("theos-theme");
  } catch {}
  document.documentElement.dataset.theme = ["light", "dark"].includes(
    preference,
  )
    ? preference
    : matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
})();

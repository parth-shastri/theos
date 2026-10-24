// Reserve the sign-in window during the click, before asynchronous discovery.
export function signInUrl(url) {
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
  return parsed.href;
}

export function prepareSignIn(service) {
  const popup = window.open("about:blank", "_blank");
  if (popup) {
    popup.opener = null;
    popup.sessionStorage.setItem("theos-connection-window", service);
    popup.document.title = "Preparing sign-in";
    popup.document.body.textContent =
      "Preparing your private sign-in. Keep this tab open.";
  }
  return popup;
}

export function closeSignIn(popup) {
  if (!popup || popup.closed) return;
  try {
    if (
      popup.location.href === "about:blank" ||
      popup.location.origin === window.location.origin
    )
      popup.close();
  } catch {
    // A disowned provider tab closes itself after its verified callback returns.
  }
}

export function continueSignIn(popup, url) {
  const target = signInUrl(url);
  if (!popup || popup.closed) return false;
  popup.location.replace(target);
  return true;
}

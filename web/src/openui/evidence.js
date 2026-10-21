// Keep the exact provider query in the source. Show readable terms separately.
export function searchPresentation(query = "") {
  query = typeof query === "string" ? query : "";
  const sites = [],
    excludedSites = [],
    formats = [];
  const terms = query
    .replace(
      /(?:^|\s)(-?)(site|filetype):(?:"([^"]+)"|(\S+))/gi,
      (_, excluded, kind, quoted, token) => {
        const value = (quoted || token).replace(/[),;]+$/, "").slice(0, 120);
        if (kind.toLowerCase() === "site")
          (excluded ? excludedSites : sites).push(value);
        else formats.push((excluded ? "Exclude " : "") + value.toUpperCase());
        return " ";
      },
    )
    .replace(/\b(?:allintitle|intitle|intext|inurl):/gi, "")
    .replace(/["“”]/g, "")
    .replace(/\s+\b(?:AND|OR)\b\s+/g, " · ")
    .replace(/\s+/g, " ")
    .trim();
  return {
    terms,
    sites: [...new Set(sites)],
    excludedSites: [...new Set(excludedSites)],
    formats: [...new Set(formats)],
    original: query,
  };
}
export function sourcePresentation(value) {
  try {
    const url = new URL(value);
    if (
      !["https:", "http:"].includes(url.protocol) ||
      url.username ||
      url.password
    )
      return null;
    const host = url.hostname.replace(/^www\./, "");
    let path = url.pathname;
    try {
      path = decodeURIComponent(path);
    } catch {}
    return {
      href: url.href,
      host,
      path: path === "/" ? "" : path,
      initial: host.charAt(0).toUpperCase(),
    };
  } catch {
    return null;
  }
}
export function excerptText(value = "") {
  return (typeof value === "string" ? value : "")
    .replace(/^\s*(?:excerpt|snippet)\s*:\s*/i, "")
    .trim();
}
export function referenceLabel(id, href) {
  if (!id || id === href || /^https?:\/\//i.test(id)) return "";
  return id.length > 64 ? id.slice(0, 61) + "…" : id;
}

// Remote media always passes through the authenticated same-origin endpoint.
export function imagePresentation(value) {
  if (typeof value !== "string" || !value || value.length > 4096) return null;
  const source = sourcePresentation(value);
  return source
    ? `/api/search-image?url=${encodeURIComponent(source.href)}`
    : null;
}

export function logoPresentation(value, sourceURL) {
  const supplied = imagePresentation(value);
  if (supplied) return supplied;
  const source = sourcePresentation(sourceURL);
  // Discover the site's declared icon, then try its conventional favicon.
  return source
    ? `/api/search-image?site=${encodeURIComponent(new URL(source.href).origin)}`
    : null;
}

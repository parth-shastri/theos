import "server-only";
import { lookup } from "node:dns/promises";
import { BlockList, isIP } from "node:net";
import { Agent, fetch as upstreamFetch } from "undici";

const blocked = new BlockList();
for (const [address, prefix] of [
  ["0.0.0.0", 8],
  ["10.0.0.0", 8],
  ["100.64.0.0", 10],
  ["127.0.0.0", 8],
  ["169.254.0.0", 16],
  ["172.16.0.0", 12],
  ["192.0.0.0", 24],
  ["192.0.2.0", 24],
  ["192.88.99.0", 24],
  ["192.168.0.0", 16],
  ["198.18.0.0", 15],
  ["198.51.100.0", 24],
  ["203.0.113.0", 24],
  ["224.0.0.0", 3],
])
  blocked.addSubnet(address, prefix, "ipv4");
const globalV6 = new BlockList();
globalV6.addSubnet("2000::", 3, "ipv6");
for (const [address, prefix] of [
  ["2001::", 23],
  ["2001:db8::", 32],
  ["2002::", 16],
  ["3fff::", 20],
])
  blocked.addSubnet(address, prefix, "ipv6");

export function publicImageAddress(address) {
  if (isIP(address) === 4) return !blocked.check(address, "ipv4");
  return (
    isIP(address) === 6 &&
    globalV6.check(address, "ipv6") &&
    !blocked.check(address, "ipv6")
  );
}
export function imageURL(value) {
  if (typeof value !== "string" || value.length > 4096)
    throw new Error("Invalid image URL.");
  const url = new URL(value);
  const host = url.hostname.replace(/^\[|\]$/g, "");
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.port ||
    host.endsWith(".") ||
    (!host.includes(".") && !isIP(host)) ||
    /(?:^|\.)(?:localhost|local|internal|home|test|invalid)$/.test(host) ||
    (isIP(host) && !publicImageAddress(host))
  )
    throw new Error("Use a public image URL.");
  url.hash = "";
  return url;
}
// Resolve and validate at connection time. The socket uses this exact result, preventing DNS rebinding.
export async function publicImageLookup(
  hostname,
  options,
  callback,
  resolve = lookup,
) {
  try {
    const addresses = await resolve(hostname, { all: true, verbatim: true });
    if (
      !addresses.length ||
      addresses.some(({ address }) => !publicImageAddress(address))
    )
      throw new Error("Image host is not public.");
    const eligible = options.family
      ? addresses.filter(({ family }) => family === options.family)
      : addresses;
    if (!eligible.length) throw new Error("Image host has no usable address.");
    if (options.all) callback(null, eligible);
    else callback(null, eligible[0].address, eligible[0].family);
  } catch (error) {
    callback(error);
  }
}
const dispatcher = new Agent({
  connect: { lookup: publicImageLookup, timeout: 5000 },
  connections: 2,
});
const MAX_BYTES = 2 * 1024 * 1024;
const CACHE_BYTES = 24 * 1024 * 1024;
const TTL = 60 * 60 * 1000;
const cache = new Map();
const pending = new Map();
let cachedBytes = 0;

export function rasterType(bytes) {
  if (
    bytes.subarray(0, 8).equals(Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]))
  )
    return "image/png";
  if (bytes[0] === 255 && bytes[1] === 216 && bytes[2] === 255)
    return "image/jpeg";
  if (["GIF87a", "GIF89a"].includes(bytes.subarray(0, 6).toString()))
    return "image/gif";
  if (
    bytes.subarray(0, 4).toString() === "RIFF" &&
    bytes.subarray(8, 12).toString() === "WEBP"
  )
    return "image/webp";
  if (bytes.length > 6 && bytes.readUInt32LE(0) === 65536)
    return "image/x-icon";
  return null;
}
async function publicResponse(value, accept, fetch, signal) {
  let url = imageURL(value);
  for (let redirects = 0; redirects <= 3; redirects++) {
    const response = await fetch(url, {
      dispatcher,
      redirect: "manual",
      signal,
      headers: { Accept: accept, "User-Agent": "Theos-Search-Images/1.0" },
    });
    if (![301, 302, 303, 307, 308].includes(response.status))
      return { response, url };
    await response.body?.cancel();
    if (redirects === 3 || !response.headers.get("location"))
      throw new Error("Image redirect limit.");
    url = imageURL(new URL(response.headers.get("location"), url).href);
  }
}

export async function downloadImage(
  value,
  { fetch = upstreamFetch, signal = AbortSignal.timeout(10000) } = {},
) {
  const { response } = await publicResponse(
    value,
    "image/png,image/jpeg,image/webp,image/gif,image/x-icon",
    fetch,
    signal,
  );
  if (
    !response.ok ||
    !response.body ||
    Number(response.headers.get("content-length")) > MAX_BYTES
  ) {
    await response.body?.cancel();
    throw new Error("Image unavailable.");
  }
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const { value: chunk, done } = await reader.read();
      if (done) break;
      size += chunk.byteLength;
      if (size > MAX_BYTES) throw new Error("Image too large.");
      chunks.push(chunk);
    }
  } finally {
    await reader.cancel();
  }
  const bytes = Buffer.concat(chunks);
  const type = rasterType(bytes);
  if (!type) throw new Error("Unsupported image.");
  return { bytes, type };
}
export function iconCandidates(html, base) {
  const candidates = [];
  for (const tag of html.match(/<link\b[^>]{0,4096}>/gi) || []) {
    const attributes = Object.fromEntries(
      [
        ...tag.matchAll(/([\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))/g),
      ].map((match) => [
        match[1].toLowerCase(),
        match[2] ?? match[3] ?? match[4],
      ]),
    );
    const rel = (attributes.rel || "").toLowerCase().split(/\s+/);
    if (!rel.includes("icon") && !rel.includes("apple-touch-icon")) continue;
    if (
      !attributes.href ||
      attributes.type?.includes("svg") ||
      /\.svg(?:[?#]|$)/i.test(attributes.href)
    )
      continue;
    try {
      const href = attributes.href
        .replace(/&amp;/gi, "&")
        .replace(/&#(x[0-9a-f]+|[0-9]+);/gi, (_, value) =>
          String.fromCodePoint(
            value[0].toLowerCase() === "x"
              ? parseInt(value.slice(1), 16)
              : Number(value),
          ),
        );
      const url = imageURL(new URL(href, base).href).href;
      const size = parseInt(attributes.sizes) || 32;
      candidates.push({
        url,
        score: Math.abs(size - 64) + (rel.includes("icon") ? 0 : 100),
      });
    } catch {}
    if (candidates.length >= 64) break;
  }
  return [
    ...new Set(
      candidates.sort((a, b) => a.score - b.score).map((item) => item.url),
    ),
  ].slice(0, 3);
}
export async function downloadLogo(
  value,
  { fetch = upstreamFetch, signal = AbortSignal.timeout(10000) } = {},
) {
  const origin = new URL("/", imageURL(value)).href;
  let candidates = [];
  try {
    const { response, url } = await publicResponse(
      origin,
      "text/html",
      fetch,
      signal,
    );
    if (
      !response.ok ||
      !response.headers.get("content-type")?.includes("text/html")
    ) {
      await response.body?.cancel();
    } else if (response.body) {
      const reader = response.body.getReader(),
        chunks = [];
      let length = 0;
      try {
        while (length < 256 * 1024) {
          const { value: chunk, done } = await reader.read();
          if (done) break;
          const bounded = chunk.subarray(0, 256 * 1024 - length);
          chunks.push(bounded);
          length += bounded.length;
          if (Buffer.concat(chunks).includes(Buffer.from("</head>"))) break;
        }
      } finally {
        await reader.cancel();
      }
      candidates = iconCandidates(Buffer.concat(chunks).toString("utf8"), url);
    }
  } catch {}
  for (const candidate of [
    ...candidates,
    new URL("/favicon.ico", origin).href,
  ]) {
    try {
      return await downloadImage(candidate, { fetch, signal });
    } catch {}
  }
  throw new Error("Source logo unavailable.");
}

export async function cachedImage(value, kind = "image") {
  const url =
    kind === "logo" ? new URL("/", imageURL(value)).href : imageURL(value).href;
  const key = kind + ":" + url;
  const existing = cache.get(key);
  if (existing && existing.expires > Date.now()) return existing;
  if (pending.has(key)) return pending.get(key);
  if (pending.size >= 8) throw new Error("Image service is busy.");
  const task = (kind === "logo" ? downloadLogo(url) : downloadImage(url))
    .then((image) => {
      const previous = cache.get(key);
      if (previous) {
        cache.delete(key);
        cachedBytes -= previous.bytes.length;
      }
      while (
        cachedBytes + image.bytes.length > CACHE_BYTES ||
        cache.size >= 128
      ) {
        const oldest = cache.keys().next().value;
        cachedBytes -= cache.get(oldest).bytes.length;
        cache.delete(oldest);
      }
      const entry = { ...image, expires: Date.now() + TTL };
      cache.set(key, entry);
      cachedBytes += image.bytes.length;
      return entry;
    })
    .finally(() => pending.delete(key));
  pending.set(key, task);
  return task;
}

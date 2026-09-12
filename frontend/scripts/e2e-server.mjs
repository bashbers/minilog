import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, resolve, sep } from "node:path";

const root = resolve("dist");
const types = new Map([
  [".css", "text/css"],
  [".html", "text/html"],
  [".js", "text/javascript"],
  [".json", "application/json"],
  [".webmanifest", "application/manifest+json"],
]);
const servedPictures = new Set();

createServer(async (request, response) => {
  const requestUrl = new URL(request.url ?? "/", "http://127.0.0.1");
  const { pathname } = requestUrl;
  if (/^\/api\/v1\/babies\/offline-cache-[^/]+\/profile-picture$/.test(pathname)) {
    const pictureKey = `${pathname}${requestUrl.search}`;
    if (servedPictures.has(pictureKey)) {
      response.writeHead(503, { "Content-Type": "text/plain" });
      response.end("origin unavailable");
      return;
    }
    servedPictures.add(pictureKey);
    response.writeHead(200, {
      "Cache-Control": "private, no-store",
      "Content-Type": "image/svg+xml",
    });
    response.end('<svg xmlns="http://www.w3.org/2000/svg"><rect fill="#216869"/></svg>');
    return;
  }

  const requested = resolve(root, pathname === "/" ? "index.html" : `.${pathname}`);
  const target = requested === root || requested.startsWith(`${root}${sep}`)
    ? requested
    : resolve(root, "index.html");
  try {
    const body = await readFile(target);
    response.writeHead(200, { "Content-Type": types.get(extname(target)) ?? "application/octet-stream" });
    response.end(body);
  } catch {
    const body = await readFile(resolve(root, "index.html"));
    response.writeHead(200, { "Content-Type": "text/html" });
    response.end(body);
  }
}).listen(4173, "127.0.0.1");

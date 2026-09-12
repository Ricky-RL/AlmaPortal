import { createServer } from "node:http";

const origin = new URL(
  process.env.E2E_SENDGRID_STUB_ORIGIN ?? "http://127.0.0.1:4319",
);
const messages = [];

function json(response, status, body) {
  response.writeHead(status, {
    "access-control-allow-origin": "*",
    "content-type": "application/json",
  });
  response.end(JSON.stringify(body));
}

const server = createServer((request, response) => {
  if (request.method === "GET" && request.url === "/__health") {
    json(response, 200, { ok: true });
    return;
  }

  if (request.method === "GET" && request.url === "/__messages") {
    json(response, 200, { messages });
    return;
  }

  if (request.method === "DELETE" && request.url === "/__messages") {
    messages.length = 0;
    response.writeHead(204, {
      "access-control-allow-origin": "*",
    });
    response.end();
    return;
  }

  if (request.method === "POST" && request.url?.endsWith("/v3/mail/send")) {
    const chunks = [];
    let size = 0;
    request.on("data", (chunk) => {
      size += chunk.length;
      if (size <= 1_000_000) chunks.push(chunk);
    });
    request.on("end", () => {
      if (size > 1_000_000) {
        json(response, 413, { error: "synthetic SendGrid request too large" });
        return;
      }
      messages.push({
        body: Buffer.concat(chunks).toString("utf8"),
        receivedAt: new Date().toISOString(),
      });
      response.writeHead(202, {
        "access-control-allow-origin": "*",
        "x-message-id": `alma-e2e-${messages.length}`,
      });
      response.end();
    });
    return;
  }

  json(response, 404, { error: "unknown SendGrid stub route" });
});

server.listen(Number(origin.port || 80), origin.hostname, () => {
  process.stdout.write(`SendGrid stub listening on ${origin.origin}\n`);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    server.close(() => process.exit(0));
  });
}

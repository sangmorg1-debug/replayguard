// Minimal metadata-only upload. Requires Node 18+ and REPLAYGUARD_API_KEY.
const response = await fetch("http://127.0.0.1:8787/v1/traces", {
  method: "POST",
  headers: {
    "content-type": "application/json",
    "x-replayguard-key": process.env.REPLAYGUARD_API_KEY!,
  },
  body: JSON.stringify({
    run: { id: "typescript-example", name: "TypeScript agent", status: "ok", events: [] },
    capture_content: false,
  }),
});
if (!response.ok) throw new Error(`${response.status}: ${await response.text()}`);
console.log(await response.json());


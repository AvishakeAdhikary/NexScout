// First-run setup (runs in the sandboxed setup window; talks only to window.nexscoutSetup).
const form = document.getElementById("setup");
const error = document.getElementById("error");
const bridge = window.nexscoutSetup;

function fail(message) {
  error.textContent = message;
}

if (!bridge) {
  fail(
    "NexScout couldn't start its setup helper. Please reinstall the app, or report this problem.",
  );
}

document.getElementById("choose").addEventListener("click", async () => {
  if (!bridge) return;
  try {
    const dir = await bridge.chooseFolder();
    if (dir) {
      document.getElementById("dir").value = dir;
      form.querySelector('input[value="local"]').checked = true;
    }
  } catch {
    fail("Couldn't open the folder picker.");
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  error.textContent = "";
  if (!bridge) return;
  const checked = form.querySelector('input[name="mode"]:checked');
  const mode = checked ? checked.value : "easy";
  const config =
    mode === "easy"
      ? { mode }
      : mode === "remote"
        ? { mode, remoteUrl: document.getElementById("url").value }
        : { mode, checkoutDir: document.getElementById("dir").value };
  const button = form.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    const res = await bridge.save(config);
    if (!res || !res.ok) fail((res && res.error) || "Something went wrong. Please try again.");
  } catch {
    fail(
      "NexScout couldn't start. Check that Docker Desktop is running (Easy mode), then try again.",
    );
  } finally {
    button.disabled = false;
  }
});

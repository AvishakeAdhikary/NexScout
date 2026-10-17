// First-run setup (runs in the sandboxed setup window; talks only to window.nexscoutSetup).
const form = document.getElementById("setup");
const error = document.getElementById("error");
document.getElementById("choose").addEventListener("click", async () => {
  const dir = await window.nexscoutSetup.chooseFolder();
  if (dir) {
    document.getElementById("dir").value = dir;
    form.querySelector('input[value="local"]').checked = true;
  }
});
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  error.textContent = "";
  const mode = form.querySelector('input[name="mode"]:checked').value;
  const config =
    mode === "easy"
      ? { mode }
      : mode === "remote"
        ? { mode, remoteUrl: document.getElementById("url").value }
        : { mode, checkoutDir: document.getElementById("dir").value };
  const res = await window.nexscoutSetup.save(config);
  if (!res.ok) error.textContent = res.error || "Something went wrong.";
});

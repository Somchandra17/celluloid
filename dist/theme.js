let colors;
const fallbacks = {
  ground: "rgb(7, 7, 7)",
  chrome: "rgb(14, 14, 14)",
  rule: "rgb(42, 42, 42)",
  label: "rgb(154, 154, 154)",
  corner: "rgb(79, 110, 79)",
  grid: "rgba(232, 232, 232, .14)",
};
export function canvasTheme() {
  if (!colors) {
    const style = window.getComputedStyle(document.documentElement);
    colors = Object.fromEntries(
      Object.entries(fallbacks).map(([key, fallback]) => [
        key,
        style.getPropertyValue(`--canvas-${key}`).trim() || fallback,
      ]),
    );
  }
  return colors;
}
export function setWorld(world) {
  if (!["nerdy", "creative"].includes(world)) world = "nerdy";
  document.documentElement.dataset.world = world;
  document.documentElement.dataset.worldActive = world;
  for (const button of document.querySelectorAll("[data-world-button]"))
    button.setAttribute(
      "aria-pressed",
      String(button.dataset.worldButton === world),
    );
  const label = document.getElementById("world-status");
  if (label)
    label.textContent =
      world === "nerdy" ? "terminal / ready" : "darkroom / lights low";
  colors = undefined;
  try {
    window.localStorage.setItem("celluloid-world", world);
  } catch {
    /* Optional preference. */
  }
}

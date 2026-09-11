const header = document.querySelector("[data-header]");
const navToggle = document.querySelector(".nav-toggle");
const nav = document.querySelector("#site-nav");

const closeNavigation = () => {
  nav?.classList.remove("open");
  navToggle?.setAttribute("aria-expanded", "false");
};

navToggle?.addEventListener("click", () => {
  const expanded = navToggle.getAttribute("aria-expanded") === "true";
  navToggle.setAttribute("aria-expanded", String(!expanded));
  nav?.classList.toggle("open", !expanded);
});

nav?.querySelectorAll("a").forEach((link) => link.addEventListener("click", closeNavigation));

window.addEventListener(
  "scroll",
  () => header?.classList.toggle("scrolled", window.scrollY > 8),
  { passive: true },
);

const copyButton = document.querySelector("[data-copy-button]");
const copySource = document.querySelector("[data-copy-source]");
copyButton?.addEventListener("click", async () => {
  if (!copySource) return;
  const originalLabel = copyButton.textContent;
  try {
    await navigator.clipboard.writeText(copySource.textContent ?? "");
    copyButton.textContent = "Copied";
  } catch {
    copyButton.textContent = "Select code";
  }
  window.setTimeout(() => {
    copyButton.textContent = originalLabel;
  }, 1600);
});

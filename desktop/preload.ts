// Marca il documento come "chrome desktop": il main lo carica come BrowserWindow
// preload (solo desktop), così in styles.css l'inset dei traffic lights e il
// drag region della sidebar si attivano SOLO sotto html[data-chrome='desktop'].
// Nel browser il preload non esiste: la finestra ha la titlebar standard.
const mark = () => {
  document.documentElement.dataset.chrome = "desktop";
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mark, { once: true });
} else {
  mark();
}

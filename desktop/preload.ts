// Marca il documento come "chrome vibrancy": il main lo carica come BrowserWindow
// preload (solo desktop), così in styles.css le superfici translucide e il drag
// region della sidebar si attivano SOLO sotto html[data-chrome='vibrancy'].
// Nel browser il preload non esiste: il fallback è il fondo opaco equivalente.
const mark = () => {
  document.documentElement.dataset.chrome = "vibrancy";
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", mark, { once: true });
} else {
  mark();
}

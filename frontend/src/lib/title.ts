// Genera un título corto (3-5 palabras significativas) a partir del primer mensaje.
// Heurística cliente: quita signos, stopwords ES/EN comunes, elige las primeras
// palabras "fuertes" y capitaliza la primera. Sin coste, sin red.

const STOPWORDS = new Set([
  // ES
  "el","la","los","las","un","una","unos","unas","de","del","y","o","u","a","en",
  "que","qué","como","cómo","para","por","con","sin","mi","tu","su","es","son",
  "ser","estar","está","están","fue","ha","he","hay","hace","haz","me","te","se",
  "lo","al","si","sí","no","ni","más","menos","muy","ya","pero","porque","cuál",
  "cuando","cuándo","dónde","donde","sobre","entre","esto","esta","ese","esa",
  "estos","estas","esos","esas","mucho","mucha","poco","poca","yo","tú","él","ella",
  // EN
  "the","a","an","and","or","of","to","in","on","for","with","is","are","was",
  "were","be","been","being","i","you","he","she","it","we","they","my","your",
  "this","that","these","those","what","how","why","when","where","which","do",
  "does","did","can","could","should","would","will","just","not","no","but",
  "about","from",
]);

export function buildTitleSummary(text: string, maxWords = 5): string {
  const cleaned = text
    .normalize("NFKD")
    .replace(/[¿?¡!.,;:()[\]{}"'`*_~<>\\/|@#$%^&+=]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (!cleaned) return "Nuevo chat";

  const words = cleaned.split(" ");
  const significant: string[] = [];
  for (const w of words) {
    const lw = w.toLowerCase();
    if (STOPWORDS.has(lw)) continue;
    if (w.length < 2) continue;
    significant.push(w);
    if (significant.length >= maxWords) break;
  }

  // Si quedó muy corto, completa con palabras del original.
  if (significant.length < 2) {
    for (const w of words) {
      if (significant.includes(w)) continue;
      significant.push(w);
      if (significant.length >= 4) break;
    }
  }

  const title = significant.join(" ").trim();
  if (!title) return cleaned.slice(0, 40);

  // Capitaliza primera letra; resto tal cual (preserva acrónimos como SQL, AWS).
  const final = title.charAt(0).toUpperCase() + title.slice(1);
  return final.length > 48 ? final.slice(0, 48) + "…" : final;
}

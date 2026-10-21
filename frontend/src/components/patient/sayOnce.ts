/**
 * Say each instruction once on the result screen.
 *
 * The care card, the server's next steps, the comfort cards and the footer were
 * written separately, so the same sentence ("Please do not leave before a nurse
 * sees you.") can show up three times. These helpers drop a sentence only when an
 * earlier part of the screen already said it in (nearly) the same words. They never
 * add or reword text, and a part with nothing removed is returned exactly as written.
 */

// Sentence ends: Latin, CJK, Devanagari/Bengali (।), Urdu (۔) and the Arabic question mark.
const SENTENCE = /[^.!?。！？।۔؟]+[.!?。！？।۔؟]*/gu;
const NEGATION = new Set(["not", "no", "never", "don't", "dont", "cannot", "can't"]);

export function sentences(text: string): string[] {
  return (text.match(SENTENCE) ?? []).map((s) => s.trim()).filter(Boolean);
}

function words(text: string): string[] {
  return text
    .toLowerCase()
    .normalize("NFKC")
    .replace(/[^\p{L}\p{M}\p{N}\s']/gu, " ")
    .split(/\s+/)
    .filter(Boolean);
}

/** The sentences already on screen, ready to compare against. */
export type Said = string[][];

export function said(...texts: Array<string | null | undefined>): Said {
  return texts.flatMap((t) => (t ? sentences(t) : [])).map(words).filter((w) => w.length > 0);
}

/**
 * True when every word of this sentence was already in one earlier sentence, with
 * the same "not" or "no" (so "do not eat" never matches "eat"). Short sentences, and
 * scripts written without spaces, must match exactly.
 */
export function alreadySaid(sentence: string, before: Said): boolean {
  const w = words(sentence);
  if (w.length === 0) return false;
  const mine = new Set(w);
  const negated = w.some((x) => NEGATION.has(x));
  for (const other of before) {
    if (w.length < 4) {
      if (other.join(" ") === w.join(" ")) return true;
      continue;
    }
    if (other.some((x) => NEGATION.has(x)) !== negated) continue;
    const theirs = new Set(other);
    let shared = 0;
    mine.forEach((x) => {
      if (theirs.has(x)) shared += 1;
    });
    if (shared / mine.size >= 0.85) return true;
  }
  return false;
}

/** The text without the sentences already said, or "" when all of them were. */
export function withoutSaid(text: string, before: Said): string {
  const parts = sentences(text);
  const kept = parts.filter((s) => !alreadySaid(s, before));
  if (kept.length === parts.length) return text;
  // Chinese and Japanese put no space between sentences.
  return kept.join(/[。！？]/.test(text) ? "" : " ");
}
